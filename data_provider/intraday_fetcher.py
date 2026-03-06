# -*- coding: utf-8 -*-
"""
分时/分钟级 K 线数据获取器
支持 1min / 5min / 15min / 30min / 60min 周期
数据源优先级：akshare(东财) [唯一有效] → efinance [已禁用，函数体直接返回None]

⚠️ 反封禁警告：
  - akshare 东财接口有反爬限制，严禁并发批量调用此模块
  - efinance 分钟线接口已禁用（import efinance 会触发全量817支股票下载）
  - 如需新增数据源，必须先通过 rate_limiter.py 的令牌桶限流

使用场景：
  - 盘中分析时获取更精细的量价数据
  - 短线分时趋势判断
  - 盘口大单检测辅助
"""

import logging
import time
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List

import pandas as pd

logger = logging.getLogger(__name__)

# 分时数据内存缓存（避免频繁请求被封）
_intraday_cache: Dict[str, Dict[str, Any]] = {}
_CACHE_TTL = 300  # 5 分钟缓存


def _cache_key(code: str, period: str) -> str:
    return f"{code}_{period}"


def _get_cached(code: str, period: str) -> Optional[pd.DataFrame]:
    key = _cache_key(code, period)
    cached = _intraday_cache.get(key)
    if cached and time.time() - cached['ts'] < _CACHE_TTL:
        return cached['df']
    return None


def _set_cache(code: str, period: str, df: pd.DataFrame):
    key = _cache_key(code, period)
    _intraday_cache[key] = {'df': df, 'ts': time.time()}


# ============ akshare 数据源 ============

def _fetch_intraday_akshare(code: str, period: str = "5", days: int = 1) -> Optional[pd.DataFrame]:
    """
    通过 akshare 获取分钟级 K 线
    
    Args:
        code: 股票代码 (6位纯数字)
        period: "1" / "5" / "15" / "30" / "60"
        days: 获取天数 (akshare 默认返回近5个交易日)
    """
    try:
        import akshare as ak
        
        # akshare 接口：stock_zh_a_hist_min_em
        # period 参数: "1", "5", "15", "30", "60"
        df = ak.stock_zh_a_hist_min_em(symbol=code, period=period, adjust="qfq")
        
        if df is None or df.empty:
            return None
        
        # 标准化列名
        col_map = {
            '时间': 'datetime',
            '开盘': 'open',
            '收盘': 'close',
            '最高': 'high',
            '最低': 'low',
            '成交量': 'volume',
            '成交额': 'amount',
            '涨跌幅': 'pct_chg',
        }
        df = df.rename(columns=col_map)
        
        # 确保时间列存在
        if 'datetime' not in df.columns:
            # 尝试其他可能的列名
            for col in df.columns:
                if '时间' in col or 'time' in col.lower() or 'date' in col.lower():
                    df = df.rename(columns={col: 'datetime'})
                    break
        
        if 'datetime' not in df.columns:
            logger.warning(f"[akshare intraday] {code} 无时间列: {df.columns.tolist()}")
            return None
        
        df['datetime'] = pd.to_datetime(df['datetime'])
        
        # 只保留近N天数据
        if days < 5:
            cutoff = datetime.now() - timedelta(days=days + 1)
            df = df[df['datetime'] >= cutoff]
        
        # 数值列处理
        for col in ['open', 'high', 'low', 'close', 'volume', 'amount', 'pct_chg']:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')
        
        df = df.sort_values('datetime').reset_index(drop=True)
        logger.info(f"✅ [akshare] {code} {period}min K线获取成功 ({len(df)}条)")
        return df
        
    except ImportError:
        logger.debug("akshare 未安装")
        return None
    except Exception as e:
        logger.debug(f"[akshare intraday] {code} 获取失败: {e}")
        return None


# ============ efinance 数据源 [已禁用 - 勿启用] ============
# ⚠️ 下方函数体第一行直接 return None，下方所有代码均为死代码
# 原因：import efinance 会在后台触发全量 817 支股票数据下载（耗时 30-60s），
# 严重阻塞主线程。如需分钟线数据，请扩展 _fetch_intraday_akshare。

