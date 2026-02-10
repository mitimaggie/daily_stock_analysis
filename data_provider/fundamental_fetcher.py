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

    def get_f10_data(self, code: str) -> Dict[str, Any]:
        """获取整合后的 F10 数据（L1内存 -> L2 DB -> 网络）"""
        # L1: 进程内存
        if code in _fundamental_cache:
            return _fundamental_cache[code]

        # L2: SQLite 持久化缓存
        db = _get_db()
        if db:
            cached = db.get_cache('f10', code, ttl_hours=_F10_CACHE_TTL_HOURS)
            if cached:
                _fundamental_cache[code] = cached  # 回填 L1
                logger.info(f"💾 [{code}] F10 命中 DB 缓存（跳过网络请求）")
                return cached

        # L3: 网络请求
        data = self._fetch_from_network(code)

        # 回写缓存
        if data.get('financial'):
            _fundamental_cache[code] = data
            if db:
                db.set_cache('f10', code, data)

        return data

    def _fetch_from_network(self, code: str) -> Dict[str, Any]:
        """从网络获取 F10 数据（THS -> EM fallback）"""
        data = {"valuation": {}, "financial": {}, "forecast": {}}

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
                    data["financial"] = {
                        "date": str(latest.get("报告期", "")),
                        "roe": str(latest.get("净资产收益率", "N/A")),
                        "net_profit_growth": str(latest.get("净利润同比增长率", "N/A")),
                        "revenue_growth": str(latest.get("营业总收入同比增长率", "N/A")),
                        "gross_margin": str(latest.get("销售毛利率", "N/A")),
                        "debt_ratio": str(latest.get("资产负债率", "N/A")),
                        "source": "ths"
                    }
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
                        data["financial"] = {
                            "date": str(latest.get("报告期", "")),
                            "roe": str(latest.get("净资产收益率", latest.get("加权净资产收益率", "N/A"))),
                            "net_profit_growth": str(latest.get("净利润同比增长率", "N/A")),
                            "revenue_growth": str(latest.get("营业总收入同比增长率", latest.get("营业收入同比增长率", "N/A"))),
                            "gross_margin": str(latest.get("销售毛利率", "N/A")),
                            "debt_ratio": str(latest.get("资产负债率", "N/A")),
                            "source": "em"
                        }
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
                    data["forecast"] = {
                        "rating": summary.get("评级", "无"),
                        "target_price": summary.get("目标价格", "无"),
                        "avg_profit_change": summary.get("平均净利润变动幅", "N/A")
                    }
            except Exception:
                pass

            logger.info(f"✅ [{code}] F10 基本面数据获取成功 (来源: {data['financial'].get('source', 'none')})")

        except Exception as e:
            logger.error(f"❌ [{code}] F10 数据获取失败: {e}")

        return data


# 全局单例
_fetcher = FundamentalFetcher()

def get_fundamental_data(code: str) -> Dict[str, Any]:
    return _fetcher.get_f10_data(code)


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
                for _, row in cons_df.iterrows():
                    peer_code = str(row['代码'])
                    _industry_pe_cache[peer_code] = median_pe
                    db.set_cache('industry_pe', peer_code, cache_val)
            db.set_cache('industry_pe', code, cache_val)
        _industry_pe_cache[code] = median_pe
        return median_pe

    except Exception as e:
        logger.debug(f"[{code}] 行业PE中位数获取失败: {e}")
        return None