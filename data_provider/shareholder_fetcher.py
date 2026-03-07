# -*- coding: utf-8 -*-
"""
股东与资本结构数据获取模块
提供：
- 高管增减持记录（内存全局缓存4h，按股票代码筛选）
- 限售解禁队列（per-stock，直接调用）
- 股票回购（内存全局缓存4h，按股票代码筛选）
"""
import logging
import time
from datetime import datetime, timedelta
from typing import Dict, Any, Optional

import pandas as pd

logger = logging.getLogger(__name__)

# === 全局内存缓存（减少API调用，4h TTL）===
_CACHE_TTL_SECONDS = 4 * 3600  # 4小时

_insider_cache: Dict[str, Any] = {
    'data': None,        # DataFrame: 增减持合并数据
    'ts': 0.0,           # 最后刷新时间戳
}
import threading as _threading
_insider_refresh_lock = _threading.Lock()  # 防止主线程与预热线程同时刷新缓存

_repurchase_cache: Dict[str, Any] = {
    'data': None,        # DataFrame: 回购数据
    'ts': 0.0,
    'fail_ts': 0.0,      # 最近一次失败时间戳（用于 backoff）
}
_REPURCHASE_FAIL_BACKOFF = 30 * 60  # 失败后30分钟内不重试


def _refresh_insider_cache(blocking: bool = True) -> bool:
    """下载最新增持+减持数据并合并，写入全局缓存。返回是否成功
    
    Args:
        blocking: True=等待获取锁（后台预热线程用），False=非阻塞（主线程调用，获取失败立即返回）
    """
    if not _insider_refresh_lock.acquire(blocking=blocking):
        return False  # 预热线程已在运行，主线程直接跳过
    try:
        import warnings
        warnings.filterwarnings('ignore')
        try:
            import akshare as ak
            df_buy = ak.stock_hold_management_detail_cninfo(symbol="增持")
            df_buy['变动方向'] = '增持'
        except Exception as e:
            logger.warning(f"[shareholder] 增持数据获取失败: {e}")
            df_buy = pd.DataFrame()

        try:
            import akshare as ak
            df_sell = ak.stock_hold_management_detail_cninfo(symbol="减持")
            df_sell['变动方向'] = '减持'
        except Exception as e:
            logger.warning(f"[shareholder] 减持数据获取失败: {e}")
            df_sell = pd.DataFrame()

        if df_buy.empty and df_sell.empty:
            return False

        df = pd.concat([df_buy, df_sell], ignore_index=True)
        _insider_cache['data'] = df
        _insider_cache['ts'] = time.time()
        logger.info(f"[shareholder] 增减持缓存已刷新: {len(df)} 条记录")
        return True
    finally:
        _insider_refresh_lock.release()


def _refresh_repurchase_cache() -> bool:
    """下载最新股票回购数据并写入全局缓存。返回是否成功"""
    import warnings
    warnings.filterwarnings('ignore')
    try:
        import akshare as ak
        from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
        _ex = ThreadPoolExecutor(max_workers=1)
        try:
            df = _ex.submit(ak.stock_repurchase_em).result(timeout=15)
        except FuturesTimeout:
            logger.warning("[shareholder] 回购数据获取超时(15s)，30分钟内不再重试")
            _repurchase_cache['fail_ts'] = time.time()
            return False
        finally:
            _ex.shutdown(wait=False)
        if df is None or df.empty:
            _repurchase_cache['fail_ts'] = time.time()
            return False
        _repurchase_cache['data'] = df
        _repurchase_cache['ts'] = time.time()
        _repurchase_cache['fail_ts'] = 0.0
        logger.info(f"[shareholder] 回购缓存已刷新: {len(df)} 条记录")
        return True
    except Exception as e:
        logger.warning(f"[shareholder] 回购数据获取失败: {e}")
        _repurchase_cache['fail_ts'] = time.time()
        return False


