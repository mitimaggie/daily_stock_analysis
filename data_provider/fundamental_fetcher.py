# -*- coding: utf-8 -*-
"""
===================================
基本面数据获取器 (F10)
===================================
职责：获取个股的财务摘要、估值指标、业绩预测
数据源优先级：同花顺(THS) -> 东方财富(EM) -> 降级(仅PE/PB)
缓存策略：L1 进程内存 + L2 SQLite 持久化
  - F10 财务数据: TTL=7天（季报级，几乎不变）
  - 行业 PE 中位数: TTL=24小时
风控：严格限制请求频率，全局计数器防止 IP 被封
"""
import logging
import time
import random
import threading
from typing import Dict, Optional, Any
import pandas as pd
from data_provider.fundamental_types import FundamentalData, FinancialSummary, ForecastData, _parse_pct

logger = logging.getLogger(__name__)

# === 全局请求限流器（所有 akshare 调用共享） ===
_request_lock = threading.Lock()
_request_timestamps: list = []  # 记录最近请求时间戳
_MAX_REQUESTS_PER_MINUTE = 12   # 每分钟最多 12 次请求（保守）
_MIN_INTERVAL = 3.0             # 最小请求间隔（秒）

def _rate_limited_sleep():
    """全局限流：确保不超过每分钟 N 次请求，每次至少间隔 M 秒"""
    with _request_lock:
        now = time.time()
        # 清理 60s 前的时间戳
        _request_timestamps[:] = [t for t in _request_timestamps if now - t < 60]
        # 超过每分钟上限，等到最早的过期
        if len(_request_timestamps) >= _MAX_REQUESTS_PER_MINUTE:
            wait = 60 - (now - _request_timestamps[0]) + 1
            if wait > 0:
                logger.info(f"🛡️ 限流等待 {wait:.1f}s（每分钟上限 {_MAX_REQUESTS_PER_MINUTE} 次）")
                time.sleep(wait)
        # 确保与上次请求间隔足够
        if _request_timestamps:
            elapsed = time.time() - _request_timestamps[-1]
            if elapsed < _MIN_INTERVAL:
                time.sleep(_MIN_INTERVAL - elapsed + random.uniform(0.5, 1.5))
        _request_timestamps.append(time.time())


# L1: 进程内存缓存
_fundamental_cache: Dict[str, Dict] = {}
_industry_pe_cache: Dict[str, float] = {}

# L2: SQLite 缓存 TTL
_F10_CACHE_TTL_HOURS = 168.0     # 7天
_INDUSTRY_PE_TTL_HOURS = 24.0    # 24小时

def _get_db():
    """延迟获取 DatabaseManager，避免循环导入"""
    try:
        from src.storage import DatabaseManager
        return DatabaseManager()
    except Exception:
        return None


class FundamentalFetcher:
    def __init__(self):
        pass

    def get_f10_data(self, code: str) -> FundamentalData:
        """获取整合后的 F10 数据（L1内存 -> L2 DB -> 网络）"""
        # L1: 进程内存
        if code in _fundamental_cache:
            return _fundamental_cache[code]

        # L2: SQLite 持久化缓存
        db = _get_db()
        if db:
            cached = db.get_cache('f10', code, ttl_hours=_F10_CACHE_TTL_HOURS)
            if cached:
                fd = FundamentalData.from_dict(cached)  # 旧格式 dict → 结构化对象
                _fundamental_cache[code] = fd  # 回填 L1
                logger.info(f"💾 [{code}] F10 命中 DB 缓存（跳过网络请求）")
                return fd

        # L3: 网络请求
        data = self._fetch_from_network(code)

        # 回写缓存
        if data.has_financial:
            _fundamental_cache[code] = data
            if db:
                db.set_cache('f10', code, data.to_dict())  # 序列化为旧格式 dict

        return data

    def _fetch_from_network(self, code: str) -> FundamentalData:
        """从网络获取 F10 数据（THS -> EM fallback）"""
        financial = FinancialSummary()
        forecast = ForecastData()

        try:
            import akshare as ak

            # === A. 财务摘要：优先同花顺，失败回退东财 ===
            financial_ok = False

            # A1. 同花顺
            _rate_limited_sleep()
            try:
                df_fin = ak.stock_financial_abstract_ths(symbol=code)
                if df_fin is not None and not df_fin.empty:
                    latest = df_fin.iloc[-1]
                    financial = FinancialSummary(
                        date=str(latest.get("报告期", "")),
                        roe=_parse_pct(latest.get("净资产收益率")),
                        net_profit_growth=_parse_pct(latest.get("净利润同比增长率")),
                        revenue_growth=_parse_pct(latest.get("营业总收入同比增长率")),
                        gross_margin=_parse_pct(latest.get("销售毛利率")),
                        debt_ratio=_parse_pct(latest.get("资产负债率")),
                        source="ths",
                    )
                    financial_ok = True
            except Exception as e:
                logger.warning(f"[{code}] THS 财务数据失败: {e}")

            # A2. 东财 fallback
            if not financial_ok:
                _rate_limited_sleep()
                try:
                    df_em = ak.stock_financial_analysis_indicator_em(symbol=code, indicator="按报告期")
                    if df_em is not None and not df_em.empty:
                        latest = df_em.iloc[0]
                        financial = FinancialSummary(
                            date=str(latest.get("报告期", "")),
                            roe=_parse_pct(latest.get("净资产收益率", latest.get("加权净资产收益率"))),
                            net_profit_growth=_parse_pct(latest.get("净利润同比增长率")),
                            revenue_growth=_parse_pct(latest.get("营业总收入同比增长率", latest.get("营业收入同比增长率"))),
                            gross_margin=_parse_pct(latest.get("销售毛利率")),
                            debt_ratio=_parse_pct(latest.get("资产负债率")),
                            source="em",
                        )
                        financial_ok = True
                        logger.info(f"[{code}] 东财财务指标 fallback 成功")
                except Exception as e:
                    logger.warning(f"[{code}] 东财财务指标也失败: {e}")

            if not financial_ok:
                logger.warning(f"[{code}] 财务数据全部失败，F10 仅有估值(PE/PB来自行情)")

            # === B. 业绩预测 (同花顺，可选) ===
            _rate_limited_sleep()
            try:
                df_fore = ak.stock_profit_forecast_ths(symbol=code)
                if df_fore is not None and not df_fore.empty:
                    summary = df_fore.head(1).to_dict('records')[0]
                    tp_raw = summary.get("目标价格", "无")
                    tp = None
                    if tp_raw not in ('无', '', 'N/A', None):
                        try:
                            tp = float(str(tp_raw).replace('元', '').strip())
                        except (ValueError, TypeError):
                            pass
                    forecast = ForecastData(
                        rating=str(summary.get("评级", "无") or "无"),
                        target_price=tp,
                        avg_profit_change=_parse_pct(summary.get("平均净利润变动幅")),
                    )
            except Exception:
                pass

            logger.info(f"✅ [{code}] F10 基本面数据获取成功 (来源: {financial.source or 'none'})")

        except Exception as e:
            logger.error(f"❌ [{code}] F10 数据获取失败: {e}")

        return FundamentalData(financial=financial, forecast=forecast)


# 全局单例
_fetcher = FundamentalFetcher()

def get_fundamental_data(code: str) -> FundamentalData:
    return _fetcher.get_f10_data(code)


# ============ P3: PE 历史数据（估值分位数）============

_pe_history_cache: Dict[str, list] = {}  # L1 内存缓存
_PE_HISTORY_TTL_HOURS = 24.0  # DB 缓存 24 小时

