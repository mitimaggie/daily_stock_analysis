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
            
            # 量比处理
            vol_ma5 = df['volume'].iloc[-6:-1].mean()
            result.volume_ratio = float(latest['volume'] / vol_ma5) if vol_ma5 > 0 else 1.0
            if 'volume_ratio' in latest and latest['volume_ratio'] > 0:
                result.volume_ratio = float(latest['volume_ratio'])
                
            # 1. 趋势判定
            ma5, ma10, ma20 = result.ma5, result.ma10, result.ma20
            score = 50
            
            if ma5 > ma10 > ma20:
                result.trend_status = TrendStatus.BULL
                score = 70
                if ma20 > 0 and (ma5 - ma20) / ma20 > 0.05:
                    result.trend_status = TrendStatus.STRONG_BULL
                    score = 75
            elif ma5 < ma10 < ma20:
                result.trend_status = TrendStatus.BEAR
                score = 30
            else:
                result.trend_status = TrendStatus.CONSOLIDATION
                score = 50

            # 2. 乖离率与择时
            bias = (result.current_price - ma5) / ma5 * 100 if ma5 > 0 else 0
            result.bias_ma5 = bias
            
            # 基础分调整
            if bias > 8: score -= 15
            elif bias > 5: score -= 5
            elif 0 <= bias <= 3 and result.trend_status in [TrendStatus.BULL]: score += 10
            elif -5 <= bias < 0:
                if result.volume_ratio < 0.8: score += 15
                else: score += 10
            elif bias < -10:
                if result.trend_status == TrendStatus.BEAR: score -= 5
                else: score += 10

            # 3. 辅助指标
            # MACD
            if latest['MACD_DIF'] > latest['MACD_DEA'] and prev['MACD_DIF'] <= prev['MACD_DEA']:
                score += 5
                result.macd_signal = "金叉"
            # KDJ
            if latest['K'] < 40 and latest['K'] > latest['D'] and prev['K'] <= prev['D']:
                score += 5
                result.kdj_signal = "金叉"

            # 4. 最终评级
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
        
        ema12 = df['close'].ewm(span=12, adjust=False).mean()
        ema26 = df['close'].ewm(span=26, adjust=False).mean()
        df['MACD_DIF'] = ema12 - ema26
        df['MACD_DEA'] = df['MACD_DIF'].ewm(span=9, adjust=False).mean()
        
        low_min = df['low'].rolling(window=9).min()
        high_max = df['high'].rolling(window=9).max()
        rsv = (df['close'] - low_min) / (high_max - low_min) * 100
        df['K'] = rsv.ewm(com=2, adjust=False).mean()
        df['D'] = df['K'].ewm(com=2, adjust=False).mean()
        return df.fillna(0)

    def format_analysis(self, result: TrendAnalysisResult) -> str:
        return f"""
【量化技术报告】
---------------------------
● 综合评分: {result.signal_score} ({result.buy_signal.value})
● 趋势状态: {result.trend_status.value}
● 关键数据: 现价{result.current_price:.2f} | MA5乖离率 {result.bias_ma5:.2f}% | 量比 {result.volume_ratio:.2f}

【技术面操作指引 (硬规则)】
👤 针对空仓者: {result.advice_for_empty}
👥 针对持仓者: {result.advice_for_holding}
---------------------------
"""