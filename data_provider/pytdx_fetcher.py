# -*- coding: utf-8 -*-
import logging
import re
import os
import threading
import pandas as pd
from contextlib import contextmanager
from typing import Optional, List, Tuple
from tenacity import retry, stop_after_attempt, wait_exponential

from .base import BaseFetcher, DataFetchError, STANDARD_COLUMNS

logger = logging.getLogger(__name__)

# === 全局锁：Pytdx 在高并发下也容易出现 Socket 竞争，加锁保平安 ===
_PYTDX_LOCK = threading.Lock()

def _is_us_code(stock_code: str) -> bool:
    return bool(re.match(r'^[A-Z]{1,5}(\.[A-Z])?$', stock_code.strip().upper()))

class PytdxFetcher(BaseFetcher):
    name = "PytdxFetcher"
    priority = int(os.getenv("PYTDX_PRIORITY", "1"))
    
    DEFAULT_HOSTS = [
        ("119.147.212.81", 7709),
        ("112.74.214.43", 7727),
        ("221.231.141.60", 7709),
        ("101.227.73.20", 7709), 
        ("14.215.128.18", 7709),
    ]
    
    def __init__(self, hosts: Optional[List[Tuple[str, int]]] = None):
        self._hosts = hosts or self.DEFAULT_HOSTS
        self._current_host_idx = 0
        self._stock_list_cache = None
        self._stock_name_cache = {}
    
    def _get_pytdx(self):
        try:
            from pytdx.hq import TdxHq_API
            return TdxHq_API
        except ImportError:
            return None
    
    @contextmanager
    def _pytdx_session(self):
        # 🔥 关键修改：加锁
        with _PYTDX_LOCK:
            TdxHq_API = self._get_pytdx()
            if TdxHq_API is None: raise DataFetchError("pytdx未安装")
            
            api = TdxHq_API()
            connected = False
            
            try:
                for i in range(len(self._hosts)):
                    host_idx = (self._current_host_idx + i) % len(self._hosts)
                    host, port = self._hosts[host_idx]
                    try:
                        if api.connect(host, port, time_out=5):
                            connected = True
                            self._current_host_idx = host_idx
                            break
                    except: continue
                
                if not connected: raise DataFetchError("无法连接通达信服务器")
                yield api
                
            finally:
                try: api.disconnect()
                except: pass
    
    def _get_market_code(self, stock_code: str) -> Tuple[int, str]:
        code = stock_code.strip()
        if code.startswith(('60', '68')): return 1, code
        return 0, code
    
    @retry(stop=stop_after_attempt(2))
    def _fetch_raw_data(self, stock_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        if _is_us_code(stock_code): return pd.DataFrame()
        market, code = self._get_market_code(stock_code)
        
        # 估算数量，宁多勿少
        count = 800 
        
        with self._pytdx_session() as api:
            data = api.get_security_bars(9, market, code, 0, count) # 9=日线
            if not data: return pd.DataFrame()
            
            df = api.to_df(data)
            df['datetime'] = pd.to_datetime(df['datetime'])
            df = df[(df['datetime'] >= start_date) & (df['datetime'] <= end_date)]
            return df
    
    def _normalize_data(self, df: pd.DataFrame, stock_code: str) -> pd.DataFrame:
        if df.empty: return df
        df = df.copy()
        df = df.rename(columns={'datetime': 'date', 'vol': 'volume'})
        
        if 'pct_chg' not in df.columns and 'close' in df.columns:
            df['pct_chg'] = df['close'].pct_change() * 100
            df['pct_chg'] = df['pct_chg'].fillna(0).round(2)
            
        df['code'] = stock_code
        for col in STANDARD_COLUMNS:
            if col not in df.columns: df[col] = 0
        return df[STANDARD_COLUMNS + ['code']]

    def get_stock_name(self, stock_code: str) -> Optional[str]:
        if stock_code in self._stock_name_cache: return self._stock_name_cache[stock_code]
        try:
            market, code = self._get_market_code(stock_code)
            with self._pytdx_session() as api:
                # 简单缓存策略
                if not self._stock_list_cache:
                    sz = api.get_security_list(0, 0)
                    sh = api.get_security_list(1, 0)
                    self._stock_list_cache = {}
                    for s in (sz or []) + (sh or []):
                        self._stock_list_cache[s['code']] = s['name']
                
                name = self._stock_list_cache.get(code)
                if name:
                    self._stock_name_cache[stock_code] = name
                    return name
        except: pass
        return None
