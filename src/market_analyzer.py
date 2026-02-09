# src/market_analyzer.py
# -*- coding: utf-8 -*-
"""
===================================
大盘复盘分析模块 (宏观策略增强版)
===================================
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Dict, Any, List

from src.config import get_config
from src.search_service import get_search_service
from src.analyzer import get_analyzer

try:
    from data_provider import DataFetcherManager
except ImportError:
    from data_provider.base import DataFetcherManager

logger = logging.getLogger(__name__)

try:
    from data_provider.market_monitor import market_monitor
except ImportError:
    market_monitor = None
    logger.warning("无法导入 data_provider.market_monitor")


@dataclass
class MarketIndex:
    """大盘指数数据"""
    code: str = ""
    name: str = ""
    current: float = 0.0
    change: float = 0.0
    change_pct: float = 0.0
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    prev_close: float = 0.0
    volume: float = 0.0
    amount: float = 0.0
    amplitude: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            'code': self.code, 'name': self.name,
            'current': self.current, 'change': self.change,
            'change_pct': self.change_pct, 'open': self.open,
            'high': self.high, 'low': self.low,
            'volume': self.volume, 'amount': self.amount,
            'amplitude': self.amplitude,
        }


@dataclass
class MarketOverview:
    """市场概览数据结构"""
    date: str
    indices: List[MarketIndex] = field(default_factory=list)
    total_amount: float = 0.0
    top_sectors: List[Dict] = field(default_factory=list)
    bottom_sectors: List[Dict] = field(default_factory=list)

    @property
    def indices_text(self) -> str:
        parts = []
        for idx in self.indices:
            emoji = "🔺" if idx.change_pct > 0 else "💚" if idx.change_pct < 0 else "➖"
            parts.append(f"{idx.name} {emoji} {idx.change_pct}%")
        return " / ".join(parts)

    
class MarketAnalyzer:
    """大盘复盘分析器"""
    
    def __init__(self, search_service=None, analyzer=None):
        self.config = get_config()
        self.search_service = search_service if search_service else get_search_service()
        self.analyzer = analyzer if analyzer else get_analyzer()
        self.data_manager = DataFetcherManager() 

    def run_daily_review(self) -> str:
        """执行每日大盘复盘流程"""
        logger.info("========== 开始大盘复盘分析 ==========")
        overview = self.get_market_overview()
        news = self.search_market_news()
        report = self.generate_market_review(overview, news)
        logger.info("========== 大盘复盘分析完成 ==========")
        return report

    def get_market_overview(self) -> MarketOverview:
        """获取市场概览数据（指数 + 成交额，来自新浪接口，稳定可靠）"""
        today = datetime.now().strftime('%Y-%m-%d')
        overview = MarketOverview(date=today)
        
        if market_monitor:
            try:
                data = market_monitor.get_market_snapshot()
                if data.get('success'):
                    overview.total_amount = data.get('total_volume', 0.0)
                    for idx_data in data.get('indices', []):
                        mi = MarketIndex(
                            name=idx_data.get('name', ''),
                            current=float(idx_data.get('close', 0)),
                            change_pct=float(idx_data.get('change_pct', 0)),
                        )
                        overview.indices.append(mi)
                    logger.info(f"[大盘] 指数数据获取完毕: {overview.indices_text}")
            except Exception as e:
                logger.warning(f"[大盘] Monitor获取数据异常: {e}")

        # 板块排行：尝试获取，失败不阻断（东财接口不稳定）
        try:
            result = self.data_manager.get_sector_rankings(n=5)
            if result:
                top_list, bottom_list = result
                if top_list:
                    overview.top_sectors = [{"name": item['name'], "change_pct": item['change_pct']} for item in top_list]
                    logger.info(f"[大盘] 领涨板块: {[s['name'] for s in overview.top_sectors]}")
                if bottom_list:
                    overview.bottom_sectors = [{"name": item['name'], "change_pct": item['change_pct']} for item in bottom_list]
        except Exception as e:
            logger.debug(f"[大盘] 板块数据获取跳过: {e}")

        return overview

    def search_market_news(self) -> List[Dict]:
        """搜索市场宏观新闻"""
        if not self.search_service:
            return []
        
        all_news = []
        keywords = [
            "今日A股 赚钱效应 涨跌家数", 
            "北向资金 流向 宏观解读",       
            "央行 货币政策 最新消息",
            "人民币汇率 A股 影响",
            "今日A股 复盘 机构观点"
        ]
        
        logger.info("[大盘] 开始搜索宏观情报...")
        for query in keywords:
            try:
                results = self.search_service.search_news(query)
                if results:
                    all_news.extend(results)
            except Exception as e:
                logger.error(f"[大盘] 搜索 '{query}' 失败: {e}")
        
        return all_news

    def generate_market_review(self, overview: MarketOverview, news: List) -> str:
        """AI 生成大盘复盘报告"""
        
        news_text = ""
        seen_titles = set()
        for n in news:
            title = n.get('title', '无标题')
            if title not in seen_titles:
                seen_titles.add(title)
                content = n.get('content', n.get('snippet', ''))[:200]
                news_text += f"{len(seen_titles)}. 【{title}】\n   {content}\n"

        volume_desc = f"{overview.total_amount} 亿元" if overview.total_amount > 0 else "暂无数据"
        indices_desc = overview.indices_text if overview.indices_text else "暂无数据"
        top_sector_desc = ", ".join(
            f"{s['name']}({s['change_pct']}%)" for s in overview.top_sectors
        ) if overview.top_sectors else "暂无数据"
        bottom_sector_desc = ", ".join(
            f"{s['name']}({s['change_pct']}%)" for s in overview.bottom_sectors
        ) if overview.bottom_sectors else "暂无数据"

        from src.core.pipeline import is_market_intraday
        now = datetime.now()
        time_label = "盘中快报" if is_market_intraday() else "收盘复盘"
        news_block = news_text if news_text else "暂无新闻数据"

        prompt = self._build_market_prompt(
            overview.date, time_label, now.strftime('%H:%M'),
            indices_desc, volume_desc,
            top_sector_desc, bottom_sector_desc, news_block
        )
        try:
            logger.info("[大盘] 正在生成大盘复盘报告...")
            report = self.analyzer.chat(prompt)
            return report
        except Exception as e:
            logger.error(f"[大盘] AI 生成报告失败: {e}")
            return f"生成报告出错: {str(e)}"

    @staticmethod
    def _build_market_prompt(date, time_label, time_now, indices, volume,
                             top_sectors, bottom_sectors, news_text):
        """构建大盘分析 prompt"""
        return (
            f"基于以下 A 股市场数据，撰写一份 {date} {time_label}。\n\n"
            "**严格要求**：\n"
            "- 只基于下方提供的数据和新闻进行分析，没有的数据写\"暂无数据\"，绝对不得编造任何数字或事实。\n"
            "- 不要使用第一人称，不要写\"致各位\"之类的开头，不要用天气/气象/风暴等比喻。\n"
            "- 直接输出结构化分析，语言简洁专业。\n\n"
            "# 市场数据\n"
            f"- 时间: {time_now}\n"
            f"- 指数表现: {indices}\n"
            f"- 两市成交: {volume}\n"
            f"- 领涨板块: {top_sectors}\n"
            f"- 领跌板块: {bottom_sectors}\n\n"
            "# 宏观舆情\n"
            f"{news_text}\n\n"
            "---\n"
            "请严格按以下 Markdown 格式输出（不要加额外的开头/问候/署名）：\n\n"
            f"## {date} 大盘{time_label}\n\n"
            "**一句话总结**: (用一句话概括今日市场核心特征和操作方向)\n\n"
            "### 1. 市场定调\n"
            "(用2-4个字定义今日市场特征，如\"缩量震荡\"、\"放量反弹\"。基于指数涨跌幅和成交额数据说明理由)\n\n"
            "### 2. 资金与结构\n"
            "- **板块轮动**: (基于领涨/领跌板块分析资金方向，无数据则写\"暂无板块数据\")\n\n"
            "### 3. 宏观与政策\n"
            "(仅基于上方新闻数据分析，无新闻则写\"暂无重大宏观消息\")\n\n"
            "### 4. 操作建议\n"
            "- **仓位**: (基于市场数据给出仓位建议)\n"
            "- **方向**: (看好/回避哪些方向)\n"
        )

def get_market_analyzer():
    return MarketAnalyzer()
