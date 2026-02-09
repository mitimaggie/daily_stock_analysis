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
    AMPLIFY = "放量"
    NORMAL = "量能正常"
    SHRINK = "缩量"

class MACDStatus(Enum):
    GOLDEN_CROSS = "金叉"
    DEATH_CROSS = "死叉"
    BULLISH = "多头"
    BEARISH = "空头"
    NEUTRAL = "中性"

class RSIStatus(Enum):
    OVERSOLD = "超卖"
    NEUTRAL = "中性"
    OVERBOUGHT = "超买"

class BuySignal(Enum):
    STRONG_BUY = "强烈买入"
    BUY = "买入"
    HOLD = "持有"
    WAIT = "观望"
    SELL = "卖出"

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
    
    # 基础数据
    ma5: float = 0.0
    ma10: float = 0.0
    ma20: float = 0.0
    bias_ma5: float = 0.0
    volume_ratio: float = 0.0
    volume_trend: str = "量能正常"
    
    # 辅助信息
    signal_reasons: List[str] = field(default_factory=list)
    risk_factors: List[str] = field(default_factory=list)
    macd_signal: str = ""
    kdj_signal: str = ""

    # 扩展指标（波动率/长周期/超买超卖）
    atr14: float = 0.0
    ma60: float = 0.0
    rsi: float = 50.0
    rsi_signal: str = ""
    # 量化锚点（供 LLM 参考，避免拍脑袋）
    stop_loss_anchor: float = 0.0
    ideal_buy_anchor: float = 0.0

    # 枚举化状态（上游风格）
    volume_status: VolumeStatus = VolumeStatus.NORMAL
    macd_status: MACDStatus = MACDStatus.NEUTRAL
    rsi_status: RSIStatus = RSIStatus.NEUTRAL

    # 支撑/阻力位
    support_levels: List[float] = field(default_factory=list)
    resistance_levels: List[float] = field(default_factory=list)

    # 结构化评分明细（总分 100：trend 30 + bias 20 + volume 15 + support 10 + macd 15 + rsi 10）
    score_breakdown: Dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """序列化为 dict，供 pipeline 注入 context 或 prompt 结构化输入"""
        return {
            "code": self.code,
            "current_price": self.current_price,
            "trend_status": self.trend_status.value,
            "buy_signal": self.buy_signal.value,
            "signal_score": self.signal_score,
            "score_breakdown": self.score_breakdown,
            "volume_status": self.volume_status.value,
            "macd_status": self.macd_status.value,
            "rsi_status": self.rsi_status.value,
            "ma5": self.ma5, "ma10": self.ma10, "ma20": self.ma20, "ma60": self.ma60,
            "bias_ma5": self.bias_ma5, "volume_ratio": self.volume_ratio,
            "atr14": self.atr14, "rsi": self.rsi,
            "stop_loss_anchor": self.stop_loss_anchor,
            "ideal_buy_anchor": self.ideal_buy_anchor,
            "support_levels": self.support_levels,
            "resistance_levels": self.resistance_levels,
            "advice_for_empty": self.advice_for_empty,
            "advice_for_holding": self.advice_for_holding,
            "macd_signal": self.macd_signal, "kdj_signal": self.kdj_signal,
        }

