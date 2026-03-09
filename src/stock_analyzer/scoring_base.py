# -*- coding: utf-8 -*-
"""
评分系统 — ScoringBase 模块
从 scoring.py 拆分，由 ScoringSystem 通过多继承聚合。
"""

import logging
from datetime import datetime
from typing import Dict, List, Union, Optional

import numpy as np
import pandas as pd
from collections import defaultdict
from .types import TrendAnalysisResult, BuySignal, MarketRegime, TrendStatus
from .types import VolumeStatus, MACDStatus, RSIStatus, KDJStatus
from data_provider.fundamental_types import FundamentalData, ValuationSnapshot, FinancialSummary, ForecastData
from data_provider.analysis_types import CapitalFlowData, SectorContext, QuoteExtra
from data_provider.realtime_types import ChipDistribution

logger = logging.getLogger(__name__)


class ScoringBase:
    """ScoringBase Mixin"""
    """评分系统：多维度评分与修正"""
    
    # P3权重优化（2026-03）：基于2694个历史样本穷举回测，夏普0.454（+0.129）,胜率45.5%（+1.1%）
    # 核心变化：牛市加强 MACD 权重（20→25）+趋势（30→32），降低量能(10→8)/乖离(12→10)
    # 震荡市：MACD上调(15→18)，Bias下调(20→18)
    REGIME_WEIGHTS = {
        MarketRegime.BULL:     {"trend": 32, "bias": 10, "volume": 8,  "support": 5,  "macd": 25, "rsi": 10, "kdj": 10},
        MarketRegime.SIDEWAYS: {"trend": 18, "bias": 18, "volume": 10, "support": 12, "macd": 18, "rsi": 12, "kdj": 12},
        MarketRegime.BEAR:     {"trend": 12, "bias": 16, "volume": 14, "support": 14, "macd": 16, "rsi": 14, "kdj": 14},
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
        raw_scores = ScoringBase._get_raw_dimension_scores(result)
        # 改进4: 优先使用时间维度权重表，未命中则回退到市场环境权重
        horizon_weights = ScoringBase.HORIZON_WEIGHTS.get(time_horizon)
        if horizon_weights:
            weights = horizon_weights
        else:
            weights = ScoringBase.REGIME_WEIGHTS.get(market_regime, ScoringBase.REGIME_WEIGHTS[MarketRegime.SIDEWAYS])
        
        result.score_breakdown = {
            k: min(weights[k], round(raw_scores[k] * weights[k])) 
            for k in raw_scores
        }
        
        score = sum(result.score_breakdown.values())
        return min(100, max(0, score))
    
    # 各维度理论满分（与 _calc_*_score 函数的返回范围上界保持一致）
    # 修改任一 _calc_*_score 时需同步更新此处
    _DIM_MAX = {
        "trend": 30,
        "bias":  20,
        "volume": 15,
        "support": 10,
        "macd":  15,
        "rsi":   10,
        "kdj":   13,
    }


    @staticmethod
    def _get_raw_dimension_scores(result: TrendAnalysisResult) -> Dict[str, float]:
        """获取各维度的原始得分率（0.0~1.0），统一以 _DIM_MAX 为分母，消除结构性评分压缩"""
        raw = {
            "trend":   ScoringBase._calc_trend_score(result),
            "bias":    ScoringBase._calc_bias_score(result),
            "volume":  ScoringBase._calc_volume_score(result),
            "support": ScoringBase._calc_support_score(result),
            "macd":    ScoringBase._calc_macd_score(result),
            "rsi":     ScoringBase._calc_rsi_score(result),
            "kdj":     ScoringBase._calc_kdj_score(result),
        }
        return {
            k: min(1.0, raw[k] / ScoringBase._DIM_MAX[k])
            for k in raw
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
        """计算RSI评分 (0-10)
        
        P0修复：RSI超买（>70）在强势多头趋势中是健康表现，不应给0分。
        强势趋势中 RSI 可长期维持超买区，一律给0分会系统性低估强势股。
        修复后：STRONG_BULL→5分（中性），BULL/WEAK_BULL→3分（轻微惩罚）。
        """
        base_scores = {
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
        score = base_scores.get(result.rsi_status, 5)
        
        # P0修复：超买状态在强势趋势中降级而非直接给0分
        if result.rsi_status == RSIStatus.OVERBOUGHT:
            if result.trend_status == TrendStatus.STRONG_BULL:
                score = 5  # 强势多头中超买 = 中性（趋势健康的体现）
            elif result.trend_status in (TrendStatus.BULL, TrendStatus.WEAK_BULL):
                score = 3  # 普通多头中超买 = 轻微惩罚（警惕但未到卖出）
            # else: 震荡/空头中超买保持0分（追高风险真实存在）
        
        return score
    

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
    def apply_kdj_weekly_bonus(result: TrendAnalysisResult):
        """P4-KDJ: 超卖金叉+周线背景组合加分（必须在 score_weekly_trend 之后调用）
        
        回测支撑（2026-03）:
        - 超卖金叉+多头周线: 20日胜率84.6%, avg+3.57% → +8分
        - 超卖金叉+弱多头周线: 20日胜率69.2%, avg+2.55% → +5分
        - 普通金叉+多头周线: 20日胜率60%, avg+4.21% → +3分
        """
        _kdj = getattr(result, 'kdj_status', None)
        _weekly = str(getattr(result, 'weekly_trend', '') or '')
        _kdj_bonus = 0
        if _kdj == KDJStatus.GOLDEN_CROSS_OVERSOLD:
            if '多头' in _weekly and '弱多头' not in _weekly:
                _kdj_bonus = 8
            elif '弱多头' in _weekly:
                _kdj_bonus = 5
        elif _kdj == KDJStatus.GOLDEN_CROSS:
            if '多头' in _weekly and '弱多头' not in _weekly:
                _kdj_bonus = 3
        if _kdj_bonus > 0:
            result.signal_score = min(100, result.signal_score + _kdj_bonus)
            result.score_breakdown['kdj_weekly_bonus'] = _kdj_bonus


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
                # 成长股豁免：净利/营收增速>30% 且 PE<150 时降低惩罚（科技/医药成长溢价合理）
                _growth = valuation.net_profit_growth or valuation.revenue_growth
                _is_growth = isinstance(_growth, (int, float)) and _growth > 30
                if result.pe_ratio > 100:
                    if _is_growth and result.pe_ratio < 150:
                        v_score = 3
                        downgrade = -8
                        result.valuation_verdict = f"成长溢价(PE{result.pe_ratio:.0f},增速{_growth:.0f}%,尚可接受)"
                    else:
                        v_score = 0
                        downgrade = -15
                        result.valuation_verdict = "严重高估"
                elif result.pe_ratio > 60:
                    if _is_growth:
                        v_score = 4
                        downgrade = -5
                        result.valuation_verdict = f"成长溢价偏高(PE{result.pe_ratio:.0f},增速{_growth:.0f}%)"
                    else:
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
    def cap_adjustments(result: TrendAnalysisResult):
        """统一应用所有评分修正因子（分组互斥 + 组预算）

        流程：
        1. 计算 Beta 系数修正并写入 score_breakdown
        2. 单因子 clamp ±8
        3. 将所有修正项按趋势/超买超卖/资金面/基本面/其他分组
        4. 组内矛盾信号互斥（取绝对值最大），同向信号求和但受组预算约束
        5. 各组 clamp 后求和，一次性加到 base_score 并 clamp [0, 100]
        6. 仅调用一次 update_buy_signal
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
                   'p3_resonance', 'p4_capital_flow', 'p5c_lhb', 'p5c_dzjy', 'p5c_holder',
                   'market_sentiment_adj', 'volume_spike_trap', 'divergence_adj',
                   'support_strength', 'kdj_weekly_bonus', 'concept_decay']

        # === Beta 系数调整 ===
        beta = getattr(result, 'beta_vs_index', 1.0) or 1.0
        is_bear = 'bear_market_cap' in result.score_breakdown
        beta_adj = 0
        if beta > 1.5 and is_bear:
            beta_adj = max(-5, round(-(beta - 1.5) * 5, 0))
        elif beta > 1.3 and is_bear:
            beta_adj = -2
        elif beta < 0.6:
            beta_adj = min(4, round((0.6 - beta) * 8, 0))
        if beta_adj != 0:
            result.score_breakdown['beta_adj'] = int(beta_adj)

        # 单因子 clamp ±8
        SINGLE_ADJ_CAP = 8
        for k in adj_keys:
            v = result.score_breakdown.get(k, 0)
            if v != 0:
                cv = max(-SINGLE_ADJ_CAP, min(SINGLE_ADJ_CAP, v))
                if cv != v:
                    result.score_breakdown[k] = cv

        # --- 分组互斥 + 组预算 ---
        GROUP_BUDGETS: Dict[str, int] = {
            'trend': 12,
            'oscillator': 12,
            'capital': 10,
            'fundamental': 8,
            'other': 5,
        }

        def _classify(key: str) -> str:
            kl = key.lower()
            if any(t in kl for t in ['macd', 'adx', 'weekly', 'trend', 'resonance',
                                      'multi_timeframe', 'timeframe', 'ma_', 'ema',
                                      'chart_pattern', 'divergence', 'candle_pattern',
                                      'support_strength', 'fib_']):
                return 'trend'
            if any(t in kl for t in ['rsi', 'kdj', 'boll', 'oversold', 'overbought',
                                      'sentiment_extreme']):
                return 'oscillator'
            if any(t in kl for t in ['capital', 'north', 'lhb', 'dzjy', 'holder',
                                      'insider', 'fund_flow', 'p4_capital', 'p5c_']):
                return 'capital'
            if any(t in kl for t in ['valuation', 'fundamental', 'earning', 'profit',
                                      'pe_', 'pb_', 'forecast']):
                return 'fundamental'
            return 'other'

        groups: Dict[str, list] = defaultdict(list)
        raw_total = 0
        for k in adj_keys:
            v = result.score_breakdown.get(k, 0)
            if v != 0:
                groups[_classify(k)].append(v)
                raw_total += v

        capped_total = 0
        for group_name, values in groups.items():
            budget = GROUP_BUDGETS.get(group_name, 5)
            positives = [v for v in values if v > 0]
            negatives = [v for v in values if v < 0]

            if positives and negatives:
                max_pos = max(positives)
                min_neg = min(negatives)
                group_adj = max_pos if max_pos >= abs(min_neg) else min_neg
            else:
                group_adj = sum(values)

            group_adj = max(-budget, min(budget, group_adj))
            capped_total += group_adj

        if capped_total != raw_total:
            result.score_breakdown['adj_cap'] = capped_total - raw_total

        result.signal_score = max(0, min(100, result.signal_score + capped_total))
        ScoringBase.update_buy_signal(result)
    

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
    
    # ---- 市场情绪温度（已迁移至 market_sentiment.get_market_sentiment_cached）----
    _sentiment_cache: dict = {'data': None, 'ts': 0.0}


    @staticmethod
    def update_buy_signal(result: TrendAnalysisResult):
        """根据 signal_score 重新判定 buy_signal 等级（7档精细分级）
        
        阈值校准依据（2026-03，7353条回测 + 495条真实记录）:
        - 60-74分：纯量化平均5日收益 -0.10%~+0.24%，无统计优势，归为持有
        - 75-77分：真实系统谨慎买入5日胜率21.4%，avg-1.02%，负期望，改为持有
        - 78-84分：avg5d +0.78%，具备操作价值，给买入
        - 85-94分：avg5d +0.80%，真实系统对应 +5%，维持强烈买入
        - 95+分：最高置信度信号，维持激进买入
        
        弱共振降级规则（2026-03，回测支撑）:
        - 弱共振+周线非多头/弱多头：5日胜率46.8%，avg-0.36%，降一级
        - 弱共振+周线多头/弱多头：5日胜率71.9%，avg+4.36%，不降级
        
        KDJ+周线组合加分规则（2026-03，回测支撑，在calculate_base_score中执行）:
        - 超卖金叉+多头周线：+8分（20日胜率84.6%，avg+3.57%）
        - 超卖金叉+弱多头周线：+5分（20日胜率69.2%，avg+2.55%）
        - 普通金叉+多头周线：+3分（20日胜率60%，avg+4.21%）
        """
        score = result.signal_score
        
        if score >= 95:
            result.buy_signal = BuySignal.AGGRESSIVE_BUY
        elif score >= 85:
            result.buy_signal = BuySignal.STRONG_BUY
        elif score >= 78:
            result.buy_signal = BuySignal.BUY
        elif score >= 55:
            result.buy_signal = BuySignal.HOLD
        elif score >= 35:
            result.buy_signal = BuySignal.REDUCE
        else:
            result.buy_signal = BuySignal.SELL
        
        # 弱共振+非多头周线 → 降级（回测数据支撑，2026-03）
        # 85-89分+弱共振+震荡：5日胜率41.7%，avg-0.76%，降两级→HOLD
        # 78-84分+弱共振+震荡：5日胜率46.8%，avg-0.36%，降一级→HOLD
        resonance = getattr(result, 'resonance_level', '') or ''
        weekly_val = str(getattr(result, 'weekly_trend', '') or '')
        score = result.signal_score or 0
        is_bull_weekly = any(kw in weekly_val for kw in ('多头', '弱多头'))
        if '弱共振' in resonance and not is_bull_weekly:
            if score >= 85:
                # 85+分弱共振+非多头：负期望，直接降至HOLD
                _DOWNGRADE = {
                    BuySignal.AGGRESSIVE_BUY: BuySignal.HOLD,
                    BuySignal.STRONG_BUY: BuySignal.HOLD,
                    BuySignal.BUY: BuySignal.HOLD,
                }
            else:
                # 78-84分弱共振+非多头：降一级
                _DOWNGRADE = {
                    BuySignal.AGGRESSIVE_BUY: BuySignal.STRONG_BUY,
                    BuySignal.STRONG_BUY: BuySignal.BUY,
                    BuySignal.BUY: BuySignal.HOLD,
                }
            result.buy_signal = _DOWNGRADE.get(result.buy_signal, result.buy_signal)
        
        # 信号分歧+非多头周线+78+分 → 降至HOLD（回测数据支撑，2026-03）
        # 信号分歧+多头周线：胜率52.1%，avg+0.94%，保留
        # 信号分歧+非多头：胜率37-42%，avg-0.3%~-3.3%，负/低期望，降为HOLD
        if '信号分歧' in resonance and not is_bull_weekly and score >= 78:
            _DIVERGENCE_DOWNGRADE = {
                BuySignal.AGGRESSIVE_BUY: BuySignal.HOLD,
                BuySignal.STRONG_BUY: BuySignal.HOLD,
                BuySignal.BUY: BuySignal.HOLD,
            }
            result.buy_signal = _DIVERGENCE_DOWNGRADE.get(result.buy_signal, result.buy_signal)
        
        # 中度共振做多+非多头周线+78+分 → 降至HOLD（回测数据支撑，2026-03）
        # 中度共振做多+多头周线：胜率50-56%，avg+0.57%~+1.4%，保留
        # 中度共振做多+非多头：85-89分胜率21.7%，avg-0.79%；78-84分胜率39.4%，avg-0.31%，均负期望
        if '中度共振做多' in resonance and not is_bull_weekly and score >= 78:
            _MED_RESONANCE_DOWNGRADE = {
                BuySignal.AGGRESSIVE_BUY: BuySignal.HOLD,
                BuySignal.STRONG_BUY: BuySignal.HOLD,
                BuySignal.BUY: BuySignal.HOLD,
            }
            result.buy_signal = _MED_RESONANCE_DOWNGRADE.get(result.buy_signal, result.buy_signal)

