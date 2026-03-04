# -*- coding: utf-8 -*-
"""
===================================
历史回溯分析脚本 - 扩充回测样本量
===================================

用 stock_daily 历史K线重算量化评分，存入独立表 backtest_simulated，
不污染 analysis_history（真实运行记录）。

使用方法：
  python scripts/historical_backtest.py              # 默认回溯近180天
  python scripts/historical_backtest.py --days 365   # 回溯近1年
  python scripts/historical_backtest.py --report     # 只生成统计报告

注意：
- 只计算量化技术面评分（无AI评分，无新闻情报）
- 结果存入 backtest_simulated 表（record_type='simulated'）
- 与 analysis_history（真实记录）完全隔离
- 不依赖 data_provider 等会触发网络请求的模块，全部本地计算
"""

import sys
import os
import logging
import argparse
from datetime import datetime, timedelta, date
from typing import Optional, List, Dict, Any

import pandas as pd
import numpy as np
from sqlalchemy import Column, Integer, String, Float, DateTime, Index, Text
from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session

# 延迟导入生产代码（屏蔽 efinance module-level stdout 后再导入）
_PROD_ANALYZER = None

def _get_analyzer():
    """
    懒加载生产评分器。
    - 屏蔽 efinance module-level stdout 登录提示
    - monkey-patch 所有会触发外部网络请求的 ScoringSystem 方法（历史回溯不需要实时数据）
    被禁用的方法：score_capital_flow_history / score_lhb_sentiment /
                  score_dzjy_and_holder / score_market_sentiment_adj
    """
    global _PROD_ANALYZER
    if _PROD_ANALYZER is not None:
        return _PROD_ANALYZER
    import io, time as _time
    old_stdout = sys.stdout
    sys.stdout = io.StringIO()
    try:
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from src.stock_analyzer.analyzer import StockTrendAnalyzer
        from src.stock_analyzer.scoring import ScoringSystem
        _PROD_ANALYZER = StockTrendAnalyzer()

        # ── Monkey-patch：禁用所有实时网络请求方法 ──────────────────────
        _noop = staticmethod(lambda *a, **kw: None)
        ScoringSystem.score_capital_flow_history = _noop   # 历史资金流 akshare
        ScoringSystem.score_lhb_sentiment        = _noop   # 龙虎榜 akshare
        ScoringSystem.score_dzjy_and_holder      = _noop   # 大宗交易/持仓者 akshare
        ScoringSystem.score_market_sentiment_adj = _noop   # 全市场快照 akshare

    finally:
        sys.stdout = old_stdout
    return _PROD_ANALYZER

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "stock_analysis.db")
DB_URL = f"sqlite:///{DB_PATH}"


# ─── 独立数据模型（不依赖 src.storage）───────────────────────────────────────

class SimBase(DeclarativeBase):
    pass


class BacktestSimulated(SimBase):
    """
    历史回溯模拟记录（与 analysis_history 完全隔离）
    record_type = 'simulated' 标记来源
    """
    __tablename__ = "backtest_simulated"

    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(10), nullable=False, index=True)
    name = Column(String(50))
    sim_date = Column(String(10), index=True)          # 模拟分析日期 YYYY-MM-DD
    signal_score = Column(Integer)                      # 量化技术面评分
    buy_signal = Column(String(32))                     # 买卖信号（buy/hold/sell/watch）
    market_regime = Column(String(16))                  # 市场环境
    trend_status = Column(String(32))                   # 趋势状态
    macd_status = Column(String(32))                    # MACD状态
    price_at_sim = Column(Float)                        # 模拟当天收盘价（作为参考价）
    price_entry = Column(Float)                         # T+1开盘价（实际买入基准）
    actual_pct_5d = Column(Float)                       # 5日后实际收益率
    actual_pct_10d = Column(Float)                      # 10日后实际收益率
    actual_pct_20d = Column(Float)                      # 20日后实际收益率
    backtest_filled = Column(Integer, default=0)        # 是否已回填价格结果
    score_breakdown = Column(Text)                      # 各维度评分明细（JSON）
    record_type = Column(String(16), default="simulated")  # 固定为 'simulated'
    # 信号组合字段（用于验证多重共振效果）
    kdj_divergence = Column(String(32))                 # KDJ背离类型
    obv_divergence = Column(String(32))                 # OBV背离类型
    rsi_macd_divergence = Column(String(32))            # RSI/MACD背离类型
    kdj_status_val = Column(String(32))                 # KDJ状态（金叉/死叉等）
    resonance_level = Column(String(32))                # 共振级别
    weekly_trend = Column(String(32))                   # 周线趋势
    created_at = Column(DateTime, default=datetime.now)

    __table_args__ = (
        Index("ix_sim_code_date", "code", "sim_date"),
    )


