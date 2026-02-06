# -*- coding: utf-8 -*-
import logging
import re
import os
import threading
import atexit
from contextlib import contextmanager
from typing import Optional
import pandas as pd
from tenacity import retry, stop_after_attempt, wait_exponential

from .base import BaseFetcher, DataFetchError, STANDARD_COLUMNS

logger = logging.getLogger(__name__)

# === 全局锁 ===
_BS_LOCK = threading.Lock()
# === 全局登录状态标记 ===
_BS_LOGGED_IN = False

def _cleanup_baostock():
    """程序退出时清理连接"""
    import baostock as bs
    try:
        bs.logout()
    except:
        pass

# 注册退出时的清理函数
atexit.register(_cleanup_baostock)

def _is_us_code(stock_code: str) -> bool:
    return bool(re.match(r'^[A-Z]{1,5}(\.[A-Z])?$', stock_code.strip().upper()))

class BaostockFetcher(BaseFetcher):
    name = "BaostockFetcher"
    priority = 0
    
    def __init__(self):
        self._bs_module = None
    
    def _get_baostock(self):
        if self._bs_module is None:
            import baostock as bs
            self._bs_module = bs
        return self._bs_module
    
    @contextmanager
    def _baostock_session(self):
        """
        管理 Baostock 会话 (长连接模式)
        """
        global _BS_LOGGED_IN
        
        # 加锁防止多线程竞争
        with _BS_LOCK:
            bs = self._get_baostock()
            
            # 如果没登录，或者连接似乎断了，尝试登录
            if not _BS_LOGGED_IN:
                try:
                    lg = bs.login()
                    if lg.error_code == '0':
                        _BS_LOGGED_IN = True
                        logger.info(f"[Baostock] 登录成功")
                    else:
                        logger.warning(f"[Baostock] 登录失败: {lg.error_msg}")
                except Exception as e:
                    logger.warning(f"[Baostock] 登录异常: {e}")

            # 直接 yield bs，不要在 finally 里 logout！
            yield bs
            
            # 注意：这里去掉了 logout()，保持连接活跃
            # 只有在程序彻底退出时 (atexit) 才执行 logout

    def _convert_code(self, code: str) -> str:
        code = code.strip()
        if '.' in code: return code.lower()
        if code.startswith(('6', '5', '9', '688')): return f"sh.{code}"
        else: return f"sz.{code}"

    @retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=1, min=2, max=5))
    def _fetch_raw_data(self, stock_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        if _is_us_code(stock_code): return pd.DataFrame()
        bs_code = self._convert_code(stock_code)
        
        with self._baostock_session() as bs:
            # 尝试获取数据
            rs = bs.query_history_k_data_plus(
                code=bs_code,
                fields="date,open,high,low,close,volume,amount,pctChg",
                start_date=start_date,
                end_date=end_date,
                frequency="d",
                adjustflag="2"
            )
            
            # 如果查询失败（可能是连接超时），尝试强制重连一次
            if rs.error_code != '0':
                logger.warning(f"[Baostock] 获取 {stock_code} 失败: {rs.error_msg}，尝试重连...")
                global _BS_LOGGED_IN
                try:
                    bs.logout()
                except: pass
                _BS_LOGGED_IN = False # 标记为未登录，下次循环会自动重登
                return pd.DataFrame()
            
            data_list = []
            while rs.next():
                data_list.append(rs.get_row_data())
            
            if not data_list: 
                return pd.DataFrame()
                
            return pd.DataFrame(data_list, columns=rs.fields)

    def _normalize_data(self, df: pd.DataFrame, stock_code: str) -> pd.DataFrame:
        if df.empty: return df
        df = df.copy()
        df = df.rename(columns={'pctChg': 'pct_chg'})
        for col in ['open', 'high', 'low', 'close', 'volume', 'amount', 'pct_chg']:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')
        df['code'] = stock_code
        for col in STANDARD_COLUMNS:
            if col not in df.columns: df[col] = 0
        return df[STANDARD_COLUMNS + ['code']]

    def get_stock_name(self, stock_code: str) -> Optional[str]:
        try:
            bs_code = self._convert_code(stock_code)
            with self._baostock_session() as bs:
                rs = bs.query_stock_basic(code=bs_code)
                if rs.error_code == '0' and rs.next():
                    row = rs.get_row_data()
                    if len(row) > 1: return row[1]
        except: pass
        return None