class StockTrendAnalyzer:
    
    def analyze(self, df: pd.DataFrame, code: str) -> TrendAnalysisResult:
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
            result.rsi = float(latest.get('RSI', 50) or 50)
            if result.rsi > 70:
                result.rsi_signal = "超买"
            elif result.rsi < 30:
                result.rsi_signal = "超卖"
            else:
                result.rsi_signal = ""

            sl_atr = result.current_price - 1.5 * result.atr14 if result.atr14 > 0 else 0
            sl_ma20 = result.ma20 * 0.98 if result.ma20 > 0 else 0
            result.stop_loss_anchor = round(min(sl_atr, sl_ma20) if (sl_atr > 0 and sl_ma20 > 0) else (sl_atr or sl_ma20 or 0), 2)
            result.ideal_buy_anchor = round(result.ma5 if result.ma5 > 0 else result.ma10, 2)

            # 量比处理
            vol_ma5 = df['volume'].iloc[-6:-1].mean()
            result.volume_ratio = float(latest['volume'] / vol_ma5) if vol_ma5 > 0 else 1.0
            if 'volume_ratio' in latest and latest['volume_ratio'] > 0:
                result.volume_ratio = float(latest['volume_ratio'])
            # VolumeStatus
            vr = result.volume_ratio
            result.volume_status = VolumeStatus.AMPLIFY if vr >= 1.5 else (VolumeStatus.SHRINK if vr < 0.8 else VolumeStatus.NORMAL)
            result.volume_trend = result.volume_status.value

            # MACDStatus
            dif, dea = latest['MACD_DIF'], latest['MACD_DEA']
            pdif, pdea = prev['MACD_DIF'], prev['MACD_DEA']
            if dif > dea and pdif <= pdea:
                result.macd_status = MACDStatus.GOLDEN_CROSS
                result.macd_signal = "金叉"
            elif dif < dea and pdif >= pdea:
                result.macd_status = MACDStatus.DEATH_CROSS
                result.macd_signal = "死叉"
            elif dif > dea:
                result.macd_status = MACDStatus.BULLISH
            elif dif < dea:
                result.macd_status = MACDStatus.BEARISH
            else:
                result.macd_status = MACDStatus.NEUTRAL

            # RSIStatus
            if result.rsi > 70:
                result.rsi_status = RSIStatus.OVERBOUGHT
                result.rsi_signal = "超买"
            elif result.rsi < 30:
                result.rsi_status = RSIStatus.OVERSOLD
                result.rsi_signal = "超卖"
            else:
                result.rsi_status = RSIStatus.NEUTRAL
                result.rsi_signal = ""

            # 支撑/阻力位（近 20 日高低点 + 均线）
            result.support_levels, result.resistance_levels = self._compute_levels(df, result)

            # 1. 趋势判定
            ma5, ma10, ma20 = result.ma5, result.ma10, result.ma20
            trend_score = 15
            if ma5 > ma10 > ma20:
                result.trend_status = TrendStatus.BULL
                trend_score = 22
                if ma20 > 0 and (ma5 - ma20) / ma20 > 0.05:
                    result.trend_status = TrendStatus.STRONG_BULL
                    trend_score = 30
            elif ma5 < ma10 < ma20:
                result.trend_status = TrendStatus.BEAR
                trend_score = 5
            else:
                result.trend_status = TrendStatus.CONSOLIDATION
                trend_score = 15

            # 2. 乖离率 (bias 0-20)
            bias = (result.current_price - ma5) / ma5 * 100 if ma5 > 0 else 0
            result.bias_ma5 = bias
            bias_score = 10
            if bias > 8:
                bias_score = 0
            elif bias > 5:
                bias_score = 5
            elif 0 <= bias <= 3 and result.trend_status in [TrendStatus.BULL, TrendStatus.STRONG_BULL]:
                bias_score = 18
            elif -5 <= bias < 0:
                bias_score = 18 if result.volume_ratio < 0.8 else 15
            elif -10 <= bias < -5:
                bias_score = 12 if result.trend_status != TrendStatus.BEAR else 5
            elif bias < -10:
                bias_score = 8 if result.trend_status != TrendStatus.BEAR else 2

            # 3. 量能 (volume 0-15)
            vol_score = 8
            if result.volume_status == VolumeStatus.AMPLIFY and result.trend_status in [TrendStatus.BULL, TrendStatus.STRONG_BULL]:
                vol_score = 15
            elif result.volume_status == VolumeStatus.SHRINK and bias < 0 and result.trend_status in [TrendStatus.BULL]:
                vol_score = 12  # 缩量回调可视为洗盘
            elif result.volume_status == VolumeStatus.SHRINK and result.trend_status == TrendStatus.BEAR:
                vol_score = 3

            # 4. 支撑接近度 (support 0-10)：现价距支撑越近越好
            support_score = 5
            if result.support_levels and result.current_price > 0:
                nearest = min((s for s in result.support_levels if s > 0 and s < result.current_price), default=0) or result.ma20
                if nearest > 0:
                    dist_pct = (result.current_price - nearest) / result.current_price * 100
                    if 0 <= dist_pct <= 2:
                        support_score = 10
                    elif dist_pct <= 5:
                        support_score = 7

            # 5. MACD (0-15)
            macd_score = 8
            if result.macd_status == MACDStatus.GOLDEN_CROSS:
                macd_score = 15
            elif result.macd_status == MACDStatus.BULLISH:
                macd_score = 12
            elif result.macd_status == MACDStatus.DEATH_CROSS:
                macd_score = 0
            elif result.macd_status == MACDStatus.BEARISH:
                macd_score = 3
            # KDJ 金叉加分（在 MACD 分内体现）
            if latest['K'] < 40 and latest['K'] > latest['D'] and prev['K'] <= prev['D']:
                result.kdj_signal = "金叉"
                macd_score = min(15, macd_score + 3)

            # 6. RSI (0-10)
            rsi_score = 5
            if result.rsi_status == RSIStatus.OVERSOLD:
                rsi_score = 8 if result.trend_status != TrendStatus.BEAR else 4
            elif result.rsi_status == RSIStatus.OVERBOUGHT:
                rsi_score = 2
            elif 40 <= result.rsi <= 60:
                rsi_score = 7

            result.score_breakdown = {
                "trend": min(30, trend_score),
                "bias": min(20, bias_score),
                "volume": min(15, vol_score),
                "support": min(10, support_score),
                "macd": min(15, macd_score),
                "rsi": min(10, rsi_score),
            }
            score = sum(result.score_breakdown.values())
            score = min(100, max(0, score))
            result.signal_score = int(score)
            
            if score >= 85: result.buy_signal = BuySignal.STRONG_BUY
            elif score >= 70: result.buy_signal = BuySignal.BUY
            elif score >= 50: result.buy_signal = BuySignal.HOLD
            elif score >= 35: result.buy_signal = BuySignal.WAIT
            else: result.buy_signal = BuySignal.SELL
            
            # === 核心逻辑：生成分情况建议 ===
            self._generate_detailed_advice(result)

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

    def _calc_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df['MA5'] = df['close'].rolling(window=5).mean()
        df['MA10'] = df['close'].rolling(window=10).mean()
        df['MA20'] = df['close'].rolling(window=20).mean()
        df['MA60'] = df['close'].rolling(window=60).mean()

        ema12 = df['close'].ewm(span=12, adjust=False).mean()
        ema26 = df['close'].ewm(span=26, adjust=False).mean()
        df['MACD_DIF'] = ema12 - ema26
        df['MACD_DEA'] = df['MACD_DIF'].ewm(span=9, adjust=False).mean()

        low_min = df['low'].rolling(window=9).min()
        high_max = df['high'].rolling(window=9).max()
        rsv = (df['close'] - low_min) / (high_max - low_min) * 100
        df['K'] = rsv.ewm(com=2, adjust=False).mean()
        df['D'] = df['K'].ewm(com=2, adjust=False).mean()

        tr = np.maximum(df['high'] - df['low'], np.maximum(abs(df['high'] - df['close'].shift(1)), abs(df['low'] - df['close'].shift(1))))
        df['ATR14'] = tr.rolling(window=14).mean()

        delta = df['close'].diff()
        gain = delta.where(delta > 0, 0.0)
        loss = (-delta).where(delta < 0, 0.0)
        avg_gain = gain.ewm(span=14, adjust=False).mean()
        avg_loss = loss.ewm(span=14, adjust=False).mean()
        rs = avg_gain / avg_loss.replace(0, np.nan)
        df['RSI'] = 100 - (100 / (1 + rs))
        df['RSI'] = df['RSI'].fillna(50)

        return df.fillna(0)

    def format_analysis(self, result: TrendAnalysisResult) -> str:
        rsi_line = f" | RSI {result.rsi:.0f}{'(' + result.rsi_signal + ')' if result.rsi_signal else ''}" if result.rsi else ""
        anchor_line = ""
        if result.stop_loss_anchor > 0 or result.ideal_buy_anchor > 0:
            anchor_line = f"""
【量化锚点 (battle_plan 须参考)】
● 建议止损参考: {result.stop_loss_anchor:.2f} (现价-1.5*ATR 与 MA20*0.98 取低，stop_loss 不得偏离过远)
● 理想买点参考: {result.ideal_buy_anchor:.2f} (MA5/MA10 支撑，ideal_buy 可微调)
● ATR14: {result.atr14:.2f} | MA60: {result.ma60:.2f}
"""
        breakdown = result.score_breakdown
        breakdown_str = ""
        if breakdown:
            breakdown_str = f" (趋势{breakdown.get('trend',0)}+乖离{breakdown.get('bias',0)}+量能{breakdown.get('volume',0)}+支撑{breakdown.get('support',0)}+MACD{breakdown.get('macd',0)}+RSI{breakdown.get('rsi',0)})"

        levels_str = ""
        if result.support_levels or result.resistance_levels:
            sup = ",".join(f"{x:.2f}" for x in result.support_levels[:3]) if result.support_levels else "无"
            res = ",".join(f"{x:.2f}" for x in result.resistance_levels[:3]) if result.resistance_levels else "无"
            levels_str = f"""
【支撑/阻力】支撑: {sup} | 阻力: {res}
"""
        return f"""
【量化技术报告】
---------------------------
● 综合评分: {result.signal_score}{breakdown_str} ({result.buy_signal.value})
● 趋势状态: {result.trend_status.value} | 量能: {result.volume_status.value} | MACD: {result.macd_status.value} | RSI: {result.rsi_status.value}
● 关键数据: 现价{result.current_price:.2f} | MA5乖离率 {result.bias_ma5:.2f}% | 量比 {result.volume_ratio:.2f}{rsi_line}
{levels_str}
【技术面操作指引 (硬规则)】
👤 针对空仓者: {result.advice_for_empty}
👥 针对持仓者: {result.advice_for_holding}
{anchor_line}---------------------------
"""