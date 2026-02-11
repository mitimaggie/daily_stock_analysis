# -*- coding: utf-8 -*-
"""
持仓管理视图模块 (改进5)

散户需要的组合层面分析：
- 板块集中度分析
- 整体风险敞口（Beta加权）
- 总仓位建议
- 个股优先级排序（加仓/减仓建议）
- 相关性风险提示
"""

import logging
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class PortfolioStock:
    """组合中的单只股票"""
    code: str
    name: str
    score: int = 50
    advice: str = ""
    sector: str = ""
    position_pct: int = 0  # 建议仓位%
    beta: float = 1.0
    price: float = 0.0
    change_pct: float = 0.0
    decision_type: str = "hold"  # buy/hold/sell


@dataclass
class PortfolioReport:
    """组合分析报告"""
    total_stocks: int = 0
    # 板块分布
    sector_distribution: Dict[str, List[str]] = field(default_factory=dict)
    sector_concentration_warning: str = ""
    # 方向分布
    buy_count: int = 0
    hold_count: int = 0
    sell_count: int = 0
    direction_warning: str = ""
    # 总仓位
    total_suggested_position: int = 0
    position_warning: str = ""
    # 加权Beta
    weighted_beta: float = 1.0
    beta_warning: str = ""
    # 优先级排序
    priority_buy: List[str] = field(default_factory=list)   # 最值得买入的
    priority_sell: List[str] = field(default_factory=list)   # 最应该卖出的
    priority_hold: List[str] = field(default_factory=list)   # 持有观望的
    # 综合建议
    overall_advice: str = ""
    # 风险告警
    risk_warnings: List[str] = field(default_factory=list)


