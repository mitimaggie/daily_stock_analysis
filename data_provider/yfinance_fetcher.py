# -*- coding: utf-8 -*-
import logging
import re
import time
import random
from datetime import datetime
from typing import Optional

import pandas as pd
from tenacity import retry, stop_after_attempt, wait_fixed

from .base import BaseFetcher, DataFetchError, STANDARD_COLUMNS
import os

logger = logging.getLogger(__name__)

class YfinanceFetcher(BaseFetcher):
    name = "YfinanceFetcher"
    priority = 4
    
    def _convert_stock_code(self, stock_code: str) -> str:
        """
        转换为 Yahoo Finance 格式:
        600519 -> 600519.SS
        000001 -> 000001.SZ
        AAPL -> AAPL
        """
        code = stock_code.strip().upper()
        # 美股直接返回
        if re.match(r'^[A-Z]{1,5}(\.[A-Z])?$', code): return code
        
        # 港股
        if code.startswith('HK'): return f"{code[2:].lstrip('0').zfill(4)}.HK"
        
        # A股
        if '.' in code: # 已经有后缀
             if code.endswith('.SH'): return code.replace('.SH', '.SS') # Yahoo用SS
             return code
        
        if code.startswith(('6', '5', '9')): return f"{code}.SS"
        return f"{code}.SZ"

    @retry(stop=stop_after_attempt(3), wait=wait_fixed(2))
    def _fetch_raw_data(self, stock_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        import yfinance as yf
        
        # 降速
        self.random_sleep(1.0, 2.0)
        
        yf_code = self._convert_stock_code(stock_code)
        
        try:
            # auto_adjust=True 自动复权
            df = yf.download(
                tickers=yf_code,
                start=start_date,
                end=end_date,
                progress=False,
                auto_adjust=True,
                timeout=10
            )
            
            if df.empty:
                raise DataFetchError("Yfinance数据为空")
                
            return df
        except Exception as e:
            raise DataFetchError(f"Yfinance异常: {e}")

    def _normalize_data(self, df: pd.DataFrame, stock_code: str) -> pd.DataFrame:
        if df.empty: return df
        df = df.copy()
        
        # 1. 处理 yfinance 新版返回的 MultiIndex 列名 (Price, Ticker)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        
        # 2. 索引变列
        df = df.reset_index()
        
        # 3. 映射
        mapping = {
            'Date': 'date', 'Open': 'open', 'High': 'high', 
            'Low': 'low', 'Close': 'close', 'Volume': 'volume'
        }
        df = df.rename(columns=mapping)
        
        # 4. 关键：去除时区，否则和 A 股数据合并时会报错
        if 'date' in df.columns and df['date'].dt.tz is not None:
             df['date'] = df['date'].dt.tz_localize(None)

        # 5. 计算缺失列
        if 'pct_chg' not in df.columns:
            df['pct_chg'] = df['close'].pct_change() * 100
            df['pct_chg'] = df['pct_chg'].fillna(0).round(2)
            
        if 'amount' not in df.columns:
            df['amount'] = df['close'] * df['volume']

        df['code'] = stock_code
        
        # 过滤需要的列
        cols = [c for c in STANDARD_COLUMNS if c in df.columns]
        return df[cols + ['code']]