def _fetch_intraday_efinance(code: str, period: str = "5", days: int = 1) -> Optional[pd.DataFrame]:
    """
    [已禁用] 通过 efinance 获取分钟级 K 线 — 函数始终返回 None

    Args:
        code: 股票代码
        period: "1" / "5" / "15" / "30" / "60"
        days: 获取天数
    """
    try:
        # efinance 分钟线已禁用：import efinance 会在后台触发全量 817 支股票下载，耗时数分钟
        # 使用 akshare 替代（_fetch_intraday_akshare）
        return None
        import efinance as ef  # noqa: unreachable
        
        # efinance 的 klt 参数: 1=1min, 5=5min, 15=15min, 30=30min, 60=60min
        klt = int(period)
        df = ef.stock.get_quote_history(code, klt=klt)
        
        if df is None or df.empty:
            return None
        
        # 标准化列名
        col_map = {
            '日期': 'datetime',
            '开盘': 'open',
            '收盘': 'close',
            '最高': 'high',
            '最低': 'low',
            '成交量': 'volume',
            '成交额': 'amount',
            '涨跌幅': 'pct_chg',
        }
        df = df.rename(columns=col_map)
        
        if 'datetime' not in df.columns:
            for col in df.columns:
                if '时间' in col or 'time' in col.lower() or 'date' in col.lower():
                    df = df.rename(columns={col: 'datetime'})
                    break
        
        if 'datetime' not in df.columns:
            return None
        
        df['datetime'] = pd.to_datetime(df['datetime'])
        
        if days < 5:
            cutoff = datetime.now() - timedelta(days=days + 1)
            df = df[df['datetime'] >= cutoff]
        
        for col in ['open', 'high', 'low', 'close', 'volume', 'amount', 'pct_chg']:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')
        
        df = df.sort_values('datetime').reset_index(drop=True)
        logger.info(f"✅ [efinance] {code} {period}min K线获取成功 ({len(df)}条)")
        return df
        
    except ImportError:
        logger.debug("efinance 未安装")
        return None
    except Exception as e:
        logger.debug(f"[efinance intraday] {code} 获取失败: {e}")
        return None


# ============ 公开 API ============

def get_intraday_kline(
    code: str,
    period: str = "5",
    days: int = 1,
    use_cache: bool = True,
) -> Optional[pd.DataFrame]:
    """
    获取分钟级 K 线数据（带缓存、多源容错）
    
    Args:
        code: 股票代码 (6位)
        period: K 线周期 "1" / "5" / "15" / "30" / "60"
        days: 获取天数
        use_cache: 是否使用缓存
        
    Returns:
        DataFrame with columns: datetime, open, high, low, close, volume, amount, pct_chg
        None if failed
    """
    if use_cache:
        cached = _get_cached(code, period)
        if cached is not None:
            return cached
    
    # 多源容错
    for fetcher in [_fetch_intraday_akshare, _fetch_intraday_efinance]:
        df = fetcher(code, period, days)
        if df is not None and not df.empty:
            _set_cache(code, period, df)
            return df
    
    logger.debug(f"[intraday] {code} 所有数据源均失败（可能为非交易时段，属正常）")
    return None


