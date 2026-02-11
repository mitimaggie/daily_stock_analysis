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
    kdj_divergence: str = ""              # KDJ背离信号（"KDJ底背离"/"KDJ顶背离"/""）
    kdj_consecutive_extreme: str = ""     # J值连续极端（"J值连续超买N天"/"J值连续超卖N天"/""）
    kdj_passivation: bool = False         # KDJ钝化状态（强趋势中超买/超卖不可靠）
    
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
    
    # === 涨跌停检测（A股特有）===
    is_limit_up: bool = False              # 当日涨停
    is_limit_down: bool = False            # 当日跌停
    limit_pct: float = 10.0                # 涨跌停幅度(10 or 20)
    consecutive_limits: int = 0            # 连续涨/跌停天数
    
    # === VWAP ===
    vwap: float = 0.0                      # 成交量加权平均价
    vwap_bias: float = 0.0                 # 现价相对VWAP偏离率(%)
    
    # === 量价背离 ===
    volume_price_divergence: str = ""      # "顶部量价背离" / "底部量缩企稳" / ""
    
    # === 换手率分位数 ===
    turnover_percentile: float = 0.5       # 换手率在历史中的分位数(0-1)
    
    # === 缺口检测 ===
    gap_type: str = ""                     # "向上跳空" / "向下跳空" / ""
    
    # === 信号详情 ===
    signal_reasons: List[str] = field(default_factory=list)
    risk_factors: List[str] = field(default_factory=list)
    
    # === 结构化评分明细 ===
    score_breakdown: Dict[str, int] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """序列化为 dict，供 pipeline 注入 context 或 prompt 结构化输入。
        
        自动遍历 dataclass 字段，Enum 类型自动取 .value，
        新增字段时无需手动同步此方法。
        """
        from dataclasses import fields as dc_fields
        d = {}
        for f in dc_fields(self):
            val = getattr(self, f.name)
            if isinstance(val, Enum):
                d[f.name] = val.value
            else:
                d[f.name] = val
        return d