def get_repurchase_summary(code: str) -> Dict[str, Any]:
    """获取指定股票的回购计划摘要

    Returns:
        dict with keys:
            has_data: bool
            plan_amount_yi: float  计划回购金额上限（亿元）
            executed_amount_yi: float  已执行回购金额（亿元）
            progress_pct: float  执行进度(%)
            status: str  回购状态
            summary: str  一句话摘要
    """
    now = time.time()
    in_backoff = (now - _repurchase_cache.get('fail_ts', 0.0)) < _REPURCHASE_FAIL_BACKOFF
    if not in_backoff and (_repurchase_cache['data'] is None or (now - _repurchase_cache['ts']) > _CACHE_TTL_SECONDS):
        _refresh_repurchase_cache()

    df = _repurchase_cache.get('data')
    if df is None or df.empty:
        return {'has_data': False, 'summary': '回购数据暂不可用'}

    try:
        # 按股票代码筛选（列名可能是「股票代码」或「代码」）
        code_col = None
        for col in ['股票代码', '代码', 'code']:
            if col in df.columns:
                code_col = col
                break
        if code_col is None:
            return {'has_data': False, 'summary': '回购数据格式异常'}

        sub = df[df[code_col].astype(str).str.strip() == str(code).strip()].copy()
    except Exception:
        return {'has_data': False, 'summary': '筛选失败'}

    if sub.empty:
        return {'has_data': False, 'summary': '无股票回购记录'}

    # 取最新一条（按公告日期排序）
    try:
        date_col = next((c for c in ['公告日期', '披露日期', '公告时间'] if c in sub.columns), None)
        if date_col:
            sub = sub.sort_values(date_col, ascending=False)
        row = sub.iloc[0]
    except Exception:
        row = sub.iloc[0]

    # 提取金额字段
    def _to_yi(val):
        try:
            v = float(str(val).replace(',', '').replace('亿', ''))
            # 判断单位：>1e6 认为是元，>1e4 认为是万元
            if v > 1e6:
                return round(v / 1e8, 2)
            elif v > 1e4:
                return round(v / 1e4, 2)
            return round(v, 2)
        except Exception:
            return 0.0

    plan_col = next((c for c in ['回购金额上限', '拟回购金额', '计划回购金额', '回购金额'] if c in sub.columns), None)
    exec_col = next((c for c in ['已回购金额', '已完成金额', '实际回购金额'] if c in sub.columns), None)
    status_col = next((c for c in ['状态', '回购状态', '进展'] if c in sub.columns), None)

    plan_yi = _to_yi(row.get(plan_col, 0)) if plan_col else 0.0
    exec_yi = _to_yi(row.get(exec_col, 0)) if exec_col else 0.0
    progress_pct = round(exec_yi / plan_yi * 100, 1) if plan_yi > 0 else 0.0
    status = str(row.get(status_col, '')) if status_col else ''

    parts = []
    if plan_yi > 0:
        parts.append(f"计划回购{plan_yi}亿元")
    if exec_yi > 0:
        parts.append(f"已执行{exec_yi}亿元")
    if progress_pct > 0:
        parts.append(f"进度{progress_pct}%")
    if status:
        parts.append(f"状态：{status}")

    if not parts:
        return {'has_data': False, 'summary': '回购记录无有效金额数据'}

    summary = '，'.join(parts)
    return {
        'has_data': True,
        'plan_amount_yi': plan_yi,
        'executed_amount_yi': exec_yi,
        'progress_pct': progress_pct,
        'status': status,
        'summary': summary,
    }


def get_insider_changes(code: str, days_back: int = 90) -> Dict[str, Any]:
    """获取指定股票近期高管增减持摘要

    Args:
        code: 股票代码（如 "600000" 或 "000001"）
        days_back: 查看最近N天内的记录

    Returns:
        dict with keys:
            has_data: bool
            buy_count: int  近期增持次数
            sell_count: int 近期减持次数
            buy_amount: float  增持市值（万元），NaN时为0
            sell_amount: float 减持市值（万元），NaN时为0
            net_direction: str  "净增持"/"净减持"/"无变动"
            latest_date: str  最新公告日期
            summary: str  一句话摘要（供LLM直接阅读）
    """
    now = time.time()
    # 缓存过期则刷新（非阻塞：若预热线程正在刷新，主线程直接用空结果，不等待）
    if _insider_cache['data'] is None or (now - _insider_cache['ts']) > _CACHE_TTL_SECONDS:
        _refresh_insider_cache(blocking=False)

    df = _insider_cache.get('data')
    if df is None or df.empty:
        return {'has_data': False, 'summary': '增减持数据暂不可用'}

    # 规范化股票代码（去前缀）
    code_clean = code.lstrip('sh').lstrip('sz').lstrip('0') if False else code
    try:
        sub = df[df['证券代码'].astype(str).str.strip() == str(code).strip()].copy()
    except Exception:
        return {'has_data': False, 'summary': '筛选失败'}

    if sub.empty:
        return {'has_data': False, 'summary': '近期无高管增减持记录'}

    # 日期过滤
    try:
        cutoff = (datetime.now() - timedelta(days=days_back)).strftime('%Y-%m-%d')
        sub['公告日期'] = pd.to_datetime(sub['公告日期'], errors='coerce')
        sub = sub[sub['公告日期'] >= cutoff].copy()
    except Exception:
        pass

    if sub.empty:
        return {'has_data': False, 'summary': f'近{days_back}日内无高管增减持记录'}

    buy_df = sub[sub['变动方向'] == '增持']
    sell_df = sub[sub['变动方向'] == '减持']
    buy_count = len(buy_df)
    sell_count = len(sell_df)

    # 变动数量（万股）
    def _sum_qty(df_part):
        try:
            return abs(pd.to_numeric(df_part['变动数量'], errors='coerce').sum()) / 1e4
        except Exception:
            return 0.0

    buy_qty = _sum_qty(buy_df)
    sell_qty = _sum_qty(sell_df)

    # 最新日期
    try:
        latest_date = sub['公告日期'].max().strftime('%Y-%m-%d')
    except Exception:
        latest_date = '未知'

    net_direction = '净增持' if buy_qty > sell_qty else ('净减持' if sell_qty > buy_qty else '无净变动')

    # 生成摘要
    parts = []
    if buy_count > 0:
        parts.append(f"增持{buy_count}次（约{buy_qty:.1f}万股）")
    if sell_count > 0:
        parts.append(f"减持{sell_count}次（约{sell_qty:.1f}万股）")

    summary = f"近{days_back}日内：{' | '.join(parts) if parts else '无记录'}，整体{net_direction}（最新公告{latest_date}）"

    return {
        'has_data': True,
        'buy_count': buy_count,
        'sell_count': sell_count,
        'buy_qty_wan': round(buy_qty, 1),
        'sell_qty_wan': round(sell_qty, 1),
        'net_direction': net_direction,
        'latest_date': latest_date,
        'summary': summary,
    }


