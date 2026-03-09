# -*- coding: utf-8 -*-
"""
评分系统 — ScoringPattern 模块
从 scoring.py 拆分，由 ScoringSystem 通过多继承聚合。
"""

import logging
from datetime import datetime
from typing import Dict, List, Union, Optional

import numpy as np
import pandas as pd
from collections import defaultdict
from .types import TrendAnalysisResult, BuySignal, MarketRegime, TrendStatus
from .types import VolumeStatus, MACDStatus, RSIStatus, KDJStatus
from data_provider.fundamental_types import FundamentalData, ValuationSnapshot, FinancialSummary, ForecastData
from data_provider.analysis_types import CapitalFlowData, SectorContext, QuoteExtra
from data_provider.realtime_types import ChipDistribution

logger = logging.getLogger(__name__)


class ScoringPattern:
    """ScoringPattern Mixin"""


    @staticmethod
    def score_obv_adx(result: TrendAnalysisResult):
        """OBV量能趋势 + ADX趋势强度 + 均线发散速率 综合评分修正"""
        adj = 0
        
        # === OBV 背离（比量价背离更可靠）===
        obv_div = getattr(result, 'obv_divergence', '')
        if obv_div == "OBV顶背离":
            adj -= 3
            result.risk_factors.append("OBV顶背离：价格新高但累积量能未跟上，上涨可能虚假")
            result.score_breakdown['obv_divergence'] = -3
        elif obv_div == "OBV底背离":
            adj += 3
            result.signal_reasons.append("OBV底背离：价格新低但累积量能企稳，底部信号")
            result.score_breakdown['obv_divergence'] = 3
        
        # === OBV 趋势确认/否定 ===
        obv_trend = getattr(result, 'obv_trend', '')
        from .types import TrendStatus
        is_bullish = result.trend_status in [TrendStatus.STRONG_BULL, TrendStatus.BULL]
        is_bearish = result.trend_status in [TrendStatus.STRONG_BEAR, TrendStatus.BEAR]
        
        if is_bullish and obv_trend == "OBV空头":
            adj -= 2
            result.risk_factors.append("OBV空头与多头趋势矛盾，量能不支持上涨")
            result.score_breakdown['obv_trend'] = -2
        elif is_bearish and obv_trend == "OBV多头":
            adj += 2
            result.signal_reasons.append("OBV多头暗示资金暗中吸筹，关注反转")
            result.score_breakdown['obv_trend'] = 2
        
        # === ADX 趋势强度修正 ===
        adx_val = getattr(result, 'adx', 0)
        if adx_val >= 30:
            # 强趋势确认：用 trend_status 判断方向（避免依赖未最终化的 signal_score）
            plus_di = getattr(result, 'plus_di', 0)
            minus_di = getattr(result, 'minus_di', 0)
            is_bull_trend = result.trend_status in [TrendStatus.STRONG_BULL, TrendStatus.BULL, TrendStatus.WEAK_BULL]
            is_bear_trend = result.trend_status in [TrendStatus.STRONG_BEAR, TrendStatus.BEAR, TrendStatus.WEAK_BEAR]
            if plus_di > minus_di and is_bull_trend:
                adj += 2
                result.signal_reasons.append(f"ADX={adx_val:.0f}(强趋势)+DI领先，多头趋势确认")
                result.score_breakdown['adx_adj'] = 2
            elif minus_di > plus_di and is_bear_trend:
                adj -= 2
                result.risk_factors.append(f"ADX={adx_val:.0f}(强趋势)-DI领先，空头趋势确认")
                result.score_breakdown['adx_adj'] = -2
        elif adx_val < 15 and adx_val > 0:
            # 极弱趋势 → 震荡市场，趋势指标信号不可靠
            result.risk_factors.append(f"ADX={adx_val:.0f}(极弱)，市场无方向，趋势信号可靠性低")
            result.score_breakdown['adx_adj'] = 0
        
        # === 均线发散速率 ===
        spread_signal = getattr(result, 'ma_spread_signal', '')
        spread = getattr(result, 'ma_spread', 0)
        if spread_signal == "加速发散" and spread > 0:
            adj += 1
            result.signal_reasons.append(f"均线加速发散(+{spread:.1f}%)，趋势加强")
            result.score_breakdown['ma_spread'] = 1
        elif spread_signal == "收敛" and spread > 0:
            adj -= 1
            result.risk_factors.append(f"均线收敛中(+{spread:.1f}%)，趋势可能转弱")
            result.score_breakdown['ma_spread'] = -1
        elif spread_signal == "加速发散" and spread < 0:
            adj -= 1
            result.risk_factors.append(f"均线空头加速发散({spread:.1f}%)，下跌加速")
            result.score_breakdown['ma_spread'] = -1
        elif spread_signal == "收敛" and spread < 0:
            adj += 1
            result.signal_reasons.append(f"均线空头收敛({spread:.1f}%)，下跌动能减弱")
            result.score_breakdown['ma_spread'] = 1
        

    @staticmethod
    def detect_rsi_macd_divergence(result: TrendAnalysisResult, df: pd.DataFrame):
        """P2: RSI / MACD 背离检测（顶背离看空、底背离看多）

        背离定义：
        - 顶背离：价格创近期新高，但 RSI/MACD_DIF 未创新高（动量衰竭，看空信号）
        - 底背离：价格创近期新低，但 RSI/MACD_DIF 未创新低（下跌动力减弱，看多信号）

        检测窗口：以近 40 根日线的局部高/低点为基础，识别最近两个同向极值点。

        评分调整：
        - RSI 顶背离：-4（高位追涨风险）
        - MACD 顶背离：-3（动量衰竭）
        - RSI+MACD 双顶背离：-6（强顶部警告）
        - RSI 底背离：+4（超跌反弹）
        - MACD 底背离：+3（动力衰竭止跌）
        - RSI+MACD 双底背离：+6（强底部信号）
        """
        if df is None or len(df) < 30:
            return
        try:
            close = df['close'].values.astype(float)
            n = len(close)

            # 计算 RSI(14)
            delta = pd.Series(close).diff()
            gain = delta.clip(lower=0).rolling(14).mean()
            loss = (-delta.clip(upper=0)).rolling(14).mean()
            rsi_series = (100 - 100 / (1 + gain / (loss + 1e-9))).values

            # 计算 MACD DIF（EMA12-EMA26）
            ema12 = pd.Series(close).ewm(span=12, adjust=False).mean().values
            ema26 = pd.Series(close).ewm(span=26, adjust=False).mean().values
            macd_dif = ema12 - ema26

            # --- 寻找最近两个局部高点（近 60 日内，窗口=5）---
            window = 5
            lookback = min(60, n - 1)
            start_idx = n - lookback

            def find_peaks(arr, start, end, k=2):
                """在 arr[start:end] 中找最近 k 个局部高点，返回 [(idx, val)]"""
                peaks = []
                for i in range(end - 1, start + window - 1, -1):
                    lo, hi = max(0, i - window), min(len(arr), i + window + 1)
                    if arr[i] >= max(arr[lo:hi]) - 1e-9:
                        # 与上一个高点至少间隔 window 日
                        if not peaks or (peaks[-1][0] - i) >= window:
                            peaks.append((i, float(arr[i])))
                        if len(peaks) >= k:
                            break
                return peaks

            def find_troughs(arr, start, end, k=2):
                """在 arr[start:end] 中找最近 k 个局部低点，返回 [(idx, val)]"""
                troughs = []
                for i in range(end - 1, start + window - 1, -1):
                    lo, hi = max(0, i - window), min(len(arr), i + window + 1)
                    if arr[i] <= min(arr[lo:hi]) + 1e-9:
                        if not troughs or (troughs[-1][0] - i) >= window:
                            troughs.append((i, float(arr[i])))
                        if len(troughs) >= k:
                            break
                return troughs

            price_peaks = find_peaks(close, start_idx, n)
            price_troughs = find_troughs(close, start_idx, n)

            rsi_div = 0    # >0 底背离, <0 顶背离
            macd_div = 0

            # === 顶背离检测 ===
            if len(price_peaks) >= 2:
                p1_idx, p1_val = price_peaks[0]   # 最近高点
                p2_idx, p2_val = price_peaks[1]   # 上一个高点
                # 价格创新高（近高点 > 前高点）
                if p1_val > p2_val * 1.005 and p1_idx > p2_idx:
                    rsi1, rsi2 = rsi_series[p1_idx], rsi_series[p2_idx]
                    dif1, dif2 = macd_dif[p1_idx], macd_dif[p2_idx]
                    # RSI 顶背离：价格新高但 RSI 更低
                    if not (np.isnan(rsi1) or np.isnan(rsi2)) and rsi1 < rsi2 - 3 and rsi1 > 50:
                        rsi_div = -1
                        result.risk_factors.append(
                            f"📉 RSI顶背离：价格高点{p1_val:.2f}>{p2_val:.2f}，"
                            f"但RSI从{rsi2:.0f}降至{rsi1:.0f}，动量衰竭"
                        )
                    # MACD 顶背离：价格新高但 DIF 更低
                    if not (np.isnan(dif1) or np.isnan(dif2)) and dif1 < dif2 - 0.001 * abs(p1_val):
                        macd_div = -1
                        result.risk_factors.append(
                            f"📉 MACD顶背离：价格新高但DIF回落"
                            f"({dif2:.4f}→{dif1:.4f})，上涨动力不足"
                        )

            # === 底背离检测 ===
            if len(price_troughs) >= 2:
                t1_idx, t1_val = price_troughs[0]   # 最近低点
                t2_idx, t2_val = price_troughs[1]   # 上一个低点
                # 价格创新低（近低点 < 前低点）
                if t1_val < t2_val * 0.995 and t1_idx > t2_idx:
                    rsi1, rsi2 = rsi_series[t1_idx], rsi_series[t2_idx]
                    dif1, dif2 = macd_dif[t1_idx], macd_dif[t2_idx]
                    # RSI 底背离：价格新低但 RSI 更高
                    if not (np.isnan(rsi1) or np.isnan(rsi2)) and rsi1 > rsi2 + 3 and rsi1 < 50:
                        rsi_div = 1
                        result.signal_reasons.append(
                            f"📈 RSI底背离：价格低点{t1_val:.2f}<{t2_val:.2f}，"
                            f"但RSI从{rsi2:.0f}升至{rsi1:.0f}，下跌动力衰竭"
                        )
                    # MACD 底背离：价格新低但 DIF 更高
                    if not (np.isnan(dif1) or np.isnan(dif2)) and dif1 > dif2 + 0.001 * abs(t1_val):
                        macd_div = 1
                        result.signal_reasons.append(
                            f"📈 MACD底背离：价格新低但DIF抬升"
                            f"({dif2:.4f}→{dif1:.4f})，止跌迹象"
                        )

            # 综合评分
            adj = 0
            if rsi_div < 0 and macd_div < 0:
                adj = -6
                result.risk_factors.append("⚠️ RSI+MACD双顶背离，高位反转风险极高，建议止盈减仓")
            elif rsi_div < 0:
                adj = -4
            elif macd_div < 0:
                adj = -3

            if rsi_div > 0 and macd_div > 0:
                adj = 6
                result.signal_reasons.append("✅ RSI+MACD双底背离，强反转信号，关注底部买入机会")
            elif rsi_div > 0:
                adj = 4
            elif macd_div > 0:
                adj = 3

            if adj != 0:
                result.score_breakdown['divergence_adj'] = adj

        except Exception as e:
            logger.debug(f"[背离检测] 失败: {e}")


    @staticmethod
    def detect_volume_spike_trap(result: TrendAnalysisResult, df: pd.DataFrame):
        """游资拉升陷阱检测：连续异常放量 + 短期大涨 = 追高风险

        触发条件（需同时满足）：
        1. 近5日内有 ≥3 日量比>2（连续异常放量）
        2. 近10日涨幅>15%（短期大涨）
        3. 当前非强势上涨趋势中的首板（排除真正突破）
        
        风险逻辑：游资连续拉升 + 量比异常 + 短期涨幅过大 → 出货迹象明显，
        追高者面临高位接盘风险。
        """
        if df is None or len(df) < 10:
            return
        try:
            recent5 = df.tail(5)
            recent10 = df.tail(10)

            # 计算近5日各日量比（当日成交量 / 近20日均量）
            vol_20d_avg = float(df['volume'].tail(20).mean())
            if vol_20d_avg <= 0:
                return
            vol_ratios_5d = [float(v) / vol_20d_avg for v in recent5['volume'].values]
            spike_days = sum(1 for r in vol_ratios_5d if r > 2.0)

            # 近10日涨幅
            price_10d_ago = float(recent10['close'].iloc[0])
            price_now = result.current_price or float(df['close'].iloc[-1])
            if price_10d_ago <= 0:
                return
            gain_10d = (price_now - price_10d_ago) / price_10d_ago * 100

            # 触发陷阱检测
            if spike_days >= 3 and gain_10d > 15:
                # 排除：真实强势突破（连板涨停 + 首板）
                is_genuine_breakout = (
                    result.is_limit_up and result.consecutive_limits <= 1
                )
                if not is_genuine_breakout:
                    adj = -8
                    result.score_breakdown['volume_spike_trap'] = adj
                    result.risk_factors.append(
                        f"⚠️ 游资拉升陷阱：近5日{spike_days}日量比>2倍+10日涨{gain_10d:.0f}%，"
                        f"连续异常放量后高位追涨风险极高"
                    )
                    result.trading_halt = True
                    halt_msg = f"异常放量拉升({spike_days}日量比>2x，10日涨{gain_10d:.0f}%)，疑似游资出货"
                    result.trading_halt_reason = (
                        (result.trading_halt_reason + "；" if result.trading_halt_reason else "") + halt_msg
                    )
        except Exception as e:
            logger.debug(f"[游资陷阱检测] 失败: {e}")


    @staticmethod
    def score_weekly_trend(result: TrendAnalysisResult, df: pd.DataFrame,
                           weekly_df: Optional[pd.DataFrame] = None):
        """P0: 周线趋势分析 — 日线分析的大背景
        
        接受预生成的 weekly_df（由 analyzer._prepare_weekly_df 统一生成）。
        若未传入则 fallback 到原有逻辑：DB 长历史 > 传入 df。
        
        - 周线多头（MA5>MA10>MA20 且 RSI>50）：+3~+6
        - 周线空头（MA5<MA10<MA20 且 RSI<50）：-3~-6
        - 日线多头但周线空头（日内反弹，大趋势向下）：额外降分至 -6
        - 周线震荡：中性
        """
        try:
            weekly = weekly_df
            if weekly is None or len(weekly) < 10:
                from .indicators import TechnicalIndicators
                try:
                    from src.storage import DatabaseManager
                    db = DatabaseManager.get_instance()
                    long_df = db.get_stock_history_df(result.code, days=500)
                    if long_df is not None and len(long_df) >= 100:
                        weekly = TechnicalIndicators.resample_to_weekly(long_df)
                except Exception:
                    pass
                if weekly is None or len(weekly) < 10:
                    if df is None or len(df) < 60:
                        return
                    weekly = TechnicalIndicators.resample_to_weekly(df)

            if weekly is None or len(weekly) < 10:
                return

            c = weekly['close']
            # 周线均线（数据不足时降级使用可用的最高阶MA）
            wma5 = float(c.rolling(5).mean().iloc[-1]) if len(c) >= 5 else float(c.iloc[-1])
            wma10 = float(c.rolling(10).mean().iloc[-1]) if len(c) >= 10 else wma5
            wma20 = float(c.rolling(20).mean().iloc[-1]) if len(c) >= 20 else wma10

            # 周线RSI — 使用与 indicators.py 一致的 Wilder's EMA 算法
            from src.stock_analyzer.indicators import TechnicalIndicators
            TechnicalIndicators._calc_rsi(weekly)
            _wrsi_raw = weekly['RSI_12'].iloc[-1]
            wrsi = float(_wrsi_raw) if pd.notna(_wrsi_raw) else 50.0

            result.weekly_ma5 = round(wma5, 2)
            result.weekly_ma10 = round(wma10, 2)
            result.weekly_ma20 = round(wma20, 2)
            result.weekly_rsi = round(wrsi, 1)

            # 判断周线趋势
            price = float(c.iloc[-1])
            is_weekly_bull = wma5 > wma10 > wma20 * 0.99 and price > wma10 and wrsi > 52
            is_weekly_bear = wma5 < wma10 < wma20 * 1.01 and price < wma10 and wrsi < 48
            is_weekly_bull_weak = wma5 > wma20 and wrsi > 50  # 弱多头
            is_weekly_bear_weak = wma5 < wma20 and wrsi < 50  # 弱空头

            adj = 0
            is_daily_bull = result.trend_status in (TrendStatus.STRONG_BULL, TrendStatus.BULL)
            is_daily_bear = result.trend_status in (TrendStatus.STRONG_BEAR, TrendStatus.BEAR)

            if is_weekly_bull:
                result.weekly_trend = "多头"
                adj = 4
                note = f"周线均线多头排列(MA5={wma5:.2f}>MA10={wma10:.2f}>MA20={wma20:.2f})，RSI{wrsi:.0f}，中长线向好"
                result.signal_reasons.append(f"🗓️ 周线多头：{note}")
                # 日线多头 + 周线多头 = 双共振
                if is_daily_bull:
                    adj = 6
                    result.signal_reasons.append("🗓️ 日周双周期多头共振，趋势强度高")
            elif is_weekly_bull_weak:
                result.weekly_trend = "弱多头"
                adj = 2
                note = f"周线偏多(MA5>{wma20:.2f})，RSI{wrsi:.0f}，趋势偏正面"
            elif is_weekly_bear:
                result.weekly_trend = "空头"
                adj = -4
                note = f"周线均线空头排列(MA5={wma5:.2f}<MA10={wma10:.2f}<MA20={wma20:.2f})，RSI{wrsi:.0f}，中长线向下"
                result.risk_factors.append(f"⚠️ 周线空头：{note}")
                # 日线多头 + 周线空头 = 日内反弹，逆势危险
                if is_daily_bull:
                    adj = -6
                    result.risk_factors.append("⚠️ 日线多头但周线空头，可能仅为下降趋势中的反弹，风险极高")
            elif is_weekly_bear_weak:
                result.weekly_trend = "弱空头"
                adj = -2
                note = f"周线偏空(MA5<{wma20:.2f})，RSI{wrsi:.0f}，趋势偏负面"
                if is_daily_bull:
                    result.risk_factors.append(f"⚠️ 周线偏空，日线上涨或为反弹，需谨慎追高")
            else:
                result.weekly_trend = "震荡"
                adj = 0
                note = f"周线横盘震荡，RSI{wrsi:.0f}"

            result.weekly_trend_adj = adj
            result.weekly_trend_note = note
            if adj != 0:
                result.score_breakdown['weekly_trend_adj'] = adj

        except Exception as e:
            logger.debug(f"[周线趋势] 计算失败: {e}")


    @staticmethod
    def score_chart_patterns(result: TrendAnalysisResult, df: pd.DataFrame):
        """P0: 经典形态识别 — 头肩顶/底、双顶/双底(M头/W底)
        
        基于日线价格序列识别主要反转形态：
        - 头肩顶：顶部反转，强烈看空信号（-6 ~ -8）
        - 头肩底：底部反转，强烈看多信号（+6 ~ +8）
        - 双顶(M头)：顶部反转，看空（-4 ~ -6）
        - 双底(W底)：底部反转，看多（+4 ~ +6）
        
        识别逻辑基于局部高低点（swing high/low），不依赖精确点位。
        """
        if df is None or len(df) < 40:
            return
        try:
            closes = df['close'].values
            highs = df['high'].values
            lows = df['low'].values
            n = len(closes)

            # 识别局部极值点（swing high/low），窗口=5日
            def find_swing_highs(arr, window=5):
                """局部最高点索引"""
                peaks = []
                for i in range(window, len(arr) - window):
                    if arr[i] == max(arr[i - window:i + window + 1]):
                        peaks.append((i, arr[i]))
                return peaks

            def find_swing_lows(arr, window=5):
                """局部最低点索引"""
                troughs = []
                for i in range(window, len(arr) - window):
                    if arr[i] == min(arr[i - window:i + window + 1]):
                        troughs.append((i, arr[i]))
                return troughs

            peaks = find_swing_highs(highs, window=5)
            troughs = find_swing_lows(lows, window=5)

            if not peaks or not troughs:
                return

            last_price = float(closes[-1])

            # === 双顶(M头) 检测 ===
            # 条件：最近2个高点高度相近(差<3%)，中间有一个低点（颈线），当前价接近或跌破颈线
            if len(peaks) >= 2:
                p1_idx, p1_val = peaks[-2]
                p2_idx, p2_val = peaks[-1]
                height_diff = abs(p1_val - p2_val) / max(p1_val, p2_val)
                # 两个高点高度相近（<3%），且第二个高点在近40根K线内
                if height_diff < 0.03 and (n - 1 - p2_idx) <= 20:
                    # 找两峰之间的最低点（颈线）
                    between_lows = [t for t in troughs if p1_idx < t[0] < p2_idx]
                    if between_lows:
                        neckline = min(t[1] for t in between_lows)
                        pattern_height = max(p1_val, p2_val) - neckline
                        # 当前价在颈线附近或已跌破
                        if last_price <= neckline * 1.02:
                            target = neckline - pattern_height
                            result.chart_pattern = "双顶(M头)"
                            result.chart_pattern_signal = "看空"
                            result.chart_pattern_note = (
                                f"双顶形态：两峰约{max(p1_val, p2_val):.2f}，颈线{neckline:.2f}，"
                                f"理论目标位{target:.2f}"
                            )
                            result.chart_pattern_adj = -5
                            result.risk_factors.append(f"⚠️ 识别到双顶(M头)形态，颈线{neckline:.2f}，看空信号")
                            result.score_breakdown['chart_pattern_adj'] = -5
                            return

            # === 双底(W底) 检测 ===
            if len(troughs) >= 2:
                t1_idx, t1_val = troughs[-2]
                t2_idx, t2_val = troughs[-1]
                height_diff = abs(t1_val - t2_val) / max(t1_val, t2_val)
                if height_diff < 0.03 and (n - 1 - t2_idx) <= 20:
                    # 找两谷之间的最高点（颈线）
                    between_highs = [p for p in peaks if t1_idx < p[0] < t2_idx]
                    if between_highs:
                        neckline = max(p[1] for p in between_highs)
                        pattern_height = neckline - min(t1_val, t2_val)
                        # 当前价在颈线附近或已突破
                        if last_price >= neckline * 0.98:
                            target = neckline + pattern_height
                            result.chart_pattern = "双底(W底)"
                            result.chart_pattern_signal = "看多"
                            result.chart_pattern_note = (
                                f"双底形态：两谷约{min(t1_val, t2_val):.2f}，颈线{neckline:.2f}，"
                                f"理论目标位{target:.2f}"
                            )
                            result.chart_pattern_adj = 5
                            result.signal_reasons.append(f"✅ 识别到双底(W底)形态，颈线{neckline:.2f}，看多信号，目标{target:.2f}")
                            result.score_breakdown['chart_pattern_adj'] = 5
                            return

            # === 头肩顶 检测 ===
            # 条件：三个高点，中间最高（头），两侧较低（肩），左右肩高度相近
            if len(peaks) >= 3:
                ls_idx, ls_val = peaks[-3]  # 左肩
                hd_idx, hd_val = peaks[-2]  # 头
                rs_idx, rs_val = peaks[-1]  # 右肩
                # 头比两肩高，两肩高度相近(差<5%)
                if (hd_val > ls_val * 1.01 and hd_val > rs_val * 1.01
                        and abs(ls_val - rs_val) / max(ls_val, rs_val) < 0.05
                        and (n - 1 - rs_idx) <= 25):
                    # 颈线 = 头左右两个低点的均值
                    left_troughs = [t for t in troughs if ls_idx < t[0] < hd_idx]
                    right_troughs = [t for t in troughs if hd_idx < t[0] < rs_idx]
                    if left_troughs and right_troughs:
                        neckline = (min(t[1] for t in left_troughs) + min(t[1] for t in right_troughs)) / 2
                        pattern_height = hd_val - neckline
                        if last_price <= neckline * 1.02:
                            target = neckline - pattern_height
                            result.chart_pattern = "头肩顶"
                            result.chart_pattern_signal = "看空"
                            result.chart_pattern_note = (
                                f"头肩顶：头部{hd_val:.2f}，颈线{neckline:.2f}，"
                                f"理论跌幅目标{target:.2f}"
                            )
                            result.chart_pattern_adj = -7
                            result.risk_factors.append(f"🚨 识别到头肩顶形态，颈线{neckline:.2f}，经典顶部反转，强烈看空")
                            result.score_breakdown['chart_pattern_adj'] = -7
                            return

            # === 头肩底 检测 ===
            if len(troughs) >= 3:
                ls_idx, ls_val = troughs[-3]
                hd_idx, hd_val = troughs[-2]
                rs_idx, rs_val = troughs[-1]
                if (hd_val < ls_val * 0.99 and hd_val < rs_val * 0.99
                        and abs(ls_val - rs_val) / max(ls_val, rs_val) < 0.05
                        and (n - 1 - rs_idx) <= 25):
                    left_peaks = [p for p in peaks if ls_idx < p[0] < hd_idx]
                    right_peaks = [p for p in peaks if hd_idx < p[0] < rs_idx]
                    if left_peaks and right_peaks:
                        neckline = (max(p[1] for p in left_peaks) + max(p[1] for p in right_peaks)) / 2
                        pattern_height = neckline - hd_val
                        if last_price >= neckline * 0.98:
                            target = neckline + pattern_height
                            result.chart_pattern = "头肩底"
                            result.chart_pattern_signal = "看多"
                            result.chart_pattern_note = (
                                f"头肩底：底部{hd_val:.2f}，颈线{neckline:.2f}，"
                                f"理论涨幅目标{target:.2f}"
                            )
                            result.chart_pattern_adj = 7
                            result.signal_reasons.append(f"✅ 识别到头肩底形态，颈线{neckline:.2f}，经典底部反转，强烈看多，目标{target:.2f}")
                            result.score_breakdown['chart_pattern_adj'] = 7
                            return

        except Exception as e:
            logger.debug(f"[形态识别] 计算失败: {e}")


    @staticmethod
    def detect_sequential_behavior(result: TrendAnalysisResult, df: pd.DataFrame):
        """P3: 多日时序行为识别
        
        识别近期连贯的量价行为链：
        
        行为分类：
        - 缩量横盘：近N日量均在MA20 70%以下且价格振幅<2%/日 → 蓄势
        - 放量上攻：近N日量均>MA20且收阳比例高 → 主动买入
        - 缩量回踩：上涨后连续缩量小跌 → 健康回调
        - 冲高回落：单日振幅>3%且收盘接近日低 → 试盘/压力
        - 连续放量下跌：近N日量均>MA20且收阴 → 出货
        - 地量止跌：极低量后出现阳线反弹 → 止跌迹象
        """
        if df is None or len(df) < 10:
            return
        try:
            close = df['close'].values.astype(float)
            high = df['high'].values.astype(float)
            low = df['low'].values.astype(float)
            volume = df['volume'].values.astype(float)
            n = len(close)

            vol_ma20 = float(pd.Series(volume).rolling(20).mean().iloc[-1]) if n >= 20 else float(volume.mean())
            
            behaviors = []
            behavior_days = {}
            notes = []

            # === 1. 冲高回落检测（近3日内是否存在）===
            for i in range(-3, 0):
                if abs(i) > n:
                    continue
                amp = (high[i] - low[i]) / close[i - 1] if close[i - 1] > 0 else 0
                shadow_down = (high[i] - close[i]) / (high[i] - low[i] + 1e-6)
                if amp > 0.025 and shadow_down > 0.55:
                    behaviors.append("冲高回落")
                    behavior_days["冲高回落"] = abs(i)
                    notes.append(f"近{abs(i)}日冲高回落（振幅{amp*100:.1f}%，上影线占比{shadow_down*100:.0f}%）")
                    break

            # === 2. 连续缩量识别（近3/5日）===
            for window in [5, 3]:
                if n < window + 2:
                    continue
                recent_vols = volume[-window:]
                if all(v < vol_ma20 * 0.75 for v in recent_vols):
                    amp_list = [(high[-window + j] - low[-window + j]) / close[-window + j - 1]
                                for j in range(window) if close[-window + j - 1] > 0]
                    if amp_list and max(amp_list) < 0.025:
                        tag = f"连续{window}日缩量横盘"
                        behaviors.append(tag)
                        behavior_days["缩量横盘"] = window
                        notes.append(f"{tag}（量均{sum(recent_vols)/len(recent_vols)/vol_ma20*100:.0f}%均量）")
                    else:
                        tag = f"连续{window}日缩量"
                        behaviors.append(tag)
                        behavior_days["缩量"] = window
                        notes.append(tag)
                    break

            # === 3. 连续放量上涨 / 放量下跌（近3/5日）===
            for window in [5, 3]:
                if n < window + 2:
                    continue
                recent_vols = volume[-window:]
                recent_close = close[-window:]
                recent_close_prev = close[-window - 1:-1]
                if all(v > vol_ma20 * 1.2 for v in recent_vols):
                    up_days = sum(1 for c, p in zip(recent_close, recent_close_prev) if c > p)
                    down_days = window - up_days
                    if up_days >= window * 0.6:
                        tag = f"连续{window}日放量上攻"
                        behaviors.append(tag)
                        behavior_days["放量上攻"] = window
                        notes.append(f"{tag}（{up_days}/{window}日收阳）")
                    elif down_days >= window * 0.6:
                        tag = f"连续{window}日放量下跌"
                        behaviors.append(tag)
                        behavior_days["放量下跌"] = window
                        notes.append(f"{tag}（{down_days}/{window}日收阴）")
                    break

            # === 4. 缩量回踩识别（前期上涨后缩量小跌）===
            if n >= 15 and "缩量横盘" not in behavior_days and "缩量" not in behavior_days:
                pre_period = close[-15:-5]
                recent_period = close[-5:]
                pre_trend_up = float(pre_period[-1]) > float(pre_period[0]) * 1.03
                recent_small_fall = float(recent_period[-1]) < float(recent_period[0]) and \
                                    float(recent_period[0]) - float(recent_period[-1]) < float(recent_period[0]) * 0.04
                recent_low_vol = all(volume[-5 + j] < vol_ma20 * 0.8 for j in range(5))
                if pre_trend_up and recent_small_fall and recent_low_vol:
                    behaviors.append("缩量回踩")
                    behavior_days["缩量回踩"] = 5
                    notes.append("前期拉升后缩量小幅回踩（健康回调形态）")

            # === 5. 地量止跌识别（极低量后反弹）===
            if n >= 5:
                prev_vols = volume[-5:-1]
                yesterday_low_vol = float(volume[-2]) < vol_ma20 * 0.4
                today_up = float(close[-1]) > float(close[-2])
                today_vol_recover = float(volume[-1]) > float(volume[-2]) * 1.3
                if yesterday_low_vol and today_up and today_vol_recover:
                    behaviors.append("地量止跌反弹")
                    behavior_days["地量止跌"] = 1
                    notes.append("昨日地量今日放量反弹，止跌迹象")

            # === 6. 主力试盘特征（冲高回落+量能异常）===
            has_surge_fall = "冲高回落" in behavior_days
            has_vol_anomaly = getattr(result, 'vol_anomaly', '') in ('天量', '次天量')
            if has_surge_fall and has_vol_anomaly:
                if "主力试盘" not in behaviors:
                    behaviors.append("主力试盘")
                    notes.append("冲高回落+放量特征，疑似主力试盘探测抛压")

            result.seq_behaviors = behaviors
            result.seq_behavior_days = behavior_days
            result.seq_behavior_note = " | ".join(notes) if notes else ""

        except Exception:
            pass


    @staticmethod
    def score_multi_signal_resonance(result: TrendAnalysisResult, df: pd.DataFrame):
        """P3: 多信号时序共振分析
        
        结合行为链 + K线 + MACD/KDJ + 量价结构 + Fib + 周线趋势，
        综合判断主力操作意图和共振强度。
        
        共振规则：
        做多共振（+信号叠加）：
        - 缩量回踩/横盘 + 周线多头 + RSI未超买 + Fib支撑区 → 洗盘后拉升
        - 放量突破 + 多信号确认 → 突破加速
        
        做空共振（-信号叠加）：
        - 冲高回落 + 主力试盘 + 放量 + 高位 → 出货警告
        - 连续放量下跌 + 周线空头 → 趋势下跌
        
        分歧（信号矛盾）：
        - 高位缩量（量能枯竭）+ 日线多头 → 信号分歧
        """
        if df is None or len(df) < 10:
            return
        try:
            close = df['close'].values.astype(float)
            n = len(close)

            behaviors = getattr(result, 'seq_behaviors', [])
            weekly_trend = getattr(result, 'weekly_trend', '')
            fib_zone = getattr(result, 'fib_current_zone', '')
            fib_adj = getattr(result, 'fib_adj', 0)
            vol_anomaly = getattr(result, 'vol_anomaly', '')
            vps = getattr(result, 'vol_price_structure', '')
            chart_pattern = getattr(result, 'chart_pattern', '')
            chart_pattern_adj = getattr(result, 'chart_pattern_adj', 0)

            from .types import TrendStatus
            trend_status = getattr(result, 'trend_status', None)
            is_bull = trend_status in (
                getattr(TrendStatus, 'STRONG_BULL', None),
                getattr(TrendStatus, 'BULL', None),
            )
            is_bear = trend_status in (
                getattr(TrendStatus, 'STRONG_BEAR', None),
                getattr(TrendStatus, 'BEAR', None),
            )

            bull_signals = 0
            bear_signals = 0
            intent_parts = []
            detail_parts = []

            # ---- 行为链信号 ----
            if "缩量回踩" in behaviors or "连续5日缩量横盘" in behaviors or "连续3日缩量横盘" in behaviors:
                bull_signals += 2
                intent_parts.append("缩量蓄势")
                detail_parts.append("缩量蓄势（看多信号）")
            # 连续放量上攻：区分「一次放量突破」和「连续多日放量上攻」
            # 连续多日放量上攻往往是顶部信号（追高风险），而非持续看多
            has_vol_up = any("放量上攻" in b for b in behaviors)
            has_consecutive_vol_up = any(("连续" in b and "放量上攻" in b) for b in behaviors)
            if has_consecutive_vol_up:
                # 连续放量上攻：短期追高风险，反而偏空
                bear_signals += 1
                intent_parts.append("追高风险")
                detail_parts.append("连续放量上攻（短期追高风险）")
            elif has_vol_up:
                bull_signals += 1
                intent_parts.append("放量上攻")
                detail_parts.append("放量主动买入")
            if "地量止跌反弹" in behaviors:
                bull_signals += 2
                intent_parts.append("止跌反弹")
                detail_parts.append("地量止跌反弹")
            if "主力试盘" in behaviors:
                bear_signals += 2
                intent_parts.append("主力试盘")
                detail_parts.append("冲高回落试盘（谨慎）")
            if "连续" in " ".join(behaviors) and "放量下跌" in " ".join(behaviors):
                bear_signals += 3
                intent_parts.append("持续出货")
                detail_parts.append("连续放量下跌（出货信号）")
            if "冲高回落" in behaviors and "主力试盘" not in behaviors:
                bear_signals += 1
                detail_parts.append("冲高回落（压力显现）")

            # ---- 周线背景 ----
            if weekly_trend in ('多头', '强多头'):
                bull_signals += 2
                detail_parts.append(f"周线{weekly_trend}背景")
            elif weekly_trend in ('空头', '强空头'):
                bear_signals += 2
                detail_parts.append(f"周线{weekly_trend}背景（系统性压力）")

            # ---- Fib支撑/阻力 ----
            if fib_adj > 0:
                bull_signals += 1
                detail_parts.append(f"处于Fib支撑区（{fib_zone}）")
            elif fib_adj < 0:
                bear_signals += 1
                detail_parts.append(f"处于Fib阻力区（{fib_zone}）")

            # ---- 量价结构 ----
            if vps == '放量突破':
                bull_signals += 2
                detail_parts.append("量价结构：放量突破")
            elif vps == '缩量回踩':
                bull_signals += 1
                detail_parts.append("量价结构：缩量回踩（健康）")
            elif vps == '放量下跌':
                bear_signals += 2
                detail_parts.append("量价结构：放量下跌")

            # ---- 形态 ----
            if chart_pattern_adj > 0:
                bull_signals += 1
                detail_parts.append(f"形态：{chart_pattern}（看多）")
            elif chart_pattern_adj < 0:
                bear_signals += 1
                detail_parts.append(f"形态：{chart_pattern}（看空）")

            # ---- 日线趋势 ----
            if is_bull:
                bull_signals += 1
            elif is_bear:
                bear_signals += 1

            total = bull_signals + bear_signals
            diff = bull_signals - bear_signals

            # 判定共振级别（提高强共振阈值，避免过度乐观/悲观）
            if diff >= 6:
                result.resonance_level = "强共振做多"
                result.resonance_score_adj = min(8, diff)
            elif diff >= 3:
                result.resonance_level = "中度共振做多"
                result.resonance_score_adj = 4
            elif diff <= -6:
                result.resonance_level = "强共振做空"
                result.resonance_score_adj = max(-8, diff)
            elif diff <= -3:
                result.resonance_level = "中度共振做空"
                result.resonance_score_adj = -4
            elif abs(diff) <= 1 and total >= 4:
                result.resonance_level = "信号分歧"
                result.resonance_score_adj = 0
            else:
                result.resonance_level = "弱共振"
                result.resonance_score_adj = diff // 2  # 弱共振调整幅度减半

            # 操作意图（需要信号差值足够大才给定性意图，避免噪声主导）
            if "持续出货" in intent_parts or ("主力试盘" in intent_parts and bear_signals > bull_signals + 1):
                result.resonance_intent = "主力出货"
            elif "主力试盘" in intent_parts and bull_signals >= bear_signals:
                result.resonance_intent = "主力洗盘"
            elif "缩量蓄势" in intent_parts and bull_signals >= bear_signals + 2:
                result.resonance_intent = "主力洗盘"
            elif "放量上攻" in intent_parts and bull_signals >= bear_signals + 3 and "追高风险" not in intent_parts:
                result.resonance_intent = "主力拉升"
            elif "止跌反弹" in intent_parts and bull_signals > bear_signals:
                result.resonance_intent = "自然止跌"
            elif bear_signals > bull_signals + 2:
                # 需要熊信号明显领先才判断"自然回调"，避免细微差距误判
                result.resonance_intent = "自然回调"
            else:
                result.resonance_intent = ""

            result.resonance_detail = " | ".join(detail_parts[:6]) if detail_parts else ""

            # 注入评分
            if result.resonance_score_adj != 0:
                result.score_breakdown['p3_resonance'] = result.resonance_score_adj

        except Exception:
            pass


    @staticmethod
    def forecast_next_days(result: TrendAnalysisResult, df: pd.DataFrame):
        """P3: 1-5日行情预判
        
        基于当前共振状态、行为链、量能，给出主要情景和概率分布，
        并生成确认/失效的触发价位条件。
        """
        if df is None or len(df) < 10:
            return
        try:
            close = df['close'].values.astype(float)
            high = df['high'].values.astype(float)
            low = df['low'].values.astype(float)
            volume = df['volume'].values.astype(float)
            n = len(close)

            current_price = float(close[-1])
            behaviors = getattr(result, 'seq_behaviors', [])
            resonance_level = getattr(result, 'resonance_level', '')
            resonance_intent = getattr(result, 'resonance_intent', '')
            vol_anomaly = getattr(result, 'vol_anomaly', '')
            vps = getattr(result, 'vol_price_structure', '')

            # 近期关键价位
            recent_high = float(high[-5:].max()) if n >= 5 else float(high[-1])
            recent_low = float(low[-5:].min()) if n >= 5 else float(low[-1])
            vol_ma5 = float(pd.Series(volume).rolling(5).mean().iloc[-1]) if n >= 5 else float(volume.mean())
            vol_ma20 = float(pd.Series(volume).rolling(20).mean().iloc[-1]) if n >= 20 else float(volume.mean())

            prob_up = 40
            prob_down = 30
            prob_sideways = 30
            scenario = ""
            trigger = ""
            note_parts = []

            intent = resonance_intent

            # 基准概率：参考 A 股实际分布（5日内 ±1.5%定向），更均衡起点
            # up≈32%, sideways≈37%, down≈31%
            prob_up = 32
            prob_down = 31
            prob_sideways = 37

            if intent == "主力洗盘":
                # 洗盘蓄势：回测按共振级别区分
                # 弱共振+洗盘：实际 dn=47%，偏空
                # 中度共振做多+洗盘：实际 up=24% sw=47% dn=29%，偏横
                if "弱共振" in resonance_level:
                    scenario = "洗盘蓄势"
                    prob_up = 20
                    prob_down = 42
                    prob_sideways = 38
                    trigger = f"跌破{recent_low:.2f}则洗盘变出货，放量突破{recent_high:.2f}才可关注"
                else:
                    scenario = "洗盘蓄势"
                    prob_up = 25
                    prob_down = 30
                    prob_sideways = 45
                    trigger = f"放量突破{recent_high:.2f}确认洗盘结束，跌破{recent_low:.2f}则洗盘变出货"
                note_parts.append("缩量蓄势/洗盘特征，等待放量突破确认")

            elif intent == "主力拉升":
                scenario = "拉升延续"
                prob_up = 48
                prob_down = 20
                prob_sideways = 32
                trigger = f"维持{current_price * 0.97:.2f}以上量能不委缩，则延续拉升"
                note_parts.append("放量上攻，主力拉升意愿强")

            elif intent == "追高风险":
                # 连续多日放量上攻后的追高险境，回测准确率趋近 0%——实际往往是短期顶部
                scenario = "高位震荡"
                prob_up = 22
                prob_down = 38
                prob_sideways = 40
                trigger = f"跌破{recent_low:.2f}确认高位调护，不建追高追入"
                note_parts.append("连续放量上攻后短期追高风险")

            elif intent == "主力出货":
                scenario = "出货下跌"
                prob_up = 18
                prob_down = 50
                prob_sideways = 32
                trigger = f"跌破{recent_low:.2f}加速下跌，反弹至{recent_high:.2f}附近关注减仓"
                note_parts.append("疑似出货特征，注意风险")

            elif intent == "自然回调":
                # 自然回调：根据回测实际方向分布设定概率
                if "中度共振做空" in resonance_level or "强共振做空" in resonance_level:
                    # 回测：自然回调+中度做空，实际 up=24% sw=50% dn=26%
                    # 横盘为主！不能假设偏空
                    scenario = "调整整理"
                    prob_up = 25
                    prob_down = 27
                    prob_sideways = 48
                    trigger = f"突破{recent_high:.2f}確認方向，跌破{recent_low:.2f}小心加展下行"
                elif "中度共振做多" in resonance_level or "强共振做多" in resonance_level:
                    # 健康回调：就算共振偷指多也要等放量确认
                    scenario = "调整整理"
                    prob_up = 35
                    prob_down = 25
                    prob_sideways = 40
                    trigger = f"缩量守住{recent_low:.2f}支撑后可关注低吸机会"
                else:
                    # 弱共振/信号分歧：纯横盘
                    scenario = "调整整理"
                    prob_up = 31
                    prob_down = 31
                    prob_sideways = 38
                    trigger = f"缩量守住{recent_low:.2f}支撑后可关注低吸机会"
                note_parts.append("正常技术性回调，关注支撑是否有效")

            elif intent == "自然止跌":
                scenario = "止跌反弹"
                prob_up = 46
                prob_down = 20
                prob_sideways = 34
                trigger = f"放量站稳{current_price:.2f}上方确认反转，否则谨慎"
                note_parts.append("地量止跌特征，但需放量确认")

            else:
                if "强共振做多" in resonance_level:
                    scenario = "强势上攻"
                    prob_up = 50
                    prob_down = 18
                    prob_sideways = 32
                elif "中度共振做多" in resonance_level:
                    scenario = "震荡偏强"
                    prob_up = 42
                    prob_down = 24
                    prob_sideways = 34
                elif "强共振做空" in resonance_level:
                    # 强共振做空实际 up=35% sw=45% dn=20%！逆势大涨。概率小幅偏空但不过度自信
                    scenario = "弱势下跌"
                    prob_up = 30
                    prob_down = 38
                    prob_sideways = 32
                elif "中度共振做空" in resonance_level:
                    scenario = "震荡偏弱"
                    prob_up = 24
                    prob_down = 42
                    prob_sideways = 34
                elif "信号分歧" in resonance_level:
                    scenario = "方向待定"
                    prob_up = 33
                    prob_down = 33
                    prob_sideways = 34
                    note_parts.append("多空信号相当，等待成交量方向选择")
                else:
                    # 弱共振默认：偏横盘
                    scenario = "震荡整理"
                    prob_up = 30
                    prob_down = 30
                    prob_sideways = 40

            # 量价极端情形微调（最多±10%，避免单因子主导）
            if vol_anomaly == "天量" and vps == "放量下跌":
                prob_down = min(60, prob_down + 10)
                prob_up = max(12, prob_up - 8)
                prob_sideways = 100 - prob_up - prob_down
                note_parts.append("天量放量下跌，短期承压")
            elif vol_anomaly in ("地量", "次地量") and vps == "缩量回踩":
                prob_up = min(55, prob_up + 8)
                prob_down = max(12, prob_down - 6)
                prob_sideways = 100 - prob_up - prob_down
                note_parts.append("缩量回踩，抛压轻，关注反弹")

            # 归一化概率（确保和为100）
            total = prob_up + prob_down + prob_sideways
            if total > 0:
                prob_up = int(prob_up / total * 100)
                prob_down = int(prob_down / total * 100)
                prob_sideways = 100 - prob_up - prob_down

            result.forecast_scenario = scenario
            result.forecast_prob_up = prob_up
            result.forecast_prob_down = prob_down
            result.forecast_prob_sideways = prob_sideways
            result.forecast_trigger = trigger
            result.forecast_note = " | ".join(note_parts) if note_parts else scenario

            # 预警注入（提高阈值，只在真正极端情况下触发）
            if prob_down >= 50 and result.risk_factors is not None:
                result.risk_factors.append(
                    f"⚠ 预判1-5日主情景「{scenario}」，下跌概率{prob_down}%，{trigger}"
                )
            elif prob_up >= 50 and result.signal_reasons is not None:
                result.signal_reasons.append(
                    f"📈 预判1-5日主情景「{scenario}」，上涨概率{prob_up}%，{trigger}"
                )

        except Exception:
            pass


    @staticmethod
    def score_vol_anomaly(result: TrendAnalysisResult, df: pd.DataFrame):
        """P2: 天量/地量异常检测
        
        基于近60日成交量历史分位，检测当日量能异常：
        
        天量（>95分位）：
        - 上涨天量：+3（放量拉升，主力积极）
        - 下跌天量：-4（放量出货，强烈警告）
        - 横盘天量：+1（量能积累，方向待定）
        
        次天量（>85分位）：
        - 上涨：+2；下跌：-2
        
        地量（<5分位）：
        - 下跌趋势中地量：+2（缩量到极致，有止跌可能）
        - 上涨趋势中地量：-1（量能枯竭，上涨乏力）
        - 横盘地量：0（蓄势待变）
        
        次地量（<15分位）：
        - 视趋势给 ±1
        """
        if df is None or len(df) < 20:
            return
        try:
            volume = df['volume'].values.astype(float)
            close = df['close'].values.astype(float)
            
            n = len(volume)
            lookback = min(60, n)
            hist_vol = volume[-lookback:]
            current_vol = float(volume[-1])
            
            # 计算当日量在历史分位
            pct = float((hist_vol < current_vol).sum()) / len(hist_vol) * 100
            result.vol_percentile_60d = round(pct, 1)
            
            # 判断价格方向（近3日涨跌）
            if n >= 4:
                price_chg = (float(close[-1]) - float(close[-4])) / float(close[-4])
            else:
                price_chg = 0.0
            
            is_rising = price_chg > 0.015
            is_falling = price_chg < -0.015
            
            from .types import TrendStatus
            trend_down = getattr(result, 'trend_status', None) in (
                getattr(TrendStatus, 'STRONG_BEAR', None),
                getattr(TrendStatus, 'BEAR', None),
            )
            trend_up = getattr(result, 'trend_status', None) in (
                getattr(TrendStatus, 'STRONG_BULL', None),
                getattr(TrendStatus, 'BULL', None),
            )
            
            vol_ma20 = float(pd.Series(volume).rolling(20).mean().iloc[-1]) if n >= 20 else float(hist_vol.mean())
            x_times = current_vol / vol_ma20 if vol_ma20 > 0 else 1.0
            
            adj = 0
            
            if pct >= 95:
                result.vol_anomaly = "天量"
                if is_rising:
                    adj = 3
                    result.signal_reasons.append(
                        f"天量放量上涨（分位{pct:.0f}%，{x_times:.1f}倍均量），主力积极买入"
                    )
                elif is_falling:
                    adj = -4
                    result.risk_factors.append(
                        f"天量放量下跌（分位{pct:.0f}%，{x_times:.1f}倍均量），强烈警告主力出货"
                    )
                else:
                    adj = 1
                    result.signal_reasons.append(
                        f"天量横盘（分位{pct:.0f}%，{x_times:.1f}倍均量），量能积累，方向待定"
                    )
            elif pct >= 85:
                result.vol_anomaly = "次天量"
                if is_rising:
                    adj = 2
                    result.signal_reasons.append(
                        f"放量上涨（量能分位{pct:.0f}%），趋势强化"
                    )
                elif is_falling:
                    adj = -2
                    result.risk_factors.append(
                        f"放量下跌（量能分位{pct:.0f}%），注意主力出货风险"
                    )
            elif pct <= 5:
                result.vol_anomaly = "地量"
                if trend_down:
                    adj = 2
                    result.signal_reasons.append(
                        f"下跌趋势中出现地量（分位{pct:.0f}%），缩量到极致，关注止跌反转"
                    )
                elif trend_up or is_rising:
                    adj = -1
                    result.risk_factors.append(
                        f"上涨趋势中量能枯竭（地量分位{pct:.0f}%），涨势恐后继无力"
                    )
                else:
                    result.signal_reasons.append(
                        f"地量横盘（分位{pct:.0f}%），蓄势待变，等待方向选择"
                    )
            elif pct <= 15:
                result.vol_anomaly = "次地量"
                if trend_down:
                    adj = 1
                    result.signal_reasons.append(
                        f"缩量下跌（分位{pct:.0f}%），抛压减轻，可关注止跌信号"
                    )
                elif trend_up or is_rising:
                    adj = -1
                    result.risk_factors.append(
                        f"缩量上涨（分位{pct:.0f}%），量能不配合，上涨持续性存疑"
                    )
            
            result.vol_anomaly_adj = adj
            if adj != 0:
                result.score_breakdown['vol_anomaly'] = adj
            
            if result.vol_anomaly:
                result.vol_anomaly_note = (
                    f"{result.vol_anomaly}（{x_times:.1f}倍均量，近60日{pct:.0f}%分位）"
                )
        except Exception:
            pass


    @staticmethod
    def _fib_count_tests(close_series, level: float, tol: float = 0.02) -> int:
        """P5-D辅助: 统计历史上价格触碰某Fib位的次数（有效测试次数）"""
        count = 0
        in_zone = False
        for p in close_series:
            if abs(p - level) / level <= tol if level > 0 else False:
                if not in_zone:
                    count += 1
                    in_zone = True
            else:
                in_zone = False
        return count


    @staticmethod
    def score_fibonacci_levels(result: TrendAnalysisResult, df: pd.DataFrame):
        """P1/P5-D: 黄金分割回撤位分析（多时间窗口 + 历史有效性）

        P5-D 增强：
        1. 多时间窗口自动选择：优先选振幅>=5%且波动最大的窗口（20/60/120日）
        2. 历史有效性验证：统计该Fib位在全段历史中被测试次数
           - >=3次：高历史有效性，评分加成+1
           - 2次：中历史有效性，评分不变
           - 1次：低历史有效性，评分打折
        """
        if df is None or len(df) < 30:
            return
        try:
            close = df['close'].values
            current_price = float(close[-1])

            # P5-D: 多窗口选择 —— 选振幅最大（信息量最丰富）且振幅>=5%的窗口
            best_window = None
            best_range = 0.0
            for w in [20, 60, 120]:
                if len(close) < w:
                    continue
                seg = close[-w:]
                hi = float(seg.max())
                lo = float(seg.min())
                amp = (hi - lo) / hi if hi > 0 else 0
                if amp >= 0.05 and amp > best_range:
                    best_range = amp
                    best_window = w

            if best_window is None:
                # 振幅均<5%，退回到最大可用窗口（至少做中性分析）
                best_window = min(60, len(close))

            n = best_window
            recent = close[-n:]
            swing_high_idx = int(recent.argmax())
            swing_low_idx = int(recent.argmin())
            swing_high = float(recent[swing_high_idx])
            swing_low = float(recent[swing_low_idx])

            if swing_high <= swing_low or (swing_high - swing_low) / swing_high < 0.03:
                return

            diff = swing_high - swing_low
            is_uptrend_context = swing_high_idx > swing_low_idx

            f382 = round(swing_high - diff * 0.382, 2)
            f500 = round(swing_high - diff * 0.500, 2)
            f618 = round(swing_high - diff * 0.618, 2)

            result.fib_swing_high = swing_high
            result.fib_swing_low = swing_low
            result.fib_level_382 = f382
            result.fib_level_500 = f500
            result.fib_level_618 = f618
            result.fib_window = n

            tol = 0.02
            adj = 0

            def near(price, level, tolerance=tol):
                return abs(price - level) / level <= tolerance if level > 0 else False

            # 确定当前触碰的Fib位
            active_level = None
            if is_uptrend_context:
                if current_price < f618 * (1 - tol):
                    result.fib_current_zone = "已跌破0.618（结构破坏）"
                    result.fib_signal = "结构破坏，谨慎"
                    adj = -3
                    result.risk_factors.append(f"价格已跌破黄金分割0.618支撑({f618:.2f})，上升结构可能破坏")
                elif near(current_price, f618):
                    result.fib_current_zone = "0.618深度回撤支撑区"
                    result.fib_signal = "接近支撑买入区"
                    adj = 3
                    active_level = f618
                    result.signal_reasons.append(f"价格触及0.618黄金分割支撑({f618:.2f})，深度回调逢低机会")
                elif near(current_price, f500):
                    result.fib_current_zone = "0.500中度回撤支撑区"
                    result.fib_signal = "接近支撑买入区"
                    adj = 2
                    active_level = f500
                    result.signal_reasons.append(f"价格在0.5回撤支撑附近({f500:.2f})，中度回调可关注")
                elif near(current_price, f382):
                    result.fib_current_zone = "0.382浅度回撤支撑区"
                    result.fib_signal = "接近支撑买入区"
                    adj = 4
                    active_level = f382
                    result.signal_reasons.append(f"价格在0.382黄金分割支撑({f382:.2f})，浅回调强势特征")
                else:
                    result.fib_current_zone = ""
                    result.fib_signal = "中性"
            else:
                if near(current_price, f382):
                    result.fib_current_zone = "0.382反弹阻力区"
                    result.fib_signal = "接近阻力卖出区"
                    adj = -2
                    active_level = f382
                    result.risk_factors.append(f"反弹触及0.382阻力位({f382:.2f})，注意减仓")
                elif near(current_price, f618):
                    result.fib_current_zone = "0.618强阻力区"
                    result.fib_signal = "接近阻力卖出区"
                    adj = -3
                    active_level = f618
                    result.risk_factors.append(f"反弹触及0.618强阻力({f618:.2f})，建议减仓防回落")
                else:
                    result.fib_current_zone = ""
                    result.fib_signal = "中性"

            # P5-D: 历史有效性验证
            if active_level is not None and len(close) > n:
                test_count = ScoringPattern._fib_count_tests(close, active_level, tol)
                result.fib_test_count = test_count
                if test_count >= 3:
                    result.fib_validity = "高历史有效性"
                    adj = adj + (1 if adj > 0 else -1)  # 加强原方向
                elif test_count == 2:
                    result.fib_validity = "中历史有效性"
                else:
                    result.fib_validity = "低历史有效性"
                    adj = int(adj * 0.7)  # 打折：首次测试可靠性较低
            elif active_level is not None:
                result.fib_test_count = 1
                result.fib_validity = "低历史有效性"

            result.fib_adj = adj
            if adj != 0:
                result.score_breakdown['fib_adj'] = adj

            validity_note = f" [{result.fib_validity}，历史测试{result.fib_test_count}次]" if result.fib_validity else ""
            result.fib_note = (
                f"波段高={swing_high:.2f} 低={swing_low:.2f}（{n}日窗口） | "
                f"0.382={f382:.2f} 0.5={f500:.2f} 0.618={f618:.2f} | "
                f"{result.fib_current_zone or '价格在区间中部'}{validity_note}"
            )
        except Exception:
            pass


    @staticmethod
    def score_vol_price_structure(result: TrendAnalysisResult, df: pd.DataFrame):
        """P1: 量价结构分析——放量突破 / 缩量回踩
        
        识别最近30根K线内是否存在有效的量价结构信号：
        
        放量突破（看多 +4~+6）：
        - 近5日内出现成交量 ≥ 近20日均量1.8倍的K线
        - 且该K线收盘价突破近20日最高价（前高阻力）
        - 当前价格仍在突破位上方
        
        缩量回踩（看多 +3~+4）：
        - 之前已有放量突破信号（10日内）
        - 当前回踩但成交量 < 5日均量的0.7倍（缩量）
        - 价格在突破位 ±3% 内（正常回踩，非破位）
        
        放量下跌（看空 -3~-4）：
        - 近5日成交量 ≥ 近20日均量1.8倍
        - 且收盘跌幅 > 2%
        
        缩量反弹（看空 -2）：
        - 当前处于下跌趋势中
        - 近3日反弹但缩量（成交量 < 5日均量0.7倍）
        """
        if df is None or len(df) < 25:
            return
        try:
            close = df['close'].values.astype(float)
            volume = df['volume'].values.astype(float)
            high = df['high'].values.astype(float)
            low = df['low'].values.astype(float)
            
            n = len(close)
            vol_ma20 = float(pd.Series(volume).rolling(20).mean().iloc[-1]) if n >= 20 else float(volume[-n:].mean())
            vol_ma5 = float(pd.Series(volume).rolling(5).mean().iloc[-1]) if n >= 5 else float(volume[-n:].mean())
            current_vol = float(volume[-1])
            current_price = float(close[-1])
            
            if vol_ma20 <= 0:
                return
            
            # === 检测近10日内有无放量突破 ===
            lookback = min(10, n - 5)
            breakout_price = None
            breakout_day_idx = None
            
            for i in range(n - lookback, n):
                vol_i = float(volume[i])
                close_i = float(close[i])
                # 以该K线前20日高点为阻力
                prev_high = float(high[max(0, i-20):i].max()) if i >= 5 else 0
                if prev_high <= 0:
                    continue
                # 放量（≥1.8倍均量）且突破前高
                local_vol_ma = float(volume[max(0, i-20):i].mean()) if i >= 5 else vol_ma20
                if local_vol_ma > 0 and vol_i >= local_vol_ma * 1.8 and close_i > prev_high:
                    breakout_price = close_i
                    breakout_day_idx = i
            
            from .types import TrendStatus
            adj = 0
            
            if breakout_price is not None:
                days_since = n - 1 - breakout_day_idx
                if days_since <= 3:
                    # 放量突破刚发生
                    result.vol_price_structure = "放量突破"
                    result.vol_price_breakout_price = breakout_price
                    adj = 5 if current_vol >= vol_ma20 * 1.5 else 4
                    result.signal_reasons.append(
                        f"放量突破前高({breakout_price:.2f})，成交量{current_vol/vol_ma20:.1f}倍均量，趋势确认"
                    )
                else:
                    # 放量突破后回踩
                    is_near_breakout = abs(current_price - breakout_price) / breakout_price <= 0.03
                    is_light_vol = current_vol < vol_ma5 * 0.7
                    if is_near_breakout and is_light_vol:
                        result.vol_price_structure = "缩量回踩"
                        result.vol_price_breakout_price = breakout_price
                        adj = 4
                        result.signal_reasons.append(
                            f"缩量回踩突破位({breakout_price:.2f})，量能萎缩健康，可关注买入机会"
                        )
                    elif not is_near_breakout and current_price < breakout_price * 0.97:
                        # 已跌破突破位，信号失败
                        result.vol_price_structure = "突破失败"
                        result.vol_price_breakout_price = breakout_price
                        adj = -3
                        result.risk_factors.append(
                            f"前期放量突破位({breakout_price:.2f})已跌破，形态失败，注意风险"
                        )
            else:
                # 无突破，检测放量下跌 / 缩量反弹
                recent_vol_avg = float(volume[-5:].mean()) if n >= 5 else vol_ma20
                recent_close_chg = (float(close[-1]) - float(close[-6])) / float(close[-6]) if n >= 6 else 0
                
                is_trending_down = result.trend_status in (
                    getattr(TrendStatus, 'STRONG_BEAR', None),
                    getattr(TrendStatus, 'BEAR', None),
                ) if hasattr(result, 'trend_status') else False
                
                if recent_vol_avg >= vol_ma20 * 1.8 and recent_close_chg < -0.02:
                    result.vol_price_structure = "放量下跌"
                    adj = -4
                    result.risk_factors.append(
                        f"近5日放量下跌，成交量{recent_vol_avg/vol_ma20:.1f}倍均量，主力出货信号"
                    )
                elif is_trending_down and recent_vol_avg < vol_ma5 * 0.7 and recent_close_chg > 0.01:
                    result.vol_price_structure = "缩量反弹"
                    adj = -2
                    result.risk_factors.append(
                        f"下跌趋势中缩量反弹，量能不支持，建议不追高"
                    )
            
            result.vol_price_structure_adj = adj
            if adj != 0:
                result.score_breakdown['vol_price_structure'] = adj
            
            if result.vol_price_structure:
                result.vol_price_structure_note = (
                    f"{result.vol_price_structure}"
                    + (f" | 关键价位={result.vol_price_breakout_price:.2f}" if result.vol_price_breakout_price else "")
                    + f" | 当量/均量={current_vol/vol_ma20:.1f}x"
                )
        except Exception:
            pass


    @staticmethod
    def score_support_strength(result: TrendAnalysisResult, df: pd.DataFrame):
        """P1-2: 支撑位强度评分 — 引入历史测试次数权重
        
        原 _calc_support_score 只考虑现价距最近支撑位的距离，不考虑支撑位强度。
        本方法补充：统计每个支撑位在历史K线中被触及（±1.5%容差）的次数，
        多次验证的支撑位得到额外加分（+1~+3），弱支撑（只出现1次）不额外加分。
        
        仅在支撑位存在且现价接近支撑位（距离 ≤8%）时触发。
        """
        if not result.support_levels or result.current_price <= 0 or df is None or len(df) < 10:
            return

        price = result.current_price
        # 只评估现价下方最近的支撑位（距离≤8%）
        candidates = [s for s in result.support_levels if 0 < s < price and (price - s) / price <= 0.08]
        if not candidates:
            return

        nearest = max(candidates)  # 最近的支撑位
        dist_pct = (price - nearest) / price * 100

        # 统计该支撑位在历史K线中被测试的次数（K线的low价落在支撑位±1.5%范围内）
        tolerance = nearest * 0.015
        try:
            lows = df['low'].astype(float)
            test_count = int(((lows >= nearest - tolerance) & (lows <= nearest + tolerance)).sum())
        except Exception:
            test_count = 0

        # 根据测试次数确定强度加分（仅在现价接近支撑位时才有意义）
        if dist_pct <= 5:
            if test_count >= 5:
                adj = 3
                result.signal_reasons.append(f"强支撑位{nearest:.2f}(历史{test_count}次测试验证)，距现价{dist_pct:.1f}%")
            elif test_count >= 3:
                adj = 2
                result.signal_reasons.append(f"有效支撑位{nearest:.2f}(历史{test_count}次测试)，距现价{dist_pct:.1f}%")
            elif test_count >= 2:
                adj = 1
                result.signal_reasons.append(f"支撑位{nearest:.2f}(历史{test_count}次测试)，距现价{dist_pct:.1f}%")
            else:
                adj = 0  # 仅出现1次的弱支撑，不额外加分
        else:
            adj = 0  # 距离超过5%，强度加分价值有限

        if adj > 0:
            result.score_breakdown['support_strength'] = adj

