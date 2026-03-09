# -*- coding: utf-8 -*-
"""
===================================
分析数据结构化类型定义
===================================
将资金流、板块上下文、行情附加数据从裸 dict 替换为强类型 dataclass。

设计原则：
1. 内部字段用 Optional[float]，消费方无需手动类型检查
2. to_dict() 输出与旧 dict 完全一致，确保 LLM context 零变化
3. from_dict() 兼容旧格式，支持缓存迁移
"""

from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List


# ============================================================
# CapitalFlowData — 资金流向
# ============================================================

@dataclass
class CapitalFlowData:
    """个股资金流向数据（来自东方财富 akshare）
    
    所有金额单位为万元，占比为百分比。
    """
    main_net_flow: float = 0.0          # 主力净流入（万元）
    main_net_flow_pct: float = 0.0      # 主力净流入占比 (%)
    super_large_net: float = 0.0        # 超大单净流入（万元）
    large_net: float = 0.0             # 大单净流入（万元）
    # pipeline 注入的扩展字段
    daily_avg_amount: Optional[float] = None   # 日均成交额（万元），供阈值相对化
    margin_history: Optional[List[float]] = None  # 融资余额历史（P3情绪极端检测）
    margin_history_dates: Optional[List[str]] = None  # 融资余额对应日期（YYYYMMDD，跨长假检测用）
    margin_balance_change: Optional[float] = None  # 融资余额变化（百分比，如 +5.2 = 增长5.2%）
    
    def to_dict(self) -> Dict[str, Any]:
        """序列化为旧格式 dict"""
        d: Dict[str, Any] = {
            'main_net_flow': self.main_net_flow,
            'main_net_flow_pct': self.main_net_flow_pct,
            'super_large_net': self.super_large_net,
            'large_net': self.large_net,
        }
        if self.daily_avg_amount is not None:
            d['daily_avg_amount'] = self.daily_avg_amount
        if self.margin_history is not None:
            d['margin_history'] = self.margin_history
        if self.margin_history_dates is not None:
            d['margin_history_dates'] = self.margin_history_dates
        if self.margin_balance_change is not None:
            d['margin_balance_change'] = self.margin_balance_change
        return d
    
    @classmethod
    def from_dict(cls, d: dict) -> 'CapitalFlowData':
        if not d or not isinstance(d, dict):
            return cls()
        return cls(
            main_net_flow=float(d.get('main_net_flow', 0) or 0),
            main_net_flow_pct=float(d.get('main_net_flow_pct', 0) or 0),
            super_large_net=float(d.get('super_large_net', 0) or 0),
            large_net=float(d.get('large_net', 0) or 0),
            daily_avg_amount=d.get('daily_avg_amount'),
            margin_history=d.get('margin_history'),
            margin_history_dates=d.get('margin_history_dates'),
            margin_balance_change=d.get('margin_balance_change'),
        )


# ============================================================
# SectorContext — 板块相对强弱
# ============================================================

@dataclass
class SectorContext:
    """个股所属板块上下文及相对强弱"""
    sector_name: str = ""                        # 板块名称
    sector_pct: Optional[float] = None           # 板块今日涨跌幅 (%)
    stock_pct: Optional[float] = None            # 个股今日涨跌幅 (%)
    relative: Optional[float] = None             # 个股 - 板块 (pp)
    sector_5d_pct: Optional[float] = None        # 板块近5日累计涨跌幅（行业轮动判断）
    sector_rank: Optional[int] = None            # 板块今日强度排名（1=最强，数字越大越弱）
    sector_rank_total: Optional[int] = None      # 参与排名的板块总数
    
    @property
    def has_data(self) -> bool:
        return bool(self.sector_name)
    
    def to_dict(self) -> Dict[str, Any]:
        """序列化为旧格式 dict"""
        d = {
            'sector_name': self.sector_name or '未知',
            'sector_pct': self.sector_pct,
            'stock_pct': self.stock_pct,
            'relative': self.relative,
        }
        if self.sector_5d_pct is not None:
            d['sector_5d_pct'] = self.sector_5d_pct
        if self.sector_rank is not None:
            d['sector_rank'] = self.sector_rank
        if self.sector_rank_total is not None:
            d['sector_rank_total'] = self.sector_rank_total
        return d
    
    @classmethod
    def from_dict(cls, d: dict) -> 'SectorContext':
        if not d or not isinstance(d, dict):
            return cls()
        return cls(
            sector_name=str(d.get('sector_name', '') or ''),
            sector_pct=d.get('sector_pct'),
            stock_pct=d.get('stock_pct'),
            relative=d.get('relative'),
            sector_5d_pct=d.get('sector_5d_pct'),
            sector_rank=d.get('sector_rank'),
            sector_rank_total=d.get('sector_rank_total'),
        )


# ============================================================
# QuoteExtra — 行情附加数据
# ============================================================

@dataclass
class QuoteExtra:
    """行情附加数据（从实时行情提取，供评分扩展使用）"""
    turnover_rate: Optional[float] = None    # 换手率 (%)
    high_52w: Optional[float] = None         # 52周最高价
    low_52w: Optional[float] = None          # 52周最低价
    total_mv: Optional[float] = None         # 总市值（元）
    circ_mv: Optional[float] = None          # 流通市值（元）
    
    @property
    def has_data(self) -> bool:
        return any(v is not None for v in [self.turnover_rate, self.high_52w,
                                            self.low_52w, self.total_mv, self.circ_mv])
    
    def to_dict(self) -> Dict[str, Any]:
        """序列化为旧格式 dict"""
        d: Dict[str, Any] = {}
        for attr in ('turnover_rate', 'high_52w', 'low_52w', 'total_mv', 'circ_mv'):
            val = getattr(self, attr)
            if val is not None:
                d[attr] = val
        return d
    
    @classmethod
    def from_dict(cls, d: dict) -> 'QuoteExtra':
        if not d or not isinstance(d, dict):
            return cls()
        return cls(
            turnover_rate=d.get('turnover_rate'),
            high_52w=d.get('high_52w'),
            low_52w=d.get('low_52w'),
            total_mv=d.get('total_mv'),
            circ_mv=d.get('circ_mv'),
        )