class PortfolioAnalyzer:
    """
    组合分析器：从整体视角审视持仓
    """

    @staticmethod
    def analyze(results: List[Any], portfolio_size: float = 0) -> PortfolioReport:
        """
        分析股票组合，生成组合报告
        
        Args:
            results: AnalysisResult 列表
            portfolio_size: 总资金（元），0=未配置
            
        Returns:
            PortfolioReport
        """
        report = PortfolioReport(total_stocks=len(results))
        if not results:
            return report

        stocks = []
        for r in results:
            stock = PortfolioStock(
                code=getattr(r, 'code', ''),
                name=getattr(r, 'name', ''),
                score=getattr(r, 'sentiment_score', 50),
                advice=getattr(r, 'operation_advice', ''),
                decision_type=getattr(r, 'decision_type', 'hold'),
                price=getattr(r, 'current_price', 0),
            )
            # 提取板块信息
            dashboard = getattr(r, 'dashboard', {}) or {}
            quant = dashboard.get('quant_extras', {}) or {}
            stock.sector = quant.get('sector_name', '')
            stock.position_pct = quant.get('suggested_position_pct', 0) or 0
            stock.beta = quant.get('beta_vs_index', 1.0) or 1.0
            # change_pct
            snap = getattr(r, 'market_snapshot', {}) or {}
            stock.change_pct = snap.get('change_pct', 0) or 0
            stocks.append(stock)

        # === 1. 板块集中度 ===
        sector_map: Dict[str, List[str]] = {}
        for s in stocks:
            if s.sector:
                sector_map.setdefault(s.sector, []).append(f"{s.name}({s.code})")
        report.sector_distribution = sector_map

        for sector, names in sector_map.items():
            ratio = len(names) / len(stocks) * 100
            if ratio >= 50 and len(names) >= 2:
                report.sector_concentration_warning = (
                    f"⚠️ {sector}板块占比{ratio:.0f}%（{', '.join(names)}），"
                    f"建议分散至不同行业"
                )
                report.risk_warnings.append(report.sector_concentration_warning)

        # === 2. 方向分布 ===
        report.buy_count = sum(1 for s in stocks if s.decision_type == 'buy')
        report.hold_count = sum(1 for s in stocks if s.decision_type == 'hold')
        report.sell_count = sum(1 for s in stocks if s.decision_type == 'sell')

        if report.buy_count == len(stocks) and len(stocks) >= 3:
            report.direction_warning = f"⚠️ 全部{len(stocks)}只均看多，警惕系统性风险"
            report.risk_warnings.append(report.direction_warning)
        elif report.sell_count == len(stocks) and len(stocks) >= 3:
            report.direction_warning = f"💡 全部{len(stocks)}只均看空，市场可能处于弱势"
            report.risk_warnings.append(report.direction_warning)

        # === 3. 总仓位 ===
        report.total_suggested_position = sum(s.position_pct for s in stocks)
        if report.total_suggested_position > 80:
            report.position_warning = (
                f"⚠️ 建议总仓位{report.total_suggested_position}%超过80%上限，"
                f"请降低部分个股仓位"
            )
            report.risk_warnings.append(report.position_warning)

        # === 4. 加权Beta ===
        total_pos = sum(s.position_pct for s in stocks) or 1
        report.weighted_beta = round(
            sum(s.beta * s.position_pct for s in stocks) / total_pos, 2
        )
        if report.weighted_beta > 1.5:
            report.beta_warning = f"⚠️ 组合Beta={report.weighted_beta}，波动高于大盘50%，注意风险"
            report.risk_warnings.append(report.beta_warning)
        elif report.weighted_beta < 0.5:
            report.beta_warning = f"💡 组合Beta={report.weighted_beta}，防御性较强"

        # === 5. 优先级排序 ===
        sorted_stocks = sorted(stocks, key=lambda s: s.score, reverse=True)
        for s in sorted_stocks:
            label = f"{s.name}({s.score}分)"
            if s.decision_type == 'buy' and s.score >= 70:
                report.priority_buy.append(label)
            elif s.decision_type == 'sell' or s.score < 35:
                report.priority_sell.append(label)
            else:
                report.priority_hold.append(label)

        # === 6. 综合建议 ===
        if report.buy_count > report.sell_count and not report.risk_warnings:
            report.overall_advice = "📈 组合整体偏多，风险可控"
        elif report.sell_count > report.buy_count:
            report.overall_advice = "📉 组合整体偏空，建议降低仓位"
        elif report.risk_warnings:
            report.overall_advice = f"⚠️ 组合存在{len(report.risk_warnings)}个风险点，请关注"
        else:
            report.overall_advice = "📊 组合中性，观望为主"

        return report

    @staticmethod
    def format_report(report: PortfolioReport, portfolio_size: float = 0) -> str:
        """格式化组合报告为文本"""
        lines = [
            "━" * 50,
            "📋 持仓组合分析报告",
            "━" * 50,
            f"📊 总览: {report.total_stocks}只股票 | "
            f"看多{report.buy_count} 观望{report.hold_count} 看空{report.sell_count}",
            f"💰 建议总仓位: {report.total_suggested_position}%",
            f"📈 组合Beta: {report.weighted_beta}",
        ]

        if portfolio_size > 0:
            invested = portfolio_size * report.total_suggested_position / 100
            lines.append(f"💵 建议投入: {invested/10000:.1f}万 / 总资金{portfolio_size/10000:.1f}万")

        lines.append(f"\n{report.overall_advice}")

        if report.priority_buy:
            lines.append(f"\n🟢 优先买入: {', '.join(report.priority_buy)}")
        if report.priority_sell:
            lines.append(f"🔴 建议离场: {', '.join(report.priority_sell)}")
        if report.priority_hold:
            lines.append(f"🟡 持有观望: {', '.join(report.priority_hold)}")

        if report.sector_distribution:
            lines.append("\n📦 板块分布:")
            for sector, names in report.sector_distribution.items():
                lines.append(f"  · {sector}: {', '.join(names)}")

        if report.risk_warnings:
            lines.append("\n⚠️ 风险告警:")
            for w in report.risk_warnings:
                lines.append(f"  {w}")

        lines.append("━" * 50)
        return "\n".join(lines)
