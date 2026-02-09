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

logger = logging.getLogger(__name__)

try:
    from data_provider.market_monitor import market_monitor
except ImportError:
    market_monitor = None
    logger.warning("无法导入 data_provider.market_monitor")


@dataclass
class MarketIndex:
    """大盘指数数据"""
    code: str = ""                   # 指数代码
    name: str = ""                   # 指数名称
    current: float = 0.0             # 当前点位
    change: float = 0.0              # 涨跌点数
    change_pct: float = 0.0          # 涨跌幅(%)
    open: float = 0.0                # 开盘点位
    high: float = 0.0                # 最高点位
    low: float = 0.0                 # 最低点位
    prev_close: float = 0.0          # 昨收点位
    volume: float = 0.0              # 成交量(手)
    amount: float = 0.0              # 成交额(元)
    amplitude: float = 0.0           # 振幅(%)

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
    indices: List[MarketIndex] = field(default_factory=list)   # 主要指数
    up_count: int = 0                  # 上涨家数
    down_count: int = 0                # 下跌家数
    flat_count: int = 0                # 平盘家数
    limit_up_count: int = 0            # 涨停家数
    limit_down_count: int = 0          # 跌停家数
    total_amount: float = 0.0          # 两市成交额(亿)
    top_sectors: List[Dict] = field(default_factory=list)      # 涨幅前5板块
    bottom_sectors: List[Dict] = field(default_factory=list)   # 跌幅前5板块

    @property
    def indices_text(self) -> str:
        """向后兼容：格式化为旧字符串"""
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
        
        # 1. 获取指数和成交额 (从 market_monitor)
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

        # 2. 获取涨跌统计（市场广度）
        self._get_market_statistics(overview)

        # 3. 获取板块涨跌榜（含领涨+领跌）
        self._get_sector_rankings(overview)
            
        return overview

    def _get_market_statistics(self, overview: MarketOverview) -> None:
        """获取涨跌家数、涨停跌停等市场广度数据
        
        复用 akshare_fetcher 的 _realtime_cache（1200s TTL），避免重复请求东财被断连。
        """
        try:
            # 优先复用 akshare_fetcher 模块级缓存（stock_zh_a_spot_em 全量表）
            from data_provider.akshare_fetcher import _realtime_cache
            import time as _time
            df = None
            if _realtime_cache['data'] is not None and _time.time() - _realtime_cache['timestamp'] < _realtime_cache['ttl']:
                df = _realtime_cache['data']
                logger.debug("[大盘] 涨跌统计: 复用 EM 缓存")
            else:
                # 缓存过期才重新拉取
                import akshare as ak
                _time.sleep(1)  # 简单限流
                df = ak.stock_zh_a_spot_em()
                if df is not None and not df.empty:
                    _realtime_cache['data'] = df
                    _realtime_cache['timestamp'] = _time.time()

            if df is not None and not df.empty:
                pct_col = '涨跌幅'
                if pct_col in df.columns:
                    valid = df[pct_col].dropna()
                    overview.up_count = int((valid > 0).sum())
                    overview.down_count = int((valid < 0).sum())
                    overview.flat_count = int((valid == 0).sum())
                    overview.limit_up_count = int((valid >= 9.9).sum())
                    overview.limit_down_count = int((valid <= -9.9).sum())
                    logger.info(f"[大盘] 涨跌统计: 涨{overview.up_count} 跌{overview.down_count} 涨停{overview.limit_up_count} 跌停{overview.limit_down_count}")
        except Exception as e:
            logger.warning(f"[大盘] 涨跌统计获取失败: {e}")

    def _get_sector_rankings(self, overview: MarketOverview) -> None:
        """获取板块涨跌排行（领涨 + 领跌）"""
        try:
            top_list, bottom_list = self.data_manager.get_sector_rankings(n=5)
            if top_list:
                overview.top_sectors = [{"name": item['name'], "change_pct": item['change_pct']} for item in top_list]
                logger.info(f"[大盘] 领涨板块: {[s['name'] for s in overview.top_sectors]}")
            if bottom_list:
                overview.bottom_sectors = [{"name": item['name'], "change_pct": item['change_pct']} for item in bottom_list]
                logger.info(f"[大盘] 领跌板块: {[s['name'] for s in overview.bottom_sectors]}")
        except Exception as e:
            logger.warning(f"[大盘] 板块数据获取失败: {e}")

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
        top_sector_desc = ", ".join(f"{s['name']}({s['change_pct']}%)" for s in overview.top_sectors) if overview.top_sectors else "接口数据缺失"
        bottom_sector_desc = ", ".join(f"{s['name']}({s['change_pct']}%)" for s in overview.bottom_sectors) if overview.bottom_sectors else "接口数据缺失"

        # 市场广度
        breadth_desc = "接口数据缺失"
        if overview.up_count > 0 or overview.down_count > 0:
            breadth_desc = (
                f"上涨{overview.up_count}家 / 下跌{overview.down_count}家 / 平盘{overview.flat_count}家 | "
                f"涨停{overview.limit_up_count} / 跌停{overview.limit_down_count}"
            )

        from src.core.pipeline import is_market_intraday
        now = datetime.now()
        time_context = "【盘中解盘】" if is_market_intraday() else "【收盘策略日报】"

        prompt = f"""请以【宏观策略师】的身份，撰写一份{time_context}。

# 1. 市场核心数据
- 时间: {now.strftime('%H:%M')}
- 指数表现: {indices_desc}
- 两市成交: {volume_desc}
- **市场广度**: {breadth_desc}
- **领涨板块**: {top_sector_desc}
- **领跌板块**: {bottom_sector_desc}

# 2. 宏观舆情与线索
{news_text if news_text else "暂无新闻"}

---
# 任务要求 (Markdown)
请输出一份对冲基金风格的策略日报，直击痛点：

## 📊 {overview.date} 市场全景
### 1. 市场定调 (Market Sentiment)
(用一个词定义今日市场：如“缩量阴跌”、“放量逼空”。简述理由)

### 2. 资金与博弈 (Flows & Game)
- **赚钱效应**: (结合涨跌家数、涨停跌停家数与领涨/领跌板块分析)
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