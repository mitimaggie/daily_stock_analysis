# -*- coding: utf-8 -*-
"""
===================================
数据源基类与管理器
===================================
"""

import logging
import random
import time
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional, List, Tuple, Dict, Any

import pandas as pd
from tenacity import retry, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)

STANDARD_COLUMNS = ['date', 'open', 'high', 'low', 'close', 'volume', 'amount', 'pct_chg']

class DataFetchError(Exception): pass
class RateLimitError(DataFetchError): pass
class DataSourceUnavailableError(DataFetchError): pass

class BaseFetcher(ABC):
    name: str = "BaseFetcher"
    priority: int = 99
    
    @abstractmethod
    def _fetch_raw_data(self, stock_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        pass
    
    @abstractmethod
    def _normalize_data(self, df: pd.DataFrame, stock_code: str) -> pd.DataFrame:
        pass

    def get_main_indices(self) -> Optional[List[Dict[str, Any]]]: return None
    def get_market_stats(self) -> Optional[Dict[str, Any]]: return None
    def get_sector_rankings(self, n: int = 5) -> Optional[Tuple[List[Dict], List[Dict]]]: return None
    def get_chip_distribution(self, stock_code: str): return None
    def get_stock_name(self, stock_code: str): return None
    def get_stock_list(self): return None

    def get_daily_data(self, stock_code: str, start_date: Optional[str] = None, end_date: Optional[str] = None, days: int = 30) -> pd.DataFrame:
        if end_date is None: end_date = datetime.now().strftime('%Y-%m-%d')
        if start_date is None:
            from datetime import timedelta
            start_dt = datetime.strptime(end_date, '%Y-%m-%d') - timedelta(days=days * 2 + 20)
            start_date = start_dt.strftime('%Y-%m-%d')
        
        try:
            raw_df = self._fetch_raw_data(stock_code, start_date, end_date)
            if raw_df is None or raw_df.empty:
                raise DataFetchError(f"[{self.name}] 未获取到数据")
            
            df = self._normalize_data(raw_df, stock_code)
            df = self._clean_data(df)
            df = self._calculate_indicators(df)
            
            logger.info(f"✅ [{self.name}] {stock_code} 获取成功 ({len(df)}条)")
            return df
        except Exception as e:
            raise DataFetchError(f"[{self.name}] {stock_code}: {str(e)}") from e
    
    def _clean_data(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        if 'date' in df.columns: 
            df['date'] = pd.to_datetime(df['date'])
            if df['date'].dt.tz is not None:
                df['date'] = df['date'].dt.tz_localize(None)

        for col in ['open', 'high', 'low', 'close', 'volume', 'amount', 'pct_chg']:
            if col in df.columns: df[col] = pd.to_numeric(df[col], errors='coerce')
        
        df = df.dropna(subset=['close'])
        df = df.sort_values('date', ascending=True).reset_index(drop=True)
        return df
    
    def _calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        if len(df) < 5: return df
        df = df.copy()
        df['ma5'] = df['close'].rolling(window=5).mean()
        df['ma10'] = df['close'].rolling(window=10).mean()
        df['ma20'] = df['close'].rolling(window=20).mean()
        avg_vol = df['volume'].rolling(window=5).mean().shift(1)
        df['volume_ratio'] = df['volume'] / avg_vol
        df['volume_ratio'] = df['volume_ratio'].fillna(1.0).round(2)
        return df
    
    @staticmethod
    def random_sleep(min_seconds: float = 1.0, max_seconds: float = 3.0) -> None:
        time.sleep(random.uniform(min_seconds, max_seconds))


class DataFetcherManager:
    def __init__(self, fetchers: Optional[List[BaseFetcher]] = None):
        self._fetchers: List[BaseFetcher] = []
        self._chip_cache = {} 
        self._stock_name_cache = {}
        self._init_default_fetchers()
    
    def _init_default_fetchers(self) -> None:
        from .efinance_fetcher import EfinanceFetcher
        from .akshare_fetcher import AkshareFetcher
        from .tushare_fetcher import TushareFetcher
        from .pytdx_fetcher import PytdxFetcher
        from .baostock_fetcher import BaostockFetcher
        from .yfinance_fetcher import YfinanceFetcher
        
        akshare = AkshareFetcher()
        efinance = EfinanceFetcher()
        baostock = BaostockFetcher()
        tushare = TushareFetcher()
        yfinance = YfinanceFetcher()
        pytdx = PytdxFetcher()
        
        # 推荐顺序
        akshare.priority = 0
        efinance.priority = 1
        baostock.priority = 2
        tushare.priority = 3
        yfinance.priority = 4
        pytdx.priority = 5

        self._fetchers = [akshare, efinance, baostock, tushare, yfinance, pytdx]
        self._fetchers.sort(key=lambda f: f.priority)
        
        logger.info(f"🚀 数据源加载顺序: {', '.join([f.name for f in self._fetchers])}")

    def get_daily_data(self, stock_code: str, **kwargs) -> Tuple[pd.DataFrame, str]:
        errors = []
        for fetcher in self._fetchers:
            try:
                df = fetcher.get_daily_data(stock_code, **kwargs)
                if df is not None and not df.empty:
                    return df, fetcher.name
            except Exception as e:
                errors.append(f"{fetcher.name}: {e}")
                continue
        logger.error(f"❌ 所有数据源均失败 {stock_code}: {errors}")
        raise DataFetchError(f"所有源失败: {stock_code}")
    
    def get_merged_data(self, code: str, days: int = 120) -> pd.DataFrame:
        """
        【核心方法】获取"缝合后"的 K 线数据
        逻辑：本地数据库历史 + 实时行情快照 = 包含今天的完整 DataFrame
        """
        # 1. 尝试从本地数据库读取历史底座
        from src.storage import get_db
        db = get_db()
        df_history = db.get_stock_history_df(code, days=days)
        
        # 如果数据库完全没数据（新关注的股），只能走老路子去网上抓全量
        if df_history.empty:
            logger.info(f"[{code}] 本地无数据，执行全量抓取...")
            df_new, _ = self.get_daily_data(code, days=days)
            return df_new

        # 2. 获取实时行情快照 (Snapshot)
        realtime_quote = self.get_realtime_quote(code)
        if not realtime_quote:
            logger.warning(f"[{code}] 无法获取实时行情，仅返回历史数据")
            return df_history

        # 3. 判断是否需要缝合
        # 逻辑：如果实时行情的日期 > 历史数据的最后一天，说明是新的一天（或者今天是交易日且正在盘中）
        try:
            if not df_history.empty:
                last_date = df_history.iloc[-1]['date'].date()
                today_date = datetime.now().date()
                
                # 简单判断：如果历史数据的最后一天不是今天，尝试缝合
                if last_date < today_date:
                    # 构造今天的 K 线行 (Mock Bar)
                    today_row = self._create_mock_bar(realtime_quote, df_history)
                    if today_row is not None:
                        # 拼接到最后
                        df_merged = pd.concat([df_history, today_row], ignore_index=True)
                        return df_merged
        except Exception as e:
            logger.error(f"[{code}] 数据缝合判断异常: {e}")
        
        # 如果无需缝合，直接返回历史
        return df_history

    def _create_mock_bar(self, quote, df_history: pd.DataFrame) -> Optional[pd.DataFrame]:
        """
        构造"虚拟 K 线" (Mock Bar)
        在此处解决盘中成交量失真的问题
        """
        try:
            # 1. 基础数据映射
            now = datetime.now()
            # 转换时间：如果现在是盘前(比如9:25前)，不要生成今天的K线
            if now.hour < 9 or (now.hour == 9 and now.minute < 25):
                return None

            # 2. 核心：成交量预测 (Virtual Volume)
            # 公式：当前量 / (已开盘分钟数 / 240)
            current_volume = quote.volume if quote.volume else 0
            predicted_volume = current_volume 
            
            # 计算开盘分钟数 (A股: 9:30-11:30, 13:00-15:00)
            minutes_elapsed = 0
            if 9 <= now.hour < 15:
                # 这是一个简化的估算，足够用于量比分析
                morning_minutes = max(0, min(120, (now.hour - 9) * 60 + now.minute - 30)) if now.hour < 12 else 120
                afternoon_minutes = max(0, min(120, (now.hour - 13) * 60 + now.minute)) if now.hour >= 13 else 0
                minutes_elapsed = morning_minutes + afternoon_minutes
                
                # 只有在开盘后超过10分钟才做预测，且防止除零
                if minutes_elapsed > 10:
                    projection_factor = 240 / minutes_elapsed
                    predicted_volume = current_volume * projection_factor
            
            # 3. 构造 DataFrame 行
            data = {
                'date': [pd.Timestamp(now.date())],
                'open': [quote.open_price],
                'high': [quote.high],
                'low': [quote.low],
                'close': [quote.price],
                'volume': [predicted_volume], # 使用预测量用于指标计算
                'amount': [quote.amount],
                'pct_chg': [quote.change_pct],
                'volume_ratio': [quote.volume_ratio if quote.volume_ratio else 0.0] # 显式传递量比
            }
            return pd.DataFrame(data)
            
        except Exception as e:
            logger.error(f"构造虚拟K线失败: {e}")
            return None

    def prefetch_realtime_quotes(self, stock_codes: List[str]) -> int:
        from src.config import get_config
        if not get_config().enable_realtime_quote: return 0
        if len(stock_codes) < 5: return 0
        try:
            self.get_realtime_quote(stock_codes[0])
            return len(stock_codes)
        except: return 0

    def get_realtime_quote(self, stock_code: str):
        from .akshare_fetcher import _is_us_code
        from src.config import get_config
        
        config = get_config()
        if not config.enable_realtime_quote: return None
        
        if _is_us_code(stock_code):
            for f in self._fetchers:
                if f.name == 'YfinanceFetcher' and hasattr(f, 'get_realtime_quote'):
                    return f.get_realtime_quote(stock_code)
            return None

        # 🔥 读取配置中的优先级
        priorities = config.realtime_source_priority.split(',')
        
        for source in priorities:
            source = source.strip()
            try:
                if 'akshare' in source:
                    fetcher = next((f for f in self._fetchers if f.name == 'AkshareFetcher'), None)
                    if fetcher:
                        sub_source = source.split('_')[1] if '_' in source else 'sina'
                        q = fetcher.get_realtime_quote(stock_code, source=sub_source)
                        if q: return q
                elif source == 'efinance':
                    fetcher = next((f for f in self._fetchers if f.name == 'EfinanceFetcher'), None)
                    if fetcher:
                        q = fetcher.get_realtime_quote(stock_code)
                        if q: return q
            except Exception: continue
        return None

    def get_chip_distribution(self, stock_code: str):
        from .realtime_types import get_chip_circuit_breaker
        from src.config import get_config
        
        # 🔥 读取配置中的开关
        if not get_config().enable_chip_distribution: return None
        if stock_code in self._chip_cache: return self._chip_cache[stock_code]
        
        circuit_breaker = get_chip_circuit_breaker()
        for fetcher in self._fetchers:
            source_key = f"{fetcher.name}_chip"
            if not circuit_breaker.is_available(source_key): continue
            
            if hasattr(fetcher, 'get_chip_distribution'):
                try:
                    chip = fetcher.get_chip_distribution(stock_code)
                    if chip:
                        circuit_breaker.record_success(source_key)
                        self._chip_cache[stock_code] = chip
                        return chip
                except Exception as e:
                    circuit_breaker.record_failure(source_key, str(e))
                    continue
        return None

    def get_stock_name(self, stock_code: str) -> Optional[str]:
        if stock_code in self._stock_name_cache: return self._stock_name_cache[stock_code]
        q = self.get_realtime_quote(stock_code)
        if q and q.name:
            self._stock_name_cache[stock_code] = q.name
            return q.name
        for f in self._fetchers:
            if hasattr(f, 'get_stock_name'):
                try:
                    name = f.get_stock_name(stock_code)
                    if name:
                        self._stock_name_cache[stock_code] = name
                        return name
                except: continue
        return stock_code
        
    def batch_get_stock_names(self, stock_codes: List[str]) -> Dict[str, str]:
        res = {}
        for code in stock_codes:
            name = self.get_stock_name(code)
            if name: res[code] = name
        return res
    
    def get_main_indices(self):
        for f in self._fetchers:
            try:
                res = f.get_main_indices()
                if res: return res
            except: continue
        return []

    def get_market_stats(self):
        for f in self._fetchers:
            try:
                res = f.get_market_stats()
                if res: return res
            except: continue
        return {}

    def get_sector_rankings(self, n=5):
        for f in self._fetchers:
            try:
                res = f.get_sector_rankings(n)
                if res: return res
            except: continue
        return [], []
