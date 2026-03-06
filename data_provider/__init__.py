# -*- coding: utf-8 -*-
"""
===================================
数据源策略层 - 包初始化
===================================

本包实现策略模式管理多个数据源，实现：
1. 统一的数据获取接口
2. 自动故障切换
3. 防封禁流控策略

数据源优先级（K线/日线）：
1. BaostockFetcher (Priority 0) - 首选：稳定、免费、无反爬
2. AkshareFetcher  (Priority 1) - 备用：功能全，批量易限流
3. TencentFetcher  (Priority 2) - 备用：腾讯K线
4. YfinanceFetcher (Priority 4) - 备用：美股首选，A股延迟
5. PytdxFetcher    (Priority 5) - 备用：通达信TCP

⚠️ 已移除 EfinanceFetcher（K线）：import efinance 触发全量817支股票下载，严重阻塞
   efinance.get_today_bill 仅在 akshare_fetcher.py 中单次串行调用（资金流盘中实时）

⚠️ 反封禁规则：akshare/efinance 均有反爬机制，严禁并发批量调用
   批量分析并发上限由 pipeline.py 控制（搜索模式≤2，纯本地≤3）
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