def get_upcoming_unlock(code: str, days_ahead: int = 180) -> Dict[str, Any]:
    """获取指定股票即将到来的限售解禁信息

    Args:
        code: 股票代码（不含前缀，如 "600000"）
        days_ahead: 查看未来N天内的解禁

    Returns:
        dict with keys:
            has_data: bool
            next_unlock_date: str  下次解禁日期
            next_unlock_qty_yi: float  下次解禁数量（亿股）
            next_unlock_mv_yi: float  下次解禁市值（亿元）
            next_unlock_float_pct: float  占流通股比例(%)
            unlock_type: str  限售股类型
            summary: str  一句话摘要
    """
    import warnings
    warnings.filterwarnings('ignore')
    _unlock_fail_cache = getattr(get_upcoming_unlock, '_fail_cache', {})
    now_ts = time.time()
    if (now_ts - _unlock_fail_cache.get(code, 0.0)) < _REPURCHASE_FAIL_BACKOFF:
        return {'has_data': False, 'summary': '限售解禁数据暂不可用'}
    try:
        import akshare as ak
        from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
        _ex = ThreadPoolExecutor(max_workers=1)
        try:
            df = _ex.submit(ak.stock_restricted_release_queue_em, code).result(timeout=10)
        except FuturesTimeout:
            logger.debug(f"[shareholder] 解禁数据获取超时(10s): {code}")
            _unlock_fail_cache[code] = time.time()
            get_upcoming_unlock._fail_cache = _unlock_fail_cache
            return {'has_data': False, 'summary': '限售解禁数据暂不可用'}
        finally:
            _ex.shutdown(wait=False)
    except Exception as e:
        logger.debug(f"[shareholder] 解禁数据获取失败({code}): {e}")
        _unlock_fail_cache[code] = time.time()
        get_upcoming_unlock._fail_cache = _unlock_fail_cache
        return {'has_data': False, 'summary': '限售解禁数据暂不可用'}

    if df is None or df.empty:
        return {'has_data': False, 'summary': '近期无限售解禁计划'}

    try:
        today = datetime.now().strftime('%Y-%m-%d')
        cutoff_end = (datetime.now() + timedelta(days=days_ahead)).strftime('%Y-%m-%d')
        df['解禁时间'] = pd.to_datetime(df['解禁时间'], errors='coerce')
        upcoming = df[(df['解禁时间'].dt.strftime('%Y-%m-%d') >= today) &
                      (df['解禁时间'].dt.strftime('%Y-%m-%d') <= cutoff_end)].copy()
    except Exception:
        upcoming = df.copy()

    if upcoming.empty:
        return {'has_data': False, 'summary': f'未来{days_ahead}日内无限售解禁'}

    # 取最近一次解禁
    row = upcoming.sort_values('解禁时间').iloc[0]

    next_date = row.get('解禁时间', pd.NaT)
    next_date_str = next_date.strftime('%Y-%m-%d') if not pd.isnull(next_date) else '未知'

    qty = float(row.get('解禁数量', 0) or 0)
    mv = float(row.get('实际解禁数量市值', 0) or 0)
    float_pct = float(row.get('占流通市值比例', 0) or 0)
    unlock_type = str(row.get('限售股类型', ''))

    qty_yi = qty / 1e8 if qty > 0 else 0.0
    mv_yi = mv / 1e8 if mv > 0 else 0.0

    # 判断解禁压力等级
    if float_pct >= 10:
        pressure = "⚠️ 重大解禁压力"
    elif float_pct >= 3:
        pressure = "中等解禁压力"
    elif float_pct > 0:
        pressure = "小额解禁"
    else:
        pressure = ""

    parts = [f"下次解禁：{next_date_str}"]
    if qty_yi > 0:
        parts.append(f"规模{qty_yi:.2f}亿股")
    if mv_yi > 0:
        parts.append(f"市值约{mv_yi:.1f}亿元")
    if float_pct > 0:
        parts.append(f"占流通股{float_pct:.1f}%")
    if unlock_type:
        parts.append(f"类型：{unlock_type}")
    if pressure:
        parts.append(pressure)

    summary = '，'.join(parts)

    return {
        'has_data': True,
        'next_unlock_date': next_date_str,
        'next_unlock_qty_yi': round(qty_yi, 3),
        'next_unlock_mv_yi': round(mv_yi, 2),
        'next_unlock_float_pct': round(float_pct, 2),
        'unlock_type': unlock_type,
        'upcoming_count': len(upcoming),
        'summary': summary,
    }
