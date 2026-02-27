# -*- coding: utf-8 -*-
import logging
import time
import random
import re
from typing import Optional, Dict, Any
from data_provider.analysis_types import CapitalFlowData

import pandas as pd
from tenacity import retry, stop_after_attempt, wait_exponential

from .base import BaseFetcher, DataFetchError, STANDARD_COLUMNS
from .rate_limiter import get_global_limiter, CircuitBreakerOpen
from .realtime_types import (
    UnifiedRealtimeQuote, ChipDistribution, RealtimeSource,
    get_realtime_circuit_breaker, safe_float, safe_int
)
from src.config import get_config  # 引入配置

logger = logging.getLogger(__name__)

# User-Agent 池
USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
]

# 缓存
_realtime_cache: Dict[str, Any] = {'data': None, 'timestamp': 0, 'ttl': 1200}
_etf_realtime_cache: Dict[str, Any] = {'data': None, 'timestamp': 0, 'ttl': 1200}

def _is_etf_code(code): return code.startswith(('51', '52', '56', '58', '15', '16', '18')) and len(code) == 6
def _is_hk_code(code): return code.lower().startswith('hk') or (code.isdigit() and len(code)==5)
def _is_us_code(code): return bool(re.match(r'^[A-Z]{1,5}(\.[A-Z])?$', code.strip().upper()))

