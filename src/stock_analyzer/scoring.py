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
                return 14  # 强势趋势中偏大正乖离：轻微惩罚
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
            return 14  # 强势趋势中偏大正乖离
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
            return 14 if is_uptrend else 7  # 上升趋势洗盘=高分，下跌趋势阴跌=低分
        
        scores = {
            VolumeStatus.HEAVY_VOLUME_UP: 12,
            VolumeStatus.NORMAL: 10,
            VolumeStatus.SHRINK_VOLUME_UP: 6,
            VolumeStatus.HEAVY_VOLUME_DOWN: 0,
        }
        return scores.get(result.volume_status, 8)
    
    @staticmethod
    def _calc_support_score(result: TrendAnalysisResult) -> int:
        """计算支撑接近度评分 (0-10)"""
        if not result.support_levels or result.current_price <= 0:
            return 5
        
        nearest = min((s for s in result.support_levels if 0 < s < result.current_price), 
                     default=result.ma20 if result.ma20 > 0 else 0)
        if nearest <= 0:
            return 5
        
        dist_pct = (result.current_price - nearest) / result.current_price * 100
        if 0 <= dist_pct <= 2:
            return 10
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
        """计算RSI评分 (0-10)"""
        scores = {
            RSIStatus.GOLDEN_CROSS_OVERSOLD: 10,
            RSIStatus.BULLISH_DIVERGENCE: 10,
            RSIStatus.OVERSOLD: 9,
            RSIStatus.GOLDEN_CROSS: 8,
            RSIStatus.STRONG_BUY: 7,
            RSIStatus.NEUTRAL: 5,
            RSIStatus.WEAK: 3,
            RSIStatus.DEATH_CROSS: 2,
            RSIStatus.BEARISH_DIVERGENCE: 1,
            RSIStatus.OVERBOUGHT: 0,
        }
        return scores.get(result.rsi_status, 5)
    
    @staticmethod
    def _calc_kdj_score(result: TrendAnalysisResult) -> int:
        """计算KDJ评分 (0-13)，含钝化/背离/连续极端修正"""
        base_scores = {
            KDJStatus.GOLDEN_CROSS_OVERSOLD: 13,
            KDJStatus.OVERSOLD: 11,
            KDJStatus.GOLDEN_CROSS: 10,
            KDJStatus.BULLISH: 7,
            KDJStatus.NEUTRAL: 5,
            KDJStatus.BEARISH: 3,
            KDJStatus.DEATH_CROSS: 1,
            KDJStatus.OVERBOUGHT: 0,
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
        
        # J 值连续极端额外修正
        if result.kdj_consecutive_extreme:
            if "超买" in result.kdj_consecutive_extreme:
                score = max(0, score - 2)
            elif "超卖" in result.kdj_consecutive_extreme:
                score = min(13, score + 2)
        
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
                adj += 1
                result.signal_reasons.append("连续3日缩量回调，洗盘特征")
                result.score_breakdown['vol_trend_3d'] = 1

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
                   'forecast_adj', 'mcap_risk', 'beta_adj']
        
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
