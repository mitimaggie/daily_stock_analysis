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
    def get_stock_belong_board(self, stock_code: str): return None
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

        # 3. 判断是否需要缝合 / 更新
        try:
            if not df_history.empty:
                last_date = df_history.iloc[-1]['date'].date()
                today_date = datetime.now().date()
                
                if last_date < today_date:
                    # 3a. 今天的数据尚未入库 → 构造 Mock Bar 拼接
                    today_row = self._create_mock_bar(realtime_quote, df_history)
                    if today_row is not None:
                        df_merged = pd.concat([df_history, today_row], ignore_index=True)
                        return df_merged
                elif last_date == today_date:
                    # 3b. 今天的数据已在 DB 中（之前的 run 写入），但可能已过时
                    #     用最新实时行情刷新最后一行，保证技术分析和报告数据是最新的
                    if realtime_quote.price and realtime_quote.price > 0:
                        df_history = df_history.copy()
                        idx = df_history.index[-1]
                        df_history.loc[idx, 'close'] = realtime_quote.price
                        if realtime_quote.high and realtime_quote.high > 0:
                            df_history.loc[idx, 'high'] = max(float(df_history.loc[idx, 'high'] or 0), realtime_quote.high)
                        if realtime_quote.low and realtime_quote.low > 0:
                            cur_low = float(df_history.loc[idx, 'low'] or 999999)
                            df_history.loc[idx, 'low'] = min(cur_low, realtime_quote.low) if cur_low > 0 else realtime_quote.low
                        if realtime_quote.volume and realtime_quote.volume > 0:
                            elapsed_w = self._calc_elapsed_weight()
                            if elapsed_w > 0.03:
                                df_history.loc[idx, 'volume'] = realtime_quote.volume / elapsed_w
                        if realtime_quote.amount and realtime_quote.amount > 0:
                            df_history.loc[idx, 'amount'] = realtime_quote.amount
                        if realtime_quote.change_pct is not None:
                            df_history.loc[idx, 'pct_chg'] = realtime_quote.change_pct
                        logger.debug(f"[{code}] 已用实时行情刷新今日K线 (close={realtime_quote.price})")
                        return df_history
        except Exception as e:
            logger.error(f"[{code}] 数据缝合判断异常: {e}")
        
        # 如果无需缝合，直接返回历史
        return df_history

    # A 股日内成交量分布权重 (U 型曲线，每 30 分钟一段，共 8 段)
    # 数据来源：万得统计 A 股典型交易日分钟级成交量分布
    # 早盘集合竞价+前 30min 占比高、午后缩量、尾盘冲量
    _VOLUME_WEIGHT_SLOTS = [
        (9*60+30,  10*60,  0.18),   # 09:30-10:00  开盘冲量 18%
        (10*60,    10*60+30, 0.13), # 10:00-10:30  13%
        (10*60+30, 11*60,  0.10),   # 10:30-11:00  10%
        (11*60,    11*60+30, 0.09), # 11:00-11:30  尾盘 9%
        (13*60,    13*60+30, 0.10), # 13:00-13:30  午后 10%
        (13*60+30, 14*60,  0.10),   # 13:30-14:00  10%
        (14*60,    14*60+30, 0.12), # 14:00-14:30  12%
        (14*60+30, 15*60,  0.18),   # 14:30-15:00  尾盘冲量 18%
    ]

    def _calc_elapsed_weight(self) -> float:
        """计算当前时间点已消耗的成交量权重占比 (0.0~1.0)"""
        now = datetime.now()
        t = now.hour * 60 + now.minute
        total_w = 0.0
        for start, end, w in self._VOLUME_WEIGHT_SLOTS:
            if t >= end:
                total_w += w       # 整段已过
            elif t > start:
                # 段内按线性插值
                total_w += w * (t - start) / (end - start)
            # t < start 说明这段还没开始
        return min(total_w, 1.0)

    def _create_mock_bar(self, quote, df_history: pd.DataFrame) -> Optional[pd.DataFrame]:
        """
        构造"虚拟 K 线" (Mock Bar)
        使用 U 型曲线权重预测全天成交量，解决盘中量比失真问题
        """
        try:
            now = datetime.now()
            # 盘前不生成今天的 K 线
            if now.hour < 9 or (now.hour == 9 and now.minute < 25):
                return None

            current_volume = quote.volume if quote.volume else 0
            predicted_volume = current_volume

            # U 型曲线成交量预测
            elapsed_weight = self._calc_elapsed_weight()
            if elapsed_weight > 0.03:  # 至少交易了 ~4 分钟才做预测
                predicted_volume = current_volume / elapsed_weight

            # 用 price 兜底缺失的 OHLC（部分数据源不提供完整的 open/high/low）
            price = quote.price or 0
            data = {
                'date': [pd.Timestamp(now.date())],
                'open': [quote.open_price if quote.open_price and quote.open_price > 0 else price],
                'high': [quote.high if quote.high and quote.high > 0 else price],
                'low': [quote.low if quote.low and quote.low > 0 else price],
                'close': [price],
                'volume': [predicted_volume],
                'amount': [quote.amount if quote.amount else 0],
                'pct_chg': [quote.change_pct if quote.change_pct is not None else 0],
                'volume_ratio': [quote.volume_ratio if quote.volume_ratio else 0.0]
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
                if source == 'tencent':
                    # 腾讯行情：量比/换手率/PE/PB 最全，推荐第一优先
                    fetcher = next((f for f in self._fetchers if f.name == 'AkshareFetcher'), None)
                    if fetcher:
                        q = fetcher.get_realtime_quote(stock_code, source='tencent')
                        if q: return q
                elif 'akshare' in source:
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

    def get_chip_distribution(self, stock_code: str, force_fetch: bool = False):
        from .realtime_types import get_chip_circuit_breaker, ChipDistribution
        from src.config import get_config
        from src.storage import DatabaseManager

        config = get_config()
        if stock_code in self._chip_cache:
            return self._chip_cache[stock_code]

        # 1) 先查 DB 缓存（在 chip_cache_hours 内直接复用，不请求不稳定接口）
        try:
            db = DatabaseManager()
            cache_hours = getattr(config, 'chip_cache_hours', 24.0)
            cached = db.get_chip_cached(stock_code, max_age_hours=cache_hours)
            if cached:
                chip = ChipDistribution(
                    code=cached['code'],
                    date=cached.get('date', ''),
                    source=cached.get('source', 'akshare'),
                    profit_ratio=cached.get('profit_ratio', 0.0),
                    avg_cost=cached.get('avg_cost', 0.0),
                    cost_90_low=cached.get('cost_90_low', 0.0),
                    cost_90_high=cached.get('cost_90_high', 0.0),
                    concentration_90=cached.get('concentration_90', 0.0),
                    cost_70_low=cached.get('cost_70_low', 0.0),
                    cost_70_high=cached.get('cost_70_high', 0.0),
                    concentration_70=cached.get('concentration_70', 0.0),
                )
                self._chip_cache[stock_code] = chip
                return chip
        except Exception:
            pass

        # 2) 仅用缓存模式（定时 --chip-only 已写入缓存，分析时不再实时拉取）
        if getattr(config, 'chip_fetch_only_from_cache', False) and not force_fetch:
            return None
        if not config.enable_chip_distribution and not force_fetch:
            return None

        # 3) 实时拉取并落库
        circuit_breaker = get_chip_circuit_breaker()
        for fetcher in self._fetchers:
            source_key = f"{fetcher.name}_chip"
            if not circuit_breaker.is_available(source_key):
                continue
            if hasattr(fetcher, 'get_chip_distribution'):
                try:
                    try:
                        chip = fetcher.get_chip_distribution(stock_code, force_fetch=force_fetch)
                    except TypeError:
                        chip = fetcher.get_chip_distribution(stock_code)
                    if chip:
                        circuit_breaker.record_success(source_key)
                        self._chip_cache[stock_code] = chip
                        try:
                            db = DatabaseManager()
                            db.save_chip_distribution(
                                code=stock_code,
                                chip_date=chip.date,
                                source=chip.source,
                                profit_ratio=chip.profit_ratio,
                                avg_cost=chip.avg_cost,
                                concentration_90=chip.concentration_90,
                                concentration_70=chip.concentration_70,
                                cost_90_low=getattr(chip, 'cost_90_low', 0.0),
                                cost_90_high=getattr(chip, 'cost_90_high', 0.0),
                                cost_70_low=getattr(chip, 'cost_70_low', 0.0),
                                cost_70_high=getattr(chip, 'cost_70_high', 0.0),
                            )
                        except Exception:
                            pass
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

    def get_stock_sector_context(self, stock_code: str, stock_pct_chg: Optional[float] = None) -> Optional[Dict[str, Any]]:
        """获取个股所属板块及相对强弱（板块今日涨跌 vs 个股涨跌）"""
        for f in self._fetchers:
            try:
                if not hasattr(f, 'get_stock_belong_board') and not hasattr(f, 'get_belong_board'):
                    continue
                get_board = getattr(f, 'get_stock_belong_board', None) or getattr(f, 'get_belong_board', None)
                if not get_board:
                    continue
                df = get_board(stock_code)
                if df is None or df.empty:
                    continue
                row = df.iloc[0]
                name = None
                for col in ['板块名称', '名称', 'name', '板块']:
                    if col in row.index and pd.notna(row.get(col)):
                        name = str(row[col]).strip()
                        break
                sector_pct = None
                for col in ['涨跌幅', '涨跌幅度', 'change_pct', '日涨跌幅']:
                    if col in row.index and pd.notna(row.get(col)):
                        try:
                            sector_pct = float(row[col])
                            break
                        except (ValueError, TypeError):
                            pass
                rel = None
                if stock_pct_chg is not None and sector_pct is not None:
                    rel = round(stock_pct_chg - sector_pct, 2)
                return {'sector_name': name or '未知', 'sector_pct': sector_pct, 'stock_pct': stock_pct_chg, 'relative': rel}
            except Exception:
                continue
        return None