def get_pe_history(code: str, period: str = '近一年') -> Optional[list]:
    """
    获取个股 PE(TTM) 历史数据，用于计算估值分位数。
    
    数据源：百度股市通（通过 akshare 封装），稳定可靠。
    返回：PE 值列表（近1年约250个交易日），或 None。
    
    缓存策略：L1 内存 → L2 DB(24h) → L3 网络
    """
    # L1: 进程内存
    if code in _pe_history_cache:
        return _pe_history_cache[code]
    
    # L2: SQLite 缓存
    db = _get_db()
    if db:
        cached = db.get_cache('pe_history', code, ttl_hours=_PE_HISTORY_TTL_HOURS)
        if cached and 'values' in cached:
            _pe_history_cache[code] = cached['values']
            return cached['values']
    
    # L3: 网络请求
    try:
        import akshare as ak
        _rate_limited_sleep()
        df = ak.stock_zh_valuation_baidu(symbol=code, indicator='市盈率(TTM)', period=period)
        if df is None or df.empty:
            return None
        
        pe_values = [float(v) for v in df['value'].dropna().tolist() if float(v) > 0]
        if len(pe_values) < 20:
            return None
        
        # 回写缓存
        _pe_history_cache[code] = pe_values
        if db:
            db.set_cache('pe_history', code, {'values': pe_values})
        
        logger.info(f"📊 [{code}] PE历史获取成功: {len(pe_values)}条, 范围 {min(pe_values):.1f}~{max(pe_values):.1f}")
        return pe_values
    
    except Exception as e:
        logger.debug(f"[{code}] PE历史获取失败: {e}")
        return None


# ============ P3: 融资余额历史（情绪极端检测）============

_margin_history_cache: Dict[str, list] = {}
_MARGIN_HISTORY_TTL_HOURS = 12.0

# 批量融资余额缓存：{date_str: DataFrame}，TTL=12小时
# 同一批次的所有股票共享同一次全市场请求结果，避免逐股重复拉取
_margin_batch_cache: dict = {}  # {'sh_20240101': (ts, df), 'sz_20240101': (ts, df)}
_MARGIN_BATCH_TTL = 12 * 3600


def _get_margin_batch(date_str: str, is_sh: bool) -> Optional[pd.DataFrame]:
    """获取指定日期全市场融资明细（带进程级缓存，避免重复请求）"""
    import akshare as ak
    key = f"{'sh' if is_sh else 'sz'}_{date_str}"
    cached = _margin_batch_cache.get(key)
    if cached and time.time() - cached[0] < _MARGIN_BATCH_TTL:
        return cached[1]
    try:
        _rate_limited_sleep()
        if is_sh:
            df = ak.stock_margin_detail_sse(date=date_str)
        else:
            df = ak.stock_margin_detail_szse(date=date_str)
        if df is not None and not df.empty:
            _margin_batch_cache[key] = (time.time(), df)
            return df
    except Exception:
        pass
    return None


def get_margin_history(code: str, days: int = 7) -> Optional[list]:
    """
    获取个股近N日融资余额历史，用于检测融资连续流入/流出趋势。
    
    优化版：批量拉取全市场数据（最多 MAX_FETCH_DAYS 次请求），在本地筛选，
    并将批次数据缓存供同日期其他股票复用，请求次数从原来 O(days) 降为 O(2-3)。
    
    返回：融资余额列表（从旧到新），或 None。
    
    缓存策略：L1 内存 → L2 DB(12h) → L3 批量网络请求
    """
    # L1: 进程内存
    if code in _margin_history_cache:
        return _margin_history_cache[code]
    
    # L2: SQLite 缓存
    db = _get_db()
    if db:
        cached = db.get_cache('margin_history', code, ttl_hours=_MARGIN_HISTORY_TTL_HOURS)
        if cached and 'values' in cached:
            _margin_history_cache[code] = cached['values']
            return cached['values']
    
    # L3: 批量网络请求（最多拉取 MAX_FETCH_DAYS 个日期，每个日期的全市场数据被缓存复用）
    try:
        from datetime import datetime, timedelta
        
        is_sh = code.startswith(('6', '5', '9'))
        
        margin_values = []
        MAX_FETCH_DAYS = days + 5  # 多取几天以覆盖非交易日
        
        # 确定列名（沪市/深市不同）
        code_col = '标的证券代码' if is_sh else None
        balance_col = '融资余额'
        
        for offset in range(MAX_FETCH_DAYS, 0, -1):
            date_str = (datetime.now() - timedelta(days=offset)).strftime('%Y%m%d')
            
            df = _get_margin_batch(date_str, is_sh)
            if df is None or df.empty:
                continue
            
            # 深市列名动态检测
            if not is_sh and code_col is None:
                code_col = '证券代码' if '证券代码' in df.columns else (df.columns[1] if len(df.columns) > 1 else None)
                balance_col = '融资余额' if '融资余额' in df.columns else (df.columns[3] if len(df.columns) > 3 else '融资余额')
            
            if code_col is None:
                continue
            
            try:
                row = df[df[code_col].astype(str) == code]
                if not row.empty:
                    balance = float(row.iloc[0][balance_col])
                    if balance > 0:
                        margin_values.append(balance)
            except Exception:
                continue
            
            if len(margin_values) >= days:
                break
        
        if len(margin_values) < 3:
            return None
        
        # 回写缓存
        _margin_history_cache[code] = margin_values
        if db:
            db.set_cache('margin_history', code, {'values': margin_values})
        
        logger.info(f"📊 [{code}] 融资余额历史获取成功: {len(margin_values)}条")
        return margin_values
    
    except Exception as e:
        logger.debug(f"[{code}] 融资余额历史获取失败: {e}")
        return None


