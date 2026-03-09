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
from data_provider.analysis_types import SectorContext
from tenacity import retry, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)

STANDARD_COLUMNS = ['date', 'open', 'high', 'low', 'close', 'volume', 'amount', 'pct_chg']


def normalize_stock_code(stock_code: str) -> str:
    """
    归一化股票代码，去除交易所前缀/后缀。

    支持格式：
    - '600519'      -> '600519'  (已是纯净格式)
    - 'SH600519'    -> '600519'  (去除 SH 前缀)
    - 'SZ000001'    -> '000001'  (去除 SZ 前缀)
    - '600519.SH'   -> '600519'  (去除 .SH 后缀)
    - '000001.SZ'   -> '000001'  (去除 .SZ 后缀)
    - 'AAPL'        -> 'AAPL'    (美股代码保持不变)
    - 'HK00700'     -> 'HK00700' (港股代码保持不变)
    """
    code = (stock_code or '').strip()
    upper = code.upper()

    # 去除 SH/SZ 前缀（如 SH600519 -> 600519）
    if upper.startswith(('SH', 'SZ')) and not upper.startswith(('SH.', 'SZ.')):
        candidate = code[2:]
        if candidate.isdigit() and len(candidate) in (5, 6):
            return candidate

    # 去除 .SH/.SZ/.SS 后缀（如 600519.SH -> 600519）
    if '.' in code:
        base, suffix = code.rsplit('.', 1)
        if suffix.upper() in ('SH', 'SZ', 'SS') and base.isdigit():
            return base

    return code


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

    def get_sector_rankings(self, n: int = 5) -> Optional[Tuple[List[Dict], List[Dict]]]: return None
    def get_stock_belong_board(self, stock_code: str): return None
    def get_chip_distribution(self, stock_code: str): return None
    def get_stock_name(self, stock_code: str): return None

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
    def __init__(self):
        self._fetchers: List[BaseFetcher] = []
        self._chip_cache = {} 
        self._stock_name_cache = {}
        self._init_default_fetchers()
    
    def _init_default_fetchers(self) -> None:
        from .akshare_fetcher import AkshareFetcher
        from .pytdx_fetcher import PytdxFetcher
        from .baostock_fetcher import BaostockFetcher
        from .yfinance_fetcher import YfinanceFetcher
        from .tencent_fetcher import TencentFetcher
        
        # 注意：EfinanceFetcher 已被移除。
        # 原因：import efinance 会在后台触发全量 817 支股票数据下载，耗时数分钟，
        # 严重阻塞分析任务。akshare/baostock/tencent 可以替代其所有核心功能。
        akshare = AkshareFetcher()
        baostock = BaostockFetcher()
        tencent = TencentFetcher()
        yfinance = YfinanceFetcher()
        pytdx = PytdxFetcher()
        
        baostock.priority = 0   # 首选：稳定、免费、不反爬、速度快
        akshare.priority = 1    # 备用：功能全，但批量易限流
        tencent.priority = 2    # 备用：腾讯K线
        yfinance.priority = 4   # 备用：美股首选，A股延迟
        pytdx.priority = 5      # 备用：需要TCP连接

        self._fetchers = [akshare, baostock, tencent, yfinance, pytdx]
        self._fetchers.sort(key=lambda f: f.priority)
        
        logger.debug(f"🚀 数据源加载顺序: {', '.join([f.name for f in self._fetchers])}")

    def get_daily_data(self, stock_code: str, **kwargs) -> Tuple[pd.DataFrame, str]:
        stock_code = normalize_stock_code(stock_code)
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
                # 健壮的日期解析（兼容 Timestamp/str/date 等类型）
                raw_date = df_history.iloc[-1]['date']
                if hasattr(raw_date, 'date'):
                    last_date = raw_date.date()
                else:
                    last_date = pd.Timestamp(str(raw_date)).date()
                today_date = datetime.now().date()
                
                if last_date < today_date:
                    # 3a. 今天的数据尚未入库 → 构造 Mock Bar 拼接
                    today_row = self._create_mock_bar(realtime_quote, df_history)
                    if today_row is not None:
                        df_merged = pd.concat([df_history, today_row], ignore_index=True)
                        return df_merged
                    else:
                        logger.warning(f"[{code}] Mock Bar 构造失败，回退到刷新最后一行")
                        # 回退：即使无法构造 Mock Bar，也要用实时价更新最后一行的 close
                        # 否则技术分析会用昨日收盘价，导致结论完全错误
                
                # 3b. 今天的数据已在 DB 中 或 Mock Bar 构造失败
                #     用最新实时行情刷新最后一行，保证技术分析和报告数据是最新的
                rt_price = float(realtime_quote.price or 0)
                if rt_price > 0:
                    df_history = df_history.copy()
                    idx = df_history.index[-1]
                    old_close = float(df_history.loc[idx, 'close'] or 0)
                    df_history.loc[idx, 'close'] = rt_price
                    if realtime_quote.high and realtime_quote.high > 0:
                        df_history.loc[idx, 'high'] = max(float(df_history.loc[idx, 'high'] or 0), realtime_quote.high)
                    if realtime_quote.low and realtime_quote.low > 0:
                        cur_low = float(df_history.loc[idx, 'low'] or 999999)
                        df_history.loc[idx, 'low'] = min(cur_low, realtime_quote.low) if cur_low > 0 else realtime_quote.low
                    if realtime_quote.volume and realtime_quote.volume > 0:
                        elapsed_w = self._calc_elapsed_weight()
                        yesterday_vol = None
                        if len(df_history) >= 2 and 'volume' in df_history.columns:
                            yesterday_vol = float(df_history.iloc[-2].get('volume', 0) or 0)
                            if yesterday_vol <= 0:
                                yesterday_vol = None
                        df_history.loc[idx, 'volume'] = self._predict_full_day_volume(
                            realtime_quote.volume, elapsed_w, yesterday_vol
                        )
                    if realtime_quote.amount and realtime_quote.amount > 0:
                        df_history.loc[idx, 'amount'] = realtime_quote.amount
                    if realtime_quote.change_pct is not None:
                        df_history.loc[idx, 'pct_chg'] = realtime_quote.change_pct
                    if abs(old_close - rt_price) > 0.01:
                        logger.info(f"[{code}] 实时价刷新K线: {old_close:.2f} → {rt_price:.2f} (last_date={last_date})")
                    return df_history
                else:
                    logger.warning(f"[{code}] 实时行情价格无效(price={realtime_quote.price})，返回未刷新的历史数据")
        except Exception as e:
            logger.error(f"[{code}] 数据缝合判断异常: {e}", exc_info=True)
        
        # 如果无需缝合，直接返回历史
        return df_history

    # 盘中成交量折算的最低可靠权重（约对应 10:00，已交易约 30 分钟）
    # 低于此阈值的折算会将实际成交量放大过多倍，导致量能指标严重失真
    MIN_RELIABLE_WEIGHT = 0.15

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

    def _predict_full_day_volume(self, current_volume: float, elapsed_w: float,
                                  yesterday_vol: Optional[float] = None) -> float:
        """
        三段式盘中成交量折算：
        - elapsed_w >= MIN_RELIABLE_WEIGHT: 正常折算
        - 0.03 < elapsed_w < MIN_RELIABLE_WEIGHT: 过渡区，与昨日成交量线性混合
        - elapsed_w <= 0.03: 不折算，返回原始 volume
        """
        if elapsed_w >= self.MIN_RELIABLE_WEIGHT:
            return current_volume / elapsed_w

        if elapsed_w > 0.03:
            alpha = (elapsed_w - 0.03) / (self.MIN_RELIABLE_WEIGHT - 0.03)
            projected = current_volume / elapsed_w
            if yesterday_vol is not None and yesterday_vol > 0:
                return alpha * projected + (1 - alpha) * yesterday_vol
            return current_volume

        return current_volume

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

            # 三段式成交量预测（避免开盘初期极小 elapsed_weight 导致量能放大失真）
            elapsed_weight = self._calc_elapsed_weight()
            yesterday_vol = None
            if not df_history.empty and 'volume' in df_history.columns:
                yesterday_vol = float(df_history.iloc[-1].get('volume', 0) or 0)
                if yesterday_vol <= 0:
                    yesterday_vol = None
            predicted_volume = self._predict_full_day_volume(current_volume, elapsed_weight, yesterday_vol)

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
        except Exception: return 0

    # 数据源补充机制：主数据源缺少的字段，自动从备用源补充（借鉴上游 #275）
    # 注意：只补充真正关键的字段，避免因可选字段缺失而触发额外请求导致被封
    _SUPPLEMENT_FIELDS_CRITICAL = [
        'volume_ratio', 'turnover_rate',  # 量化分析必需
        'pe_ratio', 'pb_ratio',           # 估值分析必需
    ]
    _SUPPLEMENT_FIELDS_OPTIONAL = [
        'total_mv', 'circ_mv', 'amplitude',  # 可选，缺失不影响核心分析
    ]

    @classmethod
    def _quote_needs_supplement(cls, quote) -> bool:
        """检查行情是否缺少关键补充字段（仅检查critical字段，避免过度请求）"""
        for f in cls._SUPPLEMENT_FIELDS_CRITICAL:
            if getattr(quote, f, None) is None:
                return True
        return False

    @classmethod
    def _merge_quote_fields(cls, primary, secondary) -> list:
        """将 secondary 中非 None 的字段补充到 primary 中缺失的字段，返回被填充的字段名列表"""
        filled = []
        all_fields = cls._SUPPLEMENT_FIELDS_CRITICAL + cls._SUPPLEMENT_FIELDS_OPTIONAL
        for f in all_fields:
            if getattr(primary, f, None) is None:
                val = getattr(secondary, f, None)
                if val is not None:
                    setattr(primary, f, val)
                    filled.append(f)
        return filled

    def get_realtime_quote(self, stock_code: str):
        stock_code = normalize_stock_code(stock_code)
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
        
        primary_quote = None
        supplement_attempts = 0
        MAX_SUPPLEMENT = 1  # 最多只尝试1个备用源补充，防止被封
        
        for source in priorities:
            source = source.strip()
            try:
                q = self._fetch_quote_from_source(stock_code, source)
                if q:
                    if primary_quote is None:
                        primary_quote = q
                        # 如果主数据源已经关键字段齐全，直接返回（不再请求备用源）
                        if not self._quote_needs_supplement(primary_quote):
                            return primary_quote
                    else:
                        # 用备用源补充缺失字段
                        supplement_attempts += 1
                        filled = self._merge_quote_fields(primary_quote, q)
                        if filled:
                            logger.debug(f"[{stock_code}] 从 {source} 补充字段: {', '.join(filled)}")
                        # 补充完成或达到上限，直接返回
                        if not self._quote_needs_supplement(primary_quote) or supplement_attempts >= MAX_SUPPLEMENT:
                            return primary_quote
            except Exception: continue
        return primary_quote  # 返回已有的（即使部分字段缺失）

    def _fetch_quote_from_source(self, stock_code: str, source: str):
        """从指定数据源获取实时行情"""
        if source == 'tencent':
            fetcher = next((f for f in self._fetchers if f.name == 'AkshareFetcher'), None)
            if fetcher:
                return fetcher.get_realtime_quote(stock_code, source='tencent')
        elif 'akshare' in source:
            fetcher = next((f for f in self._fetchers if f.name == 'AkshareFetcher'), None)
            if fetcher:
                sub_source = source.split('_')[1] if '_' in source else 'sina'
                return fetcher.get_realtime_quote(stock_code, source=sub_source)
        elif source == 'efinance':
            fetcher = next((f for f in self._fetchers if f.name == 'EfinanceFetcher'), None)
            if fetcher:
                return fetcher.get_realtime_quote(stock_code)
        return None

    @staticmethod
    def _is_intraday() -> bool:
        """判断当前是否在 A 股交易时段（9:30-15:00 工作日）"""
        now = datetime.now()
        if now.weekday() >= 5:
            return False
        t = now.hour * 60 + now.minute
        return 570 <= t <= 900  # 9:30=570, 15:00=900

    def get_chip_distribution(self, stock_code: str, force_fetch: bool = False):
        from .realtime_types import get_chip_circuit_breaker, ChipDistribution
        from src.config import get_config
        from src.storage import DatabaseManager

        config = get_config()
        if stock_code in self._chip_cache:
            return self._chip_cache[stock_code]

        intraday = self._is_intraday()

        # 1) DB 缓存：盘中放宽到 36h（尽量用缓存），盘后正常 24h
        try:
            db = DatabaseManager()
            if intraday:
                cache_hours = config.cache_ttl_chip_intraday_hours
            else:
                cache_hours = config.cache_ttl_chip_hours
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

        # 2) 盘中缓存未命中 → 用 K 线估算（不发网络请求，标记 source='estimated'）
        if intraday and not force_fetch:
            try:
                akshare_fetcher = next((f for f in self._fetchers if f.name == 'AkshareFetcher'), None)
                if akshare_fetcher and hasattr(akshare_fetcher, '_estimate_chip_from_daily'):
                    estimated = akshare_fetcher._estimate_chip_from_daily(stock_code)
                    if estimated:
                        estimated.source = 'estimated'
                        self._chip_cache[stock_code] = estimated
                        logger.debug(f"[{stock_code}] 盘中筹码使用K线估算(source=estimated)")
                        return estimated
            except Exception:
                pass
            return None

        # 3) 仅用缓存模式（定时 --chip-only 已写入缓存，分析时不再实时拉取）
        if getattr(config, 'chip_fetch_only_from_cache', False) and not force_fetch:
            return None
        if not config.enable_chip_distribution and not force_fetch:
            return None

        # 4) 盘后：实时拉取并落库
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
                except Exception: continue
        return stock_code
        
    def batch_get_stock_names(self, stock_codes: List[str]) -> Dict[str, str]:
        """批量获取股票名称，优先用缓存，缓存未命中时批量请求全A映射表"""
        result: Dict[str, str] = {}
        missing_codes: List[str] = []

        for code in stock_codes:
            cached_name = self._stock_name_cache.get(code)
            if cached_name:
                result[code] = cached_name
            else:
                missing_codes.append(code)

        if not missing_codes:
            return result

        try:
            import akshare as ak
            df_all = ak.stock_info_a_code_name()
            if df_all is not None and not df_all.empty:
                code_col = 'code' if 'code' in df_all.columns else df_all.columns[0]
                name_col = 'name' if 'name' in df_all.columns else df_all.columns[1]
                name_map = dict(zip(
                    df_all[code_col].astype(str).str.zfill(6),
                    df_all[name_col],
                ))
                for code in missing_codes:
                    name = name_map.get(code)
                    if name:
                        result[code] = name
                        self._stock_name_cache[code] = name
                missing_codes = [c for c in missing_codes if c not in result]
        except Exception as e:
            logger.warning(f"批量获取股票名称失败，回退到逐个请求: {e}")

        for code in missing_codes:
            name = self.get_stock_name(code)
            if name:
                result[code] = name

        return result
    
    def get_sector_rankings(self, n=5):
        for f in self._fetchers:
            try:
                res = f.get_sector_rankings(n)
                if res: return res
            except Exception: continue
        return [], []

    def get_capital_flow(self, stock_code: str) -> Optional[Dict[str, Any]]:
        """获取个股资金流向（主力/超大单/大单净流入）"""
        for f in self._fetchers:
            if hasattr(f, 'get_capital_flow'):
                try:
                    res = f.get_capital_flow(stock_code)
                    if res:
                        return res
                except Exception:
                    continue
        return None

    _sector_context_cache: Dict[str, Any] = {}  # {code: {'data': ..., 'ts': ...}}
    _sector_industry_cache: Dict[str, Any] = {}  # {industry: {'codes': [...], 'ts': ...}}
    _SECTOR_CONTEXT_TTL = 604800  # 7天（板块归属基本不变，仅新股上市初期会调整）
    _SECTOR_INDUSTRY_TTL = 604800  # 行业成员列表7天缓存
    def get_stock_sector_context(self, stock_code: str, stock_pct_chg: Optional[float] = None) -> Optional[SectorContext]:
        """获取个股所属板块及相对强弱（板块今日涨跌 vs 个股涨跌）"""
        # 检查缓存
        cached = self._sector_context_cache.get(stock_code)
        if cached and time.time() - cached['ts'] < self._SECTOR_CONTEXT_TTL:
            # 缓存命中，但需要更新 stock_pct 和 relative（因为个股涨跌幅可能变化）
            from dataclasses import replace
            result = cached['data']
            if stock_pct_chg is not None and result.sector_pct is not None:
                result = replace(result, stock_pct=stock_pct_chg,
                                 relative=round(stock_pct_chg - result.sector_pct, 2))
            return result

        # 注意：EfinanceFetcher.get_belong_board 会触发全量 817 支股票数据下载（耗时 30-60s），
        # 且返回的板块数据不包含今日涨跌幅（sector_pct=None），调用价值极低，直接跳过。
        # 仅尝试非 efinance 的其他 fetcher（如 akshare 等），若无可用数据则走 DB Fallback。
        for f in self._fetchers:
            if getattr(f, 'name', '') == 'EfinanceFetcher':
                continue
            try:
                if not hasattr(f, 'get_stock_belong_board') and not hasattr(f, 'get_belong_board'):
                    continue
                get_board = getattr(f, 'get_belong_board', None) or getattr(f, 'get_stock_belong_board', None)
                if not get_board:
                    continue
                df = get_board(stock_code)
                if df is None or df.empty:
                    continue
                # 优先选行业板块（BK04xx/BK12xx），避免概念板块
                row = df.iloc[0]
                _bk_col = next((c for c in ['板块代码', 'board_code'] if c in df.columns), None)
                if _bk_col:
                    _industry = df[df[_bk_col].str.startswith(('BK04', 'BK12'), na=False)]
                    if not _industry.empty:
                        row = _industry.iloc[0]
                name = None
                for col in ['板块名称', '名称', 'name', '板块']:
                    if col in row.index and pd.notna(row.get(col)):
                        name = str(row[col]).strip()
                        break
                sector_pct = None
                for col in ['涨跌幅', '涨跌幅度', 'change_pct', '日涨跌幅', '板块涨幅']:
                    if col in row.index and pd.notna(row.get(col)):
                        try:
                            sector_pct = float(row[col])
                            break
                        except (ValueError, TypeError):
                            pass
                rel = None
                if stock_pct_chg is not None and sector_pct is not None:
                    rel = round(stock_pct_chg - sector_pct, 2)
                result = SectorContext(sector_name=name or '未知', sector_pct=sector_pct, stock_pct=stock_pct_chg,
                                       relative=rel)
                # 写入缓存
                self._sector_context_cache[stock_code] = {'data': result, 'ts': time.time()}
                return result
            except Exception:
                continue

        # === DB Fallback：外部 API 不可用时，用已有缓存构建 sector_context ===
        # 静态行业映射（兜底，覆盖常见银行/消费股）
        _STATIC_INDUSTRY_MAP = {
            '000001': '银行', '600000': '银行', '600016': '银行', '601166': '银行',
            '601288': '银行', '601398': '银行', '601939': '银行', '601988': '银行',
            '600519': '白酒Ⅱ', '000858': '白酒Ⅱ', '000596': '白酒Ⅱ',
            '601985': '核电', '601088': '煤炭开采',
        }
        try:
            from src.storage import DatabaseManager
            from sqlalchemy import text as _text
            _db = DatabaseManager()
            with _db.get_session() as _s:
                # 1. 从 industry_pe 缓存查行业归属（或静态映射兜底）
                _row = _s.execute(_text(
                    "SELECT data_json FROM data_cache WHERE cache_type='industry_pe' AND cache_key=:code LIMIT 1"
                ), {"code": stock_code}).fetchone()
                _industry_from_static = _STATIC_INDUSTRY_MAP.get(stock_code)
                if _row or _industry_from_static:
                    import json as _json
                    _industry = _industry_from_static or ''
                    if _row:
                        _d = _json.loads(_row[0])
                        _industry = _d.get('industry', '') or _industry
                    if _industry:
                        # 2. 查同行业其他股票最近一日涨跌幅均值作为板块代理
                        # 优先用内存缓存，避免每次 LIKE 全表扫描
                        _cached_industry = self._sector_industry_cache.get(_industry)
                        if _cached_industry and time.time() - _cached_industry['ts'] < self._SECTOR_INDUSTRY_TTL:
                            _peer_codes = [c for c in _cached_industry['codes'] if c != stock_code]
                        else:
                            # 一次性加载所有 industry_pe 行并按行业分组（仅首次扫描）
                            _sentinel = '__all_loaded__'
                            _all_cached = self._sector_industry_cache.get(_sentinel)
                            if not _all_cached or time.time() - _all_cached['ts'] >= self._SECTOR_INDUSTRY_TTL:
                                import json as _json2
                                _all_rows = _s.execute(_text(
                                    "SELECT cache_key, data_json FROM data_cache WHERE cache_type='industry_pe'"
                                )).fetchall()
                                _industry_map: Dict[str, list] = {}
                                for _ck, _dj in _all_rows:
                                    try:
                                        _ind = _json2.loads(_dj).get('industry', '')
                                        if _ind:
                                            _industry_map.setdefault(_ind, []).append(_ck)
                                    except Exception:
                                        pass
                                _ts_now = time.time()
                                for _ind, _codes in _industry_map.items():
                                    if _ind not in self._sector_industry_cache or time.time() - self._sector_industry_cache[_ind]['ts'] >= self._SECTOR_INDUSTRY_TTL:
                                        self._sector_industry_cache[_ind] = {'codes': _codes, 'ts': _ts_now}
                                self._sector_industry_cache[_sentinel] = {'ts': _ts_now}
                            _cached_industry = self._sector_industry_cache.get(_industry)
                            _peer_codes = [c for c in (_cached_industry['codes'] if _cached_industry else []) if c != stock_code]
                            if _cached_industry:
                                pass  # already cached
                            else:
                                self._sector_industry_cache[_industry] = {'codes': [], 'ts': time.time()}
                            _peer_codes = [c for c in self._sector_industry_cache.get(_industry, {}).get('codes', []) if c != stock_code]
                        _sector_pct = None
                        _sector_5d_pct = None
                        if _peer_codes:
                            _placeholders = ','.join([f'"{c}"' for c in _peer_codes[:30]])
                            # 最近一日涨跌幅均值
                            _pct_rows = _s.execute(_text(
                                f"SELECT AVG(pct_chg) FROM stock_daily WHERE code IN ({_placeholders}) AND date=(SELECT MAX(date) FROM stock_daily WHERE code IN ({_placeholders}))"
                            )).fetchone()
                            if _pct_rows and _pct_rows[0] is not None:
                                _sector_pct = round(float(_pct_rows[0]), 2)
                            # 近5日累计涨跌幅：用 SQLite ROW_NUMBER 取每只股票最新5条
                            try:
                                _5d_rows = _s.execute(_text(
                                    f"""SELECT code, close FROM (
                                        SELECT code, close, date,
                                               ROW_NUMBER() OVER (PARTITION BY code ORDER BY date DESC) as rn
                                        FROM stock_daily WHERE code IN ({_placeholders})
                                    ) t WHERE rn <= 5 ORDER BY code, date DESC"""
                                )).fetchall()
                                if _5d_rows:
                                    import pandas as _pd
                                    _df5 = _pd.DataFrame(_5d_rows, columns=['code', 'close'])
                                    _peer_pcts = []
                                    for _pc in _peer_codes[:30]:
                                        _sub = _df5[_df5['code'] == _pc]['close'].values
                                        if len(_sub) >= 5:
                                            _peer_pcts.append((_sub[0] - _sub[4]) / _sub[4] * 100)
                                    if _peer_pcts:
                                        _sector_5d_pct = round(sum(_peer_pcts) / len(_peer_pcts), 2)
                            except Exception:
                                pass
                        _rel = round(stock_pct_chg - _sector_pct, 2) if (stock_pct_chg is not None and _sector_pct is not None) else None
                        _result = SectorContext(sector_name=_industry, sector_pct=_sector_pct, stock_pct=stock_pct_chg, relative=_rel, sector_5d_pct=_sector_5d_pct)
                        self._sector_context_cache[stock_code] = {'data': _result, 'ts': time.time()}
                        return _result
        except Exception:
            pass

        return None
