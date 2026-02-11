# -*- coding: utf-8 -*-
"""
优化的股票分析报告模板
更便于阅读和快速决策
"""

from typing import List, Dict
from .types import TrendAnalysisResult, BuySignal


class ReportTemplate:
    """优化的报告模板生成器"""
    
    @staticmethod
    def generate_quick_decision(result: TrendAnalysisResult) -> str:
        """
        生成一句话快速决策
        
        Returns:
            快速决策文本
        """
        signal_icons = {
            BuySignal.AGGRESSIVE_BUY: "🔥",
            BuySignal.STRONG_BUY: "✅",
            BuySignal.BUY: "👍",
            BuySignal.CAUTIOUS_BUY: "🤔",
            BuySignal.HOLD: "⏸️",
            BuySignal.REDUCE: "⬇️",
            BuySignal.SELL: "❌",
        }
        
        icon = signal_icons.get(result.buy_signal, "❓")
        signal_text = result.buy_signal.value
        
        if result.trading_halt:
            return f"🚨 {signal_text}：{result.trading_halt_reason}"
        
        if result.buy_signal in [BuySignal.AGGRESSIVE_BUY, BuySignal.STRONG_BUY, BuySignal.BUY]:
            return f"{icon} {signal_text}：{result.advice_for_empty}（评分{result.signal_score}/100）"
        elif result.buy_signal == BuySignal.CAUTIOUS_BUY:
            return f"{icon} {signal_text}：{result.advice_for_empty}（评分{result.signal_score}/100）"
        elif result.buy_signal == BuySignal.HOLD:
            return f"{icon} {signal_text}：{result.advice_for_holding}（评分{result.signal_score}/100）"
        else:
            return f"{icon} {signal_text}：{result.advice_for_holding}（评分{result.signal_score}/100）"
    
    @staticmethod
    def generate_visual_score(score: int) -> str:
        """生成可视化评分条"""
        filled = int(score / 10)
        empty = 10 - filled
        bar = "█" * filled + "░" * empty
        
        if score >= 85:
            color = "🟢"
        elif score >= 70:
            color = "🟡"
        elif score >= 50:
            color = "🟠"
        else:
            color = "🔴"
        
        return f"{color} {score}/100 {bar}"
    
    @staticmethod
    def generate_risk_level(result: TrendAnalysisResult) -> str:
        """生成风险等级可视化"""
        risk_factors = []
        
        if result.volatility_20d > 60:
            risk_factors.append("高波动")
        if result.max_drawdown_60d < -30:
            risk_factors.append("大回撤")
        if result.beta_vs_index > 1.5:
            risk_factors.append("高Beta")
        if result.week52_position > 90:
            risk_factors.append("52周高位")
        
        risk_count = len(risk_factors)
        
        if risk_count >= 3:
            return f"🔴 高风险 ⚠️⚠️⚠️ ({', '.join(risk_factors)})"
        elif risk_count == 2:
            return f"🟠 中高风险 ⚠️⚠️ ({', '.join(risk_factors)})"
        elif risk_count == 1:
            return f"🟡 中等风险 ⚠️ ({', '.join(risk_factors)})"
        else:
            return "🟢 风险可控 ✓"
    
    @staticmethod
    def generate_operation_anchors(result: TrendAnalysisResult) -> str:
        """生成操作锚点卡片"""
        return f"""
╔══════════════════════════════════════════════════════════════════╗
║ 🎯 操作锚点（量化硬规则，不可覆盖）                               ║
╠══════════════════════════════════════════════════════════════════╣
║ 💰 理想买点：{result.ideal_buy_anchor:.2f}元 (MA5/MA10支撑)                      ║
║ 🛡️ 止损线：                                                       ║
║    · 日内止损：{result.stop_loss_intraday:.2f}元 (0.7×ATR)                        ║
║    · 短线止损：{result.stop_loss_short:.2f}元 (1.0×ATR) 🔴 破位立刻离场            ║
║    · 中线止损：{result.stop_loss_mid:.2f}元 (1.5×ATR+MA20)                        ║
║ 🎯 目标价位：                                                      ║
║    · 短线目标：{result.take_profit_short:.2f}元 (1/3仓位止盈)                      ║
║    · 中线目标：{result.take_profit_mid:.2f}元 (1/3仓位止盈)                        ║
║    · 移动止盈：{result.take_profit_trailing:.2f}元 (底仓跟踪)                      ║
║ 📊 建议仓位：{result.suggested_position_pct}% (根据风险收益比{result.risk_reward_ratio:.1f}:1)       ║
╚══════════════════════════════════════════════════════════════════╝
"""
    
    @staticmethod
    def generate_enhanced_report(result: TrendAnalysisResult) -> str:
        """
        生成增强版分析报告
        
        特点：
        1. 快速决策区前置
        2. 可视化评分和风险
        3. 操作锚点突出
        4. 分层信息展示
        """
        quick_decision = ReportTemplate.generate_quick_decision(result)
        visual_score = ReportTemplate.generate_visual_score(result.signal_score)
        risk_level = ReportTemplate.generate_risk_level(result)
        operation_anchors = ReportTemplate.generate_operation_anchors(result)
        
        warning_block = ""
        if result.trading_halt:
            warning_block = f"""
╔══════════════════════════════════════════════════════════════════╗
║ 🚨 交易暂停警告                                                   ║
╠══════════════════════════════════════════════════════════════════╣
║ {result.trading_halt_reason:<64} ║
╚══════════════════════════════════════════════════════════════════╝
"""
        
        resonance_block = ""
        if result.indicator_resonance:
            resonance_block = f"""
【🔔 指标共振信号】
{result.indicator_resonance}
"""
        
        behavior_block = ""
        if result.market_behavior:
            behavior_block = f"""
【🧠 市场行为识别】
{result.market_behavior}
"""
        
        timeframe_block = ""
        if result.timeframe_resonance:
            timeframe_block = f"""
【📅 多周期共振】
{result.timeframe_resonance}
"""
        
        multidim_block = ""
        multidim_items = []
        if result.valuation_verdict:
            multidim_items.append(f"💎 估值：{result.valuation_verdict} (PE={result.pe_ratio:.1f}, PB={result.pb_ratio:.2f})")
        if result.capital_flow_signal and result.capital_flow_signal != "资金面数据正常":
            multidim_items.append(f"💰 资金：{result.capital_flow_signal} ({result.capital_flow_score}/10)")
        if result.sector_name:
            multidim_items.append(f"🏢 板块：{result.sector_signal} ({result.sector_score}/10)")
        if result.chip_signal and result.chip_signal != "筹码分布正常":
            multidim_items.append(f"💎 筹码：{result.chip_signal} ({result.chip_score}/10)")
        if result.fundamental_signal and result.fundamental_signal != "基本面数据正常":
            multidim_items.append(f"📈 基本面：{result.fundamental_signal} ({result.fundamental_score}/10)")
        
        if multidim_items:
            multidim_block = "\n【🎯 多维度分析】\n" + "\n".join(multidim_items) + "\n"
        
        return f"""
{'='*70}
【{result.code}】股票分析报告
{'='*70}

💡 快速决策
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{quick_decision}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📊 综合评估
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
· 综合评分：{visual_score}
· 信号等级：{result.buy_signal.value}
· 风险等级：{risk_level}
· 趋势状态：{result.trend_status.value} (强度{result.trend_strength}/100)
· 现价：{result.current_price:.2f}元 | MA5乖离{result.bias_ma5:+.1f}%
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{warning_block}
{operation_anchors}
{resonance_block}{behavior_block}{timeframe_block}{multidim_block}
📋 详细建议
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
👤 空仓者：{result.advice_for_empty}
👥 持仓者：{result.advice_for_holding}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

💡 散户白话版
{result.beginner_summary}

{'='*70}
"""
    
    @staticmethod
    def generate_dashboard(results: List[TrendAnalysisResult]) -> str:
        """
        生成决策仪表盘（优先级排序）
        
        Args:
            results: 多只股票的分析结果列表
            
        Returns:
            仪表盘文本
        """
        aggressive_buy = []
        strong_buy = []
        buy = []
        cautious_buy = []
        hold = []
        reduce = []
        sell = []
        halted = []
        
        for r in results:
            item = f"{r.code}({r.signal_score})"
            if r.trading_halt:
                halted.append(f"🚨{item}")
            elif r.buy_signal == BuySignal.AGGRESSIVE_BUY:
                aggressive_buy.append(f"🔥{item}")
            elif r.buy_signal == BuySignal.STRONG_BUY:
                strong_buy.append(f"✅{item}")
            elif r.buy_signal == BuySignal.BUY:
                buy.append(f"👍{item}")
            elif r.buy_signal == BuySignal.CAUTIOUS_BUY:
                cautious_buy.append(f"🤔{item}")
            elif r.buy_signal == BuySignal.HOLD:
                hold.append(f"⏸️{item}")
            elif r.buy_signal == BuySignal.REDUCE:
                reduce.append(f"⬇️{item}")
            elif r.buy_signal == BuySignal.SELL:
                sell.append(f"❌{item}")
        
        dashboard = f"""
╔══════════════════════════════════════════════════════════════════╗
║ 🎯 决策仪表盘 - {len(results)}只股票分析汇总                              ║
╠══════════════════════════════════════════════════════════════════╣
"""
        
        if halted:
            dashboard += f"║ 🚨 交易暂停：{', '.join(halted):<50} ║\n"
            dashboard += f"╠══════════════════════════════════════════════════════════════════╣\n"
        
        dashboard += f"║ 🔥 激进买入：{', '.join(aggressive_buy) if aggressive_buy else '无':<50} ║\n"
        dashboard += f"║ ✅ 强烈买入：{', '.join(strong_buy) if strong_buy else '无':<50} ║\n"
        dashboard += f"║ 👍 适度买入：{', '.join(buy) if buy else '无':<50} ║\n"
        dashboard += f"║ 🤔 谨慎买入：{', '.join(cautious_buy) if cautious_buy else '无':<50} ║\n"
        dashboard += f"║ ⏸️ 持股观望：{', '.join(hold) if hold else '无':<50} ║\n"
        dashboard += f"║ ⬇️ 减仓观望：{', '.join(reduce) if reduce else '无':<50} ║\n"
        dashboard += f"║ ❌ 建议离场：{', '.join(sell) if sell else '无':<50} ║\n"
        dashboard += f"╚══════════════════════════════════════════════════════════════════╝\n"
        
        return dashboard
