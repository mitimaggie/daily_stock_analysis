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


_ANNOUNCEMENT_PRIORITY_KEYWORDS = [
    "减持", "增持", "回购", "业绩预告", "业绩快报", "业绩预增", "业绩预减",
    "重大资产重组", "股权转让", "重大合同", "立案调查", "监管函", "问询函",
    "高管变动", "解禁", "质押", "增发", "配股", "退市",
]

_ANNOUNCEMENT_COOLDOWN: Dict[str, float] = {}
_ANNOUNCE_COOLDOWN_SECONDS = 1800  # 30分钟内不重复拉同一只股


def fetch_stock_announcements(code: str, days: int = 30) -> List[Dict]:
    """
    获取单只股票的高优先级公告数据（高管增减持 + 业绩快报），无需登录。

    使用全市场批量接口按代码过滤，比逐股请求更稳定：
    - stock_hold_management_detail_em(): 高管增减持明细（近期更新）
    - stock_yjkb_em(): 业绩快报（按季度）

    Args:
        code: 股票代码（如 '000858'）
        days: 近 N 天内的记录才纳入

    Returns:
        结构化公告列表 [{"title", "snippet", "url", "source", "published_date"}, ...]
    """
    last_fetch = _ANNOUNCEMENT_COOLDOWN.get(code, 0)
    if time.time() - last_fetch < _ANNOUNCE_COOLDOWN_SECONDS:
        logger.debug(f"[{code}] 公告抓取冷却中，跳过")
        return []

    results = []
    from datetime import timedelta as _td
    cutoff_date = (datetime.now() - _td(days=days)).strftime('%Y-%m-%d')
    now_str = datetime.now().strftime('%Y-%m-%d')

    _EM_API = "https://datacenter-web.eastmoney.com/api/data/v1/get"
    _HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}

    try:
        import requests as _req

        # === 1. 高管增减持（东方财富，免费直连）===
        try:
            r = _req.get(_EM_API, params={
                "reportName": "RPT_EXECUTIVE_HOLD_DETAILS",
                "columns": "SECURITY_CODE,SECURITY_NAME,CHANGE_DATE,PERSON_NAME,POSITION_NAME,"
                           "CHANGE_SHARES,AVERAGE_PRICE,CHANGE_AMOUNT,CHANGE_REASON,BEGIN_HOLD_NUM,END_HOLD_NUM",
                "filter": f'(SECURITY_CODE="{code}")',
                "pageNumber": "1", "pageSize": "20",
                "sortTypes": "-1", "sortColumns": "CHANGE_DATE",
                "source": "WEB", "client": "WEB",
            }, headers=_HEADERS, timeout=10)
            items = (r.json().get("result") or {}).get("data") or []
            for item in items:
                change_date = str(item.get("CHANGE_DATE", ""))[:10]
                if change_date < cutoff_date:
                    continue
                person = item.get("PERSON_NAME", "")
                position = item.get("POSITION_NAME", "")
                shares = item.get("CHANGE_SHARES", 0) or 0
                price = item.get("AVERAGE_PRICE", "")
                amount = item.get("CHANGE_AMOUNT", "")
                reason = item.get("CHANGE_REASON", "")
                action = "减持" if float(shares) < 0 else "增持"
                title = f"【重要公告】{person}({position}){action} {abs(float(shares)):.0f}股"
                snippet = (
                    f"高管{action}: {person}({position})于{change_date}通过{reason}"
                    f"{action}{abs(float(shares)):.0f}股，均价{price}元，"
                    f"变动金额约{amount}元"
                )
                url_key = _build_url_key(code, title + change_date, "高管增减持")
                results.append({
                    "title": title, "snippet": snippet, "url": url_key,
                    "source": "东方财富-高管增减持",
                    "published_date": change_date, "_is_important": True,
                })
        except Exception as e:
            logger.debug(f"[{code}] 高管增减持获取失败: {e}")

        # === 2. 业绩预告（东方财富，免费直连）===
        try:
            r = _req.get(_EM_API, params={
                "reportName": "RPT_PUBLIC_OP_NEWPREDICT",
                "columns": "SECURITY_CODE,SECURITY_NAME_ABBR,NOTICE_DATE,REPORT_DATE,"
                           "PREDICT_FINANCE,PREDICT_TYPE,ADD_AMP_LOWER,ADD_AMP_UPPER,"
                           "PREDICT_CONTENT,PREDICT_RATIO_LOWER,PREDICT_RATIO_UPPER",
                "filter": f'(SECURITY_CODE="{code}")',
                "pageNumber": "1", "pageSize": "5",
                "sortTypes": "-1", "sortColumns": "NOTICE_DATE",
                "source": "WEB", "client": "WEB",
            }, headers=_HEADERS, timeout=10)
            items = (r.json().get("result") or {}).get("data") or []
            for item in items:
                notice_date = str(item.get("NOTICE_DATE", ""))[:10]
                if notice_date < cutoff_date:
                    continue
                report_date = str(item.get("REPORT_DATE", ""))[:10]
                predict_type = item.get("PREDICT_TYPE", "")
                finance_item = item.get("PREDICT_FINANCE", "")
                amp_low = item.get("ADD_AMP_LOWER", "")
                amp_high = item.get("ADD_AMP_UPPER", "")
                content = (item.get("PREDICT_CONTENT") or "")[:200]
                is_important = any(k in predict_type for k in ["预减", "预亏", "预增", "扭亏"])
                tag = "【重要公告】" if is_important else ""
                title = f"{tag}业绩预告({report_date[:7]}): {predict_type}"
                snippet = (
                    f"业绩预告({report_date[:7]}): {finance_item}预计变动{amp_low}%~{amp_high}%，"
                    f"类型:{predict_type}。{content}"
                )
                url_key = _build_url_key(code, title + notice_date, "业绩预告")
                results.append({
                    "title": title, "snippet": snippet, "url": url_key,
                    "source": "东方财富-业绩预告",
                    "published_date": notice_date, "_is_important": is_important,
                })
        except Exception as e:
            logger.debug(f"[{code}] 业绩预告获取失败: {e}")

        # === 3. 同花顺机构盈利预测（akshare，无需登录）===
        try:
            import akshare as _ak
            df_forecast = _ak.stock_profit_forecast_ths(symbol=code, indicator='预测年报每股收益')
            if df_forecast is not None and not df_forecast.empty:
                row = df_forecast.iloc[0]
                year = str(row.get('年度', '')).strip()
                avg_eps = row.get('均值', 'N/A')
                min_eps = row.get('最小值', 'N/A')
                max_eps = row.get('最大值', 'N/A')
                inst_count = row.get('预测机构数', 'N/A')
                title = f"机构盈利预测({year}年): EPS均值{avg_eps}元 ({inst_count}家机构)"
                snippet = (
                    f"同花顺机构盈利预测({year}年): EPS均值{avg_eps}元"
                    f"（区间{min_eps}~{max_eps}），共{inst_count}家机构参与预测。"
                )
                url_key = _build_url_key(code, title, "机构盈利预测")
                results.append({
                    "title": title, "snippet": snippet, "url": url_key,
                    "source": "同花顺-机构盈利预测",
                    "published_date": now_str, "_is_important": False,
                })
        except Exception as e:
            logger.debug(f"[{code}] 机构盈利预测获取失败: {e}")

    except Exception as e:
        logger.warning(f"[{code}] 公告抓取整体失败: {e}")

    _ANNOUNCEMENT_COOLDOWN[code] = time.time()

    # 按重要性排序，重要公告优先
    results.sort(key=lambda x: (not x.get('_is_important', False), x.get('published_date', '')))
    for r in results:
        r.pop('_is_important', None)

    if results:
        logger.info(f"📋 [{code}] 公告数据: {len(results)} 条 (近{days}天)")
    return results