def analyze_intraday(code: str, period: str = "5") -> Dict[str, Any]:
    """
    分时数据分析：生成分时级别的量价特征摘要
    
    Returns:
        {
            'available': bool,
            'period': str,
            'bar_count': int,
            'intraday_trend': str,        # "分时上攻" / "分时下跌" / "分时震荡"
            'intraday_vwap': float,       # 分时 VWAP
            'vwap_position': str,         # "价格在VWAP上方" / "价格在VWAP下方"
            'volume_distribution': str,   # "早盘放量" / "尾盘放量" / "均匀"
            'large_bar_count': int,       # 大阳/大阴K线数量
            'momentum': str,             # "加速上涨" / "加速下跌" / "动能减弱" / "平稳"
            'summary': str,
        }
    """
    df = get_intraday_kline(code, period)
    
    result = {
        'available': False,
        'period': f'{period}min',
        'bar_count': 0,
        'intraday_trend': '',
        'intraday_vwap': 0.0,
        'vwap_position': '',
        'volume_distribution': '',
        'large_bar_count': 0,
        'momentum': '',
        'summary': '分时数据不可用',
    }
    
    if df is None or len(df) < 5:
        return result
    
    result['available'] = True
    result['bar_count'] = len(df)
    
    # 只分析今日数据
    today = datetime.now().date()
    today_df = df[df['datetime'].dt.date == today]
    if len(today_df) < 3:
        # 如果今天数据不足，用最近的数据
        today_df = df.tail(48)  # 约一天的5min K线
    
    if len(today_df) < 3:
        result['summary'] = '今日分时数据不足'
        return result
    
    closes = today_df['close'].values
    volumes = today_df['volume'].values
    
    # ---- 分时 VWAP ----
    if 'amount' in today_df.columns and today_df['amount'].sum() > 0 and today_df['volume'].sum() > 0:
        vwap = today_df['amount'].sum() / today_df['volume'].sum()
    else:
        vwap = (today_df['close'] * today_df['volume']).sum() / max(today_df['volume'].sum(), 1)
    result['intraday_vwap'] = round(float(vwap), 2)
    
    latest_price = float(closes[-1])
    result['vwap_position'] = '价格在VWAP上方' if latest_price > vwap else '价格在VWAP下方'
    
    # ---- 分时趋势 ----
    first_price = float(closes[0])
    mid_price = float(closes[len(closes) // 2])
    pct_change = (latest_price - first_price) / first_price * 100 if first_price > 0 else 0
    
    if pct_change > 0.5:
        result['intraday_trend'] = '分时上攻'
    elif pct_change < -0.5:
        result['intraday_trend'] = '分时下跌'
    else:
        result['intraday_trend'] = '分时震荡'
    
    # ---- 成交量分布 ----
    n = len(volumes)
    if n >= 6:
        first_third = volumes[:n // 3].sum()
        last_third = volumes[-n // 3:].sum()
        total = volumes.sum() if volumes.sum() > 0 else 1
        
        if first_third / total > 0.45:
            result['volume_distribution'] = '早盘放量'
        elif last_third / total > 0.45:
            result['volume_distribution'] = '尾盘放量'
        else:
            result['volume_distribution'] = '成交均匀'
    
    # ---- 大阳/大阴线计数 ----
    if 'open' in today_df.columns:
        body_pct = abs(today_df['close'] - today_df['open']) / today_df['open'].clip(lower=0.01) * 100
        result['large_bar_count'] = int((body_pct > 1.0).sum())
    
    # ---- 动能判断 ----
    if n >= 6:
        recent_half = closes[-n // 2:]
        first_half = closes[:n // 2]
        recent_vol = volumes[-n // 2:].mean()
        first_vol = volumes[:n // 2].mean() if volumes[:n // 2].mean() > 0 else 1
        
        price_accel = (float(recent_half[-1]) - float(recent_half[0])) - (float(first_half[-1]) - float(first_half[0]))
        vol_ratio = recent_vol / first_vol
        
        if price_accel > 0 and vol_ratio > 1.2:
            result['momentum'] = '加速上涨'
        elif price_accel < 0 and vol_ratio > 1.2:
            result['momentum'] = '加速下跌'
        elif abs(price_accel) < 0.01:
            result['momentum'] = '动能减弱'
        else:
            result['momentum'] = '平稳'
    
    # ---- 摘要 ----
    parts = [result['intraday_trend']]
    if result['vwap_position']:
        parts.append(result['vwap_position'])
    if result['volume_distribution']:
        parts.append(result['volume_distribution'])
    if result['momentum']:
        parts.append(result['momentum'])
    result['summary'] = '，'.join(parts)
    
    return result
