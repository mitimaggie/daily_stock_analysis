# -*- coding: utf-8 -*-
"""
股票分析器 - 类型定义模块
包含所有 Enum 状态类型和数据类
"""

import logging
from dataclasses import dataclass, field
from typing import List, Dict, Any
from enum import Enum

logger = logging.getLogger(__name__)


class TrendStatus(Enum):
    """趋势状态"""
    STRONG_BULL = "强势多头"
    BULL = "多头排列"
    WEAK_BULL = "弱势多头"
    CONSOLIDATION = "震荡整理"
    WEAK_BEAR = "弱势空头"
    BEAR = "空头排列"
    STRONG_BEAR = "强势空头"


class VolumeStatus(Enum):
    """量能状态"""
    HEAVY_VOLUME_UP = "放量上涨"       # 量价齐升
    HEAVY_VOLUME_DOWN = "放量下跌"     # 放量杀跌
    SHRINK_VOLUME_UP = "缩量上涨"      # 无量上涨
    SHRINK_VOLUME_DOWN = "缩量回调"    # 缩量回调（好）
    NORMAL = "量能正常"


class MACDStatus(Enum):
    """MACD状态"""
    GOLDEN_CROSS_ZERO = "零轴上金叉"   # DIF上穿DEA，且在零轴上方（最强买入）
    GOLDEN_CROSS = "金叉"              # DIF上穿DEA
    CROSSING_UP = "上穿零轴"           # DIF上穿零轴，趋势转强
    BULLISH = "多头"                   # DIF>DEA>0
    NEUTRAL = "中性"
    BEARISH = "空头"                   # DIF<DEA<0
    CROSSING_DOWN = "下穿零轴"         # DIF下穿零轴，趋势转弱
    DEATH_CROSS = "死叉"               # DIF下穿DEA


class RSIStatus(Enum):
    """RSI状态"""
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
    """KDJ状态"""
    GOLDEN_CROSS_OVERSOLD = "超卖金叉"   # K上穿D且J<20，强买入信号
    GOLDEN_CROSS = "金叉"               # K上穿D
    BULLISH = "多头"                     # K>D，J>50
    NEUTRAL = "中性"                     # K≈D
    BEARISH = "空头"                     # K<D，J<50
    DEATH_CROSS = "死叉"                 # K下穿D
    OVERBOUGHT = "超买"                  # J>100，短期回调风险
    OVERSOLD = "超卖"                    # J<0，反弹机会


class BuySignal(Enum):
    """买卖信号分级（7档）"""
    AGGRESSIVE_BUY = "激进买入"       # 95+: 共振信号+趋势确认，大胆上车
    STRONG_BUY = "强烈买入"       # 85-94: 多重指标共振，胜率高
    BUY = "买入"                # 70-84: 技术面看好，可建仓
    CAUTIOUS_BUY = "谨慎买入"   # 60-69: 有机会但需谨慎
    HOLD = "持有"                # 50-59: 中性，持股待涨
    REDUCE = "减仓"              # 35-49: 信号转弱，逐步减仓
    SELL = "清仓"                # 0-34: 多重风险，先走为妙


class MarketRegime(Enum):
    """市场环境"""
    BULL = "bull"
    SIDEWAYS = "sideways"
    BEAR = "bear"