def run_news_fetch_job(config) -> None:
    """
    后台定时任务入口：为所有自选股抓取新闻+公告并入库

    Args:
        config: Config 对象（需要 stock_list 和 stock_names）
    """
    config.refresh_stock_list()
    codes = config.stock_list
    if not codes:
        logger.warning("未配置自选股列表，跳过新闻抓取")
        return

    stock_names = getattr(config, 'stock_names', {}) or {}
    logger.info(f"📰 开始后台新闻+公告抓取: {len(codes)} 只股票")
    total_saved = 0

    for i, code in enumerate(codes):
        name = stock_names.get(code, code)
        try:
            # 1. 个股新闻（东方财富新闻流）
            news = fetch_stock_news(code)
            if news:
                saved = save_news_to_db(code, name, news)
                total_saved += saved

            # 2. 交易所公告（优先级更高，含减持/业绩预告/监管函等）
            announcements = fetch_stock_announcements(code, days=3)
            if announcements:
                saved_ann = save_news_to_db(code, name, announcements)
                total_saved += saved_ann
                if saved_ann > 0:
                    important = [a for a in announcements if '重要公告' in a.get('title', '')]
                    if important:
                        logger.info(f"🚨 [{code}] {name} 有 {len(important)} 条重要公告入库")

        except Exception as e:
            logger.warning(f"[{i+1}/{len(codes)}] {code} 新闻/公告抓取异常: {e}")

        # 防止请求过快被封 IP
        if i < len(codes) - 1:
            sleep_time = random.uniform(2.0, 4.0)
            time.sleep(sleep_time)

    logger.info(f"📰 后台新闻抓取完成: 共新增 {total_saved} 条新闻")
