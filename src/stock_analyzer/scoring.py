# -*- coding: utf-8 -*-
"""
评分系统模块
包含估值、资金流、板块强弱、筹码分布、基本面等多维评分逻辑
"""

import logging
import pandas as pd
from typing import Dict
from .types import TrendAnalysisResult, BuySignal, MarketRegime, TrendStatus
from .types import VolumeStatus, MACDStatus, RSIStatus, KDJStatus

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
        
        # 自适应归一化：用布林带宽度衡量该股正常波动范围
        # bb_width = (upper - lower) / middle，典型值 0.05~0.20
        # 归一化后的 bias = 实际乖离 / 正常波动幅度
        if result.bb_width > 0.01:
            half_bb_pct = result.bb_width * 50  # 半个布林带宽度(%)
            norm_bias = bias / half_bb_pct  # 归一化：1.0 = 到达布林带边缘
            if norm_bias > 1.5:
                return 0   # 远超布林上轨
            elif norm_bias > 1.0:
                return 5   # 接近或超过布林上轨
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
            return 0
        elif bias > 5:
            return 5
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

        # 常规量能评分
        scores = {
            VolumeStatus.SHRINK_VOLUME_DOWN: 15,
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
        """计算MACD评分 (0-15)"""
        scores = {
            MACDStatus.GOLDEN_CROSS_ZERO: 15,
            MACDStatus.GOLDEN_CROSS: 12,
            MACDStatus.CROSSING_UP: 10,
            MACDStatus.BULLISH: 8,
            MACDStatus.NEUTRAL: 5,
            MACDStatus.BEARISH: 2,
            MACDStatus.CROSSING_DOWN: 0,
            MACDStatus.DEATH_CROSS: 0,
        }
        return scores.get(result.macd_status, 5)
    
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
    def check_valuation(result: TrendAnalysisResult, valuation: dict = None):
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
        
        v_score = 5
        downgrade = 0
        industry_pe = valuation.get('industry_pe_median')
        
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
        
        result.valuation_score = v_score
        result.valuation_downgrade = downgrade
        
        if downgrade < 0:
            result.signal_score = max(0, result.signal_score + downgrade)
            result.score_breakdown['valuation_adj'] = downgrade
            ScoringSystem.update_buy_signal(result)
    
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
    def score_capital_flow(result: TrendAnalysisResult, capital_flow: dict = None):
        """资金面评分：北向资金、主力资金、融资余额"""
        if not capital_flow or not isinstance(capital_flow, dict):
            return
        
        cf_score = 5
        cf_signals = []
        
        north_net = capital_flow.get('north_net_flow')
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
        
        main_net = capital_flow.get('main_net_flow')
        daily_avg = capital_flow.get('daily_avg_amount')
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
        
        margin_change = capital_flow.get('margin_balance_change')
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
            result.signal_score = max(0, min(100, result.signal_score + cf_adj))
            result.score_breakdown['capital_flow_adj'] = cf_adj
            ScoringSystem.update_buy_signal(result)
    
    @staticmethod
    def score_capital_flow_trend(result: TrendAnalysisResult, df: pd.DataFrame):
        """资金面连续性检测：近3日量价关系判断持续性资金流向"""
        if df is None or len(df) < 5:
            return
        
        recent = df.tail(3)
        if len(recent) < 3:
            return
        
        closes = recent['close'].values
        opens = recent['open'].values
        volumes = recent['volume'].values
        
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
        
        if adj != 0:
            result.signal_score = max(0, min(100, result.signal_score + adj))
            ScoringSystem.update_buy_signal(result)
    
    @staticmethod
    def score_sector_strength(result: TrendAnalysisResult, sector_context: dict = None):
        """板块强弱评分"""
        if not sector_context or not isinstance(sector_context, dict):
            return
        
        sec_name = sector_context.get('sector_name', '')
        sec_pct = sector_context.get('sector_pct')
        rel = sector_context.get('relative')
        
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
            result.signal_score = max(0, min(100, result.signal_score + sector_adj))
            result.score_breakdown['sector_adj'] = sector_adj
            ScoringSystem.update_buy_signal(result)
    
    @staticmethod
    def score_chip_distribution(result: TrendAnalysisResult, chip_data: dict = None):
        """筹码分布评分"""
        if not chip_data or not isinstance(chip_data, dict):
            return
        
        c_score = 5
        signals = []
        
        profit_ratio = chip_data.get('profit_ratio')
        avg_cost = chip_data.get('avg_cost')
        concentration_90 = chip_data.get('concentration_90')
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
            result.signal_score = max(0, min(100, result.signal_score + chip_adj))
            result.score_breakdown['chip_adj'] = chip_adj
            ScoringSystem.update_buy_signal(result)
    
    @staticmethod
    def score_fundamental_quality(result: TrendAnalysisResult, fundamental_data: dict = None):
        """基本面质量评分：ROE + 负债率"""
        if not fundamental_data or not isinstance(fundamental_data, dict):
            return
        
        f_score = 5
        signals = []
        
        financial = fundamental_data.get('financial', {})
        if not isinstance(financial, dict):
            return
        
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
            ScoringSystem.update_buy_signal(result)
    
    @staticmethod
    def score_quote_extra(result: TrendAnalysisResult, quote_extra: dict = None):
        """行情附加数据评分：换手率异常检测 + 52周高低位"""
        if not quote_extra or not isinstance(quote_extra, dict):
            return
        
        adj = 0
        price = result.current_price
        
        turnover = quote_extra.get('turnover_rate')
        if isinstance(turnover, (int, float)) and turnover > 0:
            if turnover > 15:
                if not result.trading_halt:
                    result.trading_halt = True
                    result.trading_halt_reason = (result.trading_halt_reason + "；" if result.trading_halt_reason else "") + f"换手率异常({turnover:.1f}%>15%)，疑似游资炒作"
            elif turnover < 0.3:
                adj -= 1
                result.score_breakdown['liquidity_risk'] = -1
        
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
            ScoringSystem.update_buy_signal(result)
    
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

        # 应用修正
        if adj != 0:
            result.signal_score = max(0, min(100, result.signal_score + adj))
            ScoringSystem.update_buy_signal(result)

    @staticmethod
    def cap_adjustments(result: TrendAnalysisResult):
        """修正因子总量上限：防止多维修正导致分数膨胀"""
        adj_keys = ['valuation_adj', 'capital_flow_adj', 'cf_trend', 'cf_continuity',
                   'cross_resonance', 'sector_adj', 'chip_adj', 'fundamental_adj',
                   'week52_risk', 'week52_opp', 'liquidity_risk', 'resonance_adj',
                   'limit_adj', 'limit_risk', 'vp_divergence', 'vwap_adj', 'turnover_adj', 'gap_adj',
                   'timeframe_resonance']
        
        pos_adj = sum(v for k in adj_keys if (v := result.score_breakdown.get(k, 0)) > 0)
        neg_adj = sum(v for k in adj_keys if (v := result.score_breakdown.get(k, 0)) < 0)
        total_adj = pos_adj + neg_adj
        
        POS_CAP = 15
        NEG_CAP = -20
        
        if pos_adj > POS_CAP:
            capped = min(total_adj, POS_CAP + neg_adj)
            result.signal_score = max(0, min(100, result.signal_score - (pos_adj - POS_CAP)))
            result.score_breakdown['adj_cap'] = capped - total_adj
            ScoringSystem.update_buy_signal(result)
        elif neg_adj < NEG_CAP:
            capped = max(total_adj, NEG_CAP + pos_adj)
            result.signal_score = max(0, min(100, result.signal_score + (NEG_CAP - neg_adj)))
            result.score_breakdown['adj_cap'] = capped - total_adj
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
