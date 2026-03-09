# -*- coding: utf-8 -*-
"""
评分系统 — Facade 模块
ScoringSystem 通过多继承聚合 4 个子模块的所有 @staticmethod 方法。

外部调用方仍然使用:
    from src.stock_analyzer.scoring import ScoringSystem
"""

from .scoring_base import ScoringBase
from .scoring_flow import ScoringFlow
from .scoring_external import ScoringExternal
from .scoring_pattern import ScoringPattern


class ScoringSystem(ScoringBase, ScoringFlow, ScoringExternal, ScoringPattern):
    """评分系统：多维度评分与修正（多继承聚合各子模块）"""
    pass