def get_industry_pe_median(code: str) -> Optional[float]:
    """获取个股所属行业的 PE 中位数（L1内存 -> L2 DB -> 网络）"""
    # L1: 进程内存
    if code in _industry_pe_cache:
        return _industry_pe_cache[code]

    # L2: SQLite 缓存
    db = _get_db()
    if db:
        cached = db.get_cache('industry_pe', code, ttl_hours=_INDUSTRY_PE_TTL_HOURS)
        if cached and 'median_pe' in cached:
            val = cached['median_pe']
            _industry_pe_cache[code] = val
            logger.info(f"💾 [{code}] 行业PE中位数命中 DB 缓存: {val}")
            return val

    # L3: 网络请求
    try:
        import akshare as ak
        import numpy as np

        # 1. 获取个股行业分类
        _rate_limited_sleep()
        info_df = ak.stock_individual_info_em(symbol=code)
        if info_df is None or info_df.empty:
            return None

        info_dict = dict(zip(info_df.iloc[:, 0], info_df.iloc[:, 1]))
        industry = info_dict.get('行业')
        if not industry:
            return None

        # 2. 获取行业成分股
        _rate_limited_sleep()
        cons_df = ak.stock_board_industry_cons_em(symbol=industry)
        if cons_df is None or cons_df.empty:
            return None

        # 3. 提取成分股 PE
        pe_col = None
        for col_name in ['市盈率-动态', '市盈率', 'PE']:
            if col_name in cons_df.columns:
                pe_col = col_name
                break

        if pe_col is None:
            logger.debug(f"[{code}] 行业 '{industry}' 成分股表无 PE 列，列名: {list(cons_df.columns)}")
            return None

        pe_values = cons_df[pe_col].apply(lambda x: float(x) if x not in (None, '', '-', 'nan') else None)
        pe_values = pe_values.dropna()
        pe_values = pe_values[(pe_values > 0) & (pe_values < 10000)]

        if len(pe_values) < 5:
            logger.debug(f"[{code}] 行业 '{industry}' 有效 PE 数量不足({len(pe_values)})")
            return None

        median_pe = round(float(np.median(pe_values)), 2)
        logger.info(f"[{code}] 行业 '{industry}' PE中位数={median_pe} (样本{len(pe_values)})")

        # 回写缓存（同行业所有成分股共享）
        cache_val = {'median_pe': median_pe, 'industry': industry}
        if db:
            if '代码' in cons_df.columns:
                for row in cons_df.to_dict('records'):
                    peer_code = str(row['代码'])
                    _industry_pe_cache[peer_code] = median_pe
                    db.set_cache('industry_pe', peer_code, cache_val)
            db.set_cache('industry_pe', code, cache_val)
        _industry_pe_cache[code] = median_pe
        return median_pe

    except Exception as e:
        logger.debug(f"[{code}] 行业PE中位数获取失败: {e}")
        return None