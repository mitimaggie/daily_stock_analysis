# -*- coding: utf-8 -*-
"""
TencentFetcher - 腾讯行情数据源
================================
数据来源：腾讯行情 API（web.ifzq.gtimg.cn / qt.gtimg.cn）

特点：
- 免费、稳定、不限流
- 支持日K/周K/月K、前复权
- 支持个股实时行情
- 支持上证/深成/创业板指数
- 不支持美股
"""

import logging
import re
import time
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd
import requests

from .base import BaseFetcher, DataFetchError, STANDARD_COLUMNS

logger = logging.getLogger(__name__)

_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Referer': 'https://gu.qq.com/',
}

# 腾讯 K 线 URL
_KLINE_URL = 'https://web.ifzq.gtimg.cn/appstock/app/fqkline/get'
# 腾讯实时行情 URL
_REALTIME_URL = 'https://qt.gtimg.cn/q={symbols}'


def _to_tencent_code(code: str) -> str:
    """将6位股票代码转为腾讯格式（sh600519 / sz000001）"""
    c = code.strip()
    if c.startswith(('sh', 'sz', 'hk')):
        return c
    if c.startswith(('6', '5', '9', '688')):
        return f'sh{c}'
    if c.startswith(('0', '1', '2', '3')):
        return f'sz{c}'
    return f'sz{c}'


def _is_index(code: str) -> bool:
    """判断是否为指数代码"""
    c = code.lstrip('sh').lstrip('sz').lstrip('SH').lstrip('SZ')
    return c.startswith(('000', '399', '880', '881', '882', '883'))


class TencentFetcher(BaseFetcher):
    """腾讯行情 K 线数据源

    优先级设为 1.5，介于 Baostock(0) 和 Akshare(1) 之间，
    在 efinance K 线被封后作为最稳定的备用 HTTP 源。
    """

    name = "TencentFetcher"
    priority = 2  # 与 efinance 同级，替代 efinance K线

    _session: Optional[requests.Session] = None

    def _get_session(self) -> requests.Session:
        if self._session is None:
            self._session = requests.Session()
            self._session.headers.update(_HEADERS)
        return self._session

    def _to_tencent_code(self, code: str) -> str:
        return _to_tencent_code(code)

    def _fetch_raw_data(self, stock_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """调用腾讯 K 线接口，返回标准化前的 DataFrame"""
        tc = self._to_tencent_code(stock_code)

        # 腾讯接口最多返回 500 条，计算需要的条数
        try:
            d0 = datetime.strptime(start_date, '%Y-%m-%d')
            d1 = datetime.strptime(end_date, '%Y-%m-%d')
            days_needed = max(int((d1 - d0).days * 1.5) + 50, 250)
            days_needed = min(days_needed, 500)
        except Exception:
            days_needed = 300

        params = {
            'param': f'{tc},day,{start_date},{end_date},{days_needed},qfq',
        }

        try:
            session = self._get_session()
            r = session.get(_KLINE_URL, params=params, timeout=8)
            r.raise_for_status()
            data = r.json()
        except requests.exceptions.ConnectionError as e:
            raise DataFetchError(f"[TencentFetcher] 连接失败: {e}") from e
        except Exception as e:
            raise DataFetchError(f"[TencentFetcher] 请求异常: {e}") from e

        stock_data = data.get('data', {}).get(tc, {})
        # 前复权用 qfqday，无复权用 day
        rows = stock_data.get('qfqday') or stock_data.get('day') or []

        if not rows:
            raise DataFetchError(f"[TencentFetcher] {stock_code}({tc}) 返回空数据")

        # 腾讯格式: [日期, 开, 收, 高, 低, 量] 或 [日期, 开, 收, 高, 低, 量, 涨幅, ...]
        records = []
        for row in rows:
            try:
                if len(row) < 6:
                    continue
                date_str = row[0]  # '2026-02-27'
                open_ = float(row[1])
                close_ = float(row[2])
                high_ = float(row[3])
                low_ = float(row[4])
                vol = float(row[5])
                records.append({
                    'date': date_str,
                    'open': open_,
                    'close': close_,
                    'high': high_,
                    'low': low_,
                    'volume': vol,
                })
            except (ValueError, IndexError):
                continue

        if not records:
            raise DataFetchError(f"[TencentFetcher] {stock_code} 数据解析失败")

        df = pd.DataFrame(records)
        return df

    def _normalize_data(self, df: pd.DataFrame, stock_code: str) -> pd.DataFrame:
        """归一化为标准列格式"""
        df = df.copy()
        df['date'] = pd.to_datetime(df['date'])

        # 计算 pct_chg
        df = df.sort_values('date').reset_index(drop=True)
        df['pct_chg'] = df['close'].pct_change() * 100

        # 填充 amount（腾讯无成交额，用 close * volume 近似）
        if 'amount' not in df.columns:
            df['amount'] = df['close'] * df['volume']

        # 确保标准列存在
        for col in STANDARD_COLUMNS:
            if col not in df.columns:
                df[col] = 0.0

        return df[STANDARD_COLUMNS + [c for c in df.columns if c not in STANDARD_COLUMNS]]

    def get_stock_name(self, stock_code: str) -> Optional[str]:
        """通过腾讯实时行情获取股票名称"""
        try:
            tc = self._to_tencent_code(stock_code)
            r = self._get_session().get(
                f'https://qt.gtimg.cn/q={tc}',
                timeout=4
            )
            text = r.text
            parts = text.split('~')
            if len(parts) >= 2:
                return parts[1].strip()
        except Exception:
            pass
        return None
