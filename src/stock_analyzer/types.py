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
    turnover_percentile_confidence: str = ""  # "收盘确认" / "盘中折算估算" / ""
    
    # === 缺口检测 ===
    gap_type: str = ""                     # "向上跳空" / "向下跳空" / ""
    gap_upper: float = 0.0                 # 缺口上沿价格
    gap_lower: float = 0.0                 # 缺口下沿价格
    gap_filled: bool = False               # 缺口是否已回补
    gap_signal: str = ""                   # "未回补压力缺口" / "未回补支撑缺口" / "缺口回补完成" / ""
    
    # === OBV 量能趋势 ===
    obv_trend: str = ""                    # "OBV多头" / "OBV空头" / "OBV中性"
    obv_divergence: str = ""               # "OBV顶背离" / "OBV底背离" / ""
    
    # === ADX 趋势强度 ===
    adx: float = 0.0                       # ADX值 (0-100)
    plus_di: float = 0.0                   # +DI
    minus_di: float = 0.0                  # -DI
    adx_regime: str = ""                   # "强趋势" / "弱趋势" / "震荡"
    
    # === MACD 动量 ===
    macd_bar_slope: float = 0.0            # 柱状图斜率
    macd_bar_accel: int = 0                # 连续同向变化天数
    macd_momentum: str = ""                # "动能加速" / "动能减速" / "动能转向" / ""
    
    # === 均线发散速率 ===
    ma_spread: float = 0.0                 # MA5-MA20 距离百分比
    ma_spread_rate: float = 0.0            # 发散速率（5日变化量）
    ma_spread_signal: str = ""             # "加速发散" / "收敛" / ""
    
    # === K线形态识别 ===
    candle_patterns: List[Dict[str, Any]] = field(default_factory=list)  # 检测到的K线形态列表
    candle_pattern_summary: str = ""       # 一句话形态摘要
    candle_net_signal: str = ""            # "看多" / "看空" / "中性"
    candle_score_adj: int = 0              # 形态对评分的调整 (-5 ~ +5)
    
    # === 周线趋势（P0: 日线分析的大背景）===
    weekly_trend: str = ""                 # "多头" / "空头" / "震荡"
    weekly_ma5: float = 0.0               # 周线MA5（周内5周均线）
    weekly_ma10: float = 0.0              # 周线MA10
    weekly_ma20: float = 0.0              # 周线MA20
    weekly_rsi: float = 50.0             # 周线RSI(14周)
    weekly_trend_adj: int = 0             # 周线趋势对评分的调整(-6 ~ +6)
    weekly_trend_note: str = ""           # 周线趋势描述（供LLM/展示使用）
    
    # === 经典形态识别（P0: 头肩顶/底、双顶/双底）===
    chart_pattern: str = ""               # 识别到的经典形态名称
    chart_pattern_signal: str = ""        # "看空" / "看多" / ""
    chart_pattern_note: str = ""          # 形态描述（颈线位、目标位等）
    chart_pattern_adj: int = 0            # 形态对评分的调整(-8 ~ +8)
    
    # === 不交易过滤器（P0级风控）===
    no_trade: bool = False                     # True=当前不适合交易（比trading_halt更广）
    no_trade_reasons: List[str] = field(default_factory=list)  # 不交易原因列表
    no_trade_severity: str = ""                # "hard"=绝对不交易 / "soft"=建议不交易
    liquidity_warning: str = ""                # 流动性警告
    sideways_warning: str = ""                 # 横盘警告
    market_risk_cap: int = 100                 # 大盘风险导致的仓位上限(%)
    
    # === 止损触发回溯（P0级风控）===
    stop_loss_breached: bool = False           # 盘中最低价是否跌破止损位
    stop_loss_breach_detail: str = ""          # 止损触发详情
    stop_loss_breach_level: str = ""           # 触发的止损级别: "intraday"/"short"/"mid"
    intraday_low: float = 0.0                 # 当日盘中最低价
    
    # === 成交量异动检测 ===
    volume_extreme: str = ""                   # "天量"/"地量"/""
    volume_trend_3d: str = ""                  # "连续放量"/"连续缩量"/""
    
    # === 盘中关键价位监控清单 ===
    intraday_watchlist: List[Dict[str, Any]] = field(default_factory=list)  # [{price, type, action, desc, priority}]
    
    # === 估值增强（P3）===
    pe_percentile: float = -1.0             # 当前PE在历史中的百分位(0-100)，-1=无数据
    valuation_zone: str = ""                # "历史低估区"/"历史合理区"/"历史高估区"/""
    
    # === 情绪极端检测（P3）===
    profit_ratio: float = -1.0              # 获利盘比例(0-100%)，-1=无数据
    trapped_ratio: float = -1.0             # 套牢盘比例(0-100%)，-1=无数据
    sentiment_extreme: str = ""             # "极度贪婪"/"极度恐慌"/""
    sentiment_extreme_detail: str = ""      # 详细描述
    margin_trend: str = ""                  # "融资连续流入"/"融资连续流出"/""
    margin_trend_days: int = 0              # 连续天数
    
    # === 信号详情 ===
    signal_reasons: List[str] = field(default_factory=list)
    risk_factors: List[str] = field(default_factory=list)
    
    # === 场景识别（generate_trade_advice）===
    scenario_id: str = ""               # 匹配到的场景ID，如 "A","B","C","D","E","F","none"
    scenario_label: str = ""            # 场景描述，如 "超跌反弹场景"
    scenario_confidence: str = ""       # "高"/"中"/"低"，基于样本量和一致性
    scenario_expected_20d: str = ""     # 预期20日收益描述，如 "+4-6%"
    scenario_win_rate: str = ""         # 胜率描述，如 "61%"
    trade_advice_empty: str = ""        # 空仓者的操作建议（基于场景）
    trade_advice_holding: str = ""      # 持仓者的操作建议（基于场景）
    trade_advice_position_pct: int = 0  # 建议仓位比例（空仓者入场参考）
    
    # === 黄金分割回撤位（P1/P5-D）===
    fib_swing_high: float = 0.0            # 近期波段高点
    fib_swing_low: float = 0.0             # 近期波段低点
    fib_level_382: float = 0.0             # 0.382 回撤位
    fib_level_500: float = 0.0             # 0.500 回撤位
    fib_level_618: float = 0.0             # 0.618 回撤位
    fib_current_zone: str = ""             # 当前价格所处区间: "0.382支撑区"/"0.618深度回撤"/"已跌破0.618"/""
    fib_signal: str = ""                   # "接近支撑买入区"/"接近阻力卖出区"/"中性"/""
    fib_adj: int = 0                       # 黄金分割对评分的调整(-5 ~ +5)
    fib_note: str = ""                     # 说明文字
    fib_window: int = 60                   # P5-D: 实际采用的有效时间窗口（20/60/120）
    fib_validity: str = ""                 # P5-D: "高历史有效性" / "中历史有效性" / "低历史有效性" / ""
    fib_test_count: int = 0               # P5-D: Fib位在历史上被测试的次数（多次=更可靠）
    
    # === 量价结构（P1: 放量突破/缩量回踩）===
    vol_price_structure: str = ""          # "放量突破"/"缩量回踩"/"放量下跌"/"缩量反弹"/""
    vol_price_breakout_price: float = 0.0  # 突破/跌破的关键价位
    vol_price_structure_adj: int = 0       # 量价结构对评分的调整(-6 ~ +6)
    vol_price_structure_note: str = ""     # 说明文字
    
    # === 天量/地量异常检测（P2）===
    vol_percentile_60d: float = -1.0       # 当日成交量在近60日中的百分位(0-100)
    vol_anomaly: str = ""                  # "天量" / "次天量" / "地量" / "次地量" / ""
    vol_anomaly_adj: int = 0               # 天量/地量对评分的调整(-4 ~ +4)
    vol_anomaly_note: str = ""             # 说明文字
    
    # === 多日时序行为识别（P3）===
    seq_behaviors: List[str] = field(default_factory=list)   # 识别到的行为链标签列表，如["连续5日缩量","冲高回落","主力试盘"]
    seq_behavior_days: Dict[str, int] = field(default_factory=dict)  # 各行为持续天数，如{"缩量":5}
    seq_behavior_note: str = ""                               # 行为链综合说明

    # === 多信号时序共振（P3）===
    resonance_level: str = ""            # "强共振做多" / "强共振做空" / "弱共振" / "信号分歧" / ""
    resonance_intent: str = ""           # 操作意图："主力洗盘" / "主力拉升" / "主力出货" / "自然回调" / ""
    resonance_score_adj: int = 0         # 共振对评分的调整(-8 ~ +8)
    resonance_detail: str = ""           # 共振详情说明

    # === 1-5日行情预判（P3）===
    forecast_scenario: str = ""          # 主要情景："洗盘后拉升" / "高位震荡" / "趋势下跌" / "突破加速" / ""
    forecast_prob_up: int = 0            # 上涨概率(0-100)
    forecast_prob_down: int = 0          # 下跌概率(0-100)
    forecast_prob_sideways: int = 0      # 震荡概率(0-100)
    forecast_trigger: str = ""           # 确认信号："放量突破XX即确认拉升" / "跌破XX则判断回调" / ""
    forecast_note: str = ""              # 预判说明

    # === VWAP 机构成本线（P5-B）===
    vwap10: float = 0.0               # 10日成交量加权均价
    vwap20: float = 0.0               # 20日成交量加权均价
    vwap10_slope: float = 0.0         # 10日VWAP斜率（正=机构成本上移）
    vwap20_slope: float = 0.0         # 20日VWAP斜率
    vwap_trend: str = ""              # "机构成本上移" / "机构成本下移" / "机构成本横盘" / ""
    vwap_position: str = ""           # "价格在VWAP上方" / "价格在VWAP下方" / ""

    # === 主力资金追踪（P4）===
    capital_flow_days: int = 0               # 连续净流入/流出天数（正=流入，负=流出）
    capital_flow_trend: str = ""             # "持续流入" / "持续流出" / "间歇流入" / "资金离场" / ""
    capital_flow_intensity: str = ""         # "大幅" / "温和" / "轻微" / ""
    capital_flow_5d_total: float = 0.0       # 近5日主力净流入累计（万元）
    capital_flow_acceleration: str = ""      # "加速流入" / "加速流出" / "趋缓" / ""
    capital_smart_money: str = ""            # 聪明钱信号："超大单持续买入" / "超大单持续卖出" / ""

    # === 量化情绪指标（P5-C）===
    lhb_net_buy: float = 0.0           # 近一月龙虎榜净买额（元）；正=机构净买，负=净卖
    lhb_institution_net: float = 0.0   # 龙虎榜机构净买额（元）
    lhb_times: int = 0                 # 近一月上榜次数
    lhb_signal: str = ""               # "机构持续买入" / "机构持续卖出" / "龙虎榜活跃" / ""
    holder_change_pct: float = 0.0     # 最新股东人数变化率（负=筹码集中，正=筹码分散）
    holder_signal: str = ""            # "筹码集中（缩股）" / "筹码分散（增股）" / ""

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
