# -*- coding: utf-8 -*-
"""
股票趋势分析器 - 模块化重构版
保持向后兼容：from src.stock_analyzer import StockTrendAnalyzer
"""

# 导出类型定义
from .types import (
    TrendStatus,
    VolumeStatus,
    MACDStatus,
    RSIStatus,
    KDJStatus,
    BuySignal,
    MarketRegime,
    TrendAnalysisResult,
)

# 导入主分析器（从原文件）
import sys
from pathlib import Path

# 添加父目录到 sys.path
parent_dir = Path(__file__).resolve().parent.parent
if str(parent_dir) not in sys.path:
    sys.path.insert(0, str(parent_dir))

# 从原 stock_analyzer.py 导入主类（保持完全兼容）
try:
    from ..stock_analyzer import StockTrendAnalyzer
except (ImportError, ValueError):
    # 降级方案：直接从 src 目录导入
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "stock_analyzer_legacy",
        parent_dir / "stock_analyzer.py"
    )
    if spec and spec.loader:
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        StockTrendAnalyzer = module.StockTrendAnalyzer

# 导出所有公开接口
__all__ = [
    # 类型
    'TrendStatus',
    'VolumeStatus', 
    'MACDStatus',
    'RSIStatus',
    'KDJStatus',
    'BuySignal',
    'MarketRegime',
    'TrendAnalysisResult',
    # 主分析器
    'StockTrendAnalyzer',
]
