# -*- coding: utf-8 -*-
"""
格式化输出模块
包含分析结果的格式化输出、白话版解读生成等
"""

import logging
from .types import TrendAnalysisResult

logger = logging.getLogger(__name__)


class AnalysisFormatter:
    """分析结果格式化器"""
    
    # 多维修正因子中文映射（供评分明细格式化复用）
    ADJ_MAP = {
        'valuation_adj': '估值', 'capital_flow_adj': '资金', 'cf_trend': '资金趋势',
        'cf_continuity': '资金连续', 'cross_resonance': '跨维共振',
        'sector_adj': '板块', 'chip_adj': '筹码', 'fundamental_adj': '基本面',
        'week52_risk': '52周高位', 'week52_opp': '52周低位', 'liquidity_risk': '流动性',
        'limit_adj': '涨跌停', 'limit_risk': '连板风险', 'vp_divergence': '量价背离',
        'vwap_adj': 'VWAP', 'turnover_adj': '换手率', 'gap_adj': '缺口',
        'vol_extreme': '量能异动', 'vol_trend_3d': '量能趋势',
        'sentiment_extreme': '情绪极端',
    }
    
    @staticmethod
    def format_enhanced(result: TrendAnalysisResult) -> str:
        """
        生成增强版分析报告（更易读、更便于决策）
        
        特点：
        - 快速决策区前置
        - 可视化评分条和风险等级
        - 操作锚点突出显示
        - 分层信息展示
        """
        from .report_template import ReportTemplate
        return ReportTemplate.generate_enhanced_report(result)
    
    @staticmethod
    def format_for_llm(result: TrendAnalysisResult) -> str:
        """
        生成精简版技术摘要（供 LLM prompt 使用）
        
        LLM 不需要完整的量化报告，只需要关键信号和硬规则锚点。
        """
        breakdown = result.score_breakdown
        bd_str = ""
        if breakdown:
            base = "+".join(f"{k}{v}" for k in ['trend','bias','volume','support','macd','rsi','kdj'] if (v := breakdown.get(k)) is not None)
            adj = " ".join(f"{label}{v:+d}" for key, label in AnalysisFormatter.ADJ_MAP.items() if (v := breakdown.get(key, 0)) != 0)
            bd_str = f" ({base}{' | ' + adj if adj else ''})"

        lines = [
            f"评分={result.signal_score}{bd_str} 信号={result.buy_signal.value}",
            f"趋势={result.trend_status.value}(强度{result.trend_strength:.0f}) 均线={result.ma_alignment}",
            f"MACD={result.macd_status.value} KDJ={result.kdj_status.value} RSI={result.rsi_status.value}(RSI6={result.rsi_6:.0f} RSI12={result.rsi_12:.0f} RSI24={result.rsi_24:.0f})",
            f"量能={result.volume_status.value} 量比={result.volume_ratio:.2f}",
            f"现价={result.current_price:.2f} 乖离MA5={result.bias_ma5:.1f}% MA20={result.bias_ma20:.1f}%",
        ]
        # 新增指标
        if result.vwap > 0:
            lines.append(f"VWAP={result.vwap:.2f} 偏离={result.vwap_bias:+.1f}%")
        if result.is_limit_up:
            lines.append(f"🟢涨停板（连{result.consecutive_limits}板）" if result.consecutive_limits >= 2 else "🟢涨停封板")
        elif result.is_limit_down:
            lines.append("🔴跌停板")
        if result.volume_price_divergence:
            lines.append(f"⚠️{result.volume_price_divergence}")
        if result.gap_type:
            lines.append(f"缺口={result.gap_type}")
        if result.rsi_divergence:
            lines.append(f"⚠️背离={result.rsi_divergence}")
        if result.kdj_divergence:
            lines.append(f"⚠️KDJ背离={result.kdj_divergence}")
        if result.kdj_passivation:
            lines.append("KDJ钝化中，超买/超卖信号不可靠")
        if result.kdj_consecutive_extreme:
            lines.append(f"⚠️{result.kdj_consecutive_extreme}")
        if result.resonance_signals:
            lines.append(f"共振={abs(result.resonance_count)}个: {','.join(result.resonance_signals)}")
        if result.indicator_resonance:
            lines.append(f"指标共振: {result.indicator_resonance.replace(chr(10), '; ')}")
        if result.market_behavior:
            lines.append(f"市场行为: {result.market_behavior.replace(chr(10), '; ')}")
        if result.timeframe_resonance:
            lines.append(f"多周期: {result.timeframe_resonance.replace(chr(10), '; ')}")
        if hasattr(result, '_conflict_warnings') and result._conflict_warnings:
            lines.append(f"⚠️信号冲突: {'; '.join(result._conflict_warnings)}")
        if result.valuation_verdict:
            lines.append(f"估值: PE={result.pe_ratio:.1f} PB={result.pb_ratio:.2f} {result.valuation_verdict} 降档={result.valuation_downgrade}")
        if result.trading_halt:
            lines.append(f"🚨暂停交易: {result.trading_halt_reason}")
        if result.capital_flow_signal and result.capital_flow_signal != "资金面数据正常":
            lines.append(f"资金面({result.capital_flow_score}/10): {result.capital_flow_signal}")
        if result.sector_name:
            lines.append(f"板块({result.sector_score}/10): {result.sector_signal}")
        if result.chip_signal and result.chip_signal != "筹码分布正常":
            lines.append(f"筹码({result.chip_score}/10): {result.chip_signal}")
        if result.fundamental_signal and result.fundamental_signal != "基本面数据正常":
            lines.append(f"基本面({result.fundamental_score}/10): {result.fundamental_signal}")
        
        risk_items = []
        if result.beta_vs_index != 1.0:
            risk_items.append(f"Beta={result.beta_vs_index:.2f}")
        if result.volatility_20d > 0:
            risk_items.append(f"波动率={result.volatility_20d:.0f}%")
        if result.max_drawdown_60d != 0:
            risk_items.append(f"回撤={result.max_drawdown_60d:.1f}%")
        if result.week52_position > 0:
            risk_items.append(f"52周={result.week52_position:.0f}%")
        if risk_items:
            lines.append(f"风险: {' '.join(risk_items)}")
        
        if result.stop_loss_short > 0:
            lines.append(f"止损(短)={result.stop_loss_short:.2f} 止损(中)={result.stop_loss_mid:.2f} 买点={result.ideal_buy_anchor:.2f}")
        if result.take_profit_short > 0:
            lines.append(f"止盈(短)={result.take_profit_short:.2f} 止盈(中)={result.take_profit_mid:.2f} 移动止盈={result.take_profit_trailing:.2f}")
        if result.risk_reward_ratio > 0:
            lines.append(f"R:R={result.risk_reward_ratio:.1f}:1({result.risk_reward_verdict})")
        # P0 风控信号
        if result.no_trade:
            lines.append(f"🚫不交易过滤({result.no_trade_severity}): {'; '.join(result.no_trade_reasons)}")
        if result.stop_loss_breached:
            lines.append(f"🚨止损已触发: {result.stop_loss_breach_detail}")
        if result.volume_extreme:
            lines.append(f"量能异动: {result.volume_extreme}")
        if result.volume_trend_3d:
            lines.append(f"量能趋势: {result.volume_trend_3d}")
        if result.liquidity_warning:
            lines.append(f"流动性: {result.liquidity_warning}")
        # P3 情绪极端
        if result.sentiment_extreme:
            lines.append(f"🎭情绪: {result.sentiment_extreme} | {result.sentiment_extreme_detail}")
        if result.valuation_zone:
            lines.append(f"估值区间: {result.valuation_zone}" + (f" PE历史{result.pe_percentile:.0f}%分位" if result.pe_percentile >= 0 else ""))
        if result.margin_trend:
            lines.append(f"融资趋势: {result.margin_trend}({result.margin_trend_days}日)")
        lines.append(f"仓位={result.suggested_position_pct}%")
        lines.append(f"空仓建议: {result.advice_for_empty}")
        lines.append(f"持仓建议: {result.advice_for_holding}")
        return "\n".join(lines)
    
    @staticmethod
    def format_analysis(result: TrendAnalysisResult) -> str:
        """生成完整的技术分析报告"""
        breakdown = result.score_breakdown
        breakdown_str = ""
        if breakdown:
            base_parts = []
            for k in ['trend', 'bias', 'volume', 'support', 'macd', 'rsi', 'kdj']:
                if k in breakdown:
                    base_parts.append(f"{k}{breakdown[k]}")
            base_str = "+".join(base_parts) if base_parts else ""
            
            adj_parts = []
            for key, label in AnalysisFormatter.ADJ_MAP.items():
                v = breakdown.get(key, 0)
                if v != 0:
                    adj_parts.append(f"{label}{v:+d}")
            adj_str = " ".join(adj_parts) if adj_parts else ""
            breakdown_str = f" ({base_str}{' | ' + adj_str if adj_str else ''})"

        levels_str = ""
        if result.support_levels or result.resistance_levels:
            sup = ",".join(f"{x:.2f}" for x in result.support_levels[:3]) if result.support_levels else "无"
            res = ",".join(f"{x:.2f}" for x in result.resistance_levels[:3]) if result.resistance_levels else "无"
            levels_str = f"\n【支撑/阻力】支撑: {sup} | 阻力: {res}"

        anchor_line = ""
        if result.stop_loss_short > 0 or result.ideal_buy_anchor > 0:
            tp_line = ""
            if result.take_profit_short > 0:
                tp_line = f"""
● 止盈(短线): {result.take_profit_short:.2f} (1.5*ATR)
● 止盈(中线): {result.take_profit_mid:.2f} ({'第一阻力位' if result.resistance_levels else '2.5*ATR'})
● 移动止盈: {result.take_profit_trailing:.2f} (近20日高点-1.2*ATR)
● 分批方案: {result.take_profit_plan}"""
            rr_line = ""
            if result.risk_reward_ratio > 0:
                rr_line = f"\n● 风险收益比: {result.risk_reward_ratio:.1f}:1 ({result.risk_reward_verdict})"
            anchor_line = f"""
【量化锚点 (硬规则，LLM 不得覆盖)】
● 止损(日内): {result.stop_loss_intraday:.2f} (0.7*ATR)
● 止损(短线): {result.stop_loss_short:.2f} (1.0*ATR)
● 止损(中线): {result.stop_loss_mid:.2f} (1.5*ATR+MA20){tp_line}{rr_line}
● 理想买点: {result.ideal_buy_anchor:.2f} (MA5/MA10 支撑)
● ATR14: {result.atr14:.2f} | MA60: {result.ma60:.2f}
● 建议仓位: {result.suggested_position_pct}%"""

        bb_str = ""
        if result.bb_upper > 0:
            bb_str = f"\n● 布林带: 上轨{result.bb_upper:.2f} 下轨{result.bb_lower:.2f} | 带宽{result.bb_width:.4f} | %B={result.bb_pct_b:.2f}"

        risk_str = ""
        risk_parts = []
        if result.volatility_20d > 0:
            risk_parts.append(f"20日年化波动率{result.volatility_20d:.1f}%")
        if result.beta_vs_index != 1.0:
            risk_parts.append(f"Beta={result.beta_vs_index:.2f}")
        if result.max_drawdown_60d != 0:
            risk_parts.append(f"60日最大回撤{result.max_drawdown_60d:.1f}%")
        if result.week52_position > 0:
            risk_parts.append(f"52周位置{result.week52_position:.0f}%")
        if risk_parts:
            risk_str = "\n● 风险: " + " | ".join(risk_parts)

        val_str = ""
        if result.pe_ratio > 0:
            val_str = f"\n● 估值: PE={result.pe_ratio:.1f} PB={result.pb_ratio:.2f}"
            if result.peg_ratio > 0:
                val_str += f" PEG={result.peg_ratio:.2f}"
            val_str += f" | {result.valuation_verdict}"
            if result.valuation_downgrade < 0:
                val_str += f" (降档{result.valuation_downgrade}分)"

        cf_str = ""
        if result.capital_flow_signal:
            cf_str = f"\n● 资金面: {result.capital_flow_signal} (评分{result.capital_flow_score}/10)"

        sector_str = ""
        if result.sector_name:
            sector_str = f"\n● 板块: {result.sector_signal} (评分{result.sector_score}/10)"

        chip_str = ""
        if result.chip_signal and result.chip_signal != "筹码分布正常":
            chip_str = f"\n● 筹码: {result.chip_signal} (评分{result.chip_score}/10)"

        fund_str = ""
        if result.fundamental_signal and result.fundamental_signal != "基本面数据正常":
            fund_str = f"\n● 基本面: {result.fundamental_signal} (评分{result.fundamental_score}/10)"

        halt_str = ""
        if result.trading_halt:
            halt_str = f"\n🚨【交易暂停】{result.trading_halt_reason}"

        # === 利多/利空信号分组 ===
        bullish_factors = []
        bearish_factors = []
        
        if result.signal_reasons:
            bullish_factors.extend(result.signal_reasons)
        if result.risk_factors:
            bearish_factors.extend(result.risk_factors)
        
        # 从指标状态中提取利多/利空
        from .types import TrendStatus, MACDStatus, KDJStatus, RSIStatus, VolumeStatus
        if result.trend_status in [TrendStatus.STRONG_BULL, TrendStatus.BULL]:
            bullish_factors.append(f"趋势: {result.ma_alignment}")
        elif result.trend_status in [TrendStatus.STRONG_BEAR, TrendStatus.BEAR]:
            bearish_factors.append(f"趋势: {result.ma_alignment}")
        if result.macd_status in [MACDStatus.GOLDEN_CROSS_ZERO, MACDStatus.GOLDEN_CROSS]:
            bullish_factors.append(f"MACD: {result.macd_signal}")
        elif result.macd_status in [MACDStatus.DEATH_CROSS, MACDStatus.CROSSING_DOWN]:
            bearish_factors.append(f"MACD: {result.macd_signal}")
        if result.rsi_divergence == "底背离":
            bullish_factors.append(f"RSI: {result.rsi_signal}")
        elif result.rsi_divergence == "顶背离":
            bearish_factors.append(f"RSI: {result.rsi_signal}")
        if result.kdj_divergence == "KDJ底背离":
            bullish_factors.append(f"KDJ: {result.kdj_signal}")
        elif result.kdj_divergence == "KDJ顶背离":
            bearish_factors.append(f"KDJ: {result.kdj_signal}")
        if result.volume_price_divergence == "底部量缩企稳":
            bullish_factors.append("量价: 底部量缩企稳，可能筑底")
        elif result.volume_price_divergence == "顶部量价背离":
            bearish_factors.append("量价: 价格新高但量能萎缩")
        
        # 去重
        bullish_factors = list(dict.fromkeys(bullish_factors))
        bearish_factors = list(dict.fromkeys(bearish_factors))
        
        signal_group_str = ""
        if bullish_factors or bearish_factors:
            bull_str = "\n".join(f"  ✅ {f}" for f in bullish_factors[:5]) if bullish_factors else "  无"
            bear_str = "\n".join(f"  ⚠️ {f}" for f in bearish_factors[:5]) if bearish_factors else "  无"
            signal_group_str = f"""
【信号汇总】
📈 利多因素({len(bullish_factors)}):
{bull_str}
📉 利空因素({len(bearish_factors)}):
{bear_str}"""

        kdj_extra = ""
        if result.kdj_divergence:
            kdj_extra += f" ⚠️{result.kdj_divergence}"
        if result.kdj_passivation:
            kdj_extra += " 🔄钝化"
        if result.kdj_consecutive_extreme:
            kdj_extra += f" 🔥{result.kdj_consecutive_extreme}"

        return f"""
【量化技术报告】
---------------------------{halt_str}
● 综合评分: {result.signal_score}{breakdown_str} ({result.buy_signal.value})
● 趋势状态: {result.trend_status.value} (强度{result.trend_strength:.0f}) | {result.ma_alignment}
● 量能: {result.volume_status.value} ({result.volume_trend}) | 量比 {result.volume_ratio:.2f}
● MACD: {result.macd_status.value} ({result.macd_signal}) | DIF={result.macd_dif:.4f} DEA={result.macd_dea:.4f}
● RSI: {result.rsi_status.value} | RSI6={result.rsi_6:.1f} RSI12={result.rsi_12:.1f} RSI24={result.rsi_24:.1f} | {result.rsi_signal}{f' ⚠️{result.rsi_divergence}' if result.rsi_divergence else ''}
● KDJ: {result.kdj_status.value} | K={result.kdj_k:.1f} D={result.kdj_d:.1f} J={result.kdj_j:.1f} | {result.kdj_signal}{kdj_extra}{val_str}{cf_str}{sector_str}{chip_str}{fund_str}
● 关键数据: 现价{result.current_price:.2f} | 乖离MA5={result.bias_ma5:.2f}% MA10={result.bias_ma10:.2f}% MA20={result.bias_ma20:.2f}%{bb_str}{risk_str}{levels_str}
{signal_group_str}
【技术面操作指引 (硬规则)】
👤 针对空仓者: {result.advice_for_empty}
👥 针对持仓者: {result.advice_for_holding}
{anchor_line}
{f'【多指标共振】{abs(result.resonance_count)}个信号同向: {", ".join(result.resonance_signals)} (加分{result.resonance_bonus:+d})' if result.resonance_signals else ''}
{f'【散户白话版】{result.beginner_summary}' if result.beginner_summary else ''}
---------------------------
"""
    
    @staticmethod
    def generate_beginner_summary(result: TrendAnalysisResult):
        """生成白话版解读（通俗易懂的市场解读）"""
        score = result.signal_score
        trend = result.trend_status.value
        macd = result.macd_status.value
        kdj = result.kdj_status.value
        vol = result.volume_status.value
        
        summary_parts = []
        
        if score >= 85:
            summary_parts.append(f"📈 目前技术面非常强势({score}分)")
        elif score >= 70:
            summary_parts.append(f"📊 技术面看好({score}分)")
        elif score >= 60:
            summary_parts.append(f"🤔 技术面偏乐观({score}分)，但需谨慎")
        elif score >= 50:
            summary_parts.append(f"😐 技术面中性({score}分)，观望为主")
        elif score >= 35:
            summary_parts.append(f"📉 技术面偏弱({score}分)，不建议追")
        else:
            summary_parts.append(f"⚠️ 技术面较差({score}分)，建议回避")
        
        if "多头" in trend or "强势" in trend:
            summary_parts.append(f"趋势向上({trend})")
        elif "空头" in trend:
            summary_parts.append(f"趋势向下({trend})")
        else:
            summary_parts.append(f"趋势不明({trend})")
        
        if "金叉" in macd:
            summary_parts.append("MACD金叉向上")
        elif "死叉" in macd:
            summary_parts.append("MACD死叉向下")
        
        if vol == "放量上涨":
            summary_parts.append("放量上涨是好事")
        elif vol == "放量下跌":
            summary_parts.append("放量下跌要小心")
        elif vol == "缩量回调":
            summary_parts.append("缩量回调可能是洗盘")
        
        if result.rsi_divergence == "底背离":
            summary_parts.append("⚠️出现底背离，可能反转向上")
        elif result.rsi_divergence == "顶背离":
            summary_parts.append("⚠️出现顶背离，注意回调风险")
        
        # 新增指标白话版
        if result.is_limit_up:
            if result.consecutive_limits >= 3:
                summary_parts.append(f"🔥连续{result.consecutive_limits}个涨停板，非常强势但追高风险大")
            elif result.consecutive_limits >= 2:
                summary_parts.append(f"🟢连续{result.consecutive_limits}板涨停，短期强势")
            else:
                summary_parts.append("🟢涨停封板，多头强势")
        elif result.is_limit_down:
            summary_parts.append("🔴跌停板，风险极高，不要抄底")
        
        if result.volume_price_divergence == "顶部量价背离":
            summary_parts.append("⚠️价格创新高但成交量在萎缩，上涨可能快到头了")
        elif result.volume_price_divergence == "底部量缩企稳":
            summary_parts.append("💡抛压在减轻，可能正在筑底")
        
        if result.gap_type == "向上跳空":
            summary_parts.append("📈出现向上跳空缺口，短期看多")
        elif result.gap_type == "向下跳空":
            summary_parts.append("📉出现向下跳空缺口，短期风险大")
        
        if result.turnover_percentile > 0.9:
            summary_parts.append("⚠️换手率异常高，市场过热，小心见顶")
        elif result.turnover_percentile < 0.1 and result.turnover_percentile > 0:
            summary_parts.append("💤换手率极低，市场冷清，关注底部信号")

        if result.resonance_count >= 3:
            summary_parts.append(f"多个指标共振({result.resonance_count}个)，信号较强")
        elif result.resonance_count <= -3:
            summary_parts.append(f"多个指标共振向下({abs(result.resonance_count)}个)，注意风险")
        
        # KDJ 增强信号白话版
        if result.kdj_divergence == "KDJ底背离":
            summary_parts.append("⚠️KDJ底背离，价格新低但动能未新低，可能反转向上")
        elif result.kdj_divergence == "KDJ顶背离":
            summary_parts.append("⚠️KDJ顶背离，价格新高但动能跟不上，小心见顶")
        if result.kdj_passivation:
            summary_parts.append("🔄KDJ钝化中，超买/超卖信号不太靠谱，看趋势为主")
        if result.kdj_consecutive_extreme:
            if "超买" in result.kdj_consecutive_extreme:
                summary_parts.append(f"🔥{result.kdj_consecutive_extreme}，短期涨太猛了，回调概率很大")
            else:
                summary_parts.append(f"🔥{result.kdj_consecutive_extreme}，短期跌太狠了，反弹概率很大")
        
        # === 具体操作指引（散户最关心的"到底该怎么做"）===
        if score >= 70 and result.ideal_buy_anchor > 0:
            summary_parts.append(f"👉 操作建议：可以在{result.ideal_buy_anchor:.2f}元附近分批买入，止损设在{result.stop_loss_short:.2f}元")
        elif score >= 60 and result.ideal_buy_anchor > 0:
            summary_parts.append(f"👉 操作建议：轻仓试探，买点{result.ideal_buy_anchor:.2f}元，严格止损{result.stop_loss_short:.2f}元")
        elif score >= 50:
            summary_parts.append("👉 操作建议：观望为主，等技术面更明确再动手")
        elif score >= 35:
            summary_parts.append(f"👉 操作建议：不建议买入，持仓者注意止损{result.stop_loss_mid:.2f}元")
        else:
            summary_parts.append(f"👉 操作建议：远离！持仓者尽快止损离场")
        
        result.beginner_summary = "；".join(summary_parts)
