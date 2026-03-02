# -*- coding: utf-8 -*-
"""
===================================
数据源策略层 - 包初始化
===================================

本包实现策略模式管理多个数据源，实现：
1. 统一的数据获取接口
2. 自动故障切换
3. 防封禁流控策略

数据源优先级：
1. AkshareFetcher (Priority 0) - 来自 akshare 库（东财/新浪/腾讯多源）
2. EfinanceFetcher (Priority 1) - 来自 efinance 库
3. BaostockFetcher (Priority 2) - 来自 baostock 库
4. YfinanceFetcher (Priority 3) - 来自 yfinance 库（美股/港股）
5. PytdxFetcher (Priority 4) - 来自 pytdx 库（通达信）

提示：优先级数字越小越优先，同优先级按初始化顺序排列
"""

from .base import BaseFetcher, DataFetcherManager
from .akshare_fetcher import AkshareFetcher
from .pytdx_fetcher import PytdxFetcher
from .baostock_fetcher import BaostockFetcher
from .yfinance_fetcher import YfinanceFetcher
# EfinanceFetcher 已移除：import efinance 会在后台触发全量 817 支股票下载，严重拖慢分析速度

__all__ = [
    'BaseFetcher',
    'DataFetcherManager',
    'AkshareFetcher',
    'PytdxFetcher',
    'BaostockFetcher',
    'YfinanceFetcher',
]