class AkshareFetcher(BaseFetcher):
    name = "AkshareFetcher"
    priority = 1
    
    def __init__(self):
        # 🔥 从配置中读取休眠参数，而不是硬编码
        config = get_config()
        self.sleep_min = config.akshare_sleep_min
        self.sleep_max = config.akshare_sleep_max
        self._last_request_time = None
    
    def _set_random_user_agent(self): pass 
    
    def _enforce_rate_limit(self):
        """akshare限流（集成全局限流器）"""
        limiter = get_global_limiter()
        try:
            if not limiter.acquire('akshare', blocking=True, timeout=30.0):
                raise DataFetchError("akshare rate limit timeout")
        except CircuitBreakerOpen as e:
            logger.error(f" akshare熔断器打开: {e}")
            raise DataFetchError(str(e))
        self.random_sleep()
    
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    def _fetch_raw_data(self, stock_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        if _is_us_code(stock_code): return self._fetch_us_data(stock_code, start_date, end_date)
        if _is_hk_code(stock_code): return self._fetch_hk_data(stock_code, start_date, end_date)
        if _is_etf_code(stock_code): return self._fetch_etf_data(stock_code, start_date, end_date)
        
        # A股多源尝试：东财 -> 新浪 -> 腾讯
        methods = [
            (self._fetch_stock_data_em, "东方财富"),
            (self._fetch_stock_data_sina, "新浪财经"),
            (self._fetch_stock_data_tx, "腾讯财经"),
        ]
        
        last_error = None
        for method, name in methods:
            try:
                df = method(stock_code, start_date, end_date)
                if df is not None and not df.empty: return df
            except Exception as e:
                last_error = e
                continue
        raise DataFetchError(f"Akshare所有源失败: {last_error}")

    def _fetch_stock_data_em(self, code, start, end):
        import akshare as ak
        self._enforce_rate_limit()
        return ak.stock_zh_a_hist(symbol=code, period="daily", start_date=start.replace('-',''), end_date=end.replace('-',''), adjust="qfq")

    def _fetch_stock_data_sina(self, code, start, end):
        import akshare as ak
        self._enforce_rate_limit()
        symbol = f"sh{code}" if code.startswith(('6','5','9')) else f"sz{code}"
        df = ak.stock_zh_a_daily(symbol=symbol, start_date=start.replace('-',''), end_date=end.replace('-',''), adjust="qfq")
        if df is not None: 
            df = df.rename(columns={'date':'日期', 'open':'开盘', 'high':'最高', 'low':'最低', 'close':'收盘', 'volume':'成交量', 'amount':'成交额'})
        return df

    def _fetch_stock_data_tx(self, code, start, end):
        import akshare as ak
        self._enforce_rate_limit()
        symbol = f"sh{code}" if code.startswith(('6','5','9')) else f"sz{code}"
        df = ak.stock_zh_a_hist_tx(symbol=symbol, start_date=start.replace('-',''), end_date=end.replace('-',''), adjust="qfq")
        if df is not None:
             df = df.rename(columns={'date':'日期', 'open':'开盘', 'high':'最高', 'low':'最低', 'close':'收盘', 'volume':'成交量', 'amount':'成交额'})
        return df

    def _fetch_etf_data(self, code, start, end):
        import akshare as ak
        self._enforce_rate_limit()
        return ak.fund_etf_hist_em(symbol=code, period="daily", start_date=start.replace('-',''), end_date=end.replace('-',''), adjust="qfq")
        
    def _fetch_us_data(self, code, start, end):
        import akshare as ak
        self._enforce_rate_limit()
        df = ak.stock_us_daily(symbol=code.strip().upper(), adjust="qfq")
        if df is not None:
            df = df.rename(columns={'date':'日期', 'open':'开盘', 'high':'最高', 'low':'最低', 'close':'收盘', 'volume':'成交量'})
            df['日期'] = pd.to_datetime(df['日期'])
            df = df[(df['日期'] >= pd.to_datetime(start)) & (df['日期'] <= pd.to_datetime(end))]
        return df

    def _fetch_hk_data(self, code, start, end):
        import akshare as ak
        self._enforce_rate_limit()
        code = code.lower().replace('hk', '').zfill(5)
        return ak.stock_hk_hist(symbol=code, period="daily", start_date=start.replace('-',''), end_date=end.replace('-',''), adjust="qfq")

    def _normalize_data(self, df, code):
        if df is None or df.empty: return df
        df = df.copy()
        mapping = {'日期': 'date', '开盘': 'open', '收盘': 'close', '最高': 'high', '最低': 'low', '成交量': 'volume', '成交额': 'amount', '涨跌幅': 'pct_chg'}
        df = df.rename(columns=mapping)
        df['code'] = code
        for c in STANDARD_COLUMNS:
            if c not in df.columns: df[c] = 0
        return df[STANDARD_COLUMNS + ['code']]

    def get_realtime_quote(self, stock_code: str, source: str = "em") -> Optional[UnifiedRealtimeQuote]:
        if _is_us_code(stock_code): return None
        if _is_hk_code(stock_code): return None
        if _is_etf_code(stock_code): return self._get_etf_realtime_quote(stock_code)
        
        circuit_breaker = get_realtime_circuit_breaker()
        if not circuit_breaker.is_available(f"akshare_{source}"): return None
        
        try:
            if source == "sina": return self._get_sina_quote(stock_code)
            if source == "tencent": return self._get_tencent_quote(stock_code)
            return self._get_em_quote(stock_code)
        except Exception as e:
            circuit_breaker.record_failure(f"akshare_{source}", str(e))
            return None

    def _get_em_quote(self, stock_code):
        import akshare as ak
        circuit_breaker = get_realtime_circuit_breaker()
        current_time = time.time()
        if _realtime_cache['data'] is not None and current_time - _realtime_cache['timestamp'] < _realtime_cache['ttl']:
            df = _realtime_cache['data']
        else:
            self._enforce_rate_limit()
            df = ak.stock_zh_a_spot_em()
            _realtime_cache['data'] = df
            _realtime_cache['timestamp'] = current_time
            circuit_breaker.record_success("akshare_em")

        row = df[df['代码'] == stock_code]
        if row.empty: return None
        row = row.iloc[0]
        return UnifiedRealtimeQuote(
            code=stock_code, name=str(row.get('名称')), source=RealtimeSource.AKSHARE_EM,
            price=safe_float(row.get('最新价')), change_pct=safe_float(row.get('涨跌幅')),
            volume=safe_int(row.get('成交量')), amount=safe_float(row.get('成交额')),
            volume_ratio=safe_float(row.get('量比')), turnover_rate=safe_float(row.get('换手率')),
            pe_ratio=safe_float(row.get('市盈率-动态')), pb_ratio=safe_float(row.get('市净率')),
            total_mv=safe_float(row.get('总市值')), circ_mv=safe_float(row.get('流通市值'))
        )

    def _get_sina_quote(self, stock_code):
        import requests
        symbol = f"sh{stock_code}" if stock_code.startswith(('6', '5', '9')) else f"sz{stock_code}"
        url = f"http://hq.sinajs.cn/list={symbol}"
        headers = {'Referer': 'http://finance.sina.com.cn'}
        self.random_sleep(0.1, 0.5) 
        resp = requests.get(url, headers=headers, timeout=5)
        if resp.status_code != 200: return None
        data = resp.text.split('="')[1].strip('";\n').split(',')
        if len(data) < 30: return None
        
        price = safe_float(data[3])
        pre = safe_float(data[2])
        pct = (price - pre) / pre * 100 if pre > 0 else 0
        return UnifiedRealtimeQuote(
            code=stock_code, name=data[0], source=RealtimeSource.AKSHARE_SINA,
            price=price, change_pct=pct, open_price=safe_float(data[1]),
            high=safe_float(data[4]), low=safe_float(data[5]),
            volume=safe_int(data[8]), amount=safe_float(data[9]), pre_close=pre
        )

    def _get_tencent_quote(self, stock_code):
        import requests
        symbol = f"sh{stock_code}" if stock_code.startswith(('6', '5', '9')) else f"sz{stock_code}"
        url = f"http://qt.gtimg.cn/q={symbol}"
        self.random_sleep(0.1, 0.5)
        resp = requests.get(url, timeout=5)
        if resp.status_code != 200: return None
        data = resp.text.split('="')[1].strip('";\n').split('~')
        if len(data) < 40: return None
        
        return UnifiedRealtimeQuote(
            code=stock_code, name=data[1], source=RealtimeSource.TENCENT,
            price=safe_float(data[3]), change_pct=safe_float(data[32]),
            open_price=safe_float(data[5]), high=safe_float(data[33]), low=safe_float(data[34]),
            pre_close=safe_float(data[4]),
            volume=safe_int(data[6])*100, amount=safe_float(data[37])*10000,
            turnover_rate=safe_float(data[38]), pe_ratio=safe_float(data[39]),
            pb_ratio=safe_float(data[46]) if len(data) > 46 else None,
            volume_ratio=safe_float(data[49]) if len(data) > 49 else None,
            total_mv=safe_float(data[45])*100000000
        )

    def _get_etf_realtime_quote(self, stock_code):
        import akshare as ak
        current_time = time.time()
        if _etf_realtime_cache['data'] is not None and current_time - _etf_realtime_cache['timestamp'] < _etf_realtime_cache['ttl']:
            df = _etf_realtime_cache['data']
        else:
            self._enforce_rate_limit()
            df = ak.fund_etf_spot_em()
            _etf_realtime_cache['data'] = df
            _etf_realtime_cache['timestamp'] = current_time
            
        row = df[df['代码'] == stock_code]
        if row.empty: return None
        row = row.iloc[0]
        return UnifiedRealtimeQuote(
            code=stock_code, name=str(row.get('名称')), source=RealtimeSource.AKSHARE_EM,
            price=safe_float(row.get('最新价')), change_pct=safe_float(row.get('涨跌幅'))
        )

    # 板块排行缓存（避免短时间内重复请求东财被断连）
    _sector_cache: Dict[str, Any] = {'data': None, 'timestamp': 0, 'ttl': 600}

    def get_sector_rankings(self, n: int = 5):
        """获取行业板块涨跌排行（领涨 + 领跌）
        
        使用 ak.stock_board_industry_name_em() 获取东财行业板块数据。
        带 600s 缓存 + 重试，降低被断连概率。
        返回: (top_list, bottom_list)，每个元素为 {"name": str, "change_pct": float}
        """
        import akshare as ak

        # 1. 检查缓存
        current_time = time.time()
        if (self._sector_cache['data'] is not None 
                and current_time - self._sector_cache['timestamp'] < self._sector_cache['ttl']):
            df = self._sector_cache['data']
        else:
            # 2. 带重试的请求（东财接口不稳定，重试一次通常就好）
            df = None
            for attempt in range(2):
                try:
                    self._enforce_rate_limit()
                    df = ak.stock_board_industry_name_em()
                    if df is not None and not df.empty:
                        self._sector_cache['data'] = df
                        self._sector_cache['timestamp'] = current_time
                        break
                except Exception as e:
                    if attempt == 0:
                        logger.debug(f"[板块] 第1次请求失败，2s后重试: {e}")
                        time.sleep(2)
                    else:
                        logger.warning(f"[板块] 板块涨跌榜获取失败(已重试): {e}")
                        return None

        if df is None or df.empty:
            return None

        # 3. 解析
        pct_col = '涨跌幅'
        name_col = '板块名称'
        if pct_col not in df.columns or name_col not in df.columns:
            logger.warning(f"[板块] 列名不匹配，可用列: {list(df.columns)}")
            return None
        df = df[[name_col, pct_col]].dropna()
        df[pct_col] = df[pct_col].astype(float)
        df_sorted = df.sort_values(pct_col, ascending=False)
        top = [{"name": r[name_col], "change_pct": round(r[pct_col], 2)} for _, r in df_sorted.head(n).iterrows()]
        bottom = [{"name": r[name_col], "change_pct": round(r[pct_col], 2)} for _, r in df_sorted.tail(n).iterrows()]
        return (top, bottom)

    # 资金流向缓存（个股级别，TTL 10分钟，避免批量分析时重复请求东财被封）
    _capital_flow_cache: Dict[str, Any] = {}  # {code: {'data': ..., 'ts': ...}}
    _CAPITAL_FLOW_TTL = 600  # 10分钟

    def get_capital_flow(self, stock_code: str) -> Optional[CapitalFlowData]:
        """获取个股资金流向（东方财富）

        缓存策略（三层）：
        1. 内存缓存（盘中3分钟，盘后10分钟）
        2. DB缓存（data_cache 表，盘后24h内复用，避免批量分析反复请求）
        3. 实时拉取 ak.stock_individual_fund_flow，成功后落 DB

        Returns:
            CapitalFlowData or None on failure.
        """
        if _is_us_code(stock_code) or _is_etf_code(stock_code):
            return None

        # 1. 内存缓存
        cached = self._capital_flow_cache.get(stock_code)
        if cached:
            _ttl = cached.get('ttl', self._CAPITAL_FLOW_TTL)
            if time.time() - cached['ts'] < _ttl:
                return cached['data']

        # 2. DB 缓存（盘后24h内直接复用，避免批量分析打爆接口）
        try:
            from src.storage import DatabaseManager
            from sqlalchemy import text as _text
            import json as _json
            from datetime import datetime as _dt2
            _db = DatabaseManager()
            with _db.get_session() as _s:
                _row = _s.execute(_text(
                    "SELECT data_json, fetched_at FROM data_cache "
                    "WHERE cache_type='capital_flow' AND cache_key=:k "
                    "ORDER BY fetched_at DESC LIMIT 1"
                ), {'k': stock_code}).fetchone()
            if _row:
                _age_h = (_dt2.now() - _dt2.fromisoformat(str(_row[1]))).total_seconds() / 3600
                _max_age = 6 if self._is_market_open() else 24
                if _age_h < _max_age:
                    _d = _json.loads(_row[0])
                    result = CapitalFlowData(
                        main_net_flow=_d.get('main_net_flow', 0),
                        main_net_flow_pct=_d.get('main_net_flow_pct', 0),
                        super_large_net=_d.get('super_large_net', 0),
                        large_net=_d.get('large_net', 0),
                    )
                    self._capital_flow_cache[stock_code] = {'data': result, 'ts': time.time(), 'ttl': 300}
                    logger.debug(f"💰 [{stock_code}] 资金流向(DB缓存 {_age_h:.1f}h前)")
                    return result
        except Exception:
            pass

        import akshare as ak
        from datetime import datetime as _dt, date as _date

        market = "sh" if stock_code.startswith(('6', '5', '9')) else "sz"
        try:
            self._enforce_rate_limit()
            df = ak.stock_individual_fund_flow(stock=stock_code, market=market)
            if df is None or df.empty:
                return None

            # 优先取今日数据；盘中今日数据可能尚未入库，则退回最新一行并标注
            today_str = _dt.now().strftime('%Y-%m-%d')
            # 检测日期列名
            date_col = None
            for c in ('日期', 'date', 'Date'):
                if c in df.columns:
                    date_col = c
                    break
            
            latest = None
            is_today = False
            if date_col:
                df[date_col] = df[date_col].astype(str)
                today_rows = df[df[date_col] == today_str]
                if not today_rows.empty:
                    latest = today_rows.iloc[-1]
                    is_today = True
                else:
                    # 今日无数据（盘前/接口延迟），取最新一行（昨日）
                    latest = df.iloc[-1]
                    is_today = False
            else:
                latest = df.iloc[-1]
                is_today = False

            # 主力净流入（元 → 万元）
            main_net_raw = safe_float(latest.get('主力净流入-净额', 0))
            main_pct = safe_float(latest.get('主力净流入-净占比', 0))

            # 超大单+大单 = 主力；也单独暴露便于精细分析
            super_large = safe_float(latest.get('超大单净流入-净额', 0))
            large = safe_float(latest.get('大单净流入-净额', 0))

            result = CapitalFlowData(
                main_net_flow=round(main_net_raw / 10000, 2) if main_net_raw else 0,
                main_net_flow_pct=main_pct or 0,
                super_large_net=round(super_large / 10000, 2) if super_large else 0,
                large_net=round(large / 10000, 2) if large else 0,
            )
            # 落 DB 缓存（供下次批量分析复用，避免重复打接口）
            try:
                import json as _json
                from src.storage import DatabaseManager
                from sqlalchemy import text as _text
                _db = DatabaseManager()
                _payload = _json.dumps({
                    'main_net_flow': result.main_net_flow,
                    'main_net_flow_pct': result.main_net_flow_pct,
                    'super_large_net': result.super_large_net,
                    'large_net': result.large_net,
                })
                with _db.get_session() as _s:
                    _s.execute(_text(
                        "INSERT INTO data_cache (cache_type, cache_key, data_json, fetched_at) "
                        "VALUES ('capital_flow', :k, :v, datetime('now')) "
                        "ON CONFLICT(cache_type, cache_key) DO UPDATE SET data_json=excluded.data_json, fetched_at=excluded.fetched_at"
                    ), {'k': stock_code, 'v': _payload})
                    _s.commit()
            except Exception:
                pass
            # 内存缓存：盘中3分钟，盘后10分钟
            _intraday = self._is_market_open()
            ttl = 180 if _intraday else self._CAPITAL_FLOW_TTL
            self._capital_flow_cache[stock_code] = {'data': result, 'ts': time.time(), 'ttl': ttl}
            data_tag = "今日" if is_today else "昨日"
            logger.info(f"💰 [{stock_code}] 资金流向({data_tag}): 主力净流入={result.main_net_flow:.0f}万 ({result.main_net_flow_pct:.1f}%)")
            return result

        except Exception as e:
            logger.debug(f"[{stock_code}] 资金流向获取失败: {e}")
            return None

    @staticmethod
    def _is_market_open() -> bool:
        """粗略判断当前是否在交易时段（9:30-15:00 工作日）"""
        try:
            from datetime import datetime as _dt
            now = _dt.now()
            if now.weekday() >= 5:
                return False
            t = now.hour * 60 + now.minute
            return 570 <= t <= 900  # 9:30=570, 15:00=900
        except Exception:
            return False

    def get_chip_distribution(self, stock_code: str, force_fetch: bool = False) -> Optional[ChipDistribution]:
        """获取筹码分布（force_fetch 时忽略 enable_chip_distribution，用于定时 --chip-only 拉取）
        
        优先调用 ak.stock_cyq_em；若被封则自动用本地 K 线数据估算。
        """
        import akshare as ak

        config = get_config()
        if not force_fetch and not config.enable_chip_distribution:
            return None

        if _is_us_code(stock_code) or _is_etf_code(stock_code): return None
        
        try:
            self._enforce_rate_limit()
            df = ak.stock_cyq_em(symbol=stock_code)
            if df is None or df.empty: return None
            
            latest = df.iloc[-1]
            return ChipDistribution(
                code=stock_code,
                date=str(latest.get('日期', '')),
                profit_ratio=safe_float(latest.get('获利比例')),
                avg_cost=safe_float(latest.get('平均成本')),
                concentration_90=safe_float(latest.get('90集中度')),
                concentration_70=safe_float(latest.get('70集中度'))
            )
        except Exception as e:
            logger.debug(f"筹码分布外部接口失败 {stock_code}: {e}，尝试本地K线估算")
            return self._estimate_chip_from_daily(stock_code)

    def _estimate_chip_from_daily(self, stock_code: str) -> Optional[ChipDistribution]:
        """基于本地 stock_daily K 线数据估算筹码分布（无外部 API 依赖）
        
        算法：
        - 取最近 120 日 K 线，按成交量加权估算持仓成本分布
        - 获利盘 = 当前价高于加权成本的筹码比例
        - 均成本 = 最近 60 日 VWAP（成交额/成交量）
        - 筹码集中度 = 70%/90% 筹码的价格区间宽度/均价（越小越集中）
        """
        try:
            from src.storage import DatabaseManager
            from sqlalchemy import text as _text
            import numpy as np

            db = DatabaseManager()
            with db.get_session() as s:
                rows = s.execute(_text(
                    "SELECT date, close, volume, amount FROM stock_daily "
                    "WHERE code=:code AND volume>0 ORDER BY date DESC LIMIT 120"
                ), {"code": stock_code}).fetchall()

            if not rows or len(rows) < 10:
                return None

            dates = [r[0] for r in rows]
            closes = [float(r[1]) for r in rows]
            volumes = [float(r[2]) for r in rows]
            amounts = [float(r[3]) for r in rows]

            current_price = closes[0]
            today_date = dates[0]

            # 1. 均成本（60日成交量加权收盘价，避免 amount 单位不一致问题）
            vol60 = sum(volumes[:60])
            avg_cost = round(sum(c * v for c, v in zip(closes[:60], volumes[:60])) / vol60, 2) if vol60 > 0 else current_price

            # 2. 获利盘比例（成交量加权）
            total_vol = sum(volumes)
            profit_vol = sum(v for c, v in zip(closes, volumes) if c <= current_price)
            profit_ratio = round(profit_vol / total_vol, 4) if total_vol > 0 else 0.5

            # 3. 筹码集中度（90%和70%的价格区间宽度/均价）
            # 按收盘价排序，取覆盖90%/70%成交量的价格范围
            sorted_pairs = sorted(zip(closes, volumes), key=lambda x: x[0])
            sorted_closes = [p[0] for p in sorted_pairs]
            sorted_vols = [p[1] for p in sorted_pairs]
            cum_vols = []
            s_cum = 0
            for v in sorted_vols:
                s_cum += v
                cum_vols.append(s_cum)

            def price_at_pct(pct_low, pct_high):
                lo_vol = total_vol * pct_low
                hi_vol = total_vol * pct_high
                lo_price = hi_price = avg_cost
                for i, cv in enumerate(cum_vols):
                    if cv >= lo_vol:
                        lo_price = sorted_closes[i]
                        break
                for i, cv in enumerate(cum_vols):
                    if cv >= hi_vol:
                        hi_price = sorted_closes[i]
                        break
                return lo_price, hi_price

            cost_90_low, cost_90_high = price_at_pct(0.05, 0.95)
            cost_70_low, cost_70_high = price_at_pct(0.15, 0.85)
            concentration_90 = round((cost_90_high - cost_90_low) / avg_cost * 100, 2) if avg_cost > 0 else 50.0
            concentration_70 = round((cost_70_high - cost_70_low) / avg_cost * 100, 2) if avg_cost > 0 else 30.0

            logger.debug(f"[{stock_code}] 筹码本地估算: 获利盘={profit_ratio:.1%} 均成本={avg_cost} 集中度90={concentration_90}%")
            return ChipDistribution(
                code=stock_code,
                date=str(today_date),
                source='local_estimate',
                profit_ratio=profit_ratio,
                avg_cost=avg_cost,
                cost_90_low=cost_90_low,
                cost_90_high=cost_90_high,
                concentration_90=concentration_90,
                cost_70_low=cost_70_low,
                cost_70_high=cost_70_high,
                concentration_70=concentration_70,
            )
        except Exception as e:
            logger.debug(f"[{stock_code}] 筹码本地估算失败: {e}")
            return None
