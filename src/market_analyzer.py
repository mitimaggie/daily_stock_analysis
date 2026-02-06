# src/market_analyzer.py
# -*- coding: utf-8 -*-
"""
===================================
大盘复盘分析模块 (宏观策略增强版 + 板块数据)
===================================
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Dict, Any, List

from src.config import get_config
from src.search_service import get_search_service
from src.analyzer import get_analyzer

# === 核心修改：路径修正 ===
try:
    from data_provider import DataFetcherManager
except ImportError:
    from data_provider.base import DataFetcherManager

try:
    from data_provider.market_monitor import market_monitor
except ImportError:
    market_monitor = None
    logger.warning("⚠️ 警告: 无法导入 data_provider.market_monitor")

logger = logging.getLogger(__name__)

@dataclass
class MarketOverview:
    """市场概览数据结构"""
    date: str
    total_amount: float = 0.0
    indices_text: str = "" 
    top_sectors: List[str] = field(default_factory=list)
    
class MarketAnalyzer:
    """大盘复盘分析器"""
    
    def __init__(self, search_service=None, analyzer=None):
        self.config = get_config()
        self.search_service = search_service if search_service else get_search_service()
        self.analyzer = analyzer if analyzer else get_analyzer()
        self.data_manager = DataFetcherManager() 

    def run_daily_review(self) -> str:
        """执行每日大盘复盘流程"""
        logger.info("========== 开始大盘复盘分析 (宏观视角) ==========")
        overview = self.get_market_overview()
        news = self.search_market_news()
        report = self.generate_market_review(overview, news)
        logger.info("========== 大盘复盘分析完成 ==========")
        return report

    def get_market_overview(self) -> MarketOverview:
        """获取市场概览数据"""
        today = datetime.now().strftime('%Y-%m-%d')
        overview = MarketOverview(date=today)
        
        # 1. 尝试获取指数和成交额
        if market_monitor:
            try:
                data = market_monitor.get_market_snapshot()
                if data.get('success'):
                    overview.total_amount = data.get('total_volume', 0.0)
                    indices = data.get('indices', [])
                    idx_strs = []
                    for idx in indices:
                        name = idx['name']
                        pct = idx['change_pct']
                        emoji = "🔺" if pct > 0 else "💚" if pct < 0 else "➖"
                        idx_strs.append(f"{name} {emoji} {pct}%")
                    overview.indices_text = " / ".join(idx_strs)
                    logger.info(f"[大盘] 指数数据获取完毕: {overview.indices_text}")
            except Exception as e:
                logger.warning(f"[大盘] Monitor获取数据异常: {e}")

        # 2. 尝试获取板块排行
        try:
            top_list, _ = self.data_manager.get_sector_rankings(n=5)
            if top_list:
                overview.top_sectors = [f"{item['name']} ({item['change_pct']}%)" for item in top_list]
                logger.info(f"[大盘] 领涨板块: {overview.top_sectors}")
        except Exception as e:
            logger.warning(f"[大盘] 板块数据获取失败: {e}")
            
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
        """AI 生成宏观策略报告"""
        
        news_text = ""
        deduplicated_news = []
        seen_titles = set()
        
        for n in news:
            title = n.get('title', '无标题')
            if title not in seen_titles:
                deduplicated_news.append(n)
                seen_titles.add(title)

        for i, n in enumerate(deduplicated_news[:15], 1): 
            title = n.get('title', '无标题')
            content = n.get('content', n.get('snippet', ''))[:200]
            news_text += f"{i}. 【{title}】\n   {content}\n"

        volume_desc = f"{overview.total_amount} 亿元" if overview.total_amount > 0 else "接口数据缺失"
        indices_desc = overview.indices_text if overview.indices_text else "接口数据缺失"
        sector_desc = ", ".join(overview.top_sectors) if overview.top_sectors else "接口数据缺失"

        now = datetime.now()
        is_intraday = (9 <= now.hour < 15)
        time_context = "【盘中解盘】" if is_intraday else "【收盘策略日报】"

        prompt = f"""请以【宏观策略师】的身份，撰写一份{time_context}。

# 1. 市场核心数据
- 时间: {now.strftime('%H:%M')}
- 指数表现: {indices_desc}
- 两市成交: {volume_desc}
- **领涨板块**: {sector_desc}

# 2. 宏观舆情与线索
{news_text if news_text else "暂无新闻"}

---
# 任务要求 (Markdown)
请输出一份对冲基金风格的策略日报，直击痛点：

## 📊 {overview.date} 市场全景
### 1. 市场定调 (Market Sentiment)
(用一个词定义今日市场：如“缩量阴跌”、“放量逼空”。简述理由)

### 2. 资金与博弈 (Flows & Game)
- **赚钱效应**: (结合涨跌家数与领涨板块分析)
- **主力意图**: (机构是在洗盘还是出货？)

### 3. 宏观驱动 (Macro Drivers)
(分析汇率、政策、美股映射等影响)

### 4. 交易策略 (Actionable Advice)
- **仓位建议**: (例如：建议半仓防守 / 建议积极进攻)
- **方向指引**: (看好哪个风格？)
"""
        try:
            logger.info("[大盘] 正在生成宏观策略报告...")
            report = self.analyzer.chat(prompt)
            return report
        except Exception as e:
            logger.error(f"[大盘] AI 生成报告失败: {e}")
            return f"生成报告出错: {str(e)}"

def get_market_analyzer():
    return MarketAnalyzer()