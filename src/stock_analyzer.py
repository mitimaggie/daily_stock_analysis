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
    STRONG_BUY = "强烈买入"
    BUY = "买入"
    HOLD = "持有"
    WAIT = "观望"
    SELL = "卖出"

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
    buy_signal: BuySignal = BuySignal.WAIT
    
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
    # 仓位管理（量化硬规则，不交给 LLM）
    suggested_position_pct: int = 0     # 建议仓位占比 (0-30%)

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

    def analyze(self, df: pd.DataFrame, code: str, market_regime: MarketRegime = MarketRegime.SIDEWAYS, index_returns: pd.Series = None) -> TrendAnalysisResult:
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

            # --- 分层止损锚点 ---
            atr = result.atr14
            price = result.current_price
            if atr > 0:
                result.stop_loss_intraday = round(price - 0.7 * atr, 2)   # 日内：紧止损
                result.stop_loss_short = round(price - 1.0 * atr, 2)      # 短线：1 ATR
                sl_atr_mid = price - 1.5 * atr
                sl_ma20 = result.ma20 * 0.98 if result.ma20 > 0 else sl_atr_mid
                result.stop_loss_mid = round(min(sl_atr_mid, sl_ma20) if sl_ma20 > 0 else sl_atr_mid, 2)
            result.stop_loss_anchor = result.stop_loss_short  # 默认兼容
            result.ideal_buy_anchor = round(result.ma5 if result.ma5 > 0 else result.ma10, 2)

            # --- 止盈锚点 ---
            if atr > 0:
                result.take_profit_short = round(price + 1.5 * atr, 2)  # 短线止盈: 1.5 ATR
                # 中线止盈: 第一阻力位（若有）或 2.5 ATR
                if result.resistance_levels:
                    result.take_profit_mid = round(result.resistance_levels[0], 2)
                else:
                    result.take_profit_mid = round(price + 2.5 * atr, 2)
                # 移动止盈: 近20日最高价 - 1.2 ATR（趋势跟踪型止盈）
                if len(df) >= 20:
                    recent_high = float(df['high'].tail(20).max())
                    result.take_profit_trailing = round(recent_high - 1.2 * atr, 2)
                # 分批止盈方案
                tp1 = result.take_profit_short
                tp2 = result.take_profit_mid
                result.take_profit_plan = (
                    f"第1批(1/3仓位): 到{tp1:.2f}止盈 | "
                    f"第2批(1/3仓位): 到{tp2:.2f}止盈 | "
                    f"第3批(底仓): 移动止盈线{result.take_profit_trailing:.2f}跟踪"
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
            
            if score >= 85: result.buy_signal = BuySignal.STRONG_BUY
            elif score >= 70: result.buy_signal = BuySignal.BUY
            elif score >= 50: result.buy_signal = BuySignal.HOLD
            elif score >= 35: result.buy_signal = BuySignal.WAIT
            else: result.buy_signal = BuySignal.SELL

            # =============== 11. 仓位管理（量化硬规则） ===============
            if score >= 85:
                base_pos = 30
            elif score >= 70:
                base_pos = 20
            elif score >= 50:
                base_pos = 10
            else:
                base_pos = 0
            regime_mult = {MarketRegime.BULL: 1.2, MarketRegime.SIDEWAYS: 1.0, MarketRegime.BEAR: 0.6}
            result.suggested_position_pct = min(30, int(base_pos * regime_mult.get(market_regime, 1.0)))
            
            # =============== 12. 多指标共振检测 ===============
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

            # 共振后重新判定信号
            score = result.signal_score
            if score >= 85: result.buy_signal = BuySignal.STRONG_BUY
            elif score >= 70: result.buy_signal = BuySignal.BUY
            elif score >= 50: result.buy_signal = BuySignal.HOLD
            elif score >= 35: result.buy_signal = BuySignal.WAIT
            else: result.buy_signal = BuySignal.SELL

            # =============== 13. 风险收益比 ===============
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

            # === 核心逻辑：生成分情况建议 ===
            self._generate_detailed_advice(result)

            # =============== 14. 白话版解读 ===============
            self._generate_beginner_summary(result)

            return result

        except Exception as e:
            logger.error(f"[{code}] 分析异常: {e}")
            return result

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

        # 6. 止损止盈白话
        if res.stop_loss_short > 0 and res.take_profit_short > 0:
            sl_pct = abs((price - res.stop_loss_short) / price * 100)
            tp_pct = abs((res.take_profit_short - price) / price * 100)
            parts.append(f"如果买入：跌到{res.stop_loss_short:.2f}元(约跌{sl_pct:.1f}%)就该卖出止损，涨到{res.take_profit_short:.2f}元(约涨{tp_pct:.1f}%)可以先卖一部分锁定利润")

        # 去掉每段末尾的句号再统一拼接，避免双句号
        cleaned = [p.rstrip("。") for p in parts]
        res.beginner_summary = "。".join(cleaned) + "。"

    @staticmethod
    def detect_market_regime(df: pd.DataFrame, index_change_pct: float = 0.0) -> 'MarketRegime':
        """根据个股 MA20 斜率 + 大盘涨跌幅判断市场环境"""
        if df is None or df.empty or len(df) < 30:
            return MarketRegime.SIDEWAYS
        try:
            ma20 = df['close'].rolling(20).mean()
            if len(ma20) < 10:
                return MarketRegime.SIDEWAYS
            ma20_now = ma20.iloc[-1]
            ma20_10d_ago = ma20.iloc[-10]
            if ma20_now <= 0 or ma20_10d_ago <= 0:
                return MarketRegime.SIDEWAYS
            ma20_slope = (ma20_now - ma20_10d_ago) / ma20_10d_ago * 100
            if ma20_slope > 1.0 and index_change_pct >= 0:
                return MarketRegime.BULL
            elif ma20_slope < -1.0 and index_change_pct <= 0:
                return MarketRegime.BEAR
            return MarketRegime.SIDEWAYS
        except Exception:
            return MarketRegime.SIDEWAYS

    # RSI 参数
    RSI_SHORT = 6
    RSI_MID = 12
    RSI_LONG = 24
    # 量能阈值
    VOLUME_SHRINK_RATIO = 0.7
    VOLUME_HEAVY_RATIO = 1.5

    def _calc_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        # === 均线 ===
        df['MA5'] = df['close'].rolling(window=5).mean()
        df['MA10'] = df['close'].rolling(window=10).mean()
        df['MA20'] = df['close'].rolling(window=20).mean()
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

        # === 多周期 RSI (6/12/24) ===
        delta = df['close'].diff()
        for period in [self.RSI_SHORT, self.RSI_MID, self.RSI_LONG]:
            gain = delta.where(delta > 0, 0.0)
            loss_s = (-delta).where(delta < 0, 0.0)
            avg_gain = gain.rolling(window=period).mean()
            avg_loss = loss_s.rolling(window=period).mean()
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

    def format_analysis(self, result: TrendAnalysisResult) -> str:
        breakdown = result.score_breakdown
        breakdown_str = ""
        if breakdown:
            breakdown_str = f" (趋势{breakdown.get('trend',0)}+乖离{breakdown.get('bias',0)}+量能{breakdown.get('volume',0)}+支撑{breakdown.get('support',0)}+MACD{breakdown.get('macd',0)}+RSI{breakdown.get('rsi',0)}+KDJ{breakdown.get('kdj',0)})"

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
        if result.max_drawdown_60d != 0:
            risk_parts.append(f"60日最大回撤{result.max_drawdown_60d:.1f}%")
        if risk_parts:
            risk_str = "\n● 风险: " + " | ".join(risk_parts)

        return f"""
【量化技术报告】
---------------------------
● 综合评分: {result.signal_score}{breakdown_str} ({result.buy_signal.value})
● 趋势状态: {result.trend_status.value} (强度{result.trend_strength:.0f}) | {result.ma_alignment}
● 量能: {result.volume_status.value} ({result.volume_trend}) | 量比 {result.volume_ratio:.2f}
● MACD: {result.macd_status.value} ({result.macd_signal}) | DIF={result.macd_dif:.4f} DEA={result.macd_dea:.4f}
● RSI: {result.rsi_status.value} | RSI6={result.rsi_6:.1f} RSI12={result.rsi_12:.1f} RSI24={result.rsi_24:.1f} | {result.rsi_signal}{f' ⚠️{result.rsi_divergence}' if result.rsi_divergence else ''}
● KDJ: {result.kdj_status.value} | K={result.kdj_k:.1f} D={result.kdj_d:.1f} J={result.kdj_j:.1f} | {result.kdj_signal}
● 关键数据: 现价{result.current_price:.2f} | 乖离MA5={result.bias_ma5:.2f}% MA10={result.bias_ma10:.2f}% MA20={result.bias_ma20:.2f}%{bb_str}{risk_str}{levels_str}

【技术面操作指引 (硬规则)】
👤 针对空仓者: {result.advice_for_empty}
👥 针对持仓者: {result.advice_for_holding}
{anchor_line}
{f'【多指标共振】{abs(result.resonance_count)}个信号同向: {", ".join(result.resonance_signals)} (加分{result.resonance_bonus:+d})' if result.resonance_signals else ''}
{f'【散户白话版】{result.beginner_summary}' if result.beginner_summary else ''}
---------------------------
"""