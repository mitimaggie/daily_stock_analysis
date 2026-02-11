# -*- coding: utf-8 -*-
"""
风险管理模块
包含止损止盈、仓位管理、风险收益比计算等逻辑
"""

import logging
import pandas as pd
from typing import List, Tuple
from .types import TrendAnalysisResult, TrendStatus, MarketRegime

logger = logging.getLogger(__name__)


class RiskManager:
    """风险管理器：止损止盈、仓位管理"""
    
    @staticmethod
    def calculate_stop_loss_and_take_profit(result: TrendAnalysisResult, df: pd.DataFrame):
        """
        计算动态止损止盈锚点
        
        Args:
            result: 分析结果对象
            df: K线数据
        """
        atr = result.atr14
        price = result.current_price
        
        if atr <= 0 or price <= 0:
            return
        
        from .indicators import TechnicalIndicators
        atr_percentile = TechnicalIndicators.calc_atr_percentile(df)
        
        if atr_percentile > 0.8:
            atr_multiplier_short = 1.5
            atr_multiplier_mid = 2.0
        elif atr_percentile < 0.2:
            atr_multiplier_short = 0.8
            atr_multiplier_mid = 1.2
        else:
            atr_multiplier_short = 1.0
            atr_multiplier_mid = 1.5
        
        result.stop_loss_intraday = round(price - 0.7 * atr_multiplier_short * atr, 2)
        result.stop_loss_short = round(price - atr_multiplier_short * atr, 2)
        
        if len(df) >= 20:
            recent_high_20d = float(df['high'].tail(20).max())
            chandelier_sl = recent_high_20d - atr_multiplier_mid * atr
            sl_ma20 = result.ma20 * 0.98 if result.ma20 > 0 else chandelier_sl
            result.stop_loss_mid = round(min(chandelier_sl, sl_ma20), 2)
        else:
            sl_atr_mid = price - atr_multiplier_mid * atr
            sl_ma20 = result.ma20 * 0.98 if result.ma20 > 0 else sl_atr_mid
            result.stop_loss_mid = round(min(sl_atr_mid, sl_ma20) if sl_ma20 > 0 else sl_atr_mid, 2)
        
        result.stop_loss_anchor = result.stop_loss_short
        result.ideal_buy_anchor = round(result.ma5 if result.ma5 > 0 else result.ma10, 2)
        
        if result.trend_status in [TrendStatus.STRONG_BULL, TrendStatus.BULL]:
            tp_multiplier_short = 2.0
            tp_multiplier_mid = 3.5
        elif result.trend_status == TrendStatus.CONSOLIDATION:
            tp_multiplier_short = 1.2
            tp_multiplier_mid = 2.0
        else:
            tp_multiplier_short = 1.5
            tp_multiplier_mid = 2.5
        
        result.take_profit_short = round(price + tp_multiplier_short * atr, 2)
        
        if result.resistance_levels:
            result.take_profit_mid = round(result.resistance_levels[0], 2)
        else:
            result.take_profit_mid = round(price + tp_multiplier_mid * atr, 2)
        
        if len(df) >= 20:
            recent_high = float(df['high'].tail(20).max())
            trailing_atr_mult = 1.5 if result.trend_strength >= 75 else 1.2
            result.take_profit_trailing = round(recent_high - trailing_atr_mult * atr, 2)
        
        tp1 = result.take_profit_short
        tp2 = result.take_profit_mid
        result.take_profit_plan = (
            f"第1批(1/3仓位): 到{tp1:.2f}止盈 | "
            f"第2批(1/3仓位): 到{tp2:.2f}止盈 | "
            f"第3批(底仓): 移动止盈线{result.take_profit_trailing:.2f}跟踪（Parabolic SAR）"
        )
    
    @staticmethod
    def calculate_position(result: TrendAnalysisResult, market_regime: MarketRegime, regime_strength: int = 50):
        """
        增强版仓位管理系统：动态仓位 + 凯利公式 + 风险分散
        
        仓位决策因子：
        1. 信号评分 (signal_score)
        2. 风险收益比 (risk_reward_ratio)
        3. 趋势强度 (trend_strength)
        4. 市场环境 (market_regime)
        5. 波动率 (volatility_20d)
        """
        base_position = 0
        
        score = result.signal_score
        if score >= 85:
            base_position = 50
        elif score >= 70:
            base_position = 40
        elif score >= 60:
            base_position = 30
        elif score >= 50:
            base_position = 20
        elif score >= 40:
            base_position = 10
        else:
            base_position = 0
        
        multipliers = []
        
        if result.risk_reward_ratio >= 3.0:
            multipliers.append(1.3)
        elif result.risk_reward_ratio >= 2.0:
            multipliers.append(1.1)
        elif result.risk_reward_ratio < 1.0:
            multipliers.append(0.7)
        
        if result.trend_strength >= 80:
            multipliers.append(1.2)
        elif result.trend_strength < 50:
            multipliers.append(0.8)
        
        regime_mult = {
            MarketRegime.BULL: 1.2,
            MarketRegime.SIDEWAYS: 1.0,
            MarketRegime.BEAR: 0.6,
        }
        multipliers.append(regime_mult.get(market_regime, 1.0))
        
        if result.volatility_20d > 0:
            if result.volatility_20d > 60:
                multipliers.append(0.7)
            elif result.volatility_20d < 25:
                multipliers.append(1.1)
        
        position = base_position
        for mult in multipliers:
            position = position * mult
        
        position = max(0, min(80, int(position)))
        result.recommended_position = position
        
        result.suggested_position_pct = min(30, position // 2)
        
        result.position_breakdown = {
            'base': base_position,
            'multipliers': multipliers,
            'final': position
        }
    
    @staticmethod
    def calculate_risk_reward(result: TrendAnalysisResult, price: float):
        """风险收益比计算"""
        if result.stop_loss_short > 0 and result.take_profit_short > 0 and price > 0:
            risk = price - result.stop_loss_short
            reward = result.take_profit_short - price
            if risk > 0:
                result.risk_reward_ratio = round(reward / risk, 2)
                if result.risk_reward_ratio >= 2.0:
                    result.risk_reward_verdict = "值得"
                elif result.risk_reward_ratio >= 1.5:
                    result.risk_reward_verdict = "中性"
                else:
                    result.risk_reward_verdict = "不值得"
    
    @staticmethod
    def compute_support_resistance_levels(df: pd.DataFrame, result: TrendAnalysisResult) -> Tuple[List[float], List[float]]:
        """
        计算支撑位和阻力位：近 20 日 Swing 高低点 + 均线
        
        Args:
            df: K线数据
            result: 分析结果对象
            
        Returns:
            (支撑位列表, 阻力位列表)
        """
        support_set, resistance_set = set(), set()
        tail = df.tail(30)
        
        if len(tail) >= 5:
            for i in range(2, len(tail) - 2):
                h = float(tail.iloc[i]['high'])
                l = float(tail.iloc[i]['low'])
                prev_h = float(tail.iloc[i-1]['high'])
                prev_l = float(tail.iloc[i-1]['low'])
                next_h = float(tail.iloc[i+1]['high'])
                next_l = float(tail.iloc[i+1]['low'])
                
                if h > prev_h and h > next_h:
                    resistance_set.add(h)
                if l < prev_l and l < next_l:
                    support_set.add(l)
        
        if result.ma5 > 0:
            support_set.add(result.ma5)
        if result.ma10 > 0:
            support_set.add(result.ma10)
        if result.ma20 > 0:
            support_set.add(result.ma20)
        if result.ma60 > 0:
            support_set.add(result.ma60)
        
        price = result.current_price
        supports = sorted([s for s in support_set if 0 < s < price], reverse=True)[:5]
        resistances = sorted([r for r in resistance_set if r > price])[:5]
        
        return supports, resistances
    
    @staticmethod
    def generate_detailed_advice(result: TrendAnalysisResult):
        """生成持仓/空仓的分离建议"""
        bias = result.bias_ma5
        trend = result.trend_status
        score = result.signal_score
        
        if score >= 85:
            result.advice_for_empty = f"技术面强势(评分{score})，乖离{bias:.1f}%，可适当追高，止损{result.stop_loss_short:.2f}"
            result.advice_for_holding = f"持有为主(评分{score})，目标{result.take_profit_mid:.2f}，移动止盈{result.take_profit_trailing:.2f}"
        elif score >= 70:
            if -3 <= bias <= 3:
                result.advice_for_empty = f"回踩买点，可分批建仓(评分{score})，止损{result.stop_loss_short:.2f}"
                result.advice_for_holding = f"继续持有(评分{score})，目标{result.take_profit_mid:.2f}"
            else:
                result.advice_for_empty = f"技术面偏强(评分{score})但乖离{bias:.1f}%偏大，等回调至MA5附近"
                result.advice_for_holding = f"持有为主(评分{score})，分批止盈{result.take_profit_short:.2f}"
        elif score >= 60:
            result.advice_for_empty = f"谨慎乐观(评分{score})，轻仓试探，止损{result.stop_loss_short:.2f}"
            result.advice_for_holding = f"谨慎持有(评分{score})，短线目标{result.take_profit_short:.2f}"
        elif score >= 50:
            result.advice_for_empty = f"观望为主(评分{score})，等待更明确信号"
            result.advice_for_holding = f"持股待涨(评分{score})，止损{result.stop_loss_mid:.2f}"
        elif score >= 35:
            result.advice_for_empty = f"不建议入场(评分{score})，信号偏弱"
            result.advice_for_holding = f"减仓观望(评分{score})，止损{result.stop_loss_mid:.2f}"
        else:
            result.advice_for_empty = f"空仓观望(评分{score})，技术面偏空"
            result.advice_for_holding = f"建议离场(评分{score})，止损{result.stop_loss_mid:.2f}"
        
        if hasattr(result, '_conflict_warnings') and result._conflict_warnings:
            conflict_text = " | ".join(result._conflict_warnings)
            result.advice_for_empty = f"{result.advice_for_empty} [{conflict_text}]"
            result.advice_for_holding = f"{result.advice_for_holding} [{conflict_text}]"
