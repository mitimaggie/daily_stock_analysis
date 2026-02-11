# -*- coding: utf-8 -*-
"""
===================================
趋势交易分析器 (持仓/空仓双规策略版)
===================================
"""

import logging
from dataclasses import dataclass, field
from typing import List, Dict, Any
from enum import Enum
import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)

class TrendStatus(Enum):
    STRONG_BULL = "强势多头"
    BULL = "多头排列"
    WEAK_BULL = "弱势多头"
    CONSOLIDATION = "震荡整理"
    WEAK_BEAR = "弱势空头"
    BEAR = "空头排列"
    STRONG_BEAR = "强势空头"

class VolumeStatus(Enum):
    HEAVY_VOLUME_UP = "放量上涨"       # 量价齐升
    HEAVY_VOLUME_DOWN = "放量下跌"     # 放量杀跌
    SHRINK_VOLUME_UP = "缩量上涨"      # 无量上涨
    SHRINK_VOLUME_DOWN = "缩量回调"    # 缩量回调（好）
    NORMAL = "量能正常"

class MACDStatus(Enum):
    GOLDEN_CROSS_ZERO = "零轴上金叉"   # DIF上穿DEA，且在零轴上方（最强买入）
    GOLDEN_CROSS = "金叉"              # DIF上穿DEA
    CROSSING_UP = "上穿零轴"           # DIF上穿零轴，趋势转强
    BULLISH = "多头"                   # DIF>DEA>0
    NEUTRAL = "中性"
    BEARISH = "空头"                   # DIF<DEA<0
    CROSSING_DOWN = "下穿零轴"         # DIF下穿零轴，趋势转弱
    DEATH_CROSS = "死叉"               # DIF下穿DEA

class RSIStatus(Enum):
    GOLDEN_CROSS_OVERSOLD = "超卖金叉"  # RSI6上穿RSI12且RSI12<30，强买入
    GOLDEN_CROSS = "金叉"              # RSI6上穿RSI12
    OVERBOUGHT = "超买"                # RSI > 70
    STRONG_BUY = "强势"                # 50 < RSI < 70
    NEUTRAL = "中性"                   # 40 <= RSI <= 60
    WEAK = "弱势"                      # 30 < RSI < 40
    OVERSOLD = "超卖"                  # RSI < 30
    DEATH_CROSS = "死叉"               # RSI6下穿RSI12
    BULLISH_DIVERGENCE = "底背离"       # 价格新低但RSI未新低
    BEARISH_DIVERGENCE = "顶背离"       # 价格新高但RSI未新高

class KDJStatus(Enum):
    GOLDEN_CROSS_OVERSOLD = "超卖金叉"   # K上穿D且J<20，强买入信号
    GOLDEN_CROSS = "金叉"               # K上穿D
    BULLISH = "多头"                     # K>D，J>50
    NEUTRAL = "中性"                     # K≈D
    BEARISH = "空头"                     # K<D，J<50
    DEATH_CROSS = "死叉"                 # K下穿D
    OVERBOUGHT = "超买"                  # J>100，短期回调风险
    OVERSOLD = "超卖"                    # J<0，反弹机会

class BuySignal(Enum):
    AGGRESSIVE_BUY = "激进买入"       # 95+: 共振信号+趋势确认，大胆上车
    STRONG_BUY = "强烈买入"       # 85-94: 多重指标共振，胜率高
    BUY = "买入"                # 70-84: 技术面看好，可建仓
    CAUTIOUS_BUY = "谨慎买入"   # 60-69: 有机会但需谨慎
    HOLD = "持有"                # 50-59: 中性，持股待涨
    REDUCE = "减仓"              # 35-49: 信号转弱，逐步减仓
    SELL = "清仓"                # 0-34: 多重风险，先走为妙

class MarketRegime(Enum):
    BULL = "bull"
    SIDEWAYS = "sideways"
    BEAR = "bear"

@dataclass
class TrendAnalysisResult:
    code: str
    current_price: float = 0.0
    
    # 核心结论
    trend_status: TrendStatus = TrendStatus.CONSOLIDATION
    signal_score: int = 50 
    buy_signal: BuySignal = BuySignal.HOLD
    
    # === 新增：分持仓情况建议 ===
    advice_for_empty: str = ""    # 给空仓者的建议
    advice_for_holding: str = ""  # 给持仓者的建议
    
    # 趋势强度 (0-100, 基于均线间距扩张/收缩)
    trend_strength: float = 50.0
    ma_alignment: str = ""           # 均线排列描述

    # 基础数据
    ma5: float = 0.0
    ma10: float = 0.0
    ma20: float = 0.0
    bias_ma5: float = 0.0
    bias_ma10: float = 0.0
    bias_ma20: float = 0.0
    volume_ratio: float = 0.0
    volume_trend: str = "量能正常"
    
    # 辅助信息
    signal_reasons: List[str] = field(default_factory=list)
    risk_factors: List[str] = field(default_factory=list)
    macd_signal: str = ""
    kdj_signal: str = ""
    # KDJ 数值
    kdj_k: float = 50.0
    kdj_d: float = 50.0
    kdj_j: float = 50.0
    kdj_status: KDJStatus = KDJStatus.NEUTRAL

    # 扩展指标（波动率/长周期/超买超卖）
    atr14: float = 0.0
    ma60: float = 0.0
    # 多周期 RSI (短/中/长)
    rsi_6: float = 50.0
    rsi_12: float = 50.0
    rsi_24: float = 50.0
    rsi: float = 50.0          # 保留兼容（= rsi_12）
    rsi_signal: str = ""
    rsi_divergence: str = ""   # 背离信号描述（底背离/顶背离/无）
    # MACD 数值
    macd_dif: float = 0.0
    macd_dea: float = 0.0
    macd_bar: float = 0.0
    # 量化锚点（供 LLM 参考，避免拍脑袋）
    stop_loss_anchor: float = 0.0       # 保留兼容 (= stop_loss_short)
    stop_loss_intraday: float = 0.0     # 日内止损 (0.7 ATR, 紧)
    stop_loss_short: float = 0.0        # 短线止损 (1.0 ATR)
    stop_loss_mid: float = 0.0          # 中线止损 (1.5 ATR + MA20*0.98)
    ideal_buy_anchor: float = 0.0
    # 止盈锚点
    take_profit_short: float = 0.0      # 短线止盈 (1.5 ATR)
    take_profit_mid: float = 0.0        # 中线止盈 (第一阻力位)
    take_profit_trailing: float = 0.0   # 移动止盈线 (最高价 - 1.2 ATR)
    take_profit_plan: str = ""          # 分批止盈方案描述
    # 风险收益比
    risk_reward_ratio: float = 0.0      # R:R ratio (收益空间 / 风险空间)
    risk_reward_verdict: str = ""       # "值得" / "不值得" / "中性"
    # 多指标共振
    resonance_count: int = 0            # 共振信号数量 (0-5)
    resonance_signals: List[str] = field(default_factory=list)  # 共振信号列表
    resonance_bonus: int = 0            # 共振加分
    # 白话版解读
    beginner_summary: str = ""          # 通俗语言版分析结论
    # 估值安全检查
    pe_ratio: float = 0.0               # 市盈率
    pb_ratio: float = 0.0               # 市净率
    peg_ratio: float = 0.0              # PEG
    valuation_score: int = 0            # 估值评分 (0-10, 10=严重低估)
    valuation_verdict: str = ""         # "低估" / "合理" / "偏高" / "严重高估"
    valuation_downgrade: int = 0        # 估值降档扣分 (0~-15)
    # 全局暂停信号
    trading_halt: bool = False          # True=不适合交易
    trading_halt_reason: str = ""       # 暂停原因
    # 资金面
    capital_flow_score: int = 0         # 资金面评分 (0-10)
    capital_flow_signal: str = ""       # 资金面信号描述
    # 仓位管理（量化硬规则，不交给 LLM）
    suggested_position_pct: int = 0     # 建议仓位占比 (0-30%)
    # 板块强弱
    sector_name: str = ""               # 所属板块名称
    sector_pct: float = 0.0             # 板块当日涨跌幅(%)
    sector_relative: float = 0.0        # 个股 vs 板块相对强弱(百分点)
    sector_score: int = 5               # 板块评分 (0-10, 5=中性)
    sector_signal: str = ""             # 板块信号描述
    # 筹码分布
    chip_score: int = 5                 # 筹码评分 (0-10, 5=中性)
    chip_signal: str = ""              # 筹码信号描述
    # 基本面质量
    fundamental_score: int = 5          # 基本面评分 (0-10, 5=中性)
    fundamental_signal: str = ""       # 基本面信号描述
    # 52周位置
    week52_position: float = 0.0        # 当前价格在 52周高低中的位置(0-100%)

    # Bollinger Bands
    bb_upper: float = 0.0
    bb_lower: float = 0.0
    bb_width: float = 0.0       # (upper - lower) / middle, 衡量波动率
    bb_pct_b: float = 0.5       # (close - lower) / (upper - lower), 价格在带内位置

    # 风险指标
    volatility_20d: float = 0.0  # 20日年化波动率
    beta_vs_index: float = 1.0   # 相对大盘 Beta
    max_drawdown_60d: float = 0.0  # 近60日最大回撤(%)

    # 枚举化状态
    volume_status: VolumeStatus = VolumeStatus.NORMAL
    macd_status: MACDStatus = MACDStatus.NEUTRAL
    rsi_status: RSIStatus = RSIStatus.NEUTRAL
    # kdj_status 已在上方定义

    # 支撑/阻力位
    support_levels: List[float] = field(default_factory=list)
    resistance_levels: List[float] = field(default_factory=list)

    # 结构化评分明细（总分 100：trend 25 + bias 15 + volume 15 + support 10 + macd 12 + rsi 10 + kdj 13）
    score_breakdown: Dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """序列化为 dict，供 pipeline 注入 context 或 prompt 结构化输入"""
        return {
            "code": self.code,
            "current_price": self.current_price,
            "trend_status": self.trend_status.value,
            "trend_strength": self.trend_strength,
            "ma_alignment": self.ma_alignment,
            "buy_signal": self.buy_signal.value,
            "signal_score": self.signal_score,
            "score_breakdown": self.score_breakdown,
            "volume_status": self.volume_status.value,
            "macd_status": self.macd_status.value,
            "macd_dif": self.macd_dif, "macd_dea": self.macd_dea, "macd_bar": self.macd_bar,
            "rsi_status": self.rsi_status.value, "rsi_signal": self.rsi_signal, "rsi_divergence": self.rsi_divergence,
            "ma5": self.ma5, "ma10": self.ma10, "ma20": self.ma20, "ma60": self.ma60,
            "bias_ma5": self.bias_ma5, "bias_ma10": self.bias_ma10, "bias_ma20": self.bias_ma20,
            "volume_ratio": self.volume_ratio,
            "atr14": self.atr14,
            "rsi_6": self.rsi_6, "rsi_12": self.rsi_12, "rsi_24": self.rsi_24,
            "bb_upper": self.bb_upper, "bb_lower": self.bb_lower,
            "bb_width": self.bb_width, "bb_pct_b": self.bb_pct_b,
            "volatility_20d": self.volatility_20d, "beta_vs_index": self.beta_vs_index,
            "max_drawdown_60d": self.max_drawdown_60d,
            "stop_loss_anchor": self.stop_loss_anchor,
            "stop_loss_intraday": self.stop_loss_intraday,
            "stop_loss_short": self.stop_loss_short,
            "stop_loss_mid": self.stop_loss_mid,
            "ideal_buy_anchor": self.ideal_buy_anchor,
            "suggested_position_pct": self.suggested_position_pct,
            "support_levels": self.support_levels,
            "resistance_levels": self.resistance_levels,
            "advice_for_empty": self.advice_for_empty,
            "advice_for_holding": self.advice_for_holding,
            "macd_signal": self.macd_signal, "kdj_signal": self.kdj_signal,
            "kdj_k": self.kdj_k, "kdj_d": self.kdj_d, "kdj_j": self.kdj_j,
            "kdj_status": self.kdj_status.value,
            "take_profit_short": self.take_profit_short,
            "take_profit_mid": self.take_profit_mid,
            "take_profit_trailing": self.take_profit_trailing,
            "take_profit_plan": self.take_profit_plan,
            "risk_reward_ratio": self.risk_reward_ratio,
            "risk_reward_verdict": self.risk_reward_verdict,
            "resonance_count": self.resonance_count,
            "resonance_signals": self.resonance_signals,
            "resonance_bonus": self.resonance_bonus,
            "beginner_summary": self.beginner_summary,
            "pe_ratio": self.pe_ratio,
            "pb_ratio": self.pb_ratio,
            "peg_ratio": self.peg_ratio,
            "valuation_score": self.valuation_score,
            "valuation_verdict": self.valuation_verdict,
            "valuation_downgrade": self.valuation_downgrade,
            "trading_halt": self.trading_halt,
            "trading_halt_reason": self.trading_halt_reason,
            "capital_flow_score": self.capital_flow_score,
            "capital_flow_signal": self.capital_flow_signal,
            "sector_name": self.sector_name,
            "sector_pct": self.sector_pct,
            "sector_relative": self.sector_relative,
            "sector_score": self.sector_score,
            "sector_signal": self.sector_signal,
            "chip_score": self.chip_score,
            "chip_signal": self.chip_signal,
            "fundamental_score": self.fundamental_score,
            "fundamental_signal": self.fundamental_signal,
            "week52_position": self.week52_position,
        }

class StockTrendAnalyzer:

    # === 动态评分权重表（按市场环境调整） ===
    # 牛市：趋势和 MACD 权重高（顺势为王）
    # 震荡：乖离和支撑权重高（做波段）
    # 熊市：量能、支撑、RSI 权重高（防守优先）
    REGIME_WEIGHTS = {
        MarketRegime.BULL:     {"trend": 30, "bias": 12, "volume": 12, "support": 5,  "macd": 18, "rsi": 10, "kdj": 13},
        MarketRegime.SIDEWAYS: {"trend": 18, "bias": 20, "volume": 12, "support": 12, "macd": 13, "rsi": 10, "kdj": 15},
        MarketRegime.BEAR:     {"trend": 13, "bias": 17, "volume": 17, "support": 13, "macd": 12, "rsi": 13, "kdj": 15},
    }

    def analyze(self, df: pd.DataFrame, code: str, market_regime: MarketRegime = MarketRegime.SIDEWAYS, index_returns: pd.Series = None, valuation: dict = None, capital_flow: dict = None, sector_context: dict = None, chip_data: dict = None, fundamental_data: dict = None, quote_extra: dict = None) -> TrendAnalysisResult:
        result = TrendAnalysisResult(code=code)
        
        if df is None or df.empty or len(df) < 30:
            result.advice_for_empty = "数据不足，观望"
            result.advice_for_holding = "数据不足，谨慎"
            return result

        try:
            df = self._calc_indicators(df)
            latest = df.iloc[-1]
            prev = df.iloc[-2]
            
            result.current_price = float(latest['close'])
            result.ma5 = float(latest['MA5'])
            result.ma10 = float(latest['MA10'])
            result.ma20 = float(latest['MA20'])
            result.ma60 = float(latest.get('MA60', 0) or 0)
            result.atr14 = float(latest.get('ATR14', 0) or 0)

            # --- 多周期 RSI ---
            result.rsi_6 = float(latest.get(f'RSI_{self.RSI_SHORT}', 50) or 50)
            result.rsi_12 = float(latest.get(f'RSI_{self.RSI_MID}', 50) or 50)
            result.rsi_24 = float(latest.get(f'RSI_{self.RSI_LONG}', 50) or 50)
            result.rsi = result.rsi_12  # 向后兼容

            # --- MACD 数值 ---
            result.macd_dif = float(latest['MACD_DIF'])
            result.macd_dea = float(latest['MACD_DEA'])
            result.macd_bar = float(latest.get('MACD_BAR', 0) or 0)

            # --- KDJ 数值 ---
            result.kdj_k = round(float(latest.get('K', 50) or 50), 2)
            result.kdj_d = round(float(latest.get('D', 50) or 50), 2)
            result.kdj_j = round(float(latest.get('J', 50) or 50), 2)

            # --- Bollinger Bands ---
            result.bb_upper = round(float(latest.get('BB_UPPER', 0) or 0), 2)
            result.bb_lower = round(float(latest.get('BB_LOWER', 0) or 0), 2)
            result.bb_width = round(float(latest.get('BB_WIDTH', 0) or 0), 4)
            result.bb_pct_b = round(float(latest.get('BB_PCT_B', 0.5) or 0.5), 4)

            # --- 20日年化波动率 ---
            if len(df) >= 21:
                daily_ret = df['close'].pct_change().dropna().tail(20)
                result.volatility_20d = round(float(daily_ret.std() * np.sqrt(252) * 100), 2)

            # --- Beta vs 大盘 (使用 pct_chg 如有) ---
            # Beta 需要大盘收益率序列；若 pipeline 未注入则默认 1.0
            # 此处先用个股波动率 / 市场典型波动率做粗估 (后续可由 pipeline 传入大盘数据)
            # 保留默认 1.0，等 pipeline 层注入

            # --- 近60日最大回撤 ---
            if len(df) >= 60:
                high_60d = float(df['high'].tail(60).max())
                if high_60d > 0:
                    result.max_drawdown_60d = round((result.current_price - high_60d) / high_60d * 100, 2)

            # --- 动态止损锚点（Chandelier Exit + ATR自适应）---
            atr = result.atr14
            price = result.current_price
            if atr > 0:
                # 根据波动率调整ATR倍数（高波动股放宽止损，避免频繁止损）
                atr_percentile = self._calc_atr_percentile(df)
                if atr_percentile > 0.8:  # ATR处于历史高位（前20%）
                    atr_multiplier_short = 1.5  # 放宽短线止损
                    atr_multiplier_mid = 2.0
                elif atr_percentile < 0.2:  # ATR处于历史低位（后20%）
                    atr_multiplier_short = 0.8  # 收紧止损
                    atr_multiplier_mid = 1.2
                else:
                    atr_multiplier_short = 1.0  # 标准倍数
                    atr_multiplier_mid = 1.5
                
                # 日内止损（紧）
                result.stop_loss_intraday = round(price - 0.7 * atr_multiplier_short * atr, 2)
                
                # 短线止损：ATR动态倍数
                result.stop_loss_short = round(price - atr_multiplier_short * atr, 2)
                
                # 中线止损：Chandelier Exit（吊灯止损）vs MA20*0.98，取较低者
                # Chandelier Exit = 近20日最高价 - (ATR * 倍数)
                if len(df) >= 20:
                    recent_high_20d = float(df['high'].tail(20).max())
                    chandelier_sl = recent_high_20d - atr_multiplier_mid * atr
                    sl_ma20 = result.ma20 * 0.98 if result.ma20 > 0 else chandelier_sl
                    result.stop_loss_mid = round(min(chandelier_sl, sl_ma20), 2)
                else:
                    sl_atr_mid = price - atr_multiplier_mid * atr
                    sl_ma20 = result.ma20 * 0.98 if result.ma20 > 0 else sl_atr_mid
                    result.stop_loss_mid = round(min(sl_atr_mid, sl_ma20) if sl_ma20 > 0 else sl_atr_mid, 2)
            
            result.stop_loss_anchor = result.stop_loss_short  # 默认兼容
            result.ideal_buy_anchor = round(result.ma5 if result.ma5 > 0 else result.ma10, 2)

            # --- 动态止盈锚点 ---
            if atr > 0:
                # 趋势股放宽止盈，震荡股收紧止盈
                if result.trend_status in [TrendStatus.STRONG_BULL, TrendStatus.BULL]:
                    tp_multiplier_short = 2.0  # 趋势股：放宽短线止盈，避免提前离场
                    tp_multiplier_mid = 3.5
                elif result.trend_status == TrendStatus.CONSOLIDATION:
                    tp_multiplier_short = 1.2  # 震荡股：收紧止盈，快进快出
                    tp_multiplier_mid = 2.0
                else:
                    tp_multiplier_short = 1.5  # 标准倍数
                    tp_multiplier_mid = 2.5
                
                result.take_profit_short = round(price + tp_multiplier_short * atr, 2)
                
                # 中线止盈: 第一阻力位（若有）或 ATR动态倍数
                if result.resistance_levels:
                    result.take_profit_mid = round(result.resistance_levels[0], 2)
                else:
                    result.take_profit_mid = round(price + tp_multiplier_mid * atr, 2)
                
                # 移动止盈（Parabolic SAR思想）: 近20日最高价 - 动态ATR
                if len(df) >= 20:
                    recent_high = float(df['high'].tail(20).max())
                    # 趋势越强，移动止盈距离越远（避免趋势中途止盈）
                    trailing_atr_mult = 1.5 if result.trend_strength >= 75 else 1.2
                    result.take_profit_trailing = round(recent_high - trailing_atr_mult * atr, 2)
                
                # 分批止盈方案
                tp1 = result.take_profit_short
                tp2 = result.take_profit_mid
                result.take_profit_plan = (
                    f"第1批(1/3仓位): 到{tp1:.2f}止盈 | "
                    f"第2批(1/3仓位): 到{tp2:.2f}止盈 | "
                    f"第3批(底仓): 移动止盈线{result.take_profit_trailing:.2f}跟踪（Parabolic SAR）"
                )

            # --- Beta (如有大盘收益率序列) ---
            if index_returns is not None and len(df) >= 60:
                try:
                    stock_ret = df['close'].pct_change().dropna().tail(60)
                    idx_ret = index_returns.tail(60)
                    if len(stock_ret) >= 30 and len(idx_ret) >= 30:
                        # 对齐长度
                        min_len = min(len(stock_ret), len(idx_ret))
                        s = stock_ret.values[-min_len:]
                        m = idx_ret.values[-min_len:]
                        cov = np.cov(s, m)[0][1]
                        var = np.var(m)
                        if var > 0:
                            result.beta_vs_index = round(cov / var, 2)
                except Exception:
                    pass  # 保持默认 1.0

            # =============== 1. 量比 & VolumeStatus (5-state, price-volume) ===============
            vol_ma5 = df['volume'].iloc[-6:-1].mean()
            result.volume_ratio = float(latest['volume'] / vol_ma5) if vol_ma5 > 0 else 1.0
            if 'volume_ratio' in latest and latest['volume_ratio'] > 0:
                result.volume_ratio = float(latest['volume_ratio'])
            prev_close_price = float(prev['close'])
            price_change_pct = (result.current_price - prev_close_price) / prev_close_price * 100 if prev_close_price > 0 else 0
            vr = result.volume_ratio
            if vr >= self.VOLUME_HEAVY_RATIO:
                if price_change_pct > 0:
                    result.volume_status = VolumeStatus.HEAVY_VOLUME_UP
                    result.volume_trend = "放量上涨，多头力量强劲"
                else:
                    result.volume_status = VolumeStatus.HEAVY_VOLUME_DOWN
                    result.volume_trend = "放量下跌，注意风险"
            elif vr <= self.VOLUME_SHRINK_RATIO:
                if price_change_pct > 0:
                    result.volume_status = VolumeStatus.SHRINK_VOLUME_UP
                    result.volume_trend = "缩量上涨，上攻动能不足"
                else:
                    result.volume_status = VolumeStatus.SHRINK_VOLUME_DOWN
                    result.volume_trend = "缩量回调，洗盘特征明显"
            else:
                result.volume_status = VolumeStatus.NORMAL
                result.volume_trend = "量能正常"

            # =============== 2. MACD 7-state (含零轴交叉) ===============
            dif, dea = result.macd_dif, result.macd_dea
            pdif, pdea = float(prev['MACD_DIF']), float(prev['MACD_DEA'])
            is_golden_cross = (pdif - pdea) <= 0 and (dif - dea) > 0
            is_death_cross = (pdif - pdea) >= 0 and (dif - dea) < 0
            is_crossing_up = pdif <= 0 and dif > 0
            is_crossing_down = pdif >= 0 and dif < 0

            if is_golden_cross and dif > 0:
                result.macd_status = MACDStatus.GOLDEN_CROSS_ZERO
                result.macd_signal = "零轴上金叉，强烈买入信号"
            elif is_crossing_up:
                result.macd_status = MACDStatus.CROSSING_UP
                result.macd_signal = "DIF上穿零轴，趋势转强"
            elif is_golden_cross:
                result.macd_status = MACDStatus.GOLDEN_CROSS
                result.macd_signal = "金叉，趋势向上"
            elif is_death_cross:
                result.macd_status = MACDStatus.DEATH_CROSS
                result.macd_signal = "死叉，趋势向下"
            elif is_crossing_down:
                result.macd_status = MACDStatus.CROSSING_DOWN
                result.macd_signal = "DIF下穿零轴，趋势转弱"
            elif dif > 0 and dea > 0:
                result.macd_status = MACDStatus.BULLISH
                result.macd_signal = "多头排列"
            elif dif < 0 and dea < 0:
                result.macd_status = MACDStatus.BEARISH
                result.macd_signal = "空头排列"
            else:
                result.macd_status = MACDStatus.NEUTRAL
                result.macd_signal = "MACD中性"

            # =============== 3. RSI 10-state (交叉 + 背离 + 超买超卖) ===============
            rsi_mid = result.rsi_12
            rsi_short = result.rsi_6
            # RSI6/RSI12 交叉检测
            prev_rsi6 = float(prev.get(f'RSI_{self.RSI_SHORT}', 50) or 50)
            prev_rsi12 = float(prev.get(f'RSI_{self.RSI_MID}', 50) or 50)
            is_rsi_golden = (prev_rsi6 <= prev_rsi12) and (rsi_short > rsi_mid)
            is_rsi_death  = (prev_rsi6 >= prev_rsi12) and (rsi_short < rsi_mid)

            # RSI 背离检测（近 20 根 K 线）
            rsi_divergence = ""
            if len(df) >= 20:
                tail_20 = df.tail(20)
                tail_10 = df.tail(10)
                # 顶背离：近10日价格新高 > 前10日价格最高，但 RSI12 新高 < 前10日 RSI12 最高
                price_high_recent = float(tail_10['high'].max())
                price_high_prev = float(tail_20.head(10)['high'].max())
                rsi_high_recent = float(tail_10[f'RSI_{self.RSI_MID}'].max())
                rsi_high_prev = float(tail_20.head(10)[f'RSI_{self.RSI_MID}'].max())
                # 底背离：近10日价格新低 < 前10日价格最低，但 RSI12 新低 > 前10日 RSI12 最低
                price_low_recent = float(tail_10['low'].min())
                price_low_prev = float(tail_20.head(10)['low'].min())
                rsi_low_recent = float(tail_10[f'RSI_{self.RSI_MID}'].min())
                rsi_low_prev = float(tail_20.head(10)[f'RSI_{self.RSI_MID}'].min())

                if price_high_recent > price_high_prev and rsi_high_recent < rsi_high_prev - 2:
                    rsi_divergence = "顶背离"
                elif price_low_recent < price_low_prev and rsi_low_recent > rsi_low_prev + 2:
                    rsi_divergence = "底背离"
            result.rsi_divergence = rsi_divergence

            # 优先级判定：背离 > 交叉 > 超买超卖 > 区间
            if rsi_divergence == "底背离":
                result.rsi_status = RSIStatus.BULLISH_DIVERGENCE
                result.rsi_signal = f"RSI底背离(价格新低但RSI未新低)，反转买入信号"
            elif rsi_divergence == "顶背离":
                result.rsi_status = RSIStatus.BEARISH_DIVERGENCE
                result.rsi_signal = f"RSI顶背离(价格新高但RSI未新高)，回调风险"
            elif is_rsi_golden and rsi_mid < 30:
                result.rsi_status = RSIStatus.GOLDEN_CROSS_OVERSOLD
                result.rsi_signal = f"RSI超卖区金叉(RSI6={rsi_short:.1f}上穿RSI12={rsi_mid:.1f})，强买入"
            elif is_rsi_golden:
                result.rsi_status = RSIStatus.GOLDEN_CROSS
                result.rsi_signal = f"RSI金叉(RSI6={rsi_short:.1f}上穿RSI12={rsi_mid:.1f})，动能转强"
            elif is_rsi_death:
                result.rsi_status = RSIStatus.DEATH_CROSS
                result.rsi_signal = f"RSI死叉(RSI6={rsi_short:.1f}下穿RSI12={rsi_mid:.1f})，动能转弱"
            elif rsi_mid > 70:
                result.rsi_status = RSIStatus.OVERBOUGHT
                result.rsi_signal = f"RSI超买({rsi_mid:.1f}>70)，短期回调风险高"
            elif rsi_mid > 60:
                result.rsi_status = RSIStatus.STRONG_BUY
                result.rsi_signal = f"RSI强势({rsi_mid:.1f})，多头力量充足"
            elif rsi_mid >= 40:
                result.rsi_status = RSIStatus.NEUTRAL
                result.rsi_signal = f"RSI中性({rsi_mid:.1f})，震荡整理"
            elif rsi_mid >= 30:
                result.rsi_status = RSIStatus.WEAK
                result.rsi_signal = f"RSI弱势({rsi_mid:.1f})，关注反弹"
            else:
                result.rsi_status = RSIStatus.OVERSOLD
                result.rsi_signal = f"RSI超卖({rsi_mid:.1f}<30)，反弹机会大"

            # 支撑/阻力位（近 20 日高低点 + 均线）
            result.support_levels, result.resistance_levels = self._compute_levels(df, result)

            # =============== 4. 趋势判定 (含 spread expansion) ===============
            ma5, ma10, ma20 = result.ma5, result.ma10, result.ma20
            trend_score = 12
            if ma5 > ma10 > ma20:
                # 检查均线间距是否在扩大 (趋势强度)
                prev5 = df.iloc[-5] if len(df) >= 5 else prev
                prev_spread = (float(prev5['MA5']) - float(prev5['MA20'])) / float(prev5['MA20']) * 100 if float(prev5['MA20']) > 0 else 0
                curr_spread = (ma5 - ma20) / ma20 * 100 if ma20 > 0 else 0
                if curr_spread > prev_spread and curr_spread > 5:
                    result.trend_status = TrendStatus.STRONG_BULL
                    result.ma_alignment = "强势多头排列，均线发散上行"
                    result.trend_strength = 90
                    trend_score = 30
                else:
                    result.trend_status = TrendStatus.BULL
                    result.ma_alignment = "多头排列 MA5>MA10>MA20"
                    result.trend_strength = 75
                    trend_score = 26
            elif ma5 > ma10 and ma10 <= ma20:
                result.trend_status = TrendStatus.WEAK_BULL
                result.ma_alignment = "弱势多头，MA5>MA10 但 MA10<=MA20"
                result.trend_strength = 55
                trend_score = 18
            elif ma5 < ma10 < ma20:
                prev5 = df.iloc[-5] if len(df) >= 5 else prev
                prev_spread = (float(prev5['MA20']) - float(prev5['MA5'])) / float(prev5['MA5']) * 100 if float(prev5['MA5']) > 0 else 0
                curr_spread = (ma20 - ma5) / ma5 * 100 if ma5 > 0 else 0
                if curr_spread > prev_spread and curr_spread > 5:
                    result.trend_status = TrendStatus.STRONG_BEAR
                    result.ma_alignment = "强势空头排列，均线发散下行"
                    result.trend_strength = 10
                    trend_score = 0
                else:
                    result.trend_status = TrendStatus.BEAR
                    result.ma_alignment = "空头排列 MA5<MA10<MA20"
                    result.trend_strength = 25
                    trend_score = 4
            elif ma5 < ma10 and ma10 >= ma20:
                result.trend_status = TrendStatus.WEAK_BEAR
                result.ma_alignment = "弱势空头，MA5<MA10 但 MA10>=MA20"
                result.trend_strength = 40
                trend_score = 8
            else:
                result.trend_status = TrendStatus.CONSOLIDATION
                result.ma_alignment = "均线缠绕，趋势不明"
                result.trend_strength = 50
                trend_score = 12

            # =============== 5. 多周期乖离率 ===============
            result.bias_ma5 = (result.current_price - ma5) / ma5 * 100 if ma5 > 0 else 0
            result.bias_ma10 = (result.current_price - ma10) / ma10 * 100 if ma10 > 0 else 0
            result.bias_ma20 = (result.current_price - ma20) / ma20 * 100 if ma20 > 0 else 0
            bias = result.bias_ma5
            bias_score = 10
            if bias > 8:
                bias_score = 0
            elif bias > 5:
                bias_score = 5
            elif 0 <= bias <= 3 and result.trend_status in [TrendStatus.BULL, TrendStatus.STRONG_BULL]:
                bias_score = 18
            elif -3 <= bias < 0:
                bias_score = 20  # 回踩MA5，最佳买点区
            elif -5 <= bias < -3:
                bias_score = 16
            elif -10 <= bias < -5:
                bias_score = 12 if result.trend_status != TrendStatus.BEAR else 5
            elif bias < -10:
                bias_score = 8 if result.trend_status != TrendStatus.BEAR else 2

            # =============== 6. 量能评分 (0-15) ===============
            vol_scores = {
                VolumeStatus.SHRINK_VOLUME_DOWN: 15,  # 缩量回调最佳
                VolumeStatus.HEAVY_VOLUME_UP: 12,     # 放量上涨次之
                VolumeStatus.NORMAL: 10,
                VolumeStatus.SHRINK_VOLUME_UP: 6,     # 无量上涨较差
                VolumeStatus.HEAVY_VOLUME_DOWN: 0,    # 放量下跌最差
            }
            vol_score = vol_scores.get(result.volume_status, 8)

            # =============== 7. 支撑接近度 (0-10) ===============
            support_score = 5
            if result.support_levels and result.current_price > 0:
                nearest = min((s for s in result.support_levels if s > 0 and s < result.current_price), default=0) or result.ma20
                if nearest > 0:
                    dist_pct = (result.current_price - nearest) / result.current_price * 100
                    if 0 <= dist_pct <= 2:
                        support_score = 10
                    elif dist_pct <= 5:
                        support_score = 7

            # =============== 8. MACD 评分 (0-15) ===============
            macd_scores = {
                MACDStatus.GOLDEN_CROSS_ZERO: 15,
                MACDStatus.GOLDEN_CROSS: 12,
                MACDStatus.CROSSING_UP: 10,
                MACDStatus.BULLISH: 8,
                MACDStatus.NEUTRAL: 5,
                MACDStatus.BEARISH: 2,
                MACDStatus.CROSSING_DOWN: 0,
                MACDStatus.DEATH_CROSS: 0,
            }
            macd_score = macd_scores.get(result.macd_status, 5)

            # =============== 9. KDJ 8-state 分析 & 评分 (0-13) ===============
            k_val, d_val, j_val = result.kdj_k, result.kdj_d, result.kdj_j
            pk_val, pd_val = float(prev.get('K', 50) or 50), float(prev.get('D', 50) or 50)
            is_kdj_golden = (pk_val <= pd_val) and (k_val > d_val)   # K 上穿 D
            is_kdj_death  = (pk_val >= pd_val) and (k_val < d_val)   # K 下穿 D

            if is_kdj_golden and j_val < 20:
                result.kdj_status = KDJStatus.GOLDEN_CROSS_OVERSOLD
                result.kdj_signal = f"超卖区金叉(J={j_val:.1f}<20)，强买入信号"
            elif j_val > 100:
                result.kdj_status = KDJStatus.OVERBOUGHT
                result.kdj_signal = f"J值超买({j_val:.1f}>100)，短期回调风险"
            elif j_val < 0:
                result.kdj_status = KDJStatus.OVERSOLD
                result.kdj_signal = f"J值超卖({j_val:.1f}<0)，反弹机会"
            elif is_kdj_golden:
                result.kdj_status = KDJStatus.GOLDEN_CROSS
                result.kdj_signal = f"金叉(K={k_val:.1f}>D={d_val:.1f})，趋势向上"
            elif is_kdj_death:
                result.kdj_status = KDJStatus.DEATH_CROSS
                result.kdj_signal = f"死叉(K={k_val:.1f}<D={d_val:.1f})，趋势向下"
            elif k_val > d_val and j_val > 50:
                result.kdj_status = KDJStatus.BULLISH
                result.kdj_signal = f"多头排列(K={k_val:.1f}>D={d_val:.1f})，偏强"
            elif k_val < d_val and j_val < 50:
                result.kdj_status = KDJStatus.BEARISH
                result.kdj_signal = f"空头排列(K={k_val:.1f}<D={d_val:.1f})，偏弱"
            else:
                result.kdj_status = KDJStatus.NEUTRAL
                result.kdj_signal = f"KDJ中性(K={k_val:.1f} D={d_val:.1f} J={j_val:.1f})"

            kdj_scores = {
                KDJStatus.GOLDEN_CROSS_OVERSOLD: 13,
                KDJStatus.OVERSOLD: 11,
                KDJStatus.GOLDEN_CROSS: 10,
                KDJStatus.BULLISH: 7,
                KDJStatus.NEUTRAL: 5,
                KDJStatus.BEARISH: 3,
                KDJStatus.DEATH_CROSS: 1,
                KDJStatus.OVERBOUGHT: 0,
            }
            kdj_score = kdj_scores.get(result.kdj_status, 5)

            # =============== 10. RSI 评分 (0-10) ===============
            rsi_scores = {
                RSIStatus.GOLDEN_CROSS_OVERSOLD: 10,  # 超卖区金叉：最强买入
                RSIStatus.BULLISH_DIVERGENCE: 10,      # 底背离：强反转信号
                RSIStatus.OVERSOLD: 9,
                RSIStatus.GOLDEN_CROSS: 8,             # 普通金叉：动能转强
                RSIStatus.STRONG_BUY: 7,
                RSIStatus.NEUTRAL: 5,
                RSIStatus.WEAK: 3,
                RSIStatus.DEATH_CROSS: 2,              # 死叉：动能转弱
                RSIStatus.BEARISH_DIVERGENCE: 1,       # 顶背离：强回调信号
                RSIStatus.OVERBOUGHT: 0,
            }
            rsi_score = rsi_scores.get(result.rsi_status, 5)

            # =============== 11. 动态加权评分 ===============
            # 各维度的原始得分率（0.0~1.0），与权重无关
            raw = {
                "trend": trend_score / 30,
                "bias": bias_score / 20,
                "volume": vol_score / 15,
                "support": support_score / 10,
                "macd": macd_score / 15,
                "rsi": rsi_score / 10,
                "kdj": kdj_score / 13,
            }
            weights = self.REGIME_WEIGHTS.get(market_regime, self.REGIME_WEIGHTS[MarketRegime.SIDEWAYS])
            result.score_breakdown = {k: min(weights[k], round(raw[k] * weights[k])) for k in raw}
            score = sum(result.score_breakdown.values())
            score = min(100, max(0, score))
            result.signal_score = int(score)
            
            self._update_buy_signal(result)

            # =============== 11-Pre. 指标组合共振判断 & 市场行为识别 ===============
            self._detect_indicator_resonance(result, df, prev)
            self._detect_market_behavior(result, df)
            
            # =============== 11-Pre2. 多时间周期共振验证 ===============
            self._check_multi_timeframe_resonance(result, df)

            # =============== 11a. 估值安全检查（估值降档） ===============
            self._check_valuation(result, valuation)

            # =============== 11b. 全局暂停信号 ===============
            self._check_trading_halt(result)

            # =============== 11c. 资金面评分 ===============
            self._score_capital_flow(result, capital_flow)

            # =============== 11c2. 资金面连续性（近3日量价趋势） ===============
            self._score_capital_flow_trend(result, df)

            # =============== 11e. 板块强弱评分 ===============
            self._score_sector_strength(result, sector_context)

            # =============== 11f. 筹码分布评分 ===============
            self._score_chip_distribution(result, chip_data)

            # =============== 11g. 基本面质量评分 ===============
            self._score_fundamental_quality(result, fundamental_data)

            # =============== 11h. 52周位置 + 换手率异常 ===============
            self._score_quote_extra(result, quote_extra)

            # =============== 11i. 修正因子总量上限 ===============
            self._cap_adjustments(result)

            # =============== 11j. 信号冲突检测 ===============
            self._detect_signal_conflict(result)

            # =============== 11d. 仓位管理（量化硬规则） ===============
            self._calc_position(result, market_regime)
            
            # =============== 12. 多指标共振检测 ===============
            self._check_resonance(result)

            # =============== 13. 风险收益比 ===============
            self._calc_risk_reward(result, price)

            # === 核心逻辑：生成分情况建议 ===
            self._generate_detailed_advice(result)

            # =============== 14. 白话版解读 ===============
            self._generate_beginner_summary(result)

            return result

        except Exception as e:
            logger.error(f"[{code}] 分析异常: {e}")
            return result

    def _detect_indicator_resonance(self, result: TrendAnalysisResult, df: pd.DataFrame, prev: pd.Series):
        """指标组合共振判断：识别关键买卖信号
        
        组合逻辑：
        1. MACD水下金叉 + KDJ金叉 + 缩量：底部吸筹信号 ★★★★★
        2. MACD零轴上金叉 + KDJ金叉 + 放量上涨：主升浪启动 ★★★★★
        3. MACD金叉 + RSI底背离：反转信号 ★★★★
        4. MACD死叉 + KDJ死叉 + 放量下跌：恐慌抛售 ☆☆☆☆☆
        5. MACD死叉 + RSI顶背离：顶部信号 ☆☆☆☆
        6. 放量上涨 + KDJ超买 + MACD高位：诱多嫌疑 ☆☆☆
        7. 缩量下跌 + KDJ超卖 + MACD低位：洗盘特征 ★★★
        """
        resonance_signals = []
        resonance_score_adj = 0
        
        macd_status = result.macd_status
        kdj_status = result.kdj_status
        rsi_status = result.rsi_status
        vol_status = result.volume_status
        
        dif, dea = result.macd_dif, result.macd_dea
        j_val = result.kdj_j
        
        # === 组合 1：MACD水下金叉 + KDJ金叉 + 缩量：底部吸筹 ===
        if (macd_status == MACDStatus.GOLDEN_CROSS and dif < 0 and dea < 0 and 
            kdj_status in [KDJStatus.GOLDEN_CROSS, KDJStatus.GOLDEN_CROSS_OVERSOLD] and
            vol_status in [VolumeStatus.SHRINK_VOLUME_UP, VolumeStatus.NORMAL]):
            resonance_signals.append("★★★★★ 底部吸筹信号：MACD水下金叉+KDJ金叉+缩量，主力建仓阶段")
            resonance_score_adj += 10
        
        # === 组合 2：MACD零轴上金叉 + KDJ金叉 + 放量上涨：主升浪启动 ===
        elif (macd_status == MACDStatus.GOLDEN_CROSS_ZERO and 
              kdj_status in [KDJStatus.GOLDEN_CROSS, KDJStatus.BULLISH] and
              vol_status == VolumeStatus.HEAVY_VOLUME_UP):
            resonance_signals.append("★★★★★ 主升浪启动：MACD零轴上金叉+KDJ金叉+放量突破，趋势行情")
            resonance_score_adj += 12
        
        # === 组合 3：MACD金叉 + RSI底背离：反转信号 ===
        elif (macd_status in [MACDStatus.GOLDEN_CROSS, MACDStatus.GOLDEN_CROSS_ZERO] and
              rsi_status == RSIStatus.BULLISH_DIVERGENCE):
            resonance_signals.append("★★★★ 反转信号：MACD金叉+RSI底背离，跌不动了")
            resonance_score_adj += 8
        
        # === 组合 4：MACD死叉 + KDJ死叉 + 放量下跌：恐慌抛售 ===
        if (macd_status == MACDStatus.DEATH_CROSS and
            kdj_status == KDJStatus.DEATH_CROSS and
            vol_status == VolumeStatus.HEAVY_VOLUME_DOWN):
            resonance_signals.append("☆☆☆☆☆ 恐慌抛售：MACD+KDJ双死叉+放量下跌，赶紧离场")
            resonance_score_adj -= 15
        
        # === 组合 5：MACD死叉 + RSI顶背离：顶部信号 ===
        elif (macd_status == MACDStatus.DEATH_CROSS and
              rsi_status == RSIStatus.BEARISH_DIVERGENCE):
            resonance_signals.append("☆☆☆☆ 顶部信号：MACD死叉+RSI顶背离，涨不上去了")
            resonance_score_adj -= 10
        
        # === 组合 6：放量上涨 + KDJ超买 + MACD高位：诱多嫌疑 ===
        if (vol_status == VolumeStatus.HEAVY_VOLUME_UP and
            kdj_status == KDJStatus.OVERBOUGHT and
            dif > 0 and dif > dea and result.trend_strength < 70):
            resonance_signals.append("☆☆☆ 诱多嫌疑：高位放量+KDJ超买，小心接盘")
            resonance_score_adj -= 5
        
        # === 组合 7：缩量下跌 + KDJ超卖 + MACD低位：洗盘特征 ===
        if (vol_status == VolumeStatus.SHRINK_VOLUME_DOWN and
            kdj_status in [KDJStatus.OVERSOLD, KDJStatus.GOLDEN_CROSS_OVERSOLD] and
            dif < 0 and result.trend_strength > 60):
            resonance_signals.append("★★★ 洗盘特征：缩量回调+KDJ超卖，不破MA20可接")
            resonance_score_adj += 5
        
        # === 应用共振调整 ===
        if resonance_signals:
            result.indicator_resonance = "\n".join(resonance_signals)
            result.signal_score = max(0, min(100, result.signal_score + resonance_score_adj))
            result.score_breakdown['resonance_adj'] = resonance_score_adj
            self._update_buy_signal(result)
        else:
            result.indicator_resonance = ""

    def _detect_market_behavior(self, result: TrendAnalysisResult, df: pd.DataFrame):
        """市场行为识别：诱多/诱空/吸筹/洗盘/拉升/出货
        
        识别逻辑：
        1. 诱多：高位大阳线+巨量+次日低开低走（需要次日数据，暂用当日特征）
        2. 诱空：低位大阴线+巨量+次日高开高走
        3. 吸筹：低位缩量震荡+MACD水下+慢慢探底
        4. 洗盘：中位缩量回调+不破关键均线+KDJ超卖后反弹
        5. 拉升：持续放量上涨+重心上移+均线多头发散
        6. 出货：高位震荡+量价背离+MACD顶背离
        """
        if df is None or len(df) < 10:
            result.market_behavior = ""
            return
        
        behavior_signals = []
        
        latest = df.iloc[-1]
        prev = df.iloc[-2] if len(df) >= 2 else latest
        recent_5 = df.tail(5)
        recent_10 = df.tail(10)
        
        close = float(latest['close'])
        open_price = float(latest['open'])
        high = float(latest['high'])
        low = float(latest['low'])
        volume = float(latest['volume'])
        
        # 阳线/阴线实体大小
        body_size = abs(close - open_price) / open_price * 100 if open_price > 0 else 0
        is_big_candle = body_size > 5  # 实体超过5%
        is_yang = close > open_price
        
        # 量比
        vol_ratio = result.volume_ratio
        
        # 价格位置：相对于60日高低点
        if len(df) >= 60:
            high_60 = float(df['high'].tail(60).max())
            low_60 = float(df['low'].tail(60).min())
            price_position = (close - low_60) / (high_60 - low_60) * 100 if high_60 > low_60 else 50
        else:
            price_position = 50
        
        # === 1. 诱多判断 ===
        if (price_position > 70 and is_big_candle and is_yang and vol_ratio > 2.5 and
            result.kdj_status == KDJStatus.OVERBOUGHT and
            result.rsi_status in [RSIStatus.OVERBOUGHT, RSIStatus.BEARISH_DIVERGENCE]):
            behavior_signals.append("🚨 诱多嫌疑：高位巨量长阳+KDJ/RSI超买，谨防接盘")
        
        # === 2. 诱空判断 ===
        elif (price_position < 30 and is_big_candle and not is_yang and vol_ratio > 2.5 and
              result.kdj_status == KDJStatus.OVERSOLD and
              result.rsi_status in [RSIStatus.OVERSOLD, RSIStatus.BULLISH_DIVERGENCE]):
            behavior_signals.append("🔥 诱空嫌疑：低位巨量长阴+KDJ/RSI超卖，反弹在即")
        
        # === 3. 吸筹判断 ===
        if (price_position < 40 and 
            result.macd_status in [MACDStatus.BEARISH, MACDStatus.NEUTRAL] and
            result.macd_dif < 0 and
            vol_ratio < 1.2 and
            len(recent_10) >= 10):
            # 检查是否缓慢探底（近10日波动率低）
            recent_volatility = (recent_10['high'].max() - recent_10['low'].min()) / recent_10['low'].min() * 100
            if recent_volatility < 15:  # 波动率<15%
                behavior_signals.append("🧠 疑似吸筹：低位缩量震荡+MACD水下，主力慢慢建仓")
        
        # === 4. 洗盘判断 ===
        if (40 <= price_position <= 70 and
            result.volume_status in [VolumeStatus.SHRINK_VOLUME_DOWN, VolumeStatus.SHRINK_VOLUME_UP] and
            result.kdj_status in [KDJStatus.OVERSOLD, KDJStatus.GOLDEN_CROSS_OVERSOLD] and
            result.current_price > result.ma20 and
            result.trend_strength >= 65):
            behavior_signals.append("🌀 洗盘特征：缩量回调+不破MA20+KDJ超卖，上车机会")
        
        # === 5. 拉升判断 ===
        if (result.trend_status in [TrendStatus.STRONG_BULL, TrendStatus.BULL] and
            len(recent_5) >= 5):
            # 检查近5日是否持续放量上涨
            up_days = sum(1 for i in range(len(recent_5)) if recent_5.iloc[i]['close'] > recent_5.iloc[i]['open'])
            avg_vol_ratio = recent_5['volume'].mean() / df['volume'].tail(20).mean() if len(df) >= 20 else 1.0
            if up_days >= 4 and avg_vol_ratio > 1.3:
                behavior_signals.append("🚀 拉升阶段：持续放量上涨+均线多头，跟着主力吃肉")
        
        # === 6. 出货判断 ===
        if (price_position > 75 and
            result.rsi_status in [RSIStatus.BEARISH_DIVERGENCE, RSIStatus.OVERBOUGHT] and
            result.macd_status in [MACDStatus.DEATH_CROSS, MACDStatus.CROSSING_DOWN] and
            len(recent_5) >= 5):
            # 检查是否量价背离（价格新高但量能萎竭）
            price_high_recent = recent_5['high'].max()
            price_high_prev = df.tail(10).head(5)['high'].max() if len(df) >= 10 else 0
            vol_recent = recent_5['volume'].mean()
            vol_prev = df.tail(10).head(5)['volume'].mean() if len(df) >= 10 else vol_recent
            if price_high_recent > price_high_prev and vol_recent < vol_prev * 0.8:
                behavior_signals.append("⚠️ 出货嫌疑：高位震荡+量价背离+指标顶背离，先走为妙")
        
        result.market_behavior = "\n".join(behavior_signals) if behavior_signals else ""

    def _check_multi_timeframe_resonance(self, result: TrendAnalysisResult, df: pd.DataFrame):
        """多时间周期共振验证：日线 + 周线共振
        
        逻辑：
        1. 将日线数据 resample 为周线
        2. 计算周线的 MACD、KDJ、MA趋势
        3. 判断日线和周线是否同向
        4. 共振加分，背离减分
        
        共振级别：
        - 强共振：日线+周线同时金叉/死叉 +5分
        - 中共振：日线+周线趋势一致 +3分
        - 背离：日线多头但周线空头 -5分
        """
        if df is None or len(df) < 60:  # 至少需要60个交易日（约12周）
            result.timeframe_resonance = ""
            return
        
        try:
            # === 1. 将日线 resample 为周线 ===
            weekly_df = self._resample_to_weekly(df)
            if weekly_df is None or len(weekly_df) < 5:
                result.timeframe_resonance = ""
                return
            
            # === 2. 计算周线指标 ===
            weekly_df = self._calc_indicators(weekly_df)
            if len(weekly_df) < 3:
                result.timeframe_resonance = ""
                return
            
            weekly_latest = weekly_df.iloc[-1]
            weekly_prev = weekly_df.iloc[-2]
            
            # 周线 MACD
            weekly_dif = float(weekly_latest.get('MACD_DIF', 0))
            weekly_dea = float(weekly_latest.get('MACD_DEA', 0))
            weekly_prev_dif = float(weekly_prev.get('MACD_DIF', 0))
            weekly_prev_dea = float(weekly_prev.get('MACD_DEA', 0))
            
            weekly_macd_golden = (weekly_prev_dif <= weekly_prev_dea) and (weekly_dif > weekly_dea)
            weekly_macd_death = (weekly_prev_dif >= weekly_prev_dea) and (weekly_dif < weekly_dea)
            weekly_macd_bullish = weekly_dif > 0 and weekly_dea > 0
            weekly_macd_bearish = weekly_dif < 0 and weekly_dea < 0
            
            # 周线 KDJ
            weekly_k = float(weekly_latest.get('K', 50))
            weekly_d = float(weekly_latest.get('D', 50))
            weekly_prev_k = float(weekly_prev.get('K', 50))
            weekly_prev_d = float(weekly_prev.get('D', 50))
            
            weekly_kdj_golden = (weekly_prev_k <= weekly_prev_d) and (weekly_k > weekly_d)
            weekly_kdj_death = (weekly_prev_k >= weekly_prev_d) and (weekly_k < weekly_d)
            weekly_kdj_bullish = weekly_k > weekly_d
            weekly_kdj_bearish = weekly_k < weekly_d
            
            # 周线MA趋势
            weekly_ma5 = float(weekly_latest.get('MA5', 0))
            weekly_ma10 = float(weekly_latest.get('MA10', 0))
            weekly_ma20 = float(weekly_latest.get('MA20', 0))
            weekly_ma_bull = weekly_ma5 > weekly_ma10 > weekly_ma20
            weekly_ma_bear = weekly_ma5 < weekly_ma10 < weekly_ma20
            
            # === 3. 日线指标（已计算）===
            daily_macd_golden = result.macd_status in [MACDStatus.GOLDEN_CROSS, MACDStatus.GOLDEN_CROSS_ZERO]
            daily_macd_death = result.macd_status == MACDStatus.DEATH_CROSS
            daily_macd_bullish = result.macd_status in [MACDStatus.BULLISH, MACDStatus.GOLDEN_CROSS_ZERO, MACDStatus.CROSSING_UP]
            daily_macd_bearish = result.macd_status in [MACDStatus.BEARISH, MACDStatus.CROSSING_DOWN]
            
            daily_kdj_golden = result.kdj_status in [KDJStatus.GOLDEN_CROSS, KDJStatus.GOLDEN_CROSS_OVERSOLD]
            daily_kdj_death = result.kdj_status == KDJStatus.DEATH_CROSS
            daily_kdj_bullish = result.kdj_status in [KDJStatus.BULLISH, KDJStatus.GOLDEN_CROSS]
            daily_kdj_bearish = result.kdj_status in [KDJStatus.BEARISH, KDJStatus.DEATH_CROSS]
            
            daily_ma_bull = result.trend_status in [TrendStatus.STRONG_BULL, TrendStatus.BULL]
            daily_ma_bear = result.trend_status == TrendStatus.BEAR
            
            # === 4. 共振判断 ===
            resonance_signals = []
            resonance_adj = 0
            
            # 强共振：日线+周线同时金叉
            if daily_macd_golden and weekly_macd_golden:
                resonance_signals.append("🔥🔥 日周共振：MACD同时金叉，趋势确认")
                resonance_adj += 8
            
            if daily_kdj_golden and weekly_kdj_golden:
                resonance_signals.append("🔥🔥 日周共振：KDJ同时金叉，动能强劲")
                resonance_adj += 6
            
            # 中共振：日线+周线趋势一致
            if daily_ma_bull and weekly_ma_bull:
                if not (daily_macd_golden and weekly_macd_golden):  # 避免重复计分
                    resonance_signals.append("✅ 日周趋势一致：均线多头排列")
                    resonance_adj += 4
            
            if daily_macd_bullish and weekly_macd_bullish:
                if not (daily_macd_golden and weekly_macd_golden):
                    resonance_signals.append("✅ MACD多周期多头")
                    resonance_adj += 3
            
            if daily_kdj_bullish and weekly_kdj_bullish:
                if not (daily_kdj_golden and weekly_kdj_golden):
                    resonance_signals.append("✅ KDJ多周期多头")
                    resonance_adj += 2
            
            # 背离警告：日线多头但周线空头
            if daily_ma_bull and weekly_ma_bear:
                resonance_signals.append("⚠️ 多周期背离：日线多头但周线空头，谨防回调")
                resonance_adj -= 5
            
            if daily_macd_bullish and weekly_macd_bearish:
                if not (daily_ma_bull and weekly_ma_bear):  # 避免重复减分
                    resonance_signals.append("⚠️ MACD周线空头，日线反弹需谨慎")
                    resonance_adj -= 3
            
            # 强空头共振
            if daily_macd_death and weekly_macd_death:
                resonance_signals.append("❗❗ 日周共振：MACD同时死叉，趋势转弱")
                resonance_adj -= 8
            
            if daily_kdj_death and weekly_kdj_death:
                resonance_signals.append("❗❗ 日周共振：KDJ同时死叉，动能转弱")
                resonance_adj -= 6
            
            # === 5. 应用共振调整 ===
            if resonance_signals:
                result.timeframe_resonance = "\n".join(resonance_signals)
                result.signal_score = max(0, min(100, result.signal_score + resonance_adj))
                result.score_breakdown['timeframe_adj'] = resonance_adj
                self._update_buy_signal(result)
            else:
                result.timeframe_resonance = ""
        
        except Exception as e:
            logger.debug(f"多周期共振计算失败: {e}")
            result.timeframe_resonance = ""
    
    def _resample_to_weekly(self, df: pd.DataFrame) -> pd.DataFrame:
        """将日线K线 resample 为周线K线
        
        Args:
            df: 日线数据，必须包含 date列且为DatetimeIndex或可转换为DatetimeIndex
        
        Returns:
            周线数据
        """
        try:
            df_copy = df.copy()
            
            # 确保date列存在且为DatetimeIndex
            if 'date' in df_copy.columns:
                df_copy['date'] = pd.to_datetime(df_copy['date'])
                df_copy = df_copy.set_index('date')
            elif not isinstance(df_copy.index, pd.DatetimeIndex):
                return None
            
            # Resample为周线（周一开始）
            weekly = df_copy.resample('W-MON').agg({
                'open': 'first',
                'high': 'max',
                'low': 'min',
                'close': 'last',
                'volume': 'sum',
            }).dropna()
            
            return weekly
            
        except Exception as e:
            logger.debug(f"Resample到周线失败: {e}")
            return None

    def _check_valuation(self, result: TrendAnalysisResult, valuation: dict = None):
        """估值安全检查：PE/PB/PEG 评分 + 估值降档"""
        if not valuation or not isinstance(valuation, dict):
            return

        pe = valuation.get('pe')
        pb = valuation.get('pb')
        peg = valuation.get('peg')
        if isinstance(pe, (int, float)) and pe > 0:
            result.pe_ratio = float(pe)
        if isinstance(pb, (int, float)) and pb > 0:
            result.pb_ratio = float(pb)
        if isinstance(peg, (int, float)) and peg > 0:
            result.peg_ratio = float(peg)

        # 估值评分 (0-10, 10=严重低估)
        v_score = 5  # 默认中性
        downgrade = 0
        industry_pe = valuation.get('industry_pe_median')

        if result.pe_ratio > 0:
            if isinstance(industry_pe, (int, float)) and industry_pe > 0:
                # === 行业相对估值模式 ===
                pe_ratio_rel = result.pe_ratio / industry_pe
                if pe_ratio_rel > 3.0:
                    v_score = 0
                    downgrade = -15
                    result.valuation_verdict = f"严重高估(PE{result.pe_ratio:.0f},行业中位{industry_pe:.0f},倍率{pe_ratio_rel:.1f}x)"
                elif pe_ratio_rel > 2.0:
                    v_score = 2
                    downgrade = -10
                    result.valuation_verdict = f"偏高(PE{result.pe_ratio:.0f},行业{industry_pe:.0f},{pe_ratio_rel:.1f}x)"
                elif pe_ratio_rel > 1.3:
                    v_score = 4
                    downgrade = -3
                    result.valuation_verdict = f"略高(PE{result.pe_ratio:.0f},行业{industry_pe:.0f},{pe_ratio_rel:.1f}x)"
                elif pe_ratio_rel >= 0.7:
                    v_score = 6
                    result.valuation_verdict = f"合理(PE{result.pe_ratio:.0f},行业{industry_pe:.0f},{pe_ratio_rel:.1f}x)"
                elif pe_ratio_rel >= 0.4:
                    v_score = 8
                    result.valuation_verdict = f"偏低(PE{result.pe_ratio:.0f},行业{industry_pe:.0f},{pe_ratio_rel:.1f}x)"
                else:
                    v_score = 10
                    result.valuation_verdict = f"低估(PE{result.pe_ratio:.0f},行业{industry_pe:.0f},{pe_ratio_rel:.1f}x)"
            else:
                # === 绝对估值 fallback（无行业数据时） ===
                if result.pe_ratio > 100:
                    v_score = 0
                    downgrade = -15
                    result.valuation_verdict = "严重高估"
                elif result.pe_ratio > 60:
                    v_score = 2
                    downgrade = -10
                    result.valuation_verdict = "偏高"
                elif result.pe_ratio > 30:
                    v_score = 4
                    downgrade = -3
                    result.valuation_verdict = "略高"
                elif result.pe_ratio > 15:
                    v_score = 6
                    result.valuation_verdict = "合理"
                elif result.pe_ratio > 8:
                    v_score = 8
                    result.valuation_verdict = "偏低"
                else:
                    v_score = 10
                    result.valuation_verdict = "低估"

            # PEG 修正（PEG < 1 说明增速匹配估值，可放宽）
            if result.peg_ratio > 0:
                if result.peg_ratio < 0.5:
                    v_score = min(10, v_score + 3)
                    downgrade = max(0, downgrade + 5)  # 回补降档
                    result.valuation_verdict += "(PEG极低,增速优秀)"
                elif result.peg_ratio < 1.0:
                    v_score = min(10, v_score + 1)
                    downgrade = max(0, downgrade + 3)
                    result.valuation_verdict += "(PEG合理)"
                elif result.peg_ratio > 3.0:
                    v_score = max(0, v_score - 2)
                    downgrade = min(downgrade, downgrade - 3)
                    result.valuation_verdict += "(PEG过高,增速不匹配)"

        result.valuation_score = v_score
        result.valuation_downgrade = downgrade

        # 应用估值降档到评分
        if downgrade < 0:
            result.signal_score = max(0, result.signal_score + downgrade)
            result.score_breakdown['valuation_adj'] = downgrade
            # 降档后重新判定信号
            self._update_buy_signal(result)

    def _check_trading_halt(self, result: TrendAnalysisResult):
        """全局暂停信号检测：极端波动率、深度回撤、流动性枯竭、停牌"""
        halt_reasons = []
        # 检查1: ST / *ST / 退市风险（通过股票代码前缀判断不可靠，通过名称判断更准）
        # 这个检查交由 pipeline 层注入 code_name，此处检查异常技术面
        # 检查2: 极端波动率（20日年化波动率 > 100%）
        if result.volatility_20d > 100:
            halt_reasons.append(f"波动率异常({result.volatility_20d:.0f}%>100%)，疑似妖股")
        # 检查3: 近60日回撤超过40%
        if result.max_drawdown_60d < -40:
            halt_reasons.append(f"近60日回撤{result.max_drawdown_60d:.1f}%，跌幅过大")
        # 检查4: 连续缩量到极值（量比 < 0.3）且价格在布林下轨下方
        if result.volume_ratio < 0.3 and result.bb_pct_b < 0:
            halt_reasons.append("极端缩量+跌破布林下轨，流动性枯竭风险")
        # 检查5: ATR = 0（停牌或数据异常）
        if result.atr14 <= 0:
            halt_reasons.append("ATR为零，可能停牌或数据异常")

        if halt_reasons:
            result.trading_halt = True
            result.trading_halt_reason = "；".join(halt_reasons)
            result.advice_for_empty = f"🚫 暂停交易：{result.trading_halt_reason}"
            result.advice_for_holding = f"⚠️ 风险警告：{result.trading_halt_reason}，持仓者评估是否离场"

    def _score_capital_flow(self, result: TrendAnalysisResult, capital_flow: dict = None):
        """资金面评分：北向资金、主力资金、融资余额"""
        if not capital_flow or not isinstance(capital_flow, dict):
            return

        cf_score = 5  # 默认中性
        cf_signals = []

        # 北向资金
        north_net = capital_flow.get('north_net_flow')  # 正=流入(亿)
        if isinstance(north_net, (int, float)):
            if north_net > 50:
                cf_score += 3
                cf_signals.append(f"北向大幅流入{north_net:.1f}亿")
            elif north_net > 10:
                cf_score += 1
                cf_signals.append(f"北向净流入{north_net:.1f}亿")
            elif north_net < -50:
                cf_score -= 3
                cf_signals.append(f"⚠️北向大幅流出{north_net:.1f}亿")
            elif north_net < -10:
                cf_score -= 1
                cf_signals.append(f"北向净流出{north_net:.1f}亿")

        # 主力资金（阈值与日均成交额挂钩，默认 fallback 到绝对值 5000 万）
        main_net = capital_flow.get('main_net_flow')  # 正=流入(万)
        daily_avg = capital_flow.get('daily_avg_amount')  # 日均成交额(万)
        if isinstance(main_net, (int, float)):
            if isinstance(daily_avg, (int, float)) and daily_avg > 0:
                # 相对阈值：主力净流入/流出超过日均成交额的 5% 视为显著
                main_threshold = daily_avg * 0.05
                main_large_threshold = daily_avg * 0.15
            else:
                # 绝对阈值 fallback
                main_threshold = 5000   # 5000万
                main_large_threshold = 15000  # 1.5亿
            if main_net > main_large_threshold:
                cf_score += 3
                cf_signals.append(f"主力大幅净流入{main_net/10000:.1f}亿")
            elif main_net > main_threshold:
                cf_score += 2
                cf_signals.append(f"主力净流入{main_net/10000:.1f}亿")
            elif main_net < -main_large_threshold:
                cf_score -= 3
                cf_signals.append(f"⚠️主力大幅净流出{abs(main_net)/10000:.1f}亿")
            elif main_net < -main_threshold:
                cf_score -= 2
                cf_signals.append(f"⚠️主力净流出{abs(main_net)/10000:.1f}亿")

        # 融资余额变化
        margin_change = capital_flow.get('margin_balance_change')  # 正=增加
        if isinstance(margin_change, (int, float)):
            if margin_change > 0:
                cf_score += 1
                cf_signals.append(f"融资余额增加")
            elif margin_change < -1e8:  # 减少超过1亿
                cf_score -= 1
                cf_signals.append(f"融资余额减少")

        result.capital_flow_score = max(0, min(10, cf_score))
        result.capital_flow_signal = "；".join(cf_signals) if cf_signals else "资金面数据正常"

        # 资金面对 signal_score 的影响（±5 分上限）
        cf_adj = cf_score - 5
        if cf_adj != 0:
            result.signal_score = max(0, min(100, result.signal_score + cf_adj))
            result.score_breakdown['capital_flow_adj'] = cf_adj
            self._update_buy_signal(result)

    def _score_capital_flow_trend(self, result: TrendAnalysisResult, df: pd.DataFrame):
        """资金面连续性检测：近3日量价关系判断持续性资金流向

        逻辑：
        - 连续3日放量上涨(close>open, volume递增) → 持续流入 +2
        - 连续3日缩量下跌(close<open, volume递减) → 持续流出 -2
        - 连续3日放量下跌 → 恐慌抛售 -3
        """
        if df is None or len(df) < 5:
            return

        recent = df.tail(3)
        if len(recent) < 3:
            return

        closes = recent['close'].values
        opens = recent['open'].values
        volumes = recent['volume'].values

        # 判断连续涨跌
        up_days = sum(1 for c, o in zip(closes, opens) if c > o)
        down_days = sum(1 for c, o in zip(closes, opens) if c < o)

        # 判断量能趋势
        vol_increasing = volumes[-1] > volumes[-2] > volumes[-3] if all(v > 0 for v in volumes) else False
        vol_decreasing = volumes[-1] < volumes[-2] < volumes[-3] if all(v > 0 for v in volumes) else False

        adj = 0
        if up_days == 3 and vol_increasing:
            adj = 2
            result.score_breakdown['cf_trend'] = 2
        elif down_days == 3 and vol_increasing:
            adj = -3
            result.score_breakdown['cf_trend'] = -3
        elif down_days == 3 and vol_decreasing:
            adj = -2
            result.score_breakdown['cf_trend'] = -2

        if adj != 0:
            result.signal_score = max(0, min(100, result.signal_score + adj))
            self._update_buy_signal(result)

    def _score_sector_strength(self, result: TrendAnalysisResult, sector_context: dict = None):
        """板块强弱评分：板块涨跌 + 个股相对板块强弱 → 加减分

        评分逻辑：
        - 板块当日涨幅 > 2%  → 板块强势 +2
        - 板块当日涨幅 > 0%  → 板块偏强 +1
        - 板块当日跌幅 > 2%  → 板块弱势 -2
        - 板块当日跌幅 > 0%  → 板块偏弱 -1
        - 个股跑赢板块 > 2pp → 强势股 +2
        - 个股跑赢板块 > 0pp → 偏强 +1
        - 个股跑输板块 > 2pp → 弱势股 -2
        - 个股跑输板块 > 0pp → 偏弱 -1

        板块评分影响 signal_score（±5 分上限），并更新 buy_signal。
        """
        if not sector_context or not isinstance(sector_context, dict):
            return

        sec_name = sector_context.get('sector_name', '')
        sec_pct = sector_context.get('sector_pct')
        rel = sector_context.get('relative')  # stock_pct - sector_pct

        if sec_name:
            result.sector_name = sec_name
        if isinstance(sec_pct, (int, float)):
            result.sector_pct = round(sec_pct, 2)
        if isinstance(rel, (int, float)):
            result.sector_relative = round(rel, 2)

        sec_score = 5  # 中性基准
        signals = []

        # 板块绝对强弱
        if isinstance(sec_pct, (int, float)):
            if sec_pct > 2.0:
                sec_score += 2
                signals.append(f"{sec_name}板块强势(+{sec_pct:.1f}%)")
            elif sec_pct > 0:
                sec_score += 1
                signals.append(f"{sec_name}板块偏强(+{sec_pct:.1f}%)")
            elif sec_pct < -2.0:
                sec_score -= 2
                signals.append(f"⚠️{sec_name}板块弱势({sec_pct:.1f}%)")
            elif sec_pct < 0:
                sec_score -= 1
                signals.append(f"{sec_name}板块偏弱({sec_pct:.1f}%)")

        # 个股相对板块强弱
        if isinstance(rel, (int, float)):
            if rel > 2.0:
                sec_score += 2
                signals.append(f"个股跑赢板块{rel:+.1f}pp,强势")
            elif rel > 0:
                sec_score += 1
                signals.append(f"个股略强于板块{rel:+.1f}pp")
            elif rel < -2.0:
                sec_score -= 2
                signals.append(f"⚠️个股跑输板块{rel:+.1f}pp,弱势")
            elif rel < 0:
                sec_score -= 1
                signals.append(f"个股略弱于板块{rel:+.1f}pp")

        sec_score = max(0, min(10, sec_score))
        result.sector_score = sec_score
        result.sector_signal = "；".join(signals) if signals else "板块表现中性"

        # 板块强弱对 signal_score 的影响（±5 分上限）
        sector_adj = sec_score - 5  # [-5, +5]
        if sector_adj != 0:
            result.signal_score = max(0, min(100, result.signal_score + sector_adj))
            result.score_breakdown['sector_adj'] = sector_adj
            self._update_buy_signal(result)

    def _score_chip_distribution(self, result: TrendAnalysisResult, chip_data: dict = None):
        """筹码分布评分：获利盘比例 + 现价vs均成本 + 集中度

        评分逻辑：
        - 获利盘 > 90% → 高位套牢少但抛压大 -2
        - 获利盘 70-90% → 偏高 -1
        - 获利盘 30-70% → 正常区间
        - 获利盘 10-30% → 超跌但有支撑 +1
        - 获利盘 < 10%  → 深度套牢区,底部信号 +2
        - 现价 > 均成本*1.1 → 主力获利,注意抛压 -1
        - 现价 < 均成本*0.9 → 低于成本,有支撑 +1
        - 集中度(90) < 10% → 高度控盘 +1
        """
        if not chip_data or not isinstance(chip_data, dict):
            return

        c_score = 5
        signals = []

        profit_ratio = chip_data.get('profit_ratio')
        avg_cost = chip_data.get('avg_cost')
        concentration_90 = chip_data.get('concentration_90')
        price = result.current_price

        # 获利盘比例
        if isinstance(profit_ratio, (int, float)):
            pr = profit_ratio * 100 if profit_ratio <= 1.0 else profit_ratio  # 兼容 0-1 和 0-100
            if pr > 90:
                c_score -= 2
                signals.append(f"获利盘{pr:.0f}%,抛压较大")
            elif pr > 70:
                c_score -= 1
                signals.append(f"获利盘{pr:.0f}%,偏高")
            elif pr < 10:
                c_score += 2
                signals.append(f"获利盘仅{pr:.0f}%,底部信号")
            elif pr < 30:
                c_score += 1
                signals.append(f"获利盘{pr:.0f}%,偏低有支撑")

        # 现价 vs 平均成本
        if isinstance(avg_cost, (int, float)) and avg_cost > 0 and price > 0:
            cost_ratio = price / avg_cost
            if cost_ratio > 1.15:
                c_score -= 1
                signals.append(f"现价高于均成本{avg_cost:.2f}元({(cost_ratio-1)*100:.0f}%),注意获利抛压")
            elif cost_ratio < 0.85:
                c_score += 1
                signals.append(f"现价低于均成本{avg_cost:.2f}元({(1-cost_ratio)*100:.0f}%),成本支撑")

        # 筹码集中度
        if isinstance(concentration_90, (int, float)) and concentration_90 > 0:
            if concentration_90 < 10:
                c_score += 1
                signals.append(f"筹码高度集中({concentration_90:.1f}%),主力控盘")
            elif concentration_90 > 50:
                c_score -= 1
                signals.append(f"筹码分散({concentration_90:.1f}%),缺乏主力")

        c_score = max(0, min(10, c_score))
        result.chip_score = c_score
        result.chip_signal = "；".join(signals) if signals else "筹码分布正常"

        chip_adj = c_score - 5
        if chip_adj != 0:
            result.signal_score = max(0, min(100, result.signal_score + chip_adj))
            result.score_breakdown['chip_adj'] = chip_adj
            self._update_buy_signal(result)

    def _score_fundamental_quality(self, result: TrendAnalysisResult, fundamental_data: dict = None):
        """基本面质量评分：ROE + 负债率 → 盈利质量与财务风险

        评分逻辑：
        - ROE > 20% → 优秀 +2
        - ROE > 10% → 良好 +1
        - ROE < 3%  → 差 -1
        - ROE < 0   → 亏损 -2
        - 负债率 > 80% → 高风险 -2
        - 负债率 > 60% → 偏高 -1
        - 负债率 < 30% → 健康 +1
        """
        if not fundamental_data or not isinstance(fundamental_data, dict):
            return

        f_score = 5
        signals = []

        financial = fundamental_data.get('financial', {})
        if not isinstance(financial, dict):
            return

        # ROE
        roe_str = financial.get('roe', 'N/A')
        if roe_str not in ('N/A', '', None):
            try:
                roe = float(str(roe_str).replace('%', ''))
                if roe > 20:
                    f_score += 2
                    signals.append(f"ROE优秀({roe:.1f}%)")
                elif roe > 10:
                    f_score += 1
                    signals.append(f"ROE良好({roe:.1f}%)")
                elif roe < 0:
                    f_score -= 2
                    signals.append(f"⚠️ROE为负({roe:.1f}%),亏损")
                elif roe < 3:
                    f_score -= 1
                    signals.append(f"ROE偏低({roe:.1f}%)")
            except (ValueError, TypeError):
                pass

        # 负债率
        debt_str = financial.get('debt_ratio', 'N/A')
        if debt_str not in ('N/A', '', None):
            try:
                debt = float(str(debt_str).replace('%', ''))
                if debt > 80:
                    f_score -= 2
                    signals.append(f"⚠️负债率过高({debt:.1f}%)")
                elif debt > 60:
                    f_score -= 1
                    signals.append(f"负债率偏高({debt:.1f}%)")
                elif debt < 30:
                    f_score += 1
                    signals.append(f"负债率健康({debt:.1f}%)")
            except (ValueError, TypeError):
                pass

        f_score = max(0, min(10, f_score))
        result.fundamental_score = f_score
        result.fundamental_signal = "；".join(signals) if signals else "基本面数据正常"

        fund_adj = f_score - 5
        if fund_adj != 0:
            result.signal_score = max(0, min(100, result.signal_score + fund_adj))
            result.score_breakdown['fundamental_adj'] = fund_adj
            self._update_buy_signal(result)

    def _score_quote_extra(self, result: TrendAnalysisResult, quote_extra: dict = None):
        """行情附加数据评分：换手率异常检测 + 52周高低位

        评分逻辑：
        - 换手率 > 15% → 异常高换手,可能妖股/庄股 → 加入 trading_halt 检测
        - 换手率 < 0.3% → 流动性枯竭 → 减分
        - 52周位置 > 95% → 极端高位 -2
        - 52周位置 > 80% → 高位 -1
        - 52周位置 < 5%  → 极端低位 +2
        - 52周位置 < 20% → 低位 +1

        quote_extra: {"turnover_rate", "high_52w", "low_52w", "total_mv", "circ_mv"}
        """
        if not quote_extra or not isinstance(quote_extra, dict):
            return

        adj = 0
        price = result.current_price

        # 换手率异常
        turnover = quote_extra.get('turnover_rate')
        if isinstance(turnover, (int, float)) and turnover > 0:
            if turnover > 15:
                if not result.trading_halt:
                    result.trading_halt = True
                    result.trading_halt_reason = (result.trading_halt_reason + "；" if result.trading_halt_reason else "") + f"换手率异常({turnover:.1f}%>15%)，疑似游资炒作"
            elif turnover < 0.3:
                adj -= 1
                result.score_breakdown['liquidity_risk'] = -1

        # 52周位置
        high_52w = quote_extra.get('high_52w')
        low_52w = quote_extra.get('low_52w')
        if isinstance(high_52w, (int, float)) and isinstance(low_52w, (int, float)) and high_52w > low_52w > 0 and price > 0:
            week52_range = high_52w - low_52w
            if week52_range > 0:
                position = (price - low_52w) / week52_range * 100
                result.week52_position = round(position, 1)
                if position > 95:
                    adj -= 2
                    result.score_breakdown['week52_risk'] = -2
                elif position > 80:
                    adj -= 1
                    result.score_breakdown['week52_risk'] = -1
                elif position < 5:
                    adj += 2
                    result.score_breakdown['week52_opp'] = 2
                elif position < 20:
                    adj += 1
                    result.score_breakdown['week52_opp'] = 1

        if adj != 0:
            result.signal_score = max(0, min(100, result.signal_score + adj))
            self._update_buy_signal(result)

    def _cap_adjustments(self, result: TrendAnalysisResult):
        """修正因子总量上限：防止多维修正导致分数膨胀

        规则：
        - 正向修正总量上限 +15（防止中性股被吹到强买）
        - 负向修正总量上限 -20（防守可以更严格）
        - 仅截断总量，保留各项明细不变
        """
        bd = result.score_breakdown
        if not bd:
            return

        adj_keys = ['valuation_adj', 'capital_flow_adj', 'cf_trend', 'cf_continuity',
                     'cross_resonance', 'sector_adj', 'chip_adj',
                     'fundamental_adj', 'week52_risk', 'week52_opp', 'liquidity_risk']
        base_keys = ['trend', 'bias', 'volume', 'support', 'macd', 'rsi', 'kdj']

        # 计算基础分和修正总量
        base_score = sum(bd.get(k, 0) for k in base_keys)
        total_adj = sum(bd.get(k, 0) for k in adj_keys)

        if total_adj == 0:
            return

        cap_pos = 15
        cap_neg = -20

        if total_adj > cap_pos:
            capped = cap_pos
        elif total_adj < cap_neg:
            capped = cap_neg
        else:
            return  # 在范围内，无需截断

        # 应用截断后的分数
        new_score = base_score + capped
        new_score = max(0, min(100, new_score))
        old_score = result.signal_score

        if new_score != old_score:
            result.signal_score = new_score
            result.score_breakdown['adj_cap'] = capped - total_adj  # 记录截断量
            self._update_buy_signal(result)

    def _detect_signal_conflict(self, result: TrendAnalysisResult):
        """信号冲突检测：技术面与多维因子严重分歧时，显式警告

        冲突场景：
        1. 技术面看多(≥70) 但 基本面/资金面/筹码 任一≤3 → 警告"技术强但XX弱"
        2. 技术面看空(≤35) 但 基本面/筹码 任一≥8 → 提示"超跌但基本面优"
        """
        bd = result.score_breakdown
        base_keys = ['trend', 'bias', 'volume', 'support', 'macd', 'rsi', 'kdj']
        base_score = sum(bd.get(k, 0) for k in base_keys)

        conflicts = []

        # 场景1：技术面看多 但 某维度严重看空
        if base_score >= 70:
            if result.fundamental_score <= 2:
                conflicts.append("⚠️技术面偏多但基本面很差(ROE低/负债高)")
            if result.capital_flow_score <= 2:
                conflicts.append("⚠️技术面偏多但资金面大幅流出")
            if result.chip_score <= 2:
                conflicts.append("⚠️技术面偏多但筹码抛压沉重")

        # 场景2：技术面看空 但 基本面/筹码优秀
        if base_score <= 35:
            if result.fundamental_score >= 8:
                conflicts.append("💡超跌但基本面优质(高ROE/低负债)")
            if result.chip_score >= 8:
                conflicts.append("💡超跌但筹码支撑强(低位获利盘少/成本支撑)")

        if conflicts:
            conflict_str = "；".join(conflicts)
            result.score_breakdown['signal_conflict'] = conflict_str
            # 注入到建议文本中（在 _generate_detailed_advice 之前）
            if not hasattr(result, '_conflict_warnings'):
                result._conflict_warnings = []
            result._conflict_warnings = conflicts

    def _calc_position(self, result: TrendAnalysisResult, market_regime: MarketRegime, regime_strength: int = 50):
        """增强版仓位管理系统：动态仓位 + 凯利公式 + 风险分散
        
        仓位决策因子：
        1. 信号强度：signal_score
        2. 市场环境：market_regime + regime_strength
        3. 波动率：volatility_20d
        4. 估值安全边际：pe_ratio
        5. 胜率预估：基于signal_score的经验公式
        6. 盈亏比：risk_reward_ratio
        
        仓位计算逻辑：
        - 基础仓位 = f(signal_score)
        - 环境乘数 = f(market_regime, regime_strength)
        - 波动调整 = f(volatility)
        - 估值调整 = f(pe_ratio)
        - 凯利仓位 = f(胜率, 盈亏比)
        - 最终仓位 = min(基础仓位 * 各种调整, 凯利仓位)
        """
        score = result.signal_score
        
        # === 1. 基础仓位（根据信号强度）===
        if score >= 95:  # 激进买入
            base_pos = 60
        elif score >= 85:  # 强烈买入
            base_pos = 50
        elif score >= 70:  # 买入
            base_pos = 35
        elif score >= 60:  # 谨慎买入
            base_pos = 20
        elif score >= 50:  # 持有
            base_pos = 10
        else:
            base_pos = 0
        
        # === 2. 市场环境乘数（结合强度）===
        if market_regime == MarketRegime.BULL:
            regime_mult = 1.0 + (regime_strength - 50) / 100  # 1.0-1.5
        elif market_regime == MarketRegime.BEAR:
            regime_mult = 0.5 + regime_strength / 100  # 0.5-1.0
        else:  # SIDEWAYS
            regime_mult = 0.8 + (regime_strength - 35) / 100  # 0.65-0.95
        
        pos = base_pos * regime_mult
        
        # === 3. 波动率调整（高波动降仓）===
        if result.volatility_20d > 50:
            vol_mult = 0.6
        elif result.volatility_20d > 35:
            vol_mult = 0.75
        elif result.volatility_20d > 20:
            vol_mult = 0.9
        else:
            vol_mult = 1.0
        pos *= vol_mult
        
        # === 4. 估值安全边际调整 ===
        if result.pe_ratio > 0:
            if result.pe_ratio > 100:
                pe_mult = 0.5
            elif result.pe_ratio > 60:
                pe_mult = 0.7
            elif result.pe_ratio > 40:
                pe_mult = 0.85
            else:
                pe_mult = 1.0
            pos *= pe_mult
        
        # === 5. 凯利公式仓位上限（防止过度集中）===
        # 胜率预估：根据signal_score的经验公式
        if score >= 85:
            win_rate = 0.65  # 85+分胜率65%
        elif score >= 70:
            win_rate = 0.55
        elif score >= 60:
            win_rate = 0.50
        else:
            win_rate = 0.45
        
        # 盈亏比
        rr_ratio = result.risk_reward_ratio if result.risk_reward_ratio > 0 else 1.5
        
        # 凯利公式：f = (p*b - q) / b，其中p=胜率，b=盈亏比，q=1-p
        # 修正：为了保守，乘以系数 0.5
        kelly_f = (win_rate * rr_ratio - (1 - win_rate)) / rr_ratio
        kelly_pos = max(0, min(50, kelly_f * 100 * 0.5))  # 半凯利，上锆50%
        
        # === 6. 最终仓位：取较小值（保守原则）===
        final_pos = min(pos, kelly_pos)
        
        # 特殊场景调整
        # 共振信号加仓
        if hasattr(result, 'indicator_resonance') and result.indicator_resonance:
            if '★★★★★' in result.indicator_resonance:
                final_pos *= 1.2
        
        # 风险信号降仓
        if hasattr(result, 'market_behavior') and result.market_behavior:
            if '出货嫌疑' in result.market_behavior or '诱多嫌疑' in result.market_behavior:
                final_pos *= 0.5
        
        result.recommended_position = int(max(0, min(80, final_pos)))  # 上限 80%
        
        # 记录仓位计算详情（供调试）
        result.position_breakdown = {
            'base': int(base_pos),
            'regime_mult': round(regime_mult, 2),
            'vol_mult': round(vol_mult, 2),
            'kelly_cap': int(kelly_pos),
            'final': result.recommended_position
        }

    def _check_resonance(self, result: TrendAnalysisResult):
        """多指标共振检测：MACD/KDJ/RSI/量价/趋势同向信号"""
        bullish_resonance = []
        bearish_resonance = []
        # MACD 多头信号
        if result.macd_status in [MACDStatus.GOLDEN_CROSS_ZERO, MACDStatus.GOLDEN_CROSS, MACDStatus.CROSSING_UP]:
            bullish_resonance.append(f"MACD{result.macd_status.value}")
        elif result.macd_status in [MACDStatus.DEATH_CROSS, MACDStatus.CROSSING_DOWN]:
            bearish_resonance.append(f"MACD{result.macd_status.value}")
        # KDJ 多头信号
        if result.kdj_status in [KDJStatus.GOLDEN_CROSS_OVERSOLD, KDJStatus.GOLDEN_CROSS]:
            bullish_resonance.append(f"KDJ{result.kdj_status.value}")
        elif result.kdj_status in [KDJStatus.DEATH_CROSS, KDJStatus.OVERBOUGHT]:
            bearish_resonance.append(f"KDJ{result.kdj_status.value}")
        # RSI 多头信号
        if result.rsi_status in [RSIStatus.GOLDEN_CROSS_OVERSOLD, RSIStatus.GOLDEN_CROSS, RSIStatus.BULLISH_DIVERGENCE]:
            bullish_resonance.append(f"RSI{result.rsi_status.value}")
        elif result.rsi_status in [RSIStatus.DEATH_CROSS, RSIStatus.BEARISH_DIVERGENCE]:
            bearish_resonance.append(f"RSI{result.rsi_status.value}")
        # 量价共振
        if result.volume_status == VolumeStatus.HEAVY_VOLUME_UP:
            bullish_resonance.append("放量上涨")
        elif result.volume_status == VolumeStatus.SHRINK_VOLUME_DOWN:
            bullish_resonance.append("缩量回调")
        elif result.volume_status == VolumeStatus.HEAVY_VOLUME_DOWN:
            bearish_resonance.append("放量下跌")
        # 趋势共振
        if result.trend_status in [TrendStatus.STRONG_BULL, TrendStatus.BULL]:
            bullish_resonance.append("多头趋势")
        elif result.trend_status in [TrendStatus.STRONG_BEAR, TrendStatus.BEAR]:
            bearish_resonance.append("空头趋势")

        # 取方向一致性最高的一方
        if len(bullish_resonance) >= len(bearish_resonance):
            result.resonance_signals = bullish_resonance
            result.resonance_count = len(bullish_resonance)
        else:
            result.resonance_signals = [f"⚠️{s}" for s in bearish_resonance]
            result.resonance_count = -len(bearish_resonance)  # 负数表示看空共振

        # 共振加分/减分（≥3 个信号同向才触发）
        if len(bullish_resonance) >= 3:
            result.resonance_bonus = min(8, len(bullish_resonance) * 2)
            result.signal_score = min(100, result.signal_score + result.resonance_bonus)
        elif len(bearish_resonance) >= 3:
            result.resonance_bonus = -min(8, len(bearish_resonance) * 2)
            result.signal_score = max(0, result.signal_score + result.resonance_bonus)

        # === P4-4: 跨维度组合信号共振 ===
        # 放量突破 + 主力流入 + 板块领涨 → 强势启动 extra +3
        if (result.volume_status == VolumeStatus.HEAVY_VOLUME_UP
                and result.capital_flow_score >= 7
                and result.sector_score >= 7):
            result.resonance_bonus += 3
            result.signal_score = min(100, result.signal_score + 3)
            result.resonance_signals.append("🔥强势启动(放量+主力流入+板块领涨)")
            result.score_breakdown['cross_resonance'] = result.score_breakdown.get('cross_resonance', 0) + 3

        # 缩量阴跌 + 主力流出 + 高位筹码松动 → 出货特征 extra -3
        bearish_price = (result.trend_status in [TrendStatus.BEAR, TrendStatus.STRONG_BEAR, TrendStatus.WEAK_BEAR]
                         or result.volume_status == VolumeStatus.HEAVY_VOLUME_DOWN)
        if bearish_price and result.capital_flow_score <= 3 and result.chip_score <= 3:
            result.resonance_bonus -= 3
            result.signal_score = max(0, result.signal_score - 3)
            result.resonance_signals.append("⚠️出货特征(阴跌+主力流出+筹码松动)")
            result.score_breakdown['cross_resonance'] = result.score_breakdown.get('cross_resonance', 0) - 3

        # 共振后重新判定信号
        self._update_buy_signal(result)

    def _calc_risk_reward(self, result: TrendAnalysisResult, price: float):
        """风险收益比计算"""
        if result.stop_loss_short > 0 and result.take_profit_short > 0 and price > 0:
            risk = price - result.stop_loss_short
            reward = result.take_profit_mid - price if result.take_profit_mid > price else result.take_profit_short - price
            if risk > 0:
                result.risk_reward_ratio = round(reward / risk, 2)
                if result.risk_reward_ratio >= 2.0:
                    result.risk_reward_verdict = "值得"
                elif result.risk_reward_ratio >= 1.0:
                    result.risk_reward_verdict = "中性"
                else:
                    result.risk_reward_verdict = "不值得"

    @staticmethod
    def _update_buy_signal(result: TrendAnalysisResult):
        """根据 signal_score 重新判定 buy_signal 等级（7档精细分级）
        
        分级逻辑：
        - 95+: 激进买入 - 共振信号+趋势确认，适合重仓
        - 85-94: 强烈买入 - 多重指标共振，胜率高
        - 70-84: 买入 - 技术面看好，可建仓
        - 60-69: 谨慎买入 - 有机会但需谨慎
        - 50-59: 持有 - 中性，持股待涨
        - 35-49: 减仓 - 信号转弱，逐步减仓
        - 0-34: 清仓 - 多重风险，先走为妙
        
        特殊加分：
        - 共振信号（底部吸筹/主升浪启动）：+5分
        - 市场行为（洗盘/拉升）：+3分
        
        特殊减分：
        - 诱多嫌疑/出货嫌疑：-10分
        - 恐慌抛售信号：-15分
        """
        score = result.signal_score
        
        # === 特殊加分：共振和市场行为 ===
        bonus = 0
        if hasattr(result, 'indicator_resonance') and result.indicator_resonance:
            if '★★★★★' in result.indicator_resonance:  # 顶级共振信号
                bonus += 5
            elif '★★★★' in result.indicator_resonance:  # 强共振信号
                bonus += 3
        
        if hasattr(result, 'market_behavior') and result.market_behavior:
            if '拉升阶段' in result.market_behavior or '洗盘特征' in result.market_behavior:
                bonus += 3
            elif '诱多嫌疑' in result.market_behavior or '出货嫌疑' in result.market_behavior:
                bonus -= 10
            elif '恐慌抛售' in result.market_behavior:
                bonus -= 15
        
        adjusted_score = max(0, min(100, score + bonus))
        
        # === 7档分级 ===
        if adjusted_score >= 95:
            result.buy_signal = BuySignal.AGGRESSIVE_BUY
        elif adjusted_score >= 85:
            result.buy_signal = BuySignal.STRONG_BUY
        elif adjusted_score >= 70:
            result.buy_signal = BuySignal.BUY
        elif adjusted_score >= 60:
            result.buy_signal = BuySignal.CAUTIOUS_BUY
        elif adjusted_score >= 50:
            result.buy_signal = BuySignal.HOLD
        elif adjusted_score >= 35:
            result.buy_signal = BuySignal.REDUCE
        else:
            result.buy_signal = BuySignal.SELL
        
        # 记录调整后的分数（供调试）
        if bonus != 0:
            result.score_breakdown['signal_bonus'] = bonus

    def _compute_levels(self, df: pd.DataFrame, res: TrendAnalysisResult) -> tuple:
        """计算支撑位和阻力位：近 20 日 Swing 高低点 + 均线"""
        support_set, resistance_set = set(), set()
        tail = df.tail(30)
        if len(tail) < 5:
            return [], []

        price = res.current_price or 0
        # 均线支撑
        for ma_val in [res.ma20, res.ma60]:
            if ma_val and ma_val > 0 and ma_val < price:
                support_set.add(round(ma_val, 2))

        # 近 N 日 swing 低点
        lows = tail['low'].values
        for i in range(2, len(lows) - 2):
            if lows[i] <= lows[i-1] and lows[i] <= lows[i-2] and lows[i] <= lows[i+1] and lows[i] <= lows[i+2]:
                v = round(float(lows[i]), 2)
                if v > 0 and v < price:
                    support_set.add(v)

        # 近 N 日 swing 高点
        highs = tail['high'].values
        for i in range(2, len(highs) - 2):
            if highs[i] >= highs[i-1] and highs[i] >= highs[i-2] and highs[i] >= highs[i+1] and highs[i] >= highs[i+2]:
                v = round(float(highs[i]), 2)
                if v > price:
                    resistance_set.add(v)

        supports = sorted(support_set, reverse=True)[:5]
        resistances = sorted(resistance_set)[:5]
        return supports, resistances

    def _generate_detailed_advice(self, res: TrendAnalysisResult):
        """生成持仓/空仓的分离建议"""
        bias = res.bias_ma5
        trend = res.trend_status
        
        # 场景A: 强势多头/多头
        if trend in [TrendStatus.STRONG_BULL, TrendStatus.BULL]:
            # 空仓者
            if bias > 5:
                res.advice_for_empty = "❌ 乖离率过高，严禁追高，耐心等待缩量回踩MA5"
            elif bias > 2:
                res.advice_for_empty = "⚠️ 此时介入性价比一般，建议轻仓试错或等待回调"
            elif -2 <= bias <= 2:
                res.advice_for_empty = "✅ 黄金买点区间，沿MA5积极建仓"
            else: # 回调较深
                res.advice_for_empty = "✅ 也是机会，但需关注MA10/MA20支撑有效性"
            
            # 持仓者
            if bias > 8:
                res.advice_for_holding = "⚠️ 短期涨幅过大，可适当止盈锁利，底仓沿MA5持有"
            else:
                res.advice_for_holding = "✅ 趋势完好，坚定持有，以MA10作为防守线"
                
        # 场景B: 空头/强势空头
        elif trend in [TrendStatus.BEAR, TrendStatus.STRONG_BEAR]:
            # 空仓者
            if bias < -15:
                res.advice_for_empty = "⚡ 超跌严重，仅适合激进者博超短反弹（快进快出）"
            else:
                res.advice_for_empty = "❌ 趋势向下，覆巢之下无完卵，坚决空仓观望"
            
            # 持仓者
            res.advice_for_holding = "❌ 趋势已坏，建议逢反弹坚决离场，保留本金"
            
        # 场景C: 震荡
        else:
            res.advice_for_empty = "⚖️ 趋势不明，建议观望，若突破箱体再跟随"
            res.advice_for_holding = "⚖️ 做T为主，高抛低吸，降低成本"

        # 附加信号冲突警告
        if hasattr(res, '_conflict_warnings') and res._conflict_warnings:
            conflict_text = "｜".join(res._conflict_warnings)
            res.advice_for_empty = f"{res.advice_for_empty} [{conflict_text}]"
            res.advice_for_holding = f"{res.advice_for_holding} [{conflict_text}]"

    def _generate_beginner_summary(self, res: TrendAnalysisResult):
        """生成白话版解读（面向不懂技术分析的散户）"""
        price = res.current_price
        score = res.signal_score
        trend = res.trend_status
        parts = []

        # 1. 总体判断（一句话）
        if score >= 85:
            parts.append(f"这只股票目前表现非常好，多项指标同时看涨。")
        elif score >= 70:
            parts.append(f"这只股票走势不错，有买入的机会。")
        elif score >= 50:
            parts.append(f"这只股票目前走势一般，没有特别明确的方向。")
        elif score >= 35:
            parts.append(f"这只股票走势偏弱，不建议现在买入。")
        else:
            parts.append(f"这只股票目前走势很差，远离为妙。")

        # 2. 趋势白话
        trend_map = {
            TrendStatus.STRONG_BULL: "股价在持续上涨中，而且涨势在加速",
            TrendStatus.BULL: "股价在稳步上涨中",
            TrendStatus.WEAK_BULL: "股价有点涨，但力度不够强",
            TrendStatus.CONSOLIDATION: "股价在横盘震荡，没有明确方向",
            TrendStatus.WEAK_BEAR: "股价有点跌，但还不算严重",
            TrendStatus.BEAR: "股价在持续下跌中",
            TrendStatus.STRONG_BEAR: "股价在加速下跌，非常危险",
        }
        parts.append(trend_map.get(trend, "走势不明"))

        # 3. 关键风险/机会提示
        if res.bias_ma5 > 8:
            parts.append(f"⚠️ 注意：短期涨太多了（偏离均线{res.bias_ma5:.1f}%），现在追进去很可能被套")
        elif res.bias_ma5 < -10:
            parts.append(f"💡 提示：短期跌幅较大（偏离均线{res.bias_ma5:.1f}%），可能有反弹机会，但要设好止损")

        if res.rsi_divergence == "顶背离":
            parts.append("⚠️ 技术面出现顶背离信号，意味着虽然股价还在涨，但上涨动力在减弱，小心回调")
        elif res.rsi_divergence == "底背离":
            parts.append("💡 技术面出现底背离信号，意味着虽然股价还在跌，但下跌力量在减弱，可能要反弹了")

        # 4. 共振提示
        if res.resonance_count >= 3:
            parts.append(f"🔥 {res.resonance_count}个技术指标同时看涨，信号比较可靠")
        elif res.resonance_count <= -3:
            parts.append(f"❄️ {abs(res.resonance_count)}个技术指标同时看跌，风险较大")

        # 5. 风险收益比
        if res.risk_reward_verdict == "值得":
            parts.append(f"📊 赚赔比{res.risk_reward_ratio:.1f}:1，风险收益比不错，值得考虑")
        elif res.risk_reward_verdict == "不值得":
            parts.append(f"📊 赚赔比只有{res.risk_reward_ratio:.1f}:1，亏钱的风险比赚钱的空间大，不划算")

        # 6. 估值白话
        if res.valuation_verdict:
            if res.valuation_downgrade <= -10:
                parts.append(f"🚨 重要警告：这只股票估值严重偏高（市盈率{res.pe_ratio:.0f}倍），{res.valuation_verdict}，现在买入就是高位接盘")
            elif res.valuation_downgrade < 0:
                parts.append(f"⚠️ 注意估值偏高（市盈率{res.pe_ratio:.0f}倍），{res.valuation_verdict}，买入需谨慎")
            elif res.valuation_score >= 8:
                parts.append(f"💰 估值方面比较便宜（市盈率{res.pe_ratio:.0f}倍），{res.valuation_verdict}")

        # 7. 资金面白话
        if res.capital_flow_signal and res.capital_flow_signal != "资金面数据正常":
            if res.capital_flow_score >= 8:
                parts.append(f"💪 资金面很强：{res.capital_flow_signal}，说明大资金在买入")
            elif res.capital_flow_score <= 2:
                parts.append(f"⚠️ 资金面较弱：{res.capital_flow_signal}，大资金在撤退")

        # 8. 交易暂停白话
        if res.trading_halt:
            parts.insert(0, f"🚫 重要提醒：这只股票目前不适合交易！原因：{res.trading_halt_reason}")

        # 9. 止损止盈白话
        if res.stop_loss_short > 0 and res.take_profit_short > 0:
            sl_pct = abs((price - res.stop_loss_short) / price * 100)
            tp_pct = abs((res.take_profit_short - price) / price * 100)
            parts.append(f"如果买入：跌到{res.stop_loss_short:.2f}元(约跌{sl_pct:.1f}%)就该卖出止损，涨到{res.take_profit_short:.2f}元(约涨{tp_pct:.1f}%)可以先卖一部分锁定利润")

        # 去掉每段末尾的句号再统一拼接，避免双句号
        cleaned = [p.rstrip("。") for p in parts]
        res.beginner_summary = "。".join(cleaned) + "。"

    @staticmethod
    def detect_market_regime(df: pd.DataFrame, index_change_pct: float = 0.0, 
                            volume_data: pd.Series = None) -> tuple:
        """增强版市场环境检测：多维度判断 + 强度量化
        
        判断维度：
        1. MA趋势：MA5/MA10/MA20/MA60排列 + MA20斜率
        2. 大盘环境：近20日涨跌幅 + 当日方向
        3. 量能特征：放量/缩量趋势
        4. 波动率：近20日波动率（高波动=震荡/熊市）
        5. 平滑机制：连续3天方向一致才切换
        
        Returns:
            (MarketRegime, 环境强度 0-100)
        """
        SMOOTH_DAYS = 3
        SLOPE_THRESHOLD = 1.0
        
        if df is None or df.empty or len(df) < 30:
            return MarketRegime.SIDEWAYS, 50
        
        try:
            # === 1. MA趋势分析 ===
            ma5 = df['close'].rolling(5).mean()
            ma10 = df['close'].rolling(10).mean()
            ma20 = df['close'].rolling(20).mean()
            ma60 = df['close'].rolling(60).mean()
            
            if len(ma20) < 15:
                return MarketRegime.SIDEWAYS, 50
            
            # MA多头/空头排列检查
            latest_ma5 = ma5.iloc[-1]
            latest_ma10 = ma10.iloc[-1]
            latest_ma20 = ma20.iloc[-1]
            latest_ma60 = ma60.iloc[-1] if len(ma60) >= 60 else latest_ma20
            
            ma_bull_score = 0
            if latest_ma5 > latest_ma10 > latest_ma20:
                ma_bull_score += 3
            if latest_ma10 > latest_ma20 > latest_ma60:
                ma_bull_score += 2
            elif latest_ma5 < latest_ma10 < latest_ma20:
                ma_bull_score -= 3
            if latest_ma10 < latest_ma20 < latest_ma60:
                ma_bull_score -= 2
            
            # MA20斜率连续性
            bull_count = 0
            bear_count = 0
            for offset in range(SMOOTH_DAYS):
                idx = -(1 + offset)
                idx_10 = -(11 + offset)
                if abs(idx_10) > len(ma20):
                    break
                now_val = ma20.iloc[idx]
                ago_val = ma20.iloc[idx_10]
                if now_val <= 0 or ago_val <= 0:
                    break
                slope = (now_val - ago_val) / ago_val * 100
                if slope > SLOPE_THRESHOLD:
                    bull_count += 1
                elif slope < -SLOPE_THRESHOLD:
                    bear_count += 1
            
            ma_slope_score = 0
            if bull_count >= SMOOTH_DAYS:
                ma_slope_score = 3
            elif bear_count >= SMOOTH_DAYS:
                ma_slope_score = -3
            
            # === 2. 大盘环境分析 ===
            index_score = 0
            if index_change_pct > 1.0:
                index_score = 2
            elif index_change_pct > 0:
                index_score = 1
            elif index_change_pct < -1.0:
                index_score = -2
            elif index_change_pct < 0:
                index_score = -1
            
            # === 3. 量能特征分析 ===
            volume_score = 0
            if volume_data is not None and len(volume_data) >= 20:
                recent_vol = volume_data.tail(5).mean()
                avg_vol = volume_data.tail(20).mean()
                if avg_vol > 0:
                    vol_ratio = recent_vol / avg_vol
                    if vol_ratio > 1.3:  # 近5日持续放量
                        volume_score = 1
                    elif vol_ratio < 0.7:  # 近5日持续缩量
                        volume_score = -1
            
            # === 4. 波动率分析 ===
            volatility_score = 0
            if len(df) >= 20:
                recent_20 = df.tail(20)
                high_20 = recent_20['high'].max()
                low_20 = recent_20['low'].min()
                volatility = (high_20 - low_20) / low_20 * 100 if low_20 > 0 else 0
                if volatility > 30:  # 高波动，倾向震荡/熊市
                    volatility_score = -2
                elif volatility < 15:  # 低波动，倾向牛市/震荡
                    volatility_score = 1
            
            # === 5. 综合评分 ===
            total_score = ma_bull_score + ma_slope_score + index_score + volume_score + volatility_score
            
            # === 6. 判定环境 + 计算强度 ===
            if total_score >= 5:
                regime = MarketRegime.BULL
                strength = min(100, 50 + total_score * 5)  # 50-100
            elif total_score <= -5:
                regime = MarketRegime.BEAR
                strength = max(0, 50 + total_score * 5)  # 0-50
            else:
                regime = MarketRegime.SIDEWAYS
                strength = 50 + total_score * 3  # 35-65
            
            return regime, int(strength)
            
        except Exception:
            return MarketRegime.SIDEWAYS, 50

    # RSI 参数
    RSI_SHORT = 6
    RSI_MID = 12
    RSI_LONG = 24
    # 量能阈值
    VOLUME_SHRINK_RATIO = 0.7
    VOLUME_HEAVY_RATIO = 1.5

    def _calc_atr_percentile(self, df: pd.DataFrame, lookback: int = 60) -> float:
        """计算当前ATR在历史中的分位数（用于自适应止损倍数）
        
        Args:
            df: 包含ATR14列的DataFrame
            lookback: 回溯周期（天）
        
        Returns:
            分位数（0-1），0.8表示当前ATR处于历史高位（前20%）
        """
        if df is None or len(df) < lookback or 'ATR14' not in df.columns:
            return 0.5  # 默认中位数
        
        try:
            atr_hist = df['ATR14'].tail(lookback).dropna()
            if len(atr_hist) < 10:
                return 0.5
            
            current_atr = float(df['ATR14'].iloc[-1])
            if current_atr <= 0:
                return 0.5
            
            # 计算当前ATR在历史中的排名百分比
            percentile = (atr_hist <= current_atr).sum() / len(atr_hist)
            return round(percentile, 2)
        except Exception:
            return 0.5

    def _calc_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        # === 均线（复用 BaseFetcher 已计算的小写列，避免重复计算） ===
        df['MA5'] = df['ma5'] if 'ma5' in df.columns else df['close'].rolling(window=5).mean()
        df['MA10'] = df['ma10'] if 'ma10' in df.columns else df['close'].rolling(window=10).mean()
        df['MA20'] = df['ma20'] if 'ma20' in df.columns else df['close'].rolling(window=20).mean()
        df['MA60'] = df['close'].rolling(window=60).mean()

        # === MACD (12/26/9) ===
        ema12 = df['close'].ewm(span=12, adjust=False).mean()
        ema26 = df['close'].ewm(span=26, adjust=False).mean()
        df['MACD_DIF'] = ema12 - ema26
        df['MACD_DEA'] = df['MACD_DIF'].ewm(span=9, adjust=False).mean()
        df['MACD_BAR'] = (df['MACD_DIF'] - df['MACD_DEA']) * 2

        # === KDJ ===
        low_min = df['low'].rolling(window=9).min()
        high_max = df['high'].rolling(window=9).max()
        rsv = (df['close'] - low_min) / (high_max - low_min) * 100
        df['K'] = rsv.ewm(com=2, adjust=False).mean()
        df['D'] = df['K'].ewm(com=2, adjust=False).mean()
        df['J'] = 3 * df['K'] - 2 * df['D']

        # === ATR(14) ===
        tr = np.maximum(df['high'] - df['low'], np.maximum(abs(df['high'] - df['close'].shift(1)), abs(df['low'] - df['close'].shift(1))))
        df['ATR14'] = tr.rolling(window=14).mean()

        # === 多周期 RSI (6/12/24) — Wilder's EMA ===
        delta = df['close'].diff()
        for period in [self.RSI_SHORT, self.RSI_MID, self.RSI_LONG]:
            gain = delta.where(delta > 0, 0.0)
            loss_s = (-delta).where(delta < 0, 0.0)
            # Wilder's smoothing: EMA with alpha=1/period (equivalent to com=period-1)
            avg_gain = gain.ewm(alpha=1.0/period, min_periods=period, adjust=False).mean()
            avg_loss = loss_s.ewm(alpha=1.0/period, min_periods=period, adjust=False).mean()
            rs = avg_gain / avg_loss.replace(0, np.nan)
            rsi = 100 - (100 / (1 + rs))
            df[f'RSI_{period}'] = rsi.fillna(50)
        # 保留向后兼容的 RSI 列 (= RSI_12)
        df['RSI'] = df[f'RSI_{self.RSI_MID}']

        # === Bollinger Bands (20, 2) ===
        bb_mid = df['MA20']
        bb_std = df['close'].rolling(window=20).std()
        df['BB_UPPER'] = bb_mid + 2 * bb_std
        df['BB_LOWER'] = bb_mid - 2 * bb_std
        df['BB_WIDTH'] = ((df['BB_UPPER'] - df['BB_LOWER']) / bb_mid).replace([np.inf, -np.inf], 0)
        band_range = (df['BB_UPPER'] - df['BB_LOWER']).replace(0, np.nan)
        df['BB_PCT_B'] = ((df['close'] - df['BB_LOWER']) / band_range).fillna(0.5)

        return df.fillna(0)

    def format_for_llm(self, result: TrendAnalysisResult) -> str:
        """生成精简版技术摘要（供 LLM prompt 使用，约为 format_analysis 的 1/3 大小）
        
        LLM 不需要完整的量化报告，只需要关键信号和硬规则锚点。
        """
        breakdown = result.score_breakdown
        bd_str = ""
        if breakdown:
            # 技术面基础分
            base = "+".join(f"{k}{v}" for k in ['trend','bias','volume','support','macd','rsi','kdj'] if (v := breakdown.get(k)) is not None)
            # 多维修正
            from src.stock_analyzer.formatter import AnalysisFormatter
            adj = " ".join(f"{label}{v:+d}" for key, label in AnalysisFormatter.ADJ_MAP.items() if (v := breakdown.get(key, 0)) != 0)
            bd_str = f" ({base}{' | ' + adj if adj else ''})"

        lines = [
            f"评分={result.signal_score}{bd_str} 信号={result.buy_signal.value}",
            f"趋势={result.trend_status.value}(强度{result.trend_strength:.0f}) 均线={result.ma_alignment}",
            f"MACD={result.macd_status.value} KDJ={result.kdj_status.value} RSI={result.rsi_status.value}(RSI6={result.rsi_6:.0f} RSI12={result.rsi_12:.0f} RSI24={result.rsi_24:.0f})",
            f"量能={result.volume_status.value} 量比={result.volume_ratio:.2f}",
            f"现价={result.current_price:.2f} 乖离MA5={result.bias_ma5:.1f}% MA20={result.bias_ma20:.1f}%",
        ]
        if result.rsi_divergence:
            lines.append(f"⚠️背离={result.rsi_divergence}")
        if result.resonance_signals:
            lines.append(f"共振={abs(result.resonance_count)}个: {','.join(result.resonance_signals)}")
        if result.valuation_verdict:
            lines.append(f"估值: PE={result.pe_ratio:.1f} PB={result.pb_ratio:.2f} {result.valuation_verdict} 降档={result.valuation_downgrade}")
        if result.trading_halt:
            lines.append(f"🚨暂停交易: {result.trading_halt_reason}")
        if result.capital_flow_signal and result.capital_flow_signal != "资金面数据正常":
            lines.append(f"资金面({result.capital_flow_score}/10): {result.capital_flow_signal}")
        if result.sector_name:
            lines.append(f"板块({result.sector_score}/10): {result.sector_signal}")
        if result.chip_signal and result.chip_signal != "筹码分布正常":
            lines.append(f"筹码({result.chip_score}/10): {result.chip_signal}")
        if result.fundamental_signal and result.fundamental_signal != "基本面数据正常":
            lines.append(f"基本面({result.fundamental_score}/10): {result.fundamental_signal}")
        # 风险指标
        risk_items = []
        if result.beta_vs_index != 1.0:
            risk_items.append(f"Beta={result.beta_vs_index:.2f}")
        if result.volatility_20d > 0:
            risk_items.append(f"波动率={result.volatility_20d:.0f}%")
        if result.max_drawdown_60d != 0:
            risk_items.append(f"回撤={result.max_drawdown_60d:.1f}%")
        if result.week52_position > 0:
            risk_items.append(f"52周={result.week52_position:.0f}%")
        if risk_items:
            lines.append(f"风险: {' '.join(risk_items)}")
        # 硬规则锚点（LLM 不得覆盖）
        if result.stop_loss_short > 0:
            lines.append(f"止损(短)={result.stop_loss_short:.2f} 止损(中)={result.stop_loss_mid:.2f} 买点={result.ideal_buy_anchor:.2f}")
        if result.take_profit_short > 0:
            lines.append(f"止盈(短)={result.take_profit_short:.2f} 止盈(中)={result.take_profit_mid:.2f} 移动止盈={result.take_profit_trailing:.2f}")
        if result.risk_reward_ratio > 0:
            lines.append(f"R:R={result.risk_reward_ratio:.1f}:1({result.risk_reward_verdict})")
        lines.append(f"仓位={result.suggested_position_pct}%")
        lines.append(f"空仓建议: {result.advice_for_empty}")
        lines.append(f"持仓建议: {result.advice_for_holding}")
        return "\n".join(lines)

    def format_analysis(self, result: TrendAnalysisResult) -> str:
        breakdown = result.score_breakdown
        breakdown_str = ""
        if breakdown:
            # 技术面基础分
            base_parts = []
            for k in ['trend', 'bias', 'volume', 'support', 'macd', 'rsi', 'kdj']:
                if k in breakdown:
                    base_parts.append(f"{k}{breakdown[k]}")
            base_str = "+".join(base_parts) if base_parts else ""
            # 多维修正因子
            adj_parts = []
            from src.stock_analyzer.formatter import AnalysisFormatter
            for key, label in AnalysisFormatter.ADJ_MAP.items():
                v = breakdown.get(key, 0)
                if v != 0:
                    adj_parts.append(f"{label}{v:+d}")
            adj_str = " ".join(adj_parts) if adj_parts else ""
            breakdown_str = f" ({base_str}{' | ' + adj_str if adj_str else ''})"

        levels_str = ""
        if result.support_levels or result.resistance_levels:
            sup = ",".join(f"{x:.2f}" for x in result.support_levels[:3]) if result.support_levels else "无"
            res = ",".join(f"{x:.2f}" for x in result.resistance_levels[:3]) if result.resistance_levels else "无"
            levels_str = f"\n【支撑/阻力】支撑: {sup} | 阻力: {res}"

        anchor_line = ""
        if result.stop_loss_short > 0 or result.ideal_buy_anchor > 0:
            tp_line = ""
            if result.take_profit_short > 0:
                tp_line = f"""
● 止盈(短线): {result.take_profit_short:.2f} (1.5*ATR)
● 止盈(中线): {result.take_profit_mid:.2f} ({'第一阻力位' if result.resistance_levels else '2.5*ATR'})
● 移动止盈: {result.take_profit_trailing:.2f} (近20日高点-1.2*ATR)
● 分批方案: {result.take_profit_plan}"""
            rr_line = ""
            if result.risk_reward_ratio > 0:
                rr_line = f"\n● 风险收益比: {result.risk_reward_ratio:.1f}:1 ({result.risk_reward_verdict})"
            anchor_line = f"""
【量化锚点 (硬规则，LLM 不得覆盖)】
● 止损(日内): {result.stop_loss_intraday:.2f} (0.7*ATR)
● 止损(短线): {result.stop_loss_short:.2f} (1.0*ATR)
● 止损(中线): {result.stop_loss_mid:.2f} (1.5*ATR+MA20){tp_line}{rr_line}
● 理想买点: {result.ideal_buy_anchor:.2f} (MA5/MA10 支撑)
● ATR14: {result.atr14:.2f} | MA60: {result.ma60:.2f}
● 建议仓位: {result.suggested_position_pct}%"""

        # 布林带
        bb_str = ""
        if result.bb_upper > 0:
            bb_str = f"\n● 布林带: 上轨{result.bb_upper:.2f} 下轨{result.bb_lower:.2f} | 带宽{result.bb_width:.4f} | %B={result.bb_pct_b:.2f}"

        # 风险指标
        risk_str = ""
        risk_parts = []
        if result.volatility_20d > 0:
            risk_parts.append(f"20日年化波动率{result.volatility_20d:.1f}%")
        if result.beta_vs_index != 1.0:
            risk_parts.append(f"Beta={result.beta_vs_index:.2f}")
        if result.max_drawdown_60d != 0:
            risk_parts.append(f"60日最大回撤{result.max_drawdown_60d:.1f}%")
        if result.week52_position > 0:
            risk_parts.append(f"52周位置{result.week52_position:.0f}%")
        if risk_parts:
            risk_str = "\n● 风险: " + " | ".join(risk_parts)

        # 估值信息
        val_str = ""
        if result.pe_ratio > 0:
            val_str = f"\n● 估值: PE={result.pe_ratio:.1f} PB={result.pb_ratio:.2f}"
            if result.peg_ratio > 0:
                val_str += f" PEG={result.peg_ratio:.2f}"
            val_str += f" | {result.valuation_verdict}"
            if result.valuation_downgrade < 0:
                val_str += f" (降档{result.valuation_downgrade}分)"

        # 资金面
        cf_str = ""
        if result.capital_flow_signal:
            cf_str = f"\n● 资金面: {result.capital_flow_signal} (评分{result.capital_flow_score}/10)"

        # 板块强弱
        sector_str = ""
        if result.sector_name:
            sector_str = f"\n● 板块: {result.sector_signal} (评分{result.sector_score}/10)"

        # 筹码分布
        chip_str = ""
        if result.chip_signal and result.chip_signal != "筹码分布正常":
            chip_str = f"\n● 筹码: {result.chip_signal} (评分{result.chip_score}/10)"

        # 基本面质量
        fund_str = ""
        if result.fundamental_signal and result.fundamental_signal != "基本面数据正常":
            fund_str = f"\n● 基本面: {result.fundamental_signal} (评分{result.fundamental_score}/10)"

        # 交易暂停警告
        halt_str = ""
        if result.trading_halt:
            halt_str = f"\n🚨【交易暂停】{result.trading_halt_reason}"

        return f"""
【量化技术报告】
---------------------------{halt_str}
● 综合评分: {result.signal_score}{breakdown_str} ({result.buy_signal.value})
● 趋势状态: {result.trend_status.value} (强度{result.trend_strength:.0f}) | {result.ma_alignment}
● 量能: {result.volume_status.value} ({result.volume_trend}) | 量比 {result.volume_ratio:.2f}
● MACD: {result.macd_status.value} ({result.macd_signal}) | DIF={result.macd_dif:.4f} DEA={result.macd_dea:.4f}
● RSI: {result.rsi_status.value} | RSI6={result.rsi_6:.1f} RSI12={result.rsi_12:.1f} RSI24={result.rsi_24:.1f} | {result.rsi_signal}{f' ⚠️{result.rsi_divergence}' if result.rsi_divergence else ''}
● KDJ: {result.kdj_status.value} | K={result.kdj_k:.1f} D={result.kdj_d:.1f} J={result.kdj_j:.1f} | {result.kdj_signal}{val_str}{cf_str}{sector_str}{chip_str}{fund_str}
● 关键数据: 现价{result.current_price:.2f} | 乖离MA5={result.bias_ma5:.2f}% MA10={result.bias_ma10:.2f}% MA20={result.bias_ma20:.2f}%{bb_str}{risk_str}{levels_str}

【技术面操作指引 (硬规则)】
👤 针对空仓者: {result.advice_for_empty}
👥 针对持仓者: {result.advice_for_holding}
{anchor_line}
{f'【多指标共振】{abs(result.resonance_count)}个信号同向: {", ".join(result.resonance_signals)} (加分{result.resonance_bonus:+d})' if result.resonance_signals else ''}
{f'【散户白话版】{result.beginner_summary}' if result.beginner_summary else ''}
---------------------------
"""