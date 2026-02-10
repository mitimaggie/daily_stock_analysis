# -*- coding: utf-8 -*-
"""
===================================
服务层模块初始化
===================================

职责：
1. 导出所有服务类
"""

from src.services.analysis_service import AnalysisService
from src.services.history_service import HistoryService
from src.services.stock_service import StockService


def get_sentiment_label(score: int) -> str:
    """根据评分获取情绪标签（共享工具函数）"""
    if score >= 80:
        return "极度乐观"
    elif score >= 60:
        return "乐观"
    elif score >= 40:
        return "中性"
    elif score >= 20:
        return "悲观"
    else:
        return "极度悲观"


__all__ = [
    "AnalysisService",
    "HistoryService",
    "StockService",
    "get_sentiment_label",
]
