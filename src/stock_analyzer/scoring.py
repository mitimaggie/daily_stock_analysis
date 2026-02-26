# -*- coding: utf-8 -*-
"""
评分系统模块
包含估值、资金流、板块强弱、筹码分布、基本面等多维评分逻辑
"""

import logging
import pandas as pd
from typing import Dict, Union, Optional
from .types import TrendAnalysisResult, BuySignal, MarketRegime, TrendStatus
from .types import VolumeStatus, MACDStatus, RSIStatus, KDJStatus
from data_provider.fundamental_types import FundamentalData, ValuationSnapshot, FinancialSummary, ForecastData
from data_provider.analysis_types import CapitalFlowData, SectorContext, QuoteExtra
from data_provider.realtime_types import ChipDistribution

logger = logging.getLogger(__name__)


class ScoringSystem:
    """评分系统：多维度评分与修正"""
    
    REGIME_WEIGHTS = {
        MarketRegime.BULL:     {"trend": 30, "bias": 12, "volume": 12, "support": 5,  "macd": 18, "rsi": 10, "kdj": 13},
        MarketRegime.SIDEWAYS: {"trend": 18, "bias": 20, "volume": 12, "support": 12, "macd": 13, "rsi": 10, "kdj": 15},
        MarketRegime.BEAR:     {"trend": 13, "bias": 17, "volume": 17, "support": 13, "macd": 12, "rsi": 13, "kdj": 15},
    }

    # 改进4: 短线交易敏感度 - 不同时间维度使用不同权重表
    # intraday: 日内做T，KDJ/RSI/量能权重大幅提升，趋势权重降低
    # short: 短线1-5日，均衡但偏重短周期指标
    # mid: 中线1-4周，与默认一致（趋势为王）
    HORIZON_WEIGHTS = {
        "intraday": {"trend": 10, "bias": 15, "volume": 18, "support": 8, "macd": 12, "rsi": 17, "kdj": 20},
        "short":    {"trend": 15, "bias": 15, "volume": 15, "support": 8, "macd": 15, "rsi": 14, "kdj": 18},
        "mid":      None,  # None = 使用 REGIME_WEIGHTS（默认行为）
    }
    
    @staticmethod
    def calculate_base_score(result: TrendAnalysisResult, market_regime: MarketRegime, time_horizon: str = "") -> int:
        """
        计算基础技术面评分
        
        Args:
            result: 分析结果对象
            market_regime: 市场环境
            time_horizon: 时间维度 ("intraday"/"short"/"mid"/""=默认)
            
        Returns:
            基础评分 (0-100)
        """
        raw_scores = ScoringSystem._get_raw_dimension_scores(result)
        # 改进4: 优先使用时间维度权重表，未命中则回退到市场环境权重
        horizon_weights = ScoringSystem.HORIZON_WEIGHTS.get(time_horizon)
        if horizon_weights:
            weights = horizon_weights
        else:
            weights = ScoringSystem.REGIME_WEIGHTS.get(market_regime, ScoringSystem.REGIME_WEIGHTS[MarketRegime.SIDEWAYS])
        
        result.score_breakdown = {
            k: min(weights[k], round(raw_scores[k] * weights[k])) 
            for k in raw_scores
        }
        
        score = sum(result.score_breakdown.values())
        return min(100, max(0, score))
    
    @staticmethod
    def _get_raw_dimension_scores(result: TrendAnalysisResult) -> Dict[str, float]:
        """获取各维度的原始得分率（0.0~1.0）"""
        trend_score = ScoringSystem._calc_trend_score(result)
        bias_score = ScoringSystem._calc_bias_score(result)
        volume_score = ScoringSystem._calc_volume_score(result)
        support_score = ScoringSystem._calc_support_score(result)
        macd_score = ScoringSystem._calc_macd_score(result)
        rsi_score = ScoringSystem._calc_rsi_score(result)
        kdj_score = ScoringSystem._calc_kdj_score(result)
        
        return {
            "trend": trend_score / 30,
            "bias": bias_score / 20,
            "volume": volume_score / 15,
            "support": support_score / 10,
            "macd": macd_score / 15,
            "rsi": rsi_score / 10,
            "kdj": kdj_score / 13,
        }
    
    @staticmethod
    def _calc_trend_score(result: TrendAnalysisResult) -> int:
        """计算趋势评分 (0-30)"""
        if result.trend_status == TrendStatus.STRONG_BULL:
            return 30
        elif result.trend_status == TrendStatus.BULL:
            return 26
        elif result.trend_status == TrendStatus.WEAK_BULL:
            return 18
        elif result.trend_status == TrendStatus.CONSOLIDATION:
            return 12
        elif result.trend_status == TrendStatus.WEAK_BEAR:
            return 8
        elif result.trend_status == TrendStatus.BEAR:
            return 4
        else:
            return 0
    
    @staticmethod
    def _calc_bias_score(result: TrendAnalysisResult) -> int:
        """计算乖离率评分 (0-20)，使用布林带宽度自适应归一化"""
        bias = result.bias_ma5
        is_strong_bull = result.trend_status == TrendStatus.STRONG_BULL
        
        # 自适应归一化：用布林带宽度衡量该股正常波动范围
        # bb_width = (upper - lower) / middle，典型值 0.05~0.20
        # 归一化后的 bias = 实际乖离 / 正常波动幅度
        if result.bb_width > 0.01:
            half_bb_pct = result.bb_width * 50  # 半个布林带宽度(%)
            norm_bias = bias / half_bb_pct  # 归一化：1.0 = 到达布林带边缘
            if norm_bias > 1.5:
                # 强势趋势中大乖离：不追高但不严重惩罚（给中性分）
                return 8 if is_strong_bull else 0
            elif norm_bias > 1.0:
                # 强势趋势中等正乖离：给中性分，普通趋势仍惩罚
                return 12 if is_strong_bull else 5
            elif 0.5 < norm_bias <= 1.0 and is_strong_bull:
                return 10  # 强势趋势中偏大正乖离：回测5d=-0.74%，降至中性
            elif 0 <= norm_bias <= 0.5 and result.trend_status in [TrendStatus.BULL, TrendStatus.STRONG_BULL]:
                return 18  # 多头趋势中小幅正乖离
            elif -0.5 <= norm_bias < 0:
                return 20  # 小幅负乖离，回踩买点
            elif -1.0 <= norm_bias < -0.5:
                return 16  # 中等负乖离
            elif -1.5 <= norm_bias < -1.0:
                return 12 if result.trend_status != TrendStatus.BEAR else 5
            elif norm_bias < -1.5:
                return 8 if result.trend_status != TrendStatus.BEAR else 2
            return 10
        
        # 回退：无布林带数据时使用原始阈值
        if bias > 8:
            return 8 if is_strong_bull else 0
        elif bias > 5:
            return 12 if is_strong_bull else 5
        elif 3 < bias <= 5 and is_strong_bull:
            return 10  # 强势趋势中偏大正乖离：回测5d=-0.74%，降至中性
        elif 0 <= bias <= 3 and result.trend_status in [TrendStatus.BULL, TrendStatus.STRONG_BULL]:
            return 18
        elif -3 <= bias < 0:
            return 20
        elif -5 <= bias < -3:
            return 16
        elif -10 <= bias < -5:
            return 12 if result.trend_status != TrendStatus.BEAR else 5
        elif bias < -10:
            return 8 if result.trend_status != TrendStatus.BEAR else 2
        return 10
    
    @staticmethod
    def _calc_volume_score(result: TrendAnalysisResult) -> int:
        """计算量能评分 (0-15)，含涨跌停特殊处理"""
        # 涨跌停特殊评分：缩量涨停=好（筹码锁定），放量跌停=差
        if result.is_limit_up:
            # 缩量涨停封板 → 筹码锁定良好，高分
            if result.volume_status == VolumeStatus.SHRINK_VOLUME_UP:
                return 14
            # 放量涨停 → 多空分歧，中高分
            return 11
        if result.is_limit_down:
            # 放量跌停 → 有承接但抛压重
            if result.volume_status == VolumeStatus.HEAVY_VOLUME_DOWN:
                return 2
            # 缩量跌停 → 无人接盘，最差
            return 0

        # 常规量能评分（结合趋势状态：缩量下跌在上升趋势=洗盘高分，在下跌趋势=阴跌低分）
        from .types import TrendStatus
        is_uptrend = result.trend_status in [TrendStatus.STRONG_BULL, TrendStatus.BULL, TrendStatus.WEAK_BULL]
        
        if result.volume_status == VolumeStatus.SHRINK_VOLUME_DOWN:
            # 回测显示缩量下跌在上升趋势中5d均-0.21%，短期内仍调整而非反弹，从14降至8
            return 8 if is_uptrend else 5  # 上升趋势洗盘=中性，下跌趋势阴跌=偏低
        
        if result.volume_status == VolumeStatus.SHRINK_VOLUME_UP:
            # STRONG_BULL中缩量上涨20d=-1.65%（量能不支撑），降至4；BULL/WEAK_BULL保持6
            return 4 if result.trend_status == TrendStatus.STRONG_BULL else 6
        
        scores = {
            VolumeStatus.HEAVY_VOLUME_UP: 12,
            VolumeStatus.NORMAL: 10,
            VolumeStatus.HEAVY_VOLUME_DOWN: 2,  # 回测5d均-0.10%跑输基准，放量下跌是负信号
        }
        return scores.get(result.volume_status, 8)
    
    @staticmethod
    def _calc_support_score(result: TrendAnalysisResult) -> int:
        """计算支撑接近度评分 (0-10)
        
        回测结论（4680样本）:
        - near(<2%): 20d均+0.58% 低于基准 —— 贴近支撑但未量能确认时更多是下破
        - mid(2-5%): 20d均+1.24% 高于基准 ✅
        - above_all:  20d均+2.57% 最强（突破所有支撑上方=强势）
        调整：贴近支撑必须有量能放量确认才给高分，否则降至6分
        """
        if not result.support_levels or result.current_price <= 0:
            return 5
        
        nearest = min((s for s in result.support_levels if 0 < s < result.current_price), 
                     default=result.ma20 if result.ma20 > 0 else 0)
        if nearest <= 0:
            return 5
        
        dist_pct = (result.current_price - nearest) / result.current_price * 100
        has_volume_confirm = result.volume_status == VolumeStatus.HEAVY_VOLUME_UP
        
        if 0 <= dist_pct <= 2:
            # 贴近支撑：有放量确认=9分（反弹有效），无量能=6分（可能下破）
            return 9 if has_volume_confirm else 6
        elif dist_pct <= 5:
            return 7
        return 5
    
    @staticmethod
    def _calc_macd_score(result: TrendAnalysisResult) -> int:
        """计算MACD评分 (0-15)，含柱状图动量修正"""
        base_scores = {
            MACDStatus.GOLDEN_CROSS_ZERO: 15,
            MACDStatus.GOLDEN_CROSS: 12,
            MACDStatus.CROSSING_UP: 10,
            MACDStatus.BULLISH: 8,
            MACDStatus.NEUTRAL: 5,
            MACDStatus.BEARISH: 2,
            MACDStatus.CROSSING_DOWN: 0,
            MACDStatus.DEATH_CROSS: 0,
        }
        score = base_scores.get(result.macd_status, 5)

        # P1b 均线死叉屏蔽：均线空头排列时，零轴上方金叉大概率是熊市反弹出货机会
        # 水下金叉（macd_dif < 0）保留加分，属于超卖反弹信号，不屏蔽
        is_bear_trend = result.trend_status in (TrendStatus.BEAR, TrendStatus.WEAK_BEAR)
        is_above_zero_cross = result.macd_status in (MACDStatus.GOLDEN_CROSS_ZERO, MACDStatus.GOLDEN_CROSS)
        if is_bear_trend and is_above_zero_cross and result.macd_dif > 0:
            score = score // 2

        # MACD柱状图动量修正：加速=加分，减速=减分
        momentum = getattr(result, 'macd_momentum', '')
        if momentum == "动能加速":
            score = min(15, score + 2)
        elif momentum == "动能减速":
            score = max(0, score - 2)
        elif momentum == "动能转向":
            # 转向是重要信号：从负转正=加分，从正转负=减分
            bar_slope = getattr(result, 'macd_bar_slope', 0)
            if bar_slope > 0:
                score = min(15, score + 1)
            elif bar_slope < 0:
                score = max(0, score - 1)
        
        return score
    
    @staticmethod
    def _calc_rsi_score(result: TrendAnalysisResult) -> int:
        """计算RSI评分 (0-10)
        
        回测结论（9股×750日，5940样本）:
        - OVERBOUGHT(>70): 5d均+0.22%，高于基准，绩优股超买是动量延续 → 给6分
        - OVERSOLD(<30):  5d均-0.30%，低于基准，超卖继续跌 → 给4分
        - GOLDEN_CROSS_OVERSOLD: 5d均+0.65%，最优信号 → 维持10分
        - STRONG_BUY(60-70): 5d均+0.34% → 维持7分
        """
        scores = {
            RSIStatus.GOLDEN_CROSS_OVERSOLD: 10,
            RSIStatus.BULLISH_DIVERGENCE: 10,
            RSIStatus.GOLDEN_CROSS: 8,
            RSIStatus.STRONG_BUY: 7,
            RSIStatus.OVERBOUGHT: 6,   # 回测5d均+0.22%，动量延续，不再给0分
            RSIStatus.NEUTRAL: 5,
            RSIStatus.WEAK: 3,
            RSIStatus.DEATH_CROSS: 2,
            RSIStatus.BEARISH_DIVERGENCE: 1,
            RSIStatus.OVERSOLD: 4,     # 回测5d均-0.30%，超卖继续跌，从9降至4
        }
        return scores.get(result.rsi_status, 5)
    
    @staticmethod
    def _calc_kdj_score(result: TrendAnalysisResult) -> int:
        """计算KDJ评分 (0-13)，含钝化/背离/连续极端修正
        
        回测结论（9股×750日，5940样本）:
        - OVERBOUGHT(J>100): 5d均+0.73%，最高收益，绩优股超买是趋势延续 → 给9分
        - OVERSOLD(J<0):     5d均-0.28%，超卖继续跌 → 从11降至4
        - GOLDEN_CROSS_OVERSOLD: 5d均-0.21%，样本仅50次，信号不稳定 → 从13降至6
        - GOLDEN_CROSS:      5d均+0.33% → 维持10分，效果好
        """
        base_scores = {
            KDJStatus.GOLDEN_CROSS: 10,
            KDJStatus.OVERBOUGHT: 9,         # 回测5d均+0.73%，动量最强 → 从0升至9
            KDJStatus.BULLISH: 7,
            KDJStatus.NEUTRAL: 5,
            KDJStatus.BEARISH: 3,
            KDJStatus.DEATH_CROSS: 1,
            KDJStatus.GOLDEN_CROSS_OVERSOLD: 6,  # 回测5d均-0.21%，仅50次样本，降至6
            KDJStatus.OVERSOLD: 4,           # 回测5d均-0.28%，超卖继续跌 → 从11降至4
        }
        score = base_scores.get(result.kdj_status, 5)
        
        # KDJ 钝化时，将评分拉向中性（减弱极端信号的影响）
        if result.kdj_passivation:
            score = int(score * 0.6 + 5 * 0.4)  # 向中性值5靠拢40%
        
        # KDJ 背离额外修正
        if result.kdj_divergence == "KDJ底背离":
            score = min(13, score + 2)
        elif result.kdj_divergence == "KDJ顶背离":
            score = max(0, score - 2)
        
        # J 值连续极端额外修正（回测显示超买动量延续，超卖继续下跌）
        if result.kdj_consecutive_extreme:
            if "超买" in result.kdj_consecutive_extreme:
                score = min(13, score + 1)  # 动量延续，轻微加分
            elif "超卖" in result.kdj_consecutive_extreme:
                score = max(0, score - 1)   # 超卖继续跌，轻微减分
        
        return score
    
    @staticmethod
    def check_valuation(result: TrendAnalysisResult, valuation: Union[ValuationSnapshot, dict, None] = None):
        """估值安全检查：PE/PB/PEG 评分 + 估值降档"""
        if valuation is None:
            return
        # 兼容 dict（临时）和 ValuationSnapshot
        if isinstance(valuation, dict):
            valuation = ValuationSnapshot(
                pe=valuation.get('pe'), pb=valuation.get('pb'), peg=valuation.get('peg'),
                industry_pe_median=valuation.get('industry_pe_median'),
                pe_history=valuation.get('pe_history'),
                revenue_growth=valuation.get('revenue_growth'),
                net_profit_growth=valuation.get('net_profit_growth'),
            )
        
        pe = valuation.pe
        pb = valuation.pb
        peg = valuation.peg
        if isinstance(pe, (int, float)) and pe > 0:
            result.pe_ratio = float(pe)
        if isinstance(pb, (int, float)) and pb > 0:
            result.pb_ratio = float(pb)
        if isinstance(peg, (int, float)) and peg > 0:
            result.peg_ratio = float(peg)
        
        v_score = 5
        downgrade = 0
        industry_pe = valuation.industry_pe_median
        
        if result.pe_ratio > 0:
            if isinstance(industry_pe, (int, float)) and industry_pe > 0:
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
            
            if result.peg_ratio > 0:
                if result.peg_ratio < 0.5:
                    v_score = min(10, v_score + 3)
                    downgrade = min(0, downgrade + 5)  # 减轻扣分（往0靠近）
                    result.valuation_verdict += "(PEG极低,增速优秀)"
                elif result.peg_ratio < 1.0:
                    v_score = min(10, v_score + 1)
                    downgrade = min(0, downgrade + 3)  # 减轻扣分（往0靠近）
                    result.valuation_verdict += "(PEG合理)"
                elif result.peg_ratio > 3.0:
                    v_score = max(0, v_score - 2)
                    downgrade = downgrade - 3  # 加重扣分
                    result.valuation_verdict += "(PEG过高,增速不匹配)"
        
        # P3: 历史估值分位数（基于PE历史数据）
        pe_hist = valuation.pe_history
        if pe_hist and isinstance(pe_hist, (list, tuple)) and result.pe_ratio > 0:
            valid_pe = [p for p in pe_hist if isinstance(p, (int, float)) and p > 0]
            if len(valid_pe) >= 20:
                below_count = sum(1 for p in valid_pe if p <= result.pe_ratio)
                result.pe_percentile = round(below_count / len(valid_pe) * 100, 1)
                if result.pe_percentile <= 20:
                    result.valuation_zone = "历史低估区"
                    v_score = min(10, v_score + 2)
                    downgrade = min(0, downgrade + 3)
                    result.valuation_verdict += f"(PE历史{result.pe_percentile:.0f}%分位,低估区)"
                elif result.pe_percentile >= 80:
                    result.valuation_zone = "历史高估区"
                    v_score = max(0, v_score - 2)
                    downgrade = downgrade - 3
                    result.valuation_verdict += f"(PE历史{result.pe_percentile:.0f}%分位,高估区)"
                else:
                    result.valuation_zone = "历史合理区"
        
        # P3: 简易DCF估值参考（基于PEG和增长率）
        # 优先使用净利增速（与PE直接对应），次选营收增速
        growth_rate = valuation.net_profit_growth or valuation.revenue_growth
        if isinstance(growth_rate, (int, float)) and growth_rate > 0 and result.pe_ratio > 0:
            # 简易合理PE = 增长率 * PEG合理倍数(1.0)
            fair_pe = growth_rate * 1.0
            if fair_pe > 5:  # 增长率>5%才有参考意义
                pe_premium = result.pe_ratio / fair_pe
                if pe_premium > 2.0:
                    result.valuation_verdict += f"(DCF视角:PE/{fair_pe:.0f}={pe_premium:.1f}x,偏贵)"
                elif pe_premium < 0.5:
                    result.valuation_verdict += f"(DCF视角:PE/{fair_pe:.0f}={pe_premium:.1f}x,便宜)"
        
        result.valuation_score = v_score
        result.valuation_downgrade = downgrade
        
        if downgrade < 0:
            result.score_breakdown['valuation_adj'] = downgrade
    
    @staticmethod
    def check_trading_halt(result: TrendAnalysisResult):
        """全局暂停信号检测：极端波动率、深度回撤、流动性枯竭"""
        halt_reasons = []
        if result.volatility_20d > 100:
            halt_reasons.append(f"波动率异常({result.volatility_20d:.0f}%>100%)，疑似妖股")
        if result.max_drawdown_60d < -40:
            halt_reasons.append(f"近60日回撤{result.max_drawdown_60d:.1f}%，跌幅过大")
        if result.volume_ratio < 0.3 and result.bb_pct_b < 0:
            halt_reasons.append("极端缩量+跌破布林下轨，流动性枯竭风险")
        if result.atr14 <= 0:
            halt_reasons.append("ATR为零，可能停牌或数据异常")
        
        if halt_reasons:
            result.trading_halt = True
            result.trading_halt_reason = "；".join(halt_reasons)
            result.advice_for_empty = f"🚫 暂停交易：{result.trading_halt_reason}"
            result.advice_for_holding = f"⚠️ 风险警告：{result.trading_halt_reason}，持仓者评估是否离场"
    
    @staticmethod
    def score_capital_flow(result: TrendAnalysisResult, capital_flow: Union[CapitalFlowData, dict, None] = None):
        """资金面评分：主力资金（超大单+大单）+ 主力净占比 + 融资余额"""
        if capital_flow is None:
            return
        # 兼容 dict 和 CapitalFlowData
        if isinstance(capital_flow, dict):
            capital_flow = CapitalFlowData.from_dict(capital_flow)
        
        cf_score = 5
        cf_signals = []
        
        # === 主力资金（含超大单+大单拆分）===
        main_net = capital_flow.main_net_flow  # 万元
        daily_avg = capital_flow.daily_avg_amount  # 万元
        if isinstance(main_net, (int, float)):
            if isinstance(daily_avg, (int, float)) and daily_avg > 0:
                main_threshold = daily_avg * 0.05
                main_large_threshold = daily_avg * 0.15
            else:
                main_threshold = 5000
                main_large_threshold = 15000
            
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
        
        # === 超大单独立评估（机构行为信号）===
        super_large = capital_flow.super_large_net  # 万元
        if isinstance(super_large, (int, float)):
            sl_threshold = (daily_avg * 0.08) if isinstance(daily_avg, (int, float)) and daily_avg > 0 else 8000
            if super_large > sl_threshold:
                cf_score += 1
                cf_signals.append(f"超大单净流入{super_large/10000:.1f}亿（机构买入信号）")
            elif super_large < -sl_threshold:
                cf_score -= 1
                cf_signals.append(f"⚠️超大单净流出{abs(super_large)/10000:.1f}亿（机构离场）")
        
        # === 主力净占比（比绝对值更有意义）===
        main_pct = capital_flow.main_net_flow_pct
        if isinstance(main_pct, (int, float)):
            if main_pct > 15:
                cf_score += 1
                cf_signals.append(f"主力净占比{main_pct:.1f}%（资金高度集中买入）")
            elif main_pct < -15:
                cf_score -= 1
                cf_signals.append(f"⚠️主力净占比{main_pct:.1f}%（资金集中流出）")
        
        # === 融资余额趋势 ===
        margin_change = capital_flow.margin_balance_change
        if isinstance(margin_change, (int, float)):
            if margin_change > 0:
                cf_score += 1
                cf_signals.append("融资余额增加")
            elif margin_change < -1e8:
                cf_score -= 1
                cf_signals.append("融资余额减少")
        
        result.capital_flow_score = max(0, min(10, cf_score))
        result.capital_flow_signal = "；".join(cf_signals) if cf_signals else "资金面数据正常"
        
        cf_adj = cf_score - 5
        if cf_adj != 0:
            result.score_breakdown['capital_flow_adj'] = cf_adj
    
    @staticmethod
    def score_capital_flow_history(result: TrendAnalysisResult, stock_code: str):
        """P4: 主力资金追踪 - 大单净流入连续性检测

        通过 akshare 历史资金流数据（最近120日）分析：
        1. 连续净流入/流出天数
        2. 近5日主力净流入累计
        3. 资金流入趋势：持续流入 / 持续流出 / 间歇流入 / 资金离场
        4. 流入强度：大幅 / 温和 / 轻微
        5. 加速/减速信号
        6. 聪明钱（超大单）持续行为
        """
        try:
            import akshare as ak
            import time
            import random

            market = "sh" if stock_code.startswith(('6', '5', '9')) else "sz"

            # 使用项目内全局限流器
            try:
                from data_provider.rate_limiter import get_global_limiter
                limiter = get_global_limiter()
                limiter.acquire('akshare', blocking=True, timeout=10.0)
            except Exception:
                time.sleep(random.uniform(1.0, 2.0))

            df_flow = ak.stock_individual_fund_flow(stock=stock_code, market=market)
            if df_flow is None or len(df_flow) < 5:
                return

            # 标准化列名
            col_map = {
                '日期': 'date',
                '主力净流入-净额': 'main_net',
                '超大单净流入-净额': 'super_large_net',
                '大单净流入-净额': 'large_net',
                '主力净流入-净占比': 'main_pct',
            }
            df_flow = df_flow.rename(columns={k: v for k, v in col_map.items() if k in df_flow.columns})

            for col in ['main_net', 'super_large_net', 'large_net', 'main_pct']:
                if col in df_flow.columns:
                    df_flow[col] = pd.to_numeric(df_flow[col], errors='coerce').fillna(0)

            # 取最近 20 天用于分析
            recent = df_flow.tail(20).reset_index(drop=True)
            if len(recent) < 5:
                return

            main_net_series = recent['main_net'].values  # 单位：元
            sl_net_series = recent.get('super_large_net', pd.Series([0]*len(recent))).values if 'super_large_net' in recent.columns else [0]*len(recent)

            # === 1. 连续净流入/流出天数 ===
            last_net = main_net_series[-1]
            consecutive = 0
            if last_net >= 0:
                for v in reversed(main_net_series):
                    if v >= 0:
                        consecutive += 1
                    else:
                        break
            else:
                for v in reversed(main_net_series):
                    if v < 0:
                        consecutive -= 1
                    else:
                        break
            result.capital_flow_days = consecutive

            # === 2. 近5日主力净流入累计（万元）===
            last5 = main_net_series[-5:]
            total_5d = float(sum(last5)) / 10000
            result.capital_flow_5d_total = round(total_5d, 2)

            # === 3. 趋势分类 ===
            positive_count = sum(1 for v in last5 if v > 0)
            if positive_count >= 4:
                trend = "持续流入"
            elif positive_count >= 3:
                trend = "间歇流入"
            elif positive_count <= 1:
                trend = "持续流出"
            else:
                trend = "资金离场"
            result.capital_flow_trend = trend

            # === 4. 流入强度（基于近5日日均额 vs 主力净流入比例）===
            # 用 abs(主力净流入/日均成交额) 衡量强度
            avg_daily_amount = getattr(result, 'daily_avg_amount', None) or 0
            if avg_daily_amount <= 0:
                # 估算：用近5日高低中值
                try:
                    avg_daily_amount = abs(total_5d) / 5 * 20  # 粗估：净流入占5%成交额
                except Exception:
                    avg_daily_amount = 10000
            abs_5d = abs(total_5d)
            if avg_daily_amount > 0:
                intensity_ratio = abs_5d / (avg_daily_amount * 5) * 100
            else:
                intensity_ratio = 0

            if abs_5d > 50000:  # 超过5亿
                intensity = "大幅"
            elif abs_5d > 10000:  # 超过1亿
                intensity = "温和"
            elif abs_5d > 1000:
                intensity = "轻微"
            else:
                intensity = ""
            result.capital_flow_intensity = intensity

            # === 5. 加速/减速检测 ===
            if len(main_net_series) >= 10:
                prev5 = main_net_series[-10:-5]
                curr5 = main_net_series[-5:]
                prev_avg = sum(prev5) / 5
                curr_avg = sum(curr5) / 5
                if curr_avg > 0 and prev_avg > 0:
                    if curr_avg > prev_avg * 1.5:
                        result.capital_flow_acceleration = "加速流入"
                    elif curr_avg < prev_avg * 0.5:
                        result.capital_flow_acceleration = "趋缓"
                    else:
                        result.capital_flow_acceleration = ""
                elif curr_avg < 0 and prev_avg < 0:
                    if curr_avg < prev_avg * 1.5:
                        result.capital_flow_acceleration = "加速流出"
                    elif curr_avg > prev_avg * 0.5:
                        result.capital_flow_acceleration = "趋缓"
                    else:
                        result.capital_flow_acceleration = ""

            # === 6. 聪明钱（超大单）信号 ===
            sl_last5 = [float(v) for v in sl_net_series[-5:]]
            sl_positive = sum(1 for v in sl_last5 if v > 0)
            sl_total = sum(sl_last5) / 10000
            if sl_positive >= 4 and sl_total > 5000:
                result.capital_smart_money = "超大单持续买入"
            elif sl_positive <= 1 and sl_total < -5000:
                result.capital_smart_money = "超大单持续卖出"
            else:
                result.capital_smart_money = ""

            # === 7. 对 score_breakdown 做调整 ===
            p4_adj = 0
            if trend == "持续流入" and consecutive >= 3:
                p4_adj += 3
            elif trend == "持续流入":
                p4_adj += 2
            elif trend == "间歇流入":
                p4_adj += 1
            elif trend == "持续流出" and consecutive <= -3:
                p4_adj -= 3
            # 轻度流出/资金离场不给负分（回测显示是洗盘信号，给负分反向误导）
            # elif trend == "持续流出": p4_adj -= 2
            # elif trend == "资金离场": p4_adj -= 1

            if result.capital_smart_money == "超大单持续买入":
                p4_adj += 2
            elif result.capital_smart_money == "超大单持续卖出":
                p4_adj -= 2

            p4_adj = max(-5, min(5, p4_adj))
            if p4_adj != 0:
                result.score_breakdown['p4_capital_flow'] = p4_adj

        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f"[P4] {stock_code} 主力资金追踪失败: {e}", exc_info=True)

    @staticmethod
    def score_capital_flow_trend(result: TrendAnalysisResult, df: pd.DataFrame):
        """资金面连续性检测：近3日量价关系判断持续性资金流向"""
        if df is None or len(df) < 5:
            return
        
        recent = df.tail(3)
        if len(recent) < 3:
            return
        
        volumes = recent['volume'].values
        
        # 使用 pct_chg（涨跌幅）判断多空方向，比 close>open 更准确
        # close>open 忽略缺口，如低开高走 close>open 但实际偏空
        if 'pct_chg' in recent.columns:
            pct_chgs = recent['pct_chg'].values
            up_days = sum(1 for p in pct_chgs if isinstance(p, (int, float)) and p > 0)
            down_days = sum(1 for p in pct_chgs if isinstance(p, (int, float)) and p < 0)
        else:
            closes = recent['close'].values
            opens = recent['open'].values
            up_days = sum(1 for c, o in zip(closes, opens) if c > o)
            down_days = sum(1 for c, o in zip(closes, opens) if c < o)
        
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
        
    
    @staticmethod
    def score_lhb_sentiment(result: TrendAnalysisResult, stock_code: str):
        """P5-C: 量化情绪指标 - 龙虎榜机构净买额分析

        通过个股龙虎榜历史记录过滤近30天，统计机构买卖行为：
        - 机构净买额为正且上榜次数多：机构持续买入信号（+2~+3）
        - 机构净买额为负且上榜次数多：机构持续卖出信号（-2~-3）
        - 上榜但机构净买额接近零：博弈激烈，中性（0）
        - 未上榜：不处理

        使用 LHBCache 每日缓存，避免重复拉全量数据。
        """
        try:
            from .lhb_cache import LHBCache
            lhb_data = LHBCache.query(stock_code)
            if lhb_data is None:
                return

            lhb_net = lhb_data.get('lhb_net_buy', 0.0)
            inst_net = lhb_data.get('lhb_institution_net', 0.0)
            times = lhb_data.get('lhb_times', 0)

            result.lhb_net_buy = round(lhb_net, 2)
            result.lhb_institution_net = round(inst_net, 2)
            result.lhb_times = times

            p5c_adj = 0
            inst_net_wan = inst_net / 10000

            if inst_net_wan > 5000:
                p5c_adj += 3
                result.lhb_signal = "机构持续买入"
            elif inst_net_wan > 1000:
                p5c_adj += 2
                result.lhb_signal = "机构净买入"
            elif inst_net_wan < -5000:
                p5c_adj -= 3
                result.lhb_signal = "机构持续卖出"
            elif inst_net_wan < -1000:
                p5c_adj -= 2
                result.lhb_signal = "机构净卖出"
            elif times >= 3:
                result.lhb_signal = "龙虎榜活跃"

            p5c_adj = max(-3, min(3, p5c_adj))
            if p5c_adj != 0:
                result.score_breakdown['p5c_lhb'] = p5c_adj

        except Exception as e:
            import logging
            logging.getLogger(__name__).debug(f"[P5-C] {stock_code} 龙虎榜情绪分析失败: {e}")

    @staticmethod
    def score_dzjy_and_holder(result: TrendAnalysisResult, stock_code: str):
        """P5-C补充: 股东人数变化率（带超时保护）"""
        import threading
        import logging
        logger = logging.getLogger(__name__)

        # ---- 股东人数变化率（线程+超时5秒）----
        def _fetch_holder():
            try:
                import akshare as ak
                df_holder = ak.stock_zh_a_gdhs(symbol=stock_code)
                if df_holder is None or df_holder.empty or len(df_holder) < 2:
                    return
                cols = df_holder.columns.tolist()
                holder_col = next((c for c in cols if '股东' in c or '持股人数' in c), None)
                if not holder_col:
                    return
                latest = float(df_holder.iloc[-1][holder_col])
                prev = float(df_holder.iloc[-2][holder_col])
                if prev <= 0:
                    return
                change_pct = (latest - prev) / prev * 100
                result.holder_change_pct = round(change_pct, 2)
                adj_holder = 0
                if change_pct < -5:
                    result.holder_signal = "筹码集中（缩股）"
                    adj_holder = 2
                elif change_pct < -2:
                    result.holder_signal = "筹码小幅集中"
                    adj_holder = 1
                elif change_pct > 5:
                    result.holder_signal = "筹码分散（增股）"
                    adj_holder = -1
                if adj_holder != 0:
                    result.score_breakdown['p5c_holder'] = adj_holder
            except Exception as e:
                logger.debug(f"[P5-C] {stock_code} 股东人数查询失败: {e}")

        t_holder = threading.Thread(target=_fetch_holder, daemon=True)
        t_holder.start()
        t_holder.join(timeout=5)
        if t_holder.is_alive():
            logger.debug(f"[P5-C] {stock_code} 股东人数查询超时，已跳过")

    @staticmethod
    def score_vwap_trend(result: TrendAnalysisResult):
        """P5-B: VWAP 机构成本线评分

        逻辑：
        - 机构成本上移 + 价格在VWAP上方 → 机构持续增持，+2
        - 机构成本下移 + 价格在VWAP下方 → 机构持续离场，-2
        - 机构成本上移 + 价格在VWAP下方 → 短期回调（未跌破成本），+1（支撑）
        - 机构成本下移 + 价格在VWAP上方 → 反弹但成本仍在下移，-1（阻力）
        """
        vwap_trend = result.vwap_trend
        vwap_pos = result.vwap_position
        if not vwap_trend or not vwap_pos:
            return

        adj = 0
        if vwap_trend == "机构成本上移" and vwap_pos == "价格在VWAP上方":
            adj = 2
        elif vwap_trend == "机构成本下移" and vwap_pos == "价格在VWAP下方":
            adj = -2
        elif vwap_trend == "机构成本上移" and vwap_pos == "价格在VWAP下方":
            adj = 1
        elif vwap_trend == "机构成本下移" and vwap_pos == "价格在VWAP上方":
            adj = -1

        if adj != 0:
            result.score_breakdown['vwap_adj'] = adj

    @staticmethod
    def score_sector_strength(result: TrendAnalysisResult, sector_context: Union[SectorContext, dict, None] = None):
        """板块强弱评分"""
        if sector_context is None:
            return
        # 兼容 dict 和 SectorContext
        if isinstance(sector_context, dict):
            sector_context = SectorContext.from_dict(sector_context)
        
        sec_name = sector_context.sector_name
        sec_pct = sector_context.sector_pct
        rel = sector_context.relative
        
        if sec_name:
            result.sector_name = sec_name
        if isinstance(sec_pct, (int, float)):
            result.sector_pct = round(sec_pct, 2)
        if isinstance(rel, (int, float)):
            result.sector_relative = round(rel, 2)
        
        sec_score = 5
        signals = []
        
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
        
        sector_adj = sec_score - 5
        if sector_adj != 0:
            result.score_breakdown['sector_adj'] = sector_adj
    
    @staticmethod
    def score_chip_distribution(result: TrendAnalysisResult, chip_data: Union[ChipDistribution, dict, None] = None):
        """筹码分布评分"""
        if chip_data is None:
            return
        # 兼容 dict
        if isinstance(chip_data, dict):
            profit_ratio = chip_data.get('profit_ratio')
            avg_cost = chip_data.get('avg_cost')
            concentration_90 = chip_data.get('concentration_90')
        else:
            profit_ratio = chip_data.profit_ratio
            avg_cost = chip_data.avg_cost
            concentration_90 = chip_data.concentration_90
        
        c_score = 5
        signals = []
        price = result.current_price
        
        if isinstance(profit_ratio, (int, float)):
            pr = profit_ratio * 100 if profit_ratio <= 1.0 else profit_ratio
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
        
        if isinstance(avg_cost, (int, float)) and avg_cost > 0 and price > 0:
            cost_ratio = price / avg_cost
            if cost_ratio > 1.15:
                c_score -= 1
                signals.append(f"现价高于均成本{avg_cost:.2f}元({(cost_ratio-1)*100:.0f}%),注意获利抛压")
            elif cost_ratio < 0.85:
                c_score += 1
                signals.append(f"现价低于均成本{avg_cost:.2f}元({(1-cost_ratio)*100:.0f}%),成本支撑")
        
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
            result.score_breakdown['chip_adj'] = chip_adj
    
    @staticmethod
    def score_fundamental_quality(result: TrendAnalysisResult, fundamental_data: Union[FundamentalData, dict, None] = None):
        """基本面质量评分：ROE + 负债率 + 毛利率 + 净利增速 + 营收增速"""
        if fundamental_data is None:
            return
        # 兼容 dict（临时）和 FundamentalData
        if isinstance(fundamental_data, dict):
            fundamental_data = FundamentalData.from_dict(fundamental_data)
        
        fin = fundamental_data.financial
        if not fin.has_data:
            return
        
        f_score = 5
        signals = []
        
        # === ROE ===
        roe = fin.roe
        if roe is not None:
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
        
        # === 负债率 ===
        debt = fin.debt_ratio
        if debt is not None:
            if debt > 80:
                f_score -= 2
                signals.append(f"⚠️负债率过高({debt:.1f}%)")
            elif debt > 60:
                f_score -= 1
                signals.append(f"负债率偏高({debt:.1f}%)")
            elif debt < 30:
                f_score += 1
                signals.append(f"负债率健康({debt:.1f}%)")
        
        # === 毛利率（定价权指标）===
        gross = fin.gross_margin
        if gross is not None:
            if gross > 50:
                f_score += 1
                signals.append(f"毛利率优秀({gross:.1f}%)，定价权强")
            elif gross > 30:
                pass  # 正常，不加不减
            elif gross < 10:
                f_score -= 1
                signals.append(f"⚠️毛利率极低({gross:.1f}%)，竞争激烈")
        
        # === 净利润增速（成长性）===
        np_growth = fin.net_profit_growth
        if np_growth is not None:
            if np_growth > 50:
                f_score += 2
                signals.append(f"净利增速强劲({np_growth:.1f}%)")
            elif np_growth > 20:
                f_score += 1
                signals.append(f"净利增速良好({np_growth:.1f}%)")
            elif np_growth < -30:
                f_score -= 2
                signals.append(f"⚠️净利大幅下滑({np_growth:.1f}%)")
            elif np_growth < 0:
                f_score -= 1
                signals.append(f"⚠️净利负增长({np_growth:.1f}%)")
        
        # === 营收增速（业务扩张）===
        rev_growth = fin.revenue_growth
        if rev_growth is not None:
            if rev_growth > 30:
                f_score += 1
                signals.append(f"营收高增长({rev_growth:.1f}%)")
            elif rev_growth < -20:
                f_score -= 1
                signals.append(f"⚠️营收大幅萎缩({rev_growth:.1f}%)")
        
        f_score = max(0, min(10, f_score))
        result.fundamental_score = f_score
        result.fundamental_signal = "；".join(signals) if signals else "基本面数据正常"
        
        fund_adj = f_score - 5
        if fund_adj != 0:
            result.score_breakdown['fundamental_adj'] = fund_adj
    
    @staticmethod
    def score_forecast(result: TrendAnalysisResult, fundamental_data: Union[FundamentalData, dict, None] = None):
        """业绩预测评分：分析师评级 + 目标价 + 盈利预测"""
        if fundamental_data is None:
            return
        # 兼容 dict（临时）和 FundamentalData
        if isinstance(fundamental_data, dict):
            fundamental_data = FundamentalData.from_dict(fundamental_data)
        
        fc = fundamental_data.forecast
        if not fc.has_data:
            return
        
        adj = 0
        signals = []
        
        # === 分析师评级 ===
        rating = fc.rating
        if rating and rating not in ('无', '', 'N/A'):
            rating_lower = rating.strip()
            if any(k in rating_lower for k in ['买入', '增持', '强烈推荐', '推荐']):
                adj += 2
                signals.append(f"分析师评级「{rating_lower}」")
            elif any(k in rating_lower for k in ['中性', '持有', '审慎']):
                pass  # 中性不加不减
            elif any(k in rating_lower for k in ['减持', '卖出', '回避']):
                adj -= 2
                signals.append(f"⚠️分析师评级「{rating_lower}」")
        
        # === 目标价 vs 现价 ===
        if fc.target_price is not None and fc.target_price > 0 and result.current_price > 0:
            target = fc.target_price
            upside = (target - result.current_price) / result.current_price * 100
            if upside > 30:
                adj += 2
                signals.append(f"目标价{target:.2f}(上行空间{upside:.0f}%)")
            elif upside > 10:
                adj += 1
                signals.append(f"目标价{target:.2f}(上行空间{upside:.0f}%)")
            elif upside < -10:
                adj -= 1
                signals.append(f"⚠️目标价{target:.2f}(下行{upside:.0f}%)")
        
        # === 盈利预测变动 ===
        chg = fc.avg_profit_change
        if chg is not None:
            if chg > 20:
                adj += 1
                signals.append(f"盈利预测上调{chg:.1f}%")
            elif chg < -20:
                adj -= 1
                signals.append(f"⚠️盈利预测下调{chg:.1f}%")
        
        if adj != 0:
            result.score_breakdown['forecast_adj'] = adj
            if signals:
                for s in signals:
                    if '⚠️' in s:
                        result.risk_factors.append(s)
                    else:
                        result.signal_reasons.append(s)

    @staticmethod
    def detect_sentiment_extreme(result: TrendAnalysisResult, chip_data: Union[ChipDistribution, dict, None] = None,
                                  capital_flow: Union[CapitalFlowData, dict, None] = None, df: pd.DataFrame = None):
        """
        P3 情绪极端检测：综合获利盘/套牢盘比例 + 融资余额趋势
        
        - 获利盘>90% → 极度贪婪（短期回调概率高）
        - 套牢盘>80% → 极度恐慌（上方压力巨大）
        - 融资余额连续5日增加/减少 → 杠杆情绪趋势
        """
        details = []
        adj = 0
        
        # --- 1. 获利盘/套牢盘比例 ---
        if chip_data is not None:
            if isinstance(chip_data, dict):
                profit_ratio = chip_data.get('profit_ratio')
            else:
                profit_ratio = chip_data.profit_ratio
            if isinstance(profit_ratio, (int, float)):
                pr = profit_ratio * 100 if profit_ratio <= 1.0 else profit_ratio
                result.profit_ratio = pr
                result.trapped_ratio = 100 - pr
                
                if pr > 90:
                    details.append(f"🔴 获利盘{pr:.0f}%（极高），短期回调概率大，获利了结压力沉重")
                    adj -= 3
                    result.sentiment_extreme = "极度贪婪"
                elif pr > 80:
                    details.append(f"🟡 获利盘{pr:.0f}%（偏高），注意获利抛压")
                    adj -= 1
                elif pr < 10:
                    details.append(f"🟢 获利盘仅{pr:.0f}%（极低），套牢盘{100-pr:.0f}%，上方压力巨大但抛压已枯竭")
                    adj += 2
                    if not result.sentiment_extreme:
                        result.sentiment_extreme = "极度恐慌"
                elif pr < 20:
                    details.append(f"🟡 获利盘{pr:.0f}%（偏低），套牢盘{100-pr:.0f}%，上方有较大压力")
                    adj += 1
        
        # --- 2. 融资余额趋势（杠杆情绪指标）---
        if capital_flow is not None:
            if isinstance(capital_flow, dict):
                capital_flow = CapitalFlowData.from_dict(capital_flow)
            margin_history = capital_flow.margin_history  # list of recent margin balances
            
            if margin_history and isinstance(margin_history, (list, tuple)) and len(margin_history) >= 5:
                # 分别检测连续增加和连续减少
                consecutive_up = 0
                for i in range(len(margin_history) - 1, 0, -1):
                    curr, prev_val = margin_history[i], margin_history[i - 1]
                    if isinstance(curr, (int, float)) and isinstance(prev_val, (int, float)) and curr > prev_val:
                        consecutive_up += 1
                    else:
                        break
                
                consecutive_down = 0
                for i in range(len(margin_history) - 1, 0, -1):
                    curr, prev_val = margin_history[i], margin_history[i - 1]
                    if isinstance(curr, (int, float)) and isinstance(prev_val, (int, float)) and curr < prev_val:
                        consecutive_down += 1
                    else:
                        break
                
                if consecutive_up >= 5:
                    result.margin_trend = "融资连续流入"
                    result.margin_trend_days = consecutive_up
                    details.append(f"📈 融资余额连续{consecutive_up}日增加，杠杆资金看多")
                    adj += 1
                elif consecutive_down >= 5:
                    result.margin_trend = "融资连续流出"
                    result.margin_trend_days = consecutive_down
                    details.append(f"📉 融资余额连续{consecutive_down}日减少，杠杆资金撤退")
                    adj -= 1
        
        # --- 3. 价格位置 + 量能综合判断情绪 ---
        if df is not None and len(df) >= 60:
            # 近60日涨幅
            price_60d_ago = float(df.iloc[-60]['close'])
            if price_60d_ago > 0:
                gain_60d = (result.current_price - price_60d_ago) / price_60d_ago * 100
                if gain_60d > 50 and result.volume_extreme == "天量":
                    if not result.sentiment_extreme:
                        result.sentiment_extreme = "极度贪婪"
                    details.append(f"⚠️ 60日涨幅{gain_60d:.0f}%+天量，市场情绪过热")
                    adj -= 2
                elif gain_60d < -30 and result.volume_extreme == "地量":
                    if not result.sentiment_extreme:
                        result.sentiment_extreme = "极度恐慌"
                    details.append(f"💡 60日跌幅{abs(gain_60d):.0f}%+地量，恐慌情绪可能见底")
                    adj += 2
        
        # --- 汇总 ---
        if details:
            result.sentiment_extreme_detail = "；".join(details)
        
        if adj != 0:
            result.score_breakdown['sentiment_extreme'] = adj

    @staticmethod
    def score_quote_extra(result: TrendAnalysisResult, quote_extra: Union[QuoteExtra, dict, None] = None):
        """行情附加数据评分：换手率异常检测 + 52周高低位 + 市值风控"""
        if quote_extra is None:
            return
        # 兼容 dict 和 QuoteExtra
        if isinstance(quote_extra, dict):
            quote_extra = QuoteExtra.from_dict(quote_extra)
        
        adj = 0
        price = result.current_price
        
        turnover = quote_extra.turnover_rate
        if isinstance(turnover, (int, float)) and turnover > 0:
            if turnover > 15:
                if not result.trading_halt:
                    result.trading_halt = True
                    result.trading_halt_reason = (result.trading_halt_reason + "；" if result.trading_halt_reason else "") + f"换手率异常({turnover:.1f}%>15%)，疑似游资炒作"
            elif turnover < 0.3:
                adj -= 1
                result.score_breakdown['liquidity_risk'] = -1
        
        high_52w = quote_extra.high_52w
        low_52w = quote_extra.low_52w
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
        
        # === 市值风控：小盘股流动性差/波动大，压缩仓位上限 ===
        circ_mv = quote_extra.circ_mv  # 流通市值（元）
        total_mv = quote_extra.total_mv  # 总市值（元）
        mv = circ_mv or total_mv  # 优先使用流通市值
        if isinstance(mv, (int, float)) and mv > 0:
            mv_yi = mv / 1e8  # 转为亿元
            if mv_yi < 20:
                # 微盘股（<20亿）：仓位上限压缩，风险提示
                result.market_risk_cap = min(result.market_risk_cap, 15)
                result.risk_factors.append(f"微盘股(流通市值{mv_yi:.0f}亿)，流动性风险高，仓位上限15%")
                result.score_breakdown['mcap_risk'] = -1
                adj -= 1
            elif mv_yi < 50:
                # 小盘股（20-50亿）：轻微压缩
                result.market_risk_cap = min(result.market_risk_cap, 25)
                result.risk_factors.append(f"小盘股(流通市值{mv_yi:.0f}亿)，注意流动性")
        
    
    @staticmethod
    def score_limit_and_enhanced(result: TrendAnalysisResult):
        """
        涨跌停 + 量价背离 + VWAP + 换手率分位数 + 缺口 综合评分修正
        
        涨跌停规则：
        - 涨停板：连板越多越强（但高位连板风险加大）
        - 跌停板：直接大幅扣分
        - 连续涨停 ≥3 板：追高风险警告
        
        量价背离：
        - 顶部量价背离：扣分（价格新高但量能萎缩 = 上涨乏力）
        - 底部量缩企稳：加分（可能筑底）
        
        VWAP：
        - 价格在 VWAP 上方 = 多头占优
        - 价格在 VWAP 下方 = 空头占优
        
        换手率分位数：
        - >90分位：异常活跃（可能见顶）
        - <10分位：极度冷清（可能见底）
        
        缺口：
        - 向上跳空 + 放量 = 突破信号
        - 向下跳空 = 风险信号
        """
        adj = 0

        # === 涨跌停评分 ===
        if result.is_limit_up:
            if result.consecutive_limits >= 4:
                # 4板以上：追高风险极大
                adj -= 3
                result.risk_factors.append(f"连续{result.consecutive_limits}板涨停，追高风险极大")
                result.score_breakdown['limit_risk'] = -3
            elif result.consecutive_limits >= 2:
                # 连板：强势但需警惕
                adj += 2
                result.signal_reasons.append(f"连续{result.consecutive_limits}板涨停，短期强势")
                result.score_breakdown['limit_adj'] = 2
            else:
                # 首板涨停
                adj += 3
                result.signal_reasons.append("涨停封板，多头强势")
                result.score_breakdown['limit_adj'] = 3
        elif result.is_limit_down:
            adj -= 5
            result.risk_factors.append("跌停板，风险极高")
            result.score_breakdown['limit_adj'] = -5

        # === 量价背离评分 ===
        vpd = result.volume_price_divergence
        if vpd == "顶部量价背离":
            adj -= 3
            result.risk_factors.append("量价背离：价格新高但成交量萎缩，上涨动能衰竭")
            result.score_breakdown['vp_divergence'] = -3
        elif vpd == "底部量缩企稳":
            adj += 2
            result.signal_reasons.append("底部量缩企稳，抛压减轻，可能筑底")
            result.score_breakdown['vp_divergence'] = 2

        # === VWAP 偏离评分 ===
        vwap_bias = result.vwap_bias
        if vwap_bias > 3.0:
            adj += 1
            result.signal_reasons.append(f"价格在VWAP上方{vwap_bias:.1f}%，多头占优")
            result.score_breakdown['vwap_adj'] = 1
        elif vwap_bias < -3.0:
            adj -= 1
            result.risk_factors.append(f"价格在VWAP下方{abs(vwap_bias):.1f}%，空头占优")
            result.score_breakdown['vwap_adj'] = -1

        # === 换手率分位数评分 ===
        tp = result.turnover_percentile
        if tp > 0.9:
            adj -= 2
            result.risk_factors.append(f"换手率处于历史{tp*100:.0f}%分位，异常活跃，警惕见顶")
            result.score_breakdown['turnover_adj'] = -2
        elif tp < 0.1 and tp > 0:
            adj += 1
            result.signal_reasons.append(f"换手率处于历史{tp*100:.0f}%分位，极度冷清，关注底部信号")
            result.score_breakdown['turnover_adj'] = 1

        # === 缺口评分 ===
        gap = result.gap_type
        if gap == "向上跳空":
            from .types import VolumeStatus
            if result.volume_status in (VolumeStatus.HEAVY_VOLUME_UP,):
                adj += 2
                result.signal_reasons.append("放量向上跳空，突破信号")
                result.score_breakdown['gap_adj'] = 2
            else:
                adj += 1
                result.signal_reasons.append("向上跳空缺口")
                result.score_breakdown['gap_adj'] = 1
        elif gap == "向下跳空":
            adj -= 2
            result.risk_factors.append("向下跳空缺口，短期风险")
            result.score_breakdown['gap_adj'] = -2

        # === 成交量异动评分（P1）===
        vol_ext = getattr(result, 'volume_extreme', '')
        vol_trend_3d = getattr(result, 'volume_trend_3d', '')
        if vol_ext == "天量":
            # 天量 = 变盘信号：上涨中天量可能见顶，下跌中天量可能见底
            price_up = result.bias_ma5 > 0
            if price_up:
                adj -= 2
                result.risk_factors.append("天量上涨：成交量创60日新高，警惕变盘见顶")
                result.score_breakdown['vol_extreme'] = -2
            else:
                adj += 2
                result.signal_reasons.append("天量下跌：放量杀跌可能是恐慌底，关注反弹")
                result.score_breakdown['vol_extreme'] = 2
        elif vol_ext == "地量":
            # 地量 = 底部信号（下跌中）或观望信号（上涨中）
            price_down = result.bias_ma5 < -2
            if price_down:
                adj += 2
                result.signal_reasons.append("地量下跌：成交量创60日新低，抛压枯竭，关注底部")
                result.score_breakdown['vol_extreme'] = 2
            else:
                adj -= 1
                result.risk_factors.append("地量：成交量极低，市场关注度不足")
                result.score_breakdown['vol_extreme'] = -1
        
        if vol_trend_3d == "连续放量":
            # 连续放量 + 上涨 = 趋势确认；连续放量 + 下跌 = 加速下跌
            if result.bias_ma5 > 0:
                adj += 1
                result.signal_reasons.append("连续3日放量上涨，趋势确认")
                result.score_breakdown['vol_trend_3d'] = 1
            else:
                adj -= 1
                result.risk_factors.append("连续3日放量下跌，加速下跌风险")
                result.score_breakdown['vol_trend_3d'] = -1
        elif vol_trend_3d == "连续缩量":
            if result.bias_ma5 < 0:
                # 回测显示缩量下跌短期仍有压力；上升趋势中轻微加分（洗盘），其他情况中性
                from .types import TrendStatus as _TS
                _is_up = result.trend_status in (_TS.STRONG_BULL, _TS.BULL, _TS.WEAK_BULL)
                if _is_up:
                    adj += 1
                    result.signal_reasons.append("连续3日缩量回调（上升趋势洗盘，短期仍有压力）")
                    result.score_breakdown['vol_trend_3d'] = 1

    @staticmethod
    def score_obv_adx(result: TrendAnalysisResult):
        """OBV量能趋势 + ADX趋势强度 + 均线发散速率 综合评分修正"""
        adj = 0
        
        # === OBV 背离（比量价背离更可靠）===
        obv_div = getattr(result, 'obv_divergence', '')
        if obv_div == "OBV顶背离":
            adj -= 2
            result.risk_factors.append("OBV顶背离：价格新高但累积量能未跟上，上涨可能虚假")
            result.score_breakdown['obv_divergence'] = -2
        # OBV底背离不给正分（回测显示价格仍在下跌中，底部确认需结合更多信号）
        # elif obv_div == "OBV底背离": adj += 3
        
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
        # 回测显示ADX高位时均值回归效应强（强多头ADX后均-0.07%，强空头ADX后均+0.67%）
        # ADX仅作为展示信息，不影响评分
        adx_val = getattr(result, 'adx', 0)
        if adx_val < 15 and adx_val > 0:
            result.risk_factors.append(f"ADX={adx_val:.0f}(极弱)，市场无方向，趋势信号可靠性低")
        
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

        # === 弱势多头 + MACD死叉 风险提示 ===
        # 回测显示WEAK_BULL中MACD死叉20d=-1.59%（是卖出信号，非洗盘）
        if result.trend_status == TrendStatus.WEAK_BULL and result.macd_status == MACDStatus.DEATH_CROSS:
            result.risk_factors.append("弱势多头中MACD死叉，中长期风险较高（回测20日均-1.6%）")

        # === 换手率分位数 adj（回测结论：高换手=强信号）===
        # 全体: very_high 20d=+2.84%, high 20d=+1.45%, very_low 20d=+0.22%
        # WEAK_BULL: very_high 20d=+3.07%（+放量上涨则+4.18%）
        # STRONG_BEAR: very_high 20d=+4.54%（超跌资金抄底信号最强）
        tp = getattr(result, 'turnover_percentile', 0.0)
        if tp > 0:
            if tp >= 0.9:
                trend = result.trend_status
                vol_up = result.volume_status == VolumeStatus.HEAVY_VOLUME_UP
                if trend == TrendStatus.STRONG_BEAR:
                    # 强势空头极高换手=超跌资金抄底，最强反转信号
                    adj_val = 5
                    result.signal_reasons.append(f"换手率极高（>90th）+强势空头，超跌资金抄底信号（回测20d均+4.54%）")
                elif trend == TrendStatus.WEAK_BULL and vol_up:
                    # 弱势多头极高换手+放量上涨=突破反转
                    adj_val = 4
                    result.signal_reasons.append(f"换手率极高（>90th）+放量上涨，弱势多头反转共振（回测20d均+4.18%）")
                elif trend == TrendStatus.WEAK_BULL:
                    adj_val = 4
                    result.signal_reasons.append(f"换手率极高（>90th），弱势多头中资金异动（回测20d均+3.07%）")
                else:
                    adj_val = 3
                    result.signal_reasons.append(f"换手率极高（>90th），资金活跃度强（回测20d均+2.84%）")
                result.score_breakdown['turnover_adj'] = adj_val
            elif tp >= 0.7:
                result.score_breakdown['turnover_adj'] = 1
                result.signal_reasons.append(f"换手率偏高（70-90th分位），市场关注度上升（回测20d均+1.45%）")
            elif tp <= 0.1:
                result.score_breakdown['turnover_adj'] = -1
                result.risk_factors.append(f"换手率极低（<10th分位），市场活跃度不足（回测20d均+0.22%）")
        
    @staticmethod
    def score_weekly_trend(result: TrendAnalysisResult, df: pd.DataFrame):
        """P0: 周线趋势分析 — 日线分析的大背景
        
        从日线数据重采样为周线，计算 MA5/MA10/MA20/RSI 判断周线多空趋势。
        数据来源优先级：DB 长历史（500天≈2年）> 传入的 df。
        
        周线 MA20 需要至少 20 根周线 = 约 100 个交易日 ≈ 5 个月日线数据。
        因此直接从 DB 取 500 天确保足够，而不依赖分析用的短窗口 df（120天偏紧）。
        
        - 周线多头（MA5>MA10>MA20 且 RSI>50）：+3~+6
        - 周线空头（MA5<MA10<MA20 且 RSI<50）：-3~-6
        - 日线多头但周线空头（日内反弹，大趋势向下）：额外降分至 -6
        - 周线震荡：中性
        """
        try:
            # 优先级 1: efinance 接口直接拉周线（klt=102，最准确，约150根）
            weekly = None
            try:
                from data_provider.efinance_fetcher import EfinanceFetcher
                wdf = EfinanceFetcher.get_weekly_history(result.code, years=3)
                if wdf is not None and len(wdf) >= 22:
                    wdf = wdf.set_index('date')
                    weekly = wdf
            except Exception:
                pass

            # 优先级 2: DB 长历史重采样（500天日线 → 周线）
            if weekly is None:
                try:
                    from src.storage import DatabaseManager
                    db = DatabaseManager.get_instance()
                    long_df = db.get_stock_history_df(result.code, days=500)
                    if long_df is not None and len(long_df) >= 100:
                        w = long_df.copy()
                        if 'date' in w.columns:
                            w['date'] = pd.to_datetime(w['date'])
                            w = w.set_index('date')
                        weekly = w.resample('W').agg({
                            'open': 'first', 'high': 'max', 'low': 'min',
                            'close': 'last', 'volume': 'sum'
                        }).dropna()
                except Exception:
                    pass

            # 优先级 3: 传入 df 重采样（最短，仅兜底）
            if weekly is None:
                if df is None or len(df) < 60:
                    return
                w = df.copy()
                if 'date' in w.columns:
                    w['date'] = pd.to_datetime(w['date'])
                    w = w.set_index('date')
                elif not isinstance(w.index, pd.DatetimeIndex):
                    return
                weekly = w.resample('W').agg({
                    'open': 'first', 'high': 'max', 'low': 'min',
                    'close': 'last', 'volume': 'sum'
                }).dropna()

            if len(weekly) < 22:
                return

            c = weekly['close']
            # 周线均线
            wma5 = float(c.rolling(5).mean().iloc[-1]) if len(c) >= 5 else 0
            wma10 = float(c.rolling(10).mean().iloc[-1]) if len(c) >= 10 else 0
            wma20 = float(c.rolling(20).mean().iloc[-1]) if len(c) >= 20 else 0

            # 周线RSI(14)
            delta = c.diff()
            gain = delta.clip(lower=0).rolling(14).mean()
            loss = (-delta.clip(upper=0)).rolling(14).mean()
            wrsi = float(100 - 100 / (1 + gain.iloc[-1] / loss.iloc[-1])) if loss.iloc[-1] > 0 else 50.0

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

            # 周线趋势仅作背景信息展示，不影响评分
            # 回测显示周线趋势对5日短期收益无正向预测力（超跌反弹效应导致空头期间反而收益高）
            if is_weekly_bull:
                result.weekly_trend = "多头"
                note = f"周线均线多头排列(MA5={wma5:.2f}>MA10={wma10:.2f}>MA20={wma20:.2f})，RSI{wrsi:.0f}，中长线向好"
                if is_daily_bull:
                    result.signal_reasons.append(f"🗓️ 日周双多头共振（仅背景参考）")
            elif is_weekly_bull_weak:
                result.weekly_trend = "弱多头"
                note = f"周线偏多(MA5>{wma20:.2f})，RSI{wrsi:.0f}，趋势偏正面"
            elif is_weekly_bear:
                result.weekly_trend = "空头"
                note = f"周线均线空头排列(MA5={wma5:.2f}<MA10={wma10:.2f}<MA20={wma20:.2f})，RSI{wrsi:.0f}，中长线向下"
                result.risk_factors.append(f"⚠️ 周线空头背景（仅中长线参考，不影响评分）")
                if is_daily_bull:
                    result.risk_factors.append("⚠️ 日线多头但周线空头，可能为下降趋势中反弹（仅参考）")
            elif is_weekly_bear_weak:
                result.weekly_trend = "弱空头"
                note = f"周线偏空(MA5<{wma20:.2f})，RSI{wrsi:.0f}，趋势偏负面"
            else:
                result.weekly_trend = "震荡"
                note = f"周线横盘震荡，RSI{wrsi:.0f}"

            adj = 0  # 周线趋势不给分
            result.weekly_trend_adj = adj
            result.weekly_trend_note = note

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
                            # P2b 突破量能确认
                            _last_vol = float(df.iloc[-1].get('volume', 0) or 0)
                            _avg_vol20 = float(df['volume'].tail(21).iloc[:-1].mean()) if len(df) >= 21 else 0
                            vol_ratio = _last_vol / _avg_vol20 if _avg_vol20 > 0 else 1.0
                            if vol_ratio >= 1.5:
                                adj_pattern = 6
                                vol_note = f"放量突破（量比{vol_ratio:.1f}x），强势确认"
                            else:
                                adj_pattern = 0
                                vol_note = f"量能不足（量比{vol_ratio:.1f}x），需量能配合再介入"
                            result.chart_pattern_note = (
                                f"双底形态：两谷约{min(t1_val, t2_val):.2f}，颈线{neckline:.2f}，"
                                f"理论目标位{target:.2f}，{vol_note}"
                            )
                            result.chart_pattern_adj = adj_pattern
                            result.signal_reasons.append(f"✅ 识别到双底(W底)形态，颈线{neckline:.2f}，看多信号，目标{target:.2f}，{vol_note}")
                            result.score_breakdown['chart_pattern_adj'] = adj_pattern
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
                            # P2b 突破量能确认
                            _last_vol = float(df.iloc[-1].get('volume', 0) or 0)
                            _avg_vol20 = float(df['volume'].tail(21).iloc[:-1].mean()) if len(df) >= 21 else 0
                            vol_ratio = _last_vol / _avg_vol20 if _avg_vol20 > 0 else 1.0
                            if vol_ratio >= 1.5:
                                adj_pattern = 8
                                vol_note = f"放量突破（量比{vol_ratio:.1f}x），强势确认"
                            elif vol_ratio >= 1.3:
                                adj_pattern = 5
                                vol_note = f"量能确认（量比{vol_ratio:.1f}x）"
                            else:
                                adj_pattern = 0
                                vol_note = f"量能不足（量比{vol_ratio:.1f}x），需量能配合再介入"
                            result.chart_pattern_note = (
                                f"头肩底：底部{hd_val:.2f}，颈线{neckline:.2f}，"
                                f"理论涨幅目标{target:.2f}，{vol_note}"
                            )
                            result.chart_pattern_adj = adj_pattern
                            result.signal_reasons.append(f"✅ 识别到头肩底形态，颈线{neckline:.2f}，经典底部反转，强烈看多，目标{target:.2f}，{vol_note}")
                            result.score_breakdown['chart_pattern_adj'] = adj_pattern
                            return

        except Exception as e:
            logger.debug(f"[形态识别] 计算失败: {e}")

    @staticmethod
    def score_intraday_volume_signal(result: TrendAnalysisResult):
        """盘中量比×价格联动主力行为检测
        
        换手率盘中是累计残缺值，不可靠。
        量比（当前每分钟成交速率 vs 过去5日同时段均值）是已归一化的盘中指标，
        结合价格方向可判断主力行为：
        - 量比>2 + 价格上涨  → 放量拉升（主力买入信号）+2
        - 量比>3 + 价格上涨  → 强势放量拉升 +3
        - 量比>2 + 价格下跌  → 放量出货（主力离场信号）-2
        - 量比>3 + 价格下跌  → 强势出货 -3
        - 量比<0.5           → 缩量（流动性差，中性偏负）-1
        
        仅盘中（15:00前）触发，收盘后由换手率历史百分位接管。
        """
        from datetime import datetime as _dt_iv
        if _dt_iv.now().hour >= 15:
            return  # 收盘后由换手率历史百分位接管，不重复计

        vr = result.volume_ratio
        if not isinstance(vr, (int, float)) or vr <= 0:
            return

        from .types import TrendStatus, VolumeStatus
        # 用 trend_status + volume_status 联合判断价格方向
        is_rising = result.trend_status in (TrendStatus.STRONG_BULL, TrendStatus.BULL) or \
                    result.volume_status in (VolumeStatus.HEAVY_VOLUME_UP,)
        is_falling = result.trend_status in (TrendStatus.STRONG_BEAR, TrendStatus.BEAR) or \
                     result.volume_status in (VolumeStatus.HEAVY_VOLUME_DOWN,)

        adj = 0
        if vr >= 3.0:
            if is_rising:
                adj = 3
                result.signal_reasons.append(f"量比{vr:.1f}强势放量拉升，主力积极买入")
            elif is_falling:
                adj = -3
                result.risk_factors.append(f"量比{vr:.1f}强势放量下跌，主力出货信号")
        elif vr >= 2.0:
            if is_rising:
                adj = 2
                result.signal_reasons.append(f"量比{vr:.1f}放量上涨，资金活跃")
            elif is_falling:
                adj = -2
                result.risk_factors.append(f"量比{vr:.1f}放量下跌，警惕主力出货")
        elif vr < 0.5:
            adj = -1
            result.risk_factors.append(f"量比{vr:.1f}极度缩量，流动性不足")

        if adj != 0:
            result.score_breakdown['intraday_vol_signal'] = adj

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
                if amp > 0.035 and shadow_down > 0.65:
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
                if is_bear:
                    # 熊市中连续放量下跌往往是超卖反弹前兆，降权处理
                    bull_signals += 1
                    detail_parts.append("连续放量下跌（熊市超卖，关注反弹）")
                else:
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
                    # 回测fib_0.618: 20d=+0.66%仅略高于基准，需量能确认才有效
                    has_vol = result.volume_status == VolumeStatus.HEAVY_VOLUME_UP
                    adj = 2 if has_vol else 1
                    active_level = f618
                    result.signal_reasons.append(f"价格触及0.618支撑({f618:.2f})，需放量确认才可介入")
                elif near(current_price, f500):
                    result.fib_current_zone = "0.500中度回撤支撑区"
                    result.fib_signal = "中度回撤区，观望"
                    # 回测fib_0.500: 20d=-0.42%，50%回撤位无效，不加分
                    adj = 0
                    active_level = f500
                    result.signal_reasons.append(f"价格在0.5回撤位({f500:.2f})，历史有效性低，等待方向确认")
                elif near(current_price, f382):
                    result.fib_current_zone = "0.382浅度回撤支撑区"
                    result.fib_signal = "浅回调，等待企稳确认"
                    # 回测fib_0.382: 20d=+0.29%低于基准，仅展示文本，不加分
                    adj = 0
                    active_level = f382
                    result.signal_reasons.append(f"价格在0.382回撤支撑({f382:.2f})，等待企稳确认后介入")
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
                test_count = ScoringSystem._fib_count_tests(close, active_level, tol)
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
                    adj = 5 if current_vol >= vol_ma20 * 2.0 else 0
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
                        _ma5_cur = float(pd.Series(close).rolling(5).mean().iloc[-1]) if n >= 5 else current_price
                        if current_price >= _ma5_cur:
                            adj = 2
                            result.signal_reasons.append(
                                f"缩量回踩突破位({breakout_price:.2f})，价格在MA5上方，量能萎缩健康，可关注买入机会"
                            )
                        else:
                            adj = -1
                            result.risk_factors.append(
                                f"缩量回踩突破位({breakout_price:.2f})，价格跌破MA5，回踩渔度偏大，谨慎介入"
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
    def cap_adjustments(result: TrendAnalysisResult):
        """统一应用所有评分修正因子（取代逐步截断）
        
        流程：
        1. 汇总 score_breakdown 中所有 adj 键
        2. 应用正向上限 POS_CAP=15、负向下限 NEG_CAP=-20
        3. 一次性加到 base_score 并 clamp 到 [0, 100]
        4. 仅调用一次 update_buy_signal
        """
        adj_keys = ['valuation_adj', 'capital_flow_adj', 'cf_trend', 'cf_continuity',
                   'cross_resonance', 'sector_adj', 'chip_adj', 'fundamental_adj',
                   'week52_risk', 'week52_opp', 'liquidity_risk', 'resonance_adj',
                   'limit_adj', 'limit_risk', 'vp_divergence', 'vwap_adj', 'turnover_adj', 'gap_adj',
                   'timeframe_resonance', 'vol_extreme', 'vol_trend_3d', 'sentiment_extreme',
                   'candle_pattern', 'obv_divergence', 'obv_trend', 'adx_adj', 'ma_spread',
                   'forecast_adj', 'mcap_risk', 'beta_adj', 'intraday_vol_signal',
                   'weekly_trend_adj', 'chart_pattern_adj',
                   'fib_adj', 'vol_price_structure', 'vol_anomaly',
                   'p3_resonance', 'p4_capital_flow', 'vwap_adj', 'p5c_lhb', 'p5c_holder']
        
        # === Beta 系数调整 ===
        # 高 Beta (>1.5) 在熊市中系统性放大下跌，降分惩罚
        # 低 Beta (<0.6) 说明安全属性强、独立行情概率大，酌情加分
        beta = getattr(result, 'beta_vs_index', 1.0) or 1.0
        from .types import MarketRegime
        trend_st = getattr(result, 'trend_status', None)
        # 从 score_breakdown 推断 market_regime（BEAR标记由外部在 bear_market_cap 注入）
        is_bear = 'bear_market_cap' in result.score_breakdown
        beta_adj = 0
        if beta > 1.5 and is_bear:
            # 高Beta + 熊市：额外降分（最多 -5）
            beta_adj = max(-5, round(-(beta - 1.5) * 5, 0))
        elif beta > 1.3 and is_bear:
            beta_adj = -2
        elif beta < 0.6:
            # 低Beta：独立行情属性，弱市中是优势（最多 +4）
            beta_adj = min(4, round((0.6 - beta) * 8, 0))
        if beta_adj != 0:
            result.score_breakdown['beta_adj'] = int(beta_adj)
        
        # 单类 adj 上限 ±8：防止单一因子（如估值严重高估 -15）过度主导总分
        SINGLE_ADJ_CAP = 8
        clamped_breakdown = {}
        for k in adj_keys:
            v = result.score_breakdown.get(k, 0)
            if v != 0:
                cv = max(-SINGLE_ADJ_CAP, min(SINGLE_ADJ_CAP, v))
                if cv != v:
                    clamped_breakdown[k] = cv  # 记录被截断的键
                    result.score_breakdown[k] = cv
        
        pos_adj = sum(v for k in adj_keys if (v := result.score_breakdown.get(k, 0)) > 0)
        neg_adj = sum(v for k in adj_keys if (v := result.score_breakdown.get(k, 0)) < 0)
        total_adj = pos_adj + neg_adj
        
        POS_CAP = 15
        NEG_CAP = -20
        
        # 应用 cap
        capped_pos = min(pos_adj, POS_CAP)
        capped_neg = max(neg_adj, NEG_CAP)
        capped_total = capped_pos + capped_neg
        
        if pos_adj > POS_CAP or neg_adj < NEG_CAP:
            result.score_breakdown['adj_cap'] = capped_total - total_adj
        
        # base_score = signal_score 此时仍是 calculate_base_score 的原始值（因为各 score_xxx 不再修改它）
        result.signal_score = max(0, min(100, result.signal_score + capped_total))
        ScoringSystem.update_buy_signal(result)
    
    @staticmethod
    def detect_signal_conflict(result: TrendAnalysisResult):
        """信号冲突检测：技术面与多维因子严重分歧时，显式警告"""
        conflicts = []
        
        base_score = sum(result.score_breakdown.get(k, 0) 
                        for k in ['trend', 'bias', 'volume', 'support', 'macd', 'rsi', 'kdj'])
        
        adj_keys = ['valuation_adj', 'capital_flow_adj', 'sector_adj', 'chip_adj', 'fundamental_adj']
        multi_adj = sum(result.score_breakdown.get(k, 0) for k in adj_keys)
        
        if base_score >= 70 and multi_adj <= -10:
            conflicts.append("⚠️技术面强势但多维因子转弱（估值/资金/板块/筹码/基本面）")
        elif base_score <= 40 and multi_adj >= 10:
            conflicts.append("⚠️技术面偏弱但多维因子支撑（估值/资金/板块等）")
        
        if not hasattr(result, '_conflict_warnings'):
            result._conflict_warnings = []
        result._conflict_warnings = conflicts
    
    @staticmethod
    def update_buy_signal(result: TrendAnalysisResult):
        """根据 signal_score 重新判定 buy_signal 等级（7档精细分级）"""
        score = result.signal_score
        
        if score >= 95:
            result.buy_signal = BuySignal.AGGRESSIVE_BUY
        elif score >= 85:
            result.buy_signal = BuySignal.STRONG_BUY
        elif score >= 70:
            result.buy_signal = BuySignal.BUY
        elif score >= 60:
            result.buy_signal = BuySignal.CAUTIOUS_BUY
        elif score >= 50:
            result.buy_signal = BuySignal.HOLD
        elif score >= 35:
            result.buy_signal = BuySignal.REDUCE
        else:
            result.buy_signal = BuySignal.SELL

    @staticmethod
    def score_gap_analysis(result: TrendAnalysisResult, df: pd.DataFrame):
        """P2a: 缺口分析 - 识别近30日未回补跳空缺口，判断压力/支撑

        逻辑：
        - 向上跳空缺口（open > prev_high）：
          - 价格在缺口上方且未回补 → 缺口支撑，+2
          - 价格已回补缺口 → 缺口回补完成，中性 0
          - 价格已跌入缺口 → 缺口破位，-2
        - 向下跳空缺口（open < prev_low）：
          - 价格在缺口下方且未回补 → 缺口压力，-2
          - 价格已回补缺口 → 缺口回补，需谨慎（阻力位），-1
        - 扫描最近30根K线，只取最近一个有效缺口
        """
        if df is None or len(df) < 5:
            return

        price = result.current_price
        if price <= 0:
            return

        scan_df = df.tail(30).reset_index(drop=True)
        adj = 0

        for i in range(len(scan_df) - 1, 0, -1):
            row = scan_df.iloc[i]
            prev = scan_df.iloc[i - 1]
            open_p = float(row.get('open', 0) or 0)
            prev_high = float(prev.get('high', 0) or 0)
            prev_low = float(prev.get('low', 0) or 0)
            if open_p <= 0 or prev_high <= 0 or prev_low <= 0:
                continue

            # 向上跳空缺口：当日开盘 > 前日最高
            if open_p > prev_high:
                gap_lower = prev_high
                gap_upper = open_p
                result.gap_type = "向上跳空"
                result.gap_upper = round(gap_upper, 2)
                result.gap_lower = round(gap_lower, 2)
                # 判断是否已回补（价格曾进入缺口区间）
                filled = any(
                    float(scan_df.iloc[j].get('low', 0) or 0) <= gap_lower
                    for j in range(i + 1, len(scan_df))
                )
                result.gap_filled = filled
                if filled:
                    result.gap_signal = "缺口回补完成"
                    adj = 0
                elif price >= gap_lower:
                    from .types import TrendStatus as _TS
                    _bear = result.trend_status in (_TS.BEAR, _TS.STRONG_BEAR, _TS.WEAK_BEAR)
                    # 时效性：缺口距今天数（scan_df末尾=今天，i=缺口位置）
                    _days_ago = len(scan_df) - 1 - i
                    _stale = _days_ago > 10
                    # 价格历史位置：近60日分位数，高位(>60%)的向上缺口往往是顶部跳空，降级
                    _lookback60 = df.tail(60)
                    _p60_high = float(_lookback60['high'].max()) if len(_lookback60) > 0 else price
                    _p60_low = float(_lookback60['low'].min()) if len(_lookback60) > 0 else price
                    _price_pct = (price - _p60_low) / (_p60_high - _p60_low) if _p60_high > _p60_low else 0.5
                    _high_pos = _price_pct > 0.6  # 近60日60%分位以上视为高位
                    if _bear:
                        result.gap_signal = "未回补支撑缺口(空头趋势降级)"
                        adj = 1
                    elif _stale or _high_pos:
                        result.gap_signal = "未回补支撑缺口(高位/时效衰减)"
                        adj = 1
                    else:
                        result.gap_signal = "未回补支撑缺口"
                        adj = 2
                else:
                    result.gap_signal = "向上缺口已破位"
                    adj = -2
                break

            # 向下跳空缺口：当日开盘 < 前日最低
            if open_p < prev_low:
                gap_upper = prev_low
                gap_lower = open_p
                result.gap_type = "向下跳空"
                result.gap_upper = round(gap_upper, 2)
                result.gap_lower = round(gap_lower, 2)
                filled = any(
                    float(scan_df.iloc[j].get('high', 0) or 0) >= gap_upper
                    for j in range(i + 1, len(scan_df))
                )
                result.gap_filled = filled
                if filled:
                    result.gap_signal = "向下缺口已回补"
                    adj = 0
                else:
                    result.gap_signal = "未回补压力缺口"
                    adj = -2
                break

        if adj != 0:
            result.score_breakdown['gap_adj'] = adj