@dataclass
class TrendAnalysisResult:
    """趋势分析结果数据类"""
    code: str
    current_price: float = 0.0
    
    # === 核心结论 ===
    trend_status: TrendStatus = TrendStatus.CONSOLIDATION
    signal_score: int = 50 
    buy_signal: BuySignal = BuySignal.HOLD
    
    # === 分持仓情况建议 ===
    advice_for_empty: str = ""    # 给空仓者的建议
    advice_for_holding: str = ""  # 给持仓者的建议
    
    # === 趋势强度 ===
    trend_strength: float = 50.0  # 0-100, 基于均线间距扩张/收缩
    ma_alignment: str = ""        # 均线排列描述

    # === 基础均线数据 ===
    ma5: float = 0.0
    ma10: float = 0.0
    ma20: float = 0.0
    ma60: float = 0.0
    bias_ma5: float = 0.0
    bias_ma10: float = 0.0
    bias_ma20: float = 0.0
    
    # === 量能数据 ===
    volume_ratio: float = 0.0
    volume_trend: str = "量能正常"
    volume_status: VolumeStatus = VolumeStatus.NORMAL
    
    # === MACD指标 ===
    macd_dif: float = 0.0
    macd_dea: float = 0.0
    macd_bar: float = 0.0
    macd_status: MACDStatus = MACDStatus.NEUTRAL
    macd_signal: str = ""
    
    # === RSI指标 ===
    rsi_6: float = 50.0
    rsi_12: float = 50.0
    rsi_24: float = 50.0
    rsi: float = 50.0             # 保留兼容（= rsi_12）
    rsi_status: RSIStatus = RSIStatus.NEUTRAL
    rsi_signal: str = ""
    rsi_divergence: str = ""      # 背离信号描述（底背离/顶背离/无）
    
    # === KDJ指标 ===
    kdj_k: float = 50.0
    kdj_d: float = 50.0
    kdj_j: float = 50.0
    kdj_status: KDJStatus = KDJStatus.NEUTRAL
    kdj_signal: str = ""
    
    # === 波动率指标 ===
    atr14: float = 0.0
    volatility_20d: float = 0.0   # 20日年化波动率
    
    # === 布林带指标 ===
    bb_upper: float = 0.0
    bb_lower: float = 0.0
    bb_width: float = 0.0         # (upper - lower) / middle, 衡量波动率
    bb_pct_b: float = 0.5         # (close - lower) / (upper - lower), 价格在带内位置
    
    # === 风险指标 ===
    beta_vs_index: float = 1.0    # 相对大盘 Beta
    max_drawdown_60d: float = 0.0 # 近60日最大回撤(%)
    
    # === 止损止盈锚点 ===
    stop_loss_anchor: float = 0.0       # 保留兼容 (= stop_loss_short)
    stop_loss_intraday: float = 0.0     # 日内止损 (0.7 ATR, 紧)
    stop_loss_short: float = 0.0        # 短线止损 (1.0 ATR)
    stop_loss_mid: float = 0.0          # 中线止损 (1.5 ATR + MA20*0.98)
    ideal_buy_anchor: float = 0.0
    take_profit_short: float = 0.0      # 短线止盈 (1.5 ATR)
    take_profit_mid: float = 0.0        # 中线止盈 (第一阻力位)
    take_profit_trailing: float = 0.0   # 移动止盈线 (最高价 - 1.2 ATR)
    take_profit_plan: str = ""          # 分批止盈方案描述
    risk_reward_ratio: float = 0.0      # R:R ratio (收益空间 / 风险空间)
    risk_reward_verdict: str = ""       # "值得" / "不值得" / "中性"
    
    # === 支撑/阻力位 ===
    support_levels: List[float] = field(default_factory=list)
    resistance_levels: List[float] = field(default_factory=list)
    
    # === 多指标共振 ===
    resonance_count: int = 0            # 共振信号数量 (0-5)
    resonance_signals: List[str] = field(default_factory=list)  # 共振信号列表
    resonance_bonus: int = 0            # 共振加分
    indicator_resonance: str = ""       # P1新增：指标组合共振判断结果
    market_behavior: str = ""           # P1新增：市场行为识别结果
    timeframe_resonance: str = ""       # P2新增：多时间周期共振结果
    
    # === 白话版解读 ===
    beginner_summary: str = ""          # 通俗语言版分析结论
    
    # === 估值安全检查 ===
    pe_ratio: float = 0.0               # 市盈率
    pb_ratio: float = 0.0               # 市净率
    peg_ratio: float = 0.0              # PEG
    valuation_score: int = 0            # 估值评分 (0-10, 10=严重低估)
    valuation_verdict: str = ""         # "低估" / "合理" / "偏高" / "严重高估"
    valuation_downgrade: int = 0        # 估值降档扣分 (0~-15)
    
    # === 全局暂停信号 ===
    trading_halt: bool = False          # True=不适合交易
    trading_halt_reason: str = ""       # 暂停原因
    
    # === 资金面评分 ===
    capital_flow_score: int = 0         # 资金面评分 (0-10)
    capital_flow_signal: str = ""       # 资金面信号描述
    
    # === 仓位管理 ===
    suggested_position_pct: int = 0     # 建议仓位占比 (0-30%)
    recommended_position: int = 0       # P2新增：动态仓位管理（0-80%）
    position_breakdown: Dict[str, Any] = field(default_factory=dict)  # P2新增：仓位计算详情
    
    # === 板块强弱 ===
    sector_name: str = ""               # 所属板块名称
    sector_pct: float = 0.0             # 板块当日涨跌幅(%)
    sector_relative: float = 0.0        # 个股 vs 板块相对强弱(百分点)
    sector_score: int = 5               # 板块评分 (0-10, 5=中性)
    sector_signal: str = ""             # 板块信号描述
    
    # === 筹码分布 ===
    chip_score: int = 5                 # 筹码评分 (0-10, 5=中性)
    chip_signal: str = ""               # 筹码信号描述
    
    # === 基本面质量 ===
    fundamental_score: int = 5          # 基本面评分 (0-10, 5=中性)
    fundamental_signal: str = ""        # 基本面信号描述
    
    # === 52周位置 ===
    week52_position: float = 0.0        # 当前价格在 52周高低中的位置(0-100%)
    
    # === 信号详情 ===
    signal_reasons: List[str] = field(default_factory=list)
    risk_factors: List[str] = field(default_factory=list)
    
    # === 结构化评分明细 ===
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
            "recommended_position": self.recommended_position,
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
            "indicator_resonance": self.indicator_resonance,
            "market_behavior": self.market_behavior,
            "timeframe_resonance": self.timeframe_resonance,
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
