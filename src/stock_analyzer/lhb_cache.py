# -*- coding: utf-8 -*-
"""
龙虎榜缓存模块

策略：
- 每日仅拉取一次全量龙虎榜数据（stock_lhb_stock_statistic_em 近一月）
- 数据缓存到内存，当天有效，隔天自动失效重拉
- 个股查询直接走内存缓存，< 1ms，不触发网络请求
- 避免每次分析个股都拉全量数据导致 IP 被封
"""

import logging
from datetime import date
from typing import Dict, Optional, Any

logger = logging.getLogger(__name__)

_CACHE_DATE: Optional[date] = None
_CACHE_DATA: Dict[str, Dict[str, Any]] = {}


class LHBCache:
    """龙虎榜每日缓存，支持个股按需查询。"""

    @classmethod
    def _is_stale(cls) -> bool:
        return _CACHE_DATE is None or _CACHE_DATE != date.today()

    @classmethod
    def _load(cls) -> None:
        """拉取全量龙虎榜近一月数据并写入缓存。"""
        global _CACHE_DATE, _CACHE_DATA
        try:
            import akshare as ak
            df = ak.stock_lhb_stock_statistic_em(symbol='近一月')
            if df is None or df.empty:
                logger.warning("[LHBCache] 龙虎榜数据为空，跳过缓存")
                _CACHE_DATA = {}
                _CACHE_DATE = date.today()
                return

            mapping: Dict[str, Dict[str, Any]] = {}
            for row in df.to_dict('records'):
                code = str(row.get('代码', '') or '').strip()
                if not code:
                    continue
                mapping[code] = {
                    'lhb_net_buy': float(row.get('龙虎榜净买额', 0) or 0),
                    'lhb_institution_net': float(row.get('机构买入净额', 0) or 0),
                    'lhb_times': int(row.get('上榜次数', 0) or 0),
                }

            _CACHE_DATA = mapping
            _CACHE_DATE = date.today()
            logger.info(f"[LHBCache] 缓存完成，共 {len(mapping)} 只股票上榜")

        except Exception as e:
            logger.warning(f"[LHBCache] 加载龙虎榜失败: {e}")
            _CACHE_DATA = {}
            _CACHE_DATE = date.today()

    @classmethod
    def query(cls, stock_code: str) -> Optional[Dict[str, Any]]:
        """
        查询个股近一月龙虎榜数据。

        Args:
            stock_code: 股票代码（纯6位数字，如 '600519'）

        Returns:
            dict 含 lhb_net_buy / lhb_institution_net / lhb_times，
            如果近一月未上榜返回 None。
        """
        if cls._is_stale():
            cls._load()
        return _CACHE_DATA.get(stock_code)

    @classmethod
    def prefetch(cls) -> None:
        """主动预拉取（可在每日收盘后由 scheduler 调用）。"""
        cls._load()

    @classmethod
    def clear(cls) -> None:
        """清空缓存（用于测试或手动刷新）。"""
        global _CACHE_DATE, _CACHE_DATA
        _CACHE_DATE = None
        _CACHE_DATA = {}
