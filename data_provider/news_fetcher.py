# -*- coding: utf-8 -*-
"""
===================================
Akshare 免费新闻采集器
===================================

职责：
1. 调用 ak.stock_news_em() 获取东方财富个股新闻
2. 格式化为 SearchResult 并存入 news_intel 表
3. 批量采集所有自选股新闻（供后台定时任务调用）

数据源：东方财富（免费，A股覆盖最全）
"""

import logging
import time
import random
import hashlib
from datetime import datetime
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

# 内存级去重缓存，避免同一进程内短时间重复拉取同一只股票
_fetch_cooldown: Dict[str, float] = {}
_COOLDOWN_SECONDS = 600  # 同一只股票 10 分钟内不重复拉


def _parse_news_datetime(date_str: str) -> Optional[datetime]:
    """解析东方财富新闻的发布时间字符串"""
    if not date_str:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d", "%Y%m%d %H:%M:%S"):
        try:
            return datetime.strptime(str(date_str).strip(), fmt)
        except (ValueError, TypeError):
            continue
    return None


def _build_url_key(code: str, title: str, source: str) -> str:
    """当新闻没有 URL 时，用标题+来源生成稳定的伪 URL（用于去重）"""
    raw = f"{code}:{title}:{source}"
    digest = hashlib.md5(raw.encode()).hexdigest()[:12]
    return f"akshare://news/{code}/{digest}"


def fetch_stock_news(code: str, limit: int = 20) -> List[Dict]:
    """
    获取单只股票的东方财富新闻

    Args:
        code: 股票代码（如 '002270'）
        limit: 最多返回条数

    Returns:
        结构化新闻列表 [{"title", "snippet", "url", "source", "published_date"}, ...]
    """
    # 冷却检查
    last_fetch = _fetch_cooldown.get(code, 0)
    if time.time() - last_fetch < _COOLDOWN_SECONDS:
        logger.debug(f"[{code}] 新闻抓取冷却中，跳过")
        return []

    try:
        import akshare as ak
        df = ak.stock_news_em(symbol=code)
    except Exception as e:
        logger.warning(f"[{code}] Akshare 新闻获取失败: {e}")
        return []

    if df is None or df.empty:
        logger.debug(f"[{code}] 东方财富无新闻数据")
        _fetch_cooldown[code] = time.time()
        return []

    results = []
    # 东方财富返回的列名：新闻标题, 新闻内容, 发布时间, 文章来源, 新闻链接
    for _, row in df.head(limit).iterrows():
        title = str(row.get("新闻标题", row.get("title", ""))).strip()
        snippet = str(row.get("新闻内容", row.get("content", ""))).strip()
        pub_date = str(row.get("发布时间", row.get("publish_time", "")))
        source = str(row.get("文章来源", row.get("source", "东方财富")))
        url = str(row.get("新闻链接", row.get("url", ""))).strip()

        if not title:
            continue
        if not url:
            url = _build_url_key(code, title, source)

        # 截断过长的摘要（节省 token）
        if len(snippet) > 500:
            snippet = snippet[:500] + "..."

        results.append({
            "title": title,
            "snippet": snippet,
            "url": url,
            "source": source,
            "published_date": pub_date,
        })

    _fetch_cooldown[code] = time.time()
    logger.info(f"📰 [{code}] 东方财富新闻抓取成功: {len(results)} 条")
    return results


def save_news_to_db(code: str, stock_name: str, news_list: List[Dict]) -> int:
    """
    将新闻列表存入 news_intel 表

    Args:
        code: 股票代码
        stock_name: 股票名称
        news_list: fetch_stock_news 返回的列表

    Returns:
        新增入库条数
    """
    if not news_list:
        return 0

    from src.storage import DatabaseManager, NewsIntel
    from sqlalchemy import select
    from sqlalchemy.exc import IntegrityError

    storage = DatabaseManager.get_instance()
    saved = 0
    with storage.get_session() as session:
        try:
            for item in news_list:
                url_key = item["url"]
                existing = session.execute(
                    select(NewsIntel).where(NewsIntel.url == url_key)
                ).scalar_one_or_none()

                if existing:
                    # 已存在：刷新 fetched_at（表示仍然活跃）
                    existing.fetched_at = datetime.now()
                else:
                    try:
                        with session.begin_nested():
                            record = NewsIntel(
                                code=code,
                                name=stock_name,
                                dimension="舆情",
                                query=f"akshare_news_{code}",
                                provider="akshare",
                                title=item["title"],
                                snippet=item["snippet"],
                                url=url_key,
                                source=item["source"],
                                published_date=_parse_news_datetime(item["published_date"]),
                                fetched_at=datetime.now(),
                                query_source="background",
                            )
                            session.add(record)
                        saved += 1
                    except IntegrityError:
                        pass
            session.commit()
        except Exception as e:
            session.rollback()
            logger.error(f"[{code}] 新闻入库失败: {e}")

    if saved > 0:
        logger.info(f"💾 [{code}] {stock_name} 新增 {saved} 条新闻入库")
    return saved


def run_news_fetch_job(config) -> None:
    """
    后台定时任务入口：为所有自选股抓取新闻并入库

    Args:
        config: Config 对象（需要 stock_list 和 stock_names）
    """
    config.refresh_stock_list()
    codes = config.stock_list
    if not codes:
        logger.warning("未配置自选股列表，跳过新闻抓取")
        return

    stock_names = getattr(config, 'stock_names', {}) or {}
    logger.info(f"📰 开始后台新闻抓取: {len(codes)} 只股票")
    total_saved = 0

    for i, code in enumerate(codes):
        name = stock_names.get(code, code)
        try:
            news = fetch_stock_news(code)
            if news:
                saved = save_news_to_db(code, name, news)
                total_saved += saved
        except Exception as e:
            logger.warning(f"[{i+1}/{len(codes)}] {code} 新闻抓取异常: {e}")

        # 防止请求过快被封 IP
        if i < len(codes) - 1:
            sleep_time = random.uniform(2.0, 4.0)
            time.sleep(sleep_time)

    logger.info(f"📰 后台新闻抓取完成: 共新增 {total_saved} 条新闻")
