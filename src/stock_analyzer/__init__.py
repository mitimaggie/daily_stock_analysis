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

# 导入重构后的模块
from .indicators import TechnicalIndicators
from .scoring import ScoringSystem
from .resonance import ResonanceDetector
from .risk_management import RiskManager
from .formatter import AnalysisFormatter
from .report_template import ReportTemplate
from .analyzer import StockTrendAnalyzer

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
    # 子模块（可选，供高级用户使用）
    'TechnicalIndicators',
    'ScoringSystem',
    'ResonanceDetector',
    'RiskManager',
    'AnalysisFormatter',
    'ReportTemplate',
]