# ─── 核心回溯器 ──────────────────────────────────────────────────────────────

class HistoricalBacktestRunner:
    """用历史K线重算量化评分，存入独立回溯表"""

    def __init__(self):
        self.engine = create_engine(DB_URL, echo=False)
        SimBase.metadata.create_all(self.engine)
        logger.info(f"数据库已就绪: {DB_PATH}")

    # ── 1. 获取有历史数据的股票列表 ────────────────────────────────────────
    def get_available_stocks(self) -> List[Dict[str, str]]:
        """从 stock_daily 获取有足够历史数据的股票"""
        with self.engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT code, 
                       COUNT(*) as days,
                       MIN(date) as earliest,
                       MAX(date) as latest
                FROM stock_daily
                GROUP BY code
                HAVING days >= 60
                ORDER BY code
            """)).fetchall()
        
        # 尝试从 analysis_history 获取股票名称
        name_map: Dict[str, str] = {}
        try:
            with self.engine.connect() as conn:
                names = conn.execute(text(
                    "SELECT DISTINCT code, name FROM analysis_history WHERE name IS NOT NULL"
                )).fetchall()
                name_map = {r[0]: r[1] for r in names}
        except Exception:
            pass

        stocks = []
        for row in rows:
            stocks.append({
                "code": row[0],
                "name": name_map.get(row[0], row[0]),
                "days": row[1],
                "earliest": row[2],
                "latest": row[3],
            })
        logger.info(f"找到 {len(stocks)} 只有效股票（≥60日K线数据）")
        return stocks

    # ── 2. 获取某只股票的全量K线 ───────────────────────────────────────────
    def load_kline(self, code: str, start_date: str = None, end_date: str = None) -> pd.DataFrame:
        """从 stock_daily 读取K线，返回DataFrame"""
        params = {"code": code}
        where_parts = ["code = :code"]
        if start_date:
            where_parts.append("date >= :start_date")
            params["start_date"] = start_date
        if end_date:
            where_parts.append("date <= :end_date")
            params["end_date"] = end_date

        sql = f"""
            SELECT date, open, high, low, close, volume
            FROM stock_daily
            WHERE {" AND ".join(where_parts)}
            ORDER BY date ASC
        """
        with self.engine.connect() as conn:
            df = pd.read_sql(text(sql), conn, params=params)
        
        if df.empty:
            return df
        
        df["date"] = pd.to_datetime(df["date"])
        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df = df.dropna(subset=["close"])
        return df

    # ── 3. 内联技术指标计算（完全本地，无网络请求）──────────────────────────
    @staticmethod
    def _calc_indicators(df: pd.DataFrame) -> pd.DataFrame:
        """内联计算所有需要的技术指标（复制自 TechnicalIndicators，避免导入触发网络请求）"""
        df = df.copy()
        # 均线
        df["MA5"]  = df["close"].rolling(5).mean()
        df["MA10"] = df["close"].rolling(10).mean()
        df["MA20"] = df["close"].rolling(20).mean()
        df["MA60"] = df["close"].rolling(60).mean()
        # MACD (12/26/9)
        ema12 = df["close"].ewm(span=12, adjust=False).mean()
        ema26 = df["close"].ewm(span=26, adjust=False).mean()
        df["MACD_DIF"] = ema12 - ema26
        df["MACD_DEA"] = df["MACD_DIF"].ewm(span=9, adjust=False).mean()
        df["MACD_BAR"] = (df["MACD_DIF"] - df["MACD_DEA"]) * 2
        # KDJ
        low9  = df["low"].rolling(9).min()
        high9 = df["high"].rolling(9).max()
        rsv   = (df["close"] - low9) / (high9 - low9 + 1e-9) * 100
        df["K"] = rsv.ewm(com=2, adjust=False).mean()
        df["D"] = df["K"].ewm(com=2, adjust=False).mean()
        df["J"] = 3 * df["K"] - 2 * df["D"]
        # RSI (6/12/24)
        delta = df["close"].diff()
        for p in [6, 12, 24]:
            gain = delta.clip(lower=0).ewm(alpha=1/p, adjust=False).mean()
            loss = (-delta.clip(upper=0)).ewm(alpha=1/p, adjust=False).mean()
            rs   = gain / (loss + 1e-9)
            df[f"RSI_{p}"] = 100 - 100 / (1 + rs)
        # 布林带 (20, 2)
        df["BB_MID"]   = df["MA20"]
        bb_std         = df["close"].rolling(20).std()
        df["BB_UPPER"] = df["BB_MID"] + 2 * bb_std
        df["BB_LOWER"] = df["BB_MID"] - 2 * bb_std
        df["BB_WIDTH"] = (df["BB_UPPER"] - df["BB_LOWER"]) / df["BB_MID"].replace(0, np.nan)
        df["BB_PCT_B"] = (df["close"] - df["BB_LOWER"]) / (df["BB_UPPER"] - df["BB_LOWER"] + 1e-9)
        return df.fillna(0)

    @staticmethod
    def _score_from_df(df: pd.DataFrame) -> Dict[str, Any]:
        """
        根据计算好指标的 DataFrame（最后一行为当天）计算评分。
        完全内联，不依赖任何 src.* 模块。
        返回 dict: signal_score, buy_signal, market_regime, trend_status, macd_status, score_breakdown
        """
        if len(df) < 5:
            return None

        latest = df.iloc[-1]
        prev   = df.iloc[-2] if len(df) >= 2 else latest

        close  = float(latest["close"])
        ma5    = float(latest["MA5"]  or 0)
        ma10   = float(latest["MA10"] or 0)
        ma20   = float(latest["MA20"] or 0)
        ma60   = float(latest["MA60"] or 0)
        dif    = float(latest["MACD_DIF"] or 0)
        dea    = float(latest["MACD_DEA"] or 0)
        bar    = float(latest["MACD_BAR"] or 0)
        k_val  = float(latest["K"]  or 50)
        d_val  = float(latest["D"]  or 50)
        j_val  = float(latest["J"]  or 50)
        rsi6   = float(latest["RSI_6"]  or 50)
        rsi12  = float(latest["RSI_12"] or 50)
        bb_w   = float(latest["BB_WIDTH"] or 0)
        vol    = float(latest["volume"] or 0)

        p_dif  = float(prev["MACD_DIF"] or 0)
        p_dea  = float(prev["MACD_DEA"] or 0)
        p_k    = float(prev["K"] or 50)
        p_d    = float(prev["D"] or 50)
        avg_vol_20 = float(df["volume"].tail(20).mean() or 1)

        # ── 市场环境 (market_regime) ─────────────────────────────────────
        mas_aligned = (ma5 > ma10 > ma20) if (ma5 > 0 and ma10 > 0 and ma20 > 0) else False
        mas_bear    = (ma5 < ma10 < ma20) if (ma5 > 0 and ma10 > 0 and ma20 > 0) else False
        pct_20d     = (close - float(df["close"].iloc[-20])) / float(df["close"].iloc[-20]) * 100 if len(df) >= 20 else 0
        if mas_aligned and pct_20d > 5:
            market_regime = "bull"
        elif mas_bear and pct_20d < -5:
            market_regime = "bear"
        else:
            market_regime = "sideways"

        # ── 趋势状态 (trend_status) ──────────────────────────────────────
        if mas_aligned and close > ma5 and pct_20d > 10:
            trend_status = "strong_bull"
        elif mas_aligned and close > ma10:
            trend_status = "bull"
        elif ma5 > ma20 and close > ma20:
            trend_status = "weak_bull"
        elif mas_bear and close < ma5:
            trend_status = "bear"
        elif close < ma20 and ma5 < ma20:
            trend_status = "weak_bear"
        else:
            trend_status = "consolidation"

        # ── MACD 状态 ────────────────────────────────────────────────────
        golden_cross = (dif > dea) and (p_dif <= p_dea)
        death_cross  = (dif < dea) and (p_dif >= p_dea)
        if golden_cross and dif > 0 and dea > 0:
            macd_status = "golden_cross_zero"
        elif golden_cross:
            macd_status = "golden_cross"
        elif death_cross:
            macd_status = "death_cross"
        elif dif > dea and dif > 0:
            macd_status = "bullish"
        elif dif > dea:
            macd_status = "crossing_up"
        elif dif < dea and dif < 0:
            macd_status = "bearish"
        else:
            macd_status = "neutral"

        # ── 评分：各维度 ─────────────────────────────────────────────────
        # 1. 趋势
        trend_scores = {"strong_bull": 30, "bull": 26, "weak_bull": 18,
                        "consolidation": 12, "weak_bear": 8, "bear": 4}
        raw_trend = trend_scores.get(trend_status, 0)

        # 2. 乖离率 (bias_ma5)
        bias = (close - ma5) / ma5 * 100 if ma5 > 0 else 0
        is_strong = trend_status == "strong_bull"
        if bb_w > 0.01:
            half_bb = bb_w * 50
            nb = bias / half_bb
            if nb > 1.5:   raw_bias = 8 if is_strong else 0
            elif nb > 1.0: raw_bias = 12 if is_strong else 5
            elif 0.5 < nb <= 1.0 and is_strong: raw_bias = 14
            elif 0 <= nb <= 0.5 and trend_status in ("bull", "strong_bull"): raw_bias = 18
            elif -0.5 <= nb < 0:   raw_bias = 20
            elif -1.0 <= nb < -0.5: raw_bias = 16
            elif -1.5 <= nb < -1.0: raw_bias = 12 if trend_status != "bear" else 5
            else: raw_bias = 8 if trend_status != "bear" else 2
        else:
            if bias > 8:   raw_bias = 8 if is_strong else 0
            elif bias > 5: raw_bias = 12 if is_strong else 5
            elif 0 <= bias <= 3 and trend_status in ("bull", "strong_bull"): raw_bias = 18
            elif -3 <= bias < 0:   raw_bias = 20
            elif -5 <= bias < -3:  raw_bias = 16
            else: raw_bias = 10

        # 3. 量能
        vol_ratio = vol / avg_vol_20 if avg_vol_20 > 0 else 1.0
        price_up  = close >= float(prev["close"])
        if vol_ratio >= 1.5 and price_up:   raw_vol = 12
        elif vol_ratio <= 0.7 and not price_up: raw_vol = 7
        elif vol_ratio <= 0.7 and price_up: raw_vol = 14  # 缩量上涨=洗盘
        elif price_up: raw_vol = 10
        else: raw_vol = 0

        # 4. 支撑（简化：价格离 MA20 的距离）
        if ma20 > 0:
            dist = (close - ma20) / close * 100
            if 0 <= dist <= 2:   raw_support = 10
            elif dist <= 5:      raw_support = 7
            else:                raw_support = 5
        else:
            raw_support = 5

        # 5. MACD
        macd_base = {"golden_cross_zero": 15, "golden_cross": 12, "crossing_up": 10,
                     "bullish": 8, "neutral": 5, "bearish": 2, "death_cross": 0}
        raw_macd = macd_base.get(macd_status, 5)

        # 6. RSI
        if rsi12 < 30:    raw_rsi = 9
        elif rsi12 < 40:  raw_rsi = 7
        elif rsi12 < 60:  raw_rsi = 5
        elif rsi12 < 70:  raw_rsi = 3
        else:  # 超买
            raw_rsi = 5 if trend_status == "strong_bull" else (3 if "bull" in trend_status else 0)

        # 7. KDJ
        kdj_golden = (k_val > d_val) and (p_k <= p_d)
        kdj_death  = (k_val < d_val) and (p_k >= p_d)
        if kdj_golden and k_val < 30:   raw_kdj = 13
        elif k_val < 20:                raw_kdj = 11
        elif kdj_golden:                raw_kdj = 10
        elif k_val > d_val:             raw_kdj = 7
        elif k_val > 80:                raw_kdj = 0
        elif kdj_death:                 raw_kdj = 1
        else:                           raw_kdj = 5

        # ── 权重（与 ScoringSystem.REGIME_WEIGHTS 保持一致）──────────────
        W = {
            "bull":     {"trend": 32, "bias": 10, "volume": 8,  "support": 5,  "macd": 25, "rsi": 10, "kdj": 10},
            "sideways": {"trend": 18, "bias": 18, "volume": 10, "support": 12, "macd": 18, "rsi": 12, "kdj": 12},
            "bear":     {"trend": 12, "bias": 16, "volume": 14, "support": 14, "macd": 16, "rsi": 14, "kdj": 14},
        }
        DIM_MAX = {"trend": 30, "bias": 20, "volume": 15, "support": 10, "macd": 15, "rsi": 10, "kdj": 13}
        w = W[market_regime]
        raws = {"trend": raw_trend, "bias": raw_bias, "volume": raw_vol,
                "support": raw_support, "macd": raw_macd, "rsi": raw_rsi, "kdj": raw_kdj}
        breakdown = {k: min(w[k], round(raws[k] / DIM_MAX[k] * w[k])) for k in raws}
        score = max(0, min(100, sum(breakdown.values())))

        # ── 买入信号等级 ─────────────────────────────────────────────────
        if score >= 85:   buy_signal = "strong_buy"
        elif score >= 75: buy_signal = "buy"
        elif score >= 65: buy_signal = "watch_buy"
        elif score >= 50: buy_signal = "hold"
        elif score >= 40: buy_signal = "watch_sell"
        elif score >= 30: buy_signal = "sell"
        else:             buy_signal = "strong_sell"

        return {
            "signal_score": score,
            "buy_signal": buy_signal,
            "market_regime": market_regime,
            "trend_status": trend_status,
            "macd_status": macd_status,
            "score_breakdown": breakdown,
        }

    # ── 4. 对某只股票按日期窗口滚动计算评分（使用生产代码评分器）────────
    def simulate_stock(
        self,
        code: str,
        name: str,
        df_full: pd.DataFrame,
        sim_start: date,
        sim_end: date,
        lookback_window: int = 120,
    ) -> List[Dict[str, Any]]:
        """
        滚动窗口模拟：对每个交易日，用前 lookback_window 天K线调用生产评分器计算当天评分。
        使用与真实 pipeline 相同的 StockTrendAnalyzer.analyze()，评分口径完全一致。
        """
        import json
        analyzer = _get_analyzer()
        records = []

        sim_dates = df_full[
            (df_full["date"].dt.date >= sim_start) &
            (df_full["date"].dt.date <= sim_end)
        ]["date"].dt.date.tolist()

        for sim_date in sim_dates:
            try:
                window_df = df_full[df_full["date"].dt.date <= sim_date].tail(lookback_window).copy()
                if len(window_df) < 30:
                    continue

                # 调用生产代码评分器（纯K线，无AI/新闻/基本面）
                result = analyzer.analyze(window_df.reset_index(drop=True), code)

                if result is None or result.signal_score is None:
                    continue

                today_rows = df_full[df_full["date"].dt.date == sim_date]
                if today_rows.empty:
                    continue
                price_today = float(today_rows.iloc[-1]["close"])

                future_rows = df_full[df_full["date"].dt.date > sim_date]
                price_entry = float(future_rows.iloc[0]["open"]) if len(future_rows) >= 1 else None

                # market_regime 不在 TrendAnalysisResult 上，从 analyzer 推断
                try:
                    mr, _ = analyzer._detect_market_regime(window_df.reset_index(drop=True), code)
                    market_regime = mr.value if hasattr(mr, 'value') else str(mr)
                except Exception:
                    market_regime = "sideways"
                trend_status  = result.trend_status.value  if result.trend_status  else ""
                macd_status   = result.macd_status.value   if result.macd_status   else ""
                buy_signal    = result.buy_signal.value    if result.buy_signal    else "watch"

                # 提取信号组合字段
                kdj_div = getattr(result, 'kdj_divergence', '') or ''
                obv_div = getattr(result, 'obv_divergence', '') or ''
                # rsi_macd 背离从 score_breakdown 读取
                bd = result.score_breakdown or {}
                rsi_macd_div_adj = bd.get('divergence_adj', 0)
                rsi_macd_div = ('底背离' if rsi_macd_div_adj > 0
                                else '顶背离' if rsi_macd_div_adj < 0
                                else '')
                kdj_status_val = result.kdj_status.value if result.kdj_status else ''
                resonance_lv = getattr(result, 'resonance_level', '') or ''
                weekly_tr = getattr(result, 'weekly_trend', '') or ''

                records.append({
                    "code": code,
                    "name": name,
                    "sim_date": str(sim_date),
                    "signal_score": int(result.signal_score),
                    "buy_signal": buy_signal,
                    "market_regime": market_regime,
                    "trend_status": trend_status,
                    "macd_status": macd_status,
                    "price_at_sim": price_today,
                    "price_entry": price_entry,
                    "score_breakdown": json.dumps(result.score_breakdown or {}, ensure_ascii=False),
                    "record_type": "simulated",
                    "actual_pct_5d": None,
                    "actual_pct_10d": None,
                    "actual_pct_20d": None,
                    "backtest_filled": 0,
                    "kdj_divergence": kdj_div,
                    "obv_divergence": obv_div,
                    "rsi_macd_divergence": rsi_macd_div,
                    "kdj_status_val": kdj_status_val,
                    "resonance_level": resonance_lv,
                    "weekly_trend": weekly_tr,
                })

            except Exception as e:
                logger.debug(f"[{code}] {sim_date} 模拟失败: {e}")
                continue

        return records

    # ── 4. 回填结果（用后续价格计算实际收益） ────────────────────────────
    def backfill_results(self, df_full: pd.DataFrame, records: List[Dict]) -> List[Dict]:
        """用实际价格回填5/10/20日收益率"""
        for rec in records:
            if rec["price_entry"] is None or rec["price_entry"] <= 0:
                rec["backtest_filled"] = 0
                continue
            
            sim_date = date.fromisoformat(rec["sim_date"])
            future = df_full[df_full["date"].dt.date > sim_date].reset_index(drop=True)
            entry = rec["price_entry"]

            if len(future) >= 5:
                p5 = float(future.iloc[4]["close"])
                rec["actual_pct_5d"] = round((p5 - entry) / entry * 100, 2)
            
            if len(future) >= 10:
                p10 = float(future.iloc[9]["close"])
                rec["actual_pct_10d"] = round((p10 - entry) / entry * 100, 2)
            
            if len(future) >= 20:
                p20 = float(future.iloc[19]["close"])
                rec["actual_pct_20d"] = round((p20 - entry) / entry * 100, 2)

            if rec["actual_pct_5d"] is not None:
                rec["backtest_filled"] = 1

        return records

    # ── 5. 批量存储 ────────────────────────────────────────────────────────
    def reset_simulated_data(self):
        """清空 backtest_simulated 表中所有 record_type='simulated' 的数据，保留 backtest_filled 结果"""
        with self.engine.connect() as conn:
            result = conn.execute(text("DELETE FROM backtest_simulated WHERE record_type='simulated'"))
            conn.commit()
        logger.info(f"已清空 backtest_simulated 表，删除 {result.rowcount} 条旧数据")

    def save_records(self, records: List[Dict], skip_existing: bool = True) -> int:
        """批量存储模拟记录（跳过已存在的日期）"""
        if not records:
            return 0

        # 查询已存在的 (code, sim_date) 组合
        existing_keys: set = set()
        if skip_existing:
            code = records[0]["code"]
            with self.engine.connect() as conn:
                rows = conn.execute(text(
                    "SELECT sim_date FROM backtest_simulated WHERE code = :code"
                ), {"code": code}).fetchall()
                existing_keys = {r[0] for r in rows}

        new_records = [r for r in records if r["sim_date"] not in existing_keys]
        if not new_records:
            return 0

        with Session(self.engine) as session:
            for rec in new_records:
                obj = BacktestSimulated(**rec)
                session.add(obj)
            session.commit()

        return len(new_records)

    # ── 6. 主运行函数 ──────────────────────────────────────────────────────
    def run(self, lookback_days: int = 180) -> str:
        """
        执行历史回溯：对所有可用股票，模拟过去 lookback_days 天的量化评分
        
        Args:
            lookback_days: 回溯天数（模拟分析的日期范围）
        
        Returns:
            统计报告文本
        """
        stocks = self.get_available_stocks()
        if not stocks:
            return "⚠️ 无可用历史数据"

        sim_end = date.today() - timedelta(days=6)   # 留6天供回填
        sim_start = date.today() - timedelta(days=lookback_days)

        total_saved = 0
        total_stocks = 0

        for stock in stocks:
            code, name = stock["code"], stock["name"]
            try:
                # 加载K线（需要比模拟窗口多120天历史）
                kline_start = (sim_start - timedelta(days=150)).strftime("%Y-%m-%d")
                df = self.load_kline(code, start_date=kline_start)

                if df.empty or len(df) < 60:
                    logger.warning(f"[{code}] K线数据不足，跳过")
                    continue

                logger.info(f"[{code} {name}] 模拟 {sim_start} ~ {sim_end}，共 {len(df)} 条K线")

                # 计算评分
                records = self.simulate_stock(code, name, df, sim_start, sim_end)
                if not records:
                    continue

                # 回填结果
                records = self.backfill_results(df, records)

                # 存储
                saved = self.save_records(records)
                total_saved += saved
                total_stocks += 1
                logger.info(f"[{code}] 新增 {saved} 条模拟记录（共 {len(records)} 条，{saved} 条为新增）")

            except Exception as e:
                logger.error(f"[{code}] 处理异常: {e}")
                continue

        logger.info(f"回溯完成：{total_stocks} 只股票，共 {total_saved} 条新记录")
        return self.generate_report()

    # ── 7. 统计报告 ────────────────────────────────────────────────────────
    def generate_report(self, lookback_days: int = 365) -> str:
        """生成回溯统计报告"""
        with self.engine.connect() as conn:
            total = conn.execute(text(
                "SELECT COUNT(*) FROM backtest_simulated WHERE backtest_filled=1"
            )).scalar()

            if not total:
                return "⚠️ 暂无已回填的模拟记录"

            # 按评分段位统计
            rows = conn.execute(text("""
                SELECT 
                    signal_score,
                    actual_pct_5d,
                    actual_pct_10d,
                    buy_signal,
                    market_regime
                FROM backtest_simulated
                WHERE backtest_filled = 1
                  AND actual_pct_5d IS NOT NULL
                ORDER BY sim_date DESC
                LIMIT 10000
            """)).fetchall()

        import json as _json

        # 分组
        buckets = {
            "90+": [], "85-89": [], "80-84": [],
            "75-79": [], "70-74": [], "60-69": [], "<60": [],
        }
        buy_pcts = []

        for row in rows:
            score = row[0] or 50
            pct = row[1]
            if pct is None:
                continue
            
            if score >= 90:   buckets["90+"].append(pct)
            elif score >= 85: buckets["85-89"].append(pct)
            elif score >= 80: buckets["80-84"].append(pct)
            elif score >= 75: buckets["75-79"].append(pct)
            elif score >= 70: buckets["70-74"].append(pct)
            elif score >= 60: buckets["60-69"].append(pct)
            else:             buckets["<60"].append(pct)

            if row[3] and ("buy" in str(row[3]).lower() or "买" in str(row[3])):
                buy_pcts.append(pct)

        all_pcts = [r[1] for r in rows if r[1] is not None]
        all_avg = sum(all_pcts) / len(all_pcts) if all_pcts else 0
        all_win = sum(1 for p in all_pcts if p > 0) / len(all_pcts) * 100 if all_pcts else 0

        lines = [
            f"## 📊 历史回溯报告（模拟数据，与真实运行记录隔离）",
            f"**记录类型**：`simulated`（量化技术面评分，不含AI研判）",
            f"**总样本**：{total} 条已回填 | **涉及股票**：见下方",
            "",
            "---",
            "",
            "### 🎯 全量统计",
            f"- 平均5日收益：**{all_avg:+.2f}%**",
            f"- 胜率：**{all_win:.1f}%**",
            "",
            "### 📈 各评分段位表现",
            "",
            "| 评分段位 | 样本数 | 平均5日收益 | 胜率 | 夏普 |",
            "|---------|--------|------------|------|------|",
        ]

        def _sharpe(pcts):
            if len(pcts) < 2:
                return 0.0
            arr = np.array(pcts)
            std = arr.std(ddof=1)
            return float(arr.mean() / std * np.sqrt(50)) if std > 0 else 0.0

        for bucket_name, pcts in buckets.items():
            if not pcts:
                lines.append(f"| {bucket_name} | 0 | - | - | - |")
                continue
            avg = sum(pcts) / len(pcts)
            win = sum(1 for p in pcts if p > 0) / len(pcts) * 100
            sh = _sharpe(pcts)
            lines.append(f"| {bucket_name} | {len(pcts)} | {avg:+.2f}% | {win:.0f}% | {sh:.2f} |")

        if buy_pcts:
            lines.extend([
                "",
                "### 💰 买入信号验证（买入/加仓信号）",
                f"- 信号数：**{len(buy_pcts)}**",
                f"- 平均5日收益：**{sum(buy_pcts)/len(buy_pcts):+.2f}%**",
                f"- 胜率：**{sum(1 for p in buy_pcts if p>0)/len(buy_pcts)*100:.1f}%**",
                f"- 夏普：**{_sharpe(buy_pcts):.2f}**",
            ])

        lines.extend([
            "",
            "---",
            "",
            "### ⚠️ 数据说明",
            "- 本报告基于**模拟历史回溯数据**（`record_type='simulated'`），非真实运行记录",
            "- 仅包含量化技术面评分，不含AI研判、新闻情报、基本面修正",
            "- 买入基准：T+1开盘价（已消除前视偏差）",
            "- 真实运行记录请用 `python main.py --backtest` 查看",
        ])

        return "\n".join(lines)


# ─── CLI 入口 ────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="历史回溯分析脚本")
    parser.add_argument("--days", type=int, default=180, help="回溯天数（默认180天）")
    parser.add_argument("--report", action="store_true", help="仅生成报告，不重新计算")
    parser.add_argument("--reset", action="store_true", help="清空旧数据后用新评分器重跑")
    args = parser.parse_args()

    runner = HistoricalBacktestRunner()

    if args.report:
        print(runner.generate_report())
    else:
        if args.reset:
            runner.reset_simulated_data()
        report = runner.run(lookback_days=args.days)
        print(report)


if __name__ == "__main__":
    main()
