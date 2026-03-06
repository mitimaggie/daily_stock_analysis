# -*- coding: utf-8 -*-
"""
===================================
交易日历模块
===================================

职责：
1. 判断今日是否为A股交易日
2. 非交易日时提供跳过信号，避免无效分析
3. fail-open：若无法获取日历数据，返回 True 不干扰分析

数据来源：akshare tool_trade_date_hist_sina（已有依赖，无额外开销）
缓存策略：进程级缓存，当天内不重复请求
"""

import logging
from datetime import date, datetime
from typing import Optional, Set

logger = logging.getLogger(__name__)

# 进程级缓存
_trading_dates_cache: Optional[Set[str]] = None
_cache_date: Optional[date] = None

_WEEKDAY_NAMES = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']


def _fetch_trading_dates() -> Set[str]:
    """从 akshare 获取A股交易日期表（带进程级缓存，当日内不重复请求）"""
    global _trading_dates_cache, _cache_date

    today = date.today()
    if _trading_dates_cache is not None and _cache_date == today:
        return _trading_dates_cache

    try:
        import akshare as ak
        df = ak.tool_trade_date_hist_sina()
        if df is not None and not df.empty:
            col = df.columns[0]
            dates: Set[str] = set()
            for d in df[col]:
                s = str(d).strip()
                if len(s) >= 10:
                    dates.add(s[:10])
            _trading_dates_cache = dates
            _cache_date = today
            logger.debug(f"[交易日历] 已加载 {len(dates)} 个交易日")
            return dates
    except Exception as e:
        logger.warning(f"[交易日历] 获取交易日历失败，降级为仅排除周末: {e}")

    # 返回空集合 → 降级路径
    return set()


def is_cn_trading_day(check_date: Optional[date] = None) -> bool:
    """
    检查指定日期是否为A股交易日。

    fail-open：若akshare调用失败，仅排除周末，不排除节假日（不干扰正常运行）。

    Args:
        check_date: 要检查的日期，默认为今日

    Returns:
        True = 交易日，False = 非交易日（休市）
    """
    if check_date is None:
        check_date = date.today()

    # 快速排除：周六/周日一定不是交易日
    if check_date.weekday() >= 5:
        return False

    # 尝试用精确日历判断（包含节假日）
    trading_dates = _fetch_trading_dates()
    if not trading_dates:
        # 降级：只排除周末，节假日判断缺失（fail-open）
        return True

    return check_date.strftime('%Y-%m-%d') in trading_dates


def get_trading_day_status(check_date: Optional[date] = None) -> str:
    """返回可读的交易日状态描述"""
    if check_date is None:
        check_date = date.today()

    day_name = _WEEKDAY_NAMES[check_date.weekday()]
    date_str = check_date.strftime('%Y-%m-%d')

    if is_cn_trading_day(check_date):
        return f"今日 {date_str}（{day_name}）为A股交易日 ✅"
    else:
        return f"今日 {date_str}（{day_name}）为非交易日（休市）⏭️"
