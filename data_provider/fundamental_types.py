# -*- coding: utf-8 -*-
"""
===================================
基本面数据结构化类型定义
===================================
将原先 fundamental_data 的裸 dict 替换为强类型 dataclass，
消除 fetcher → pipeline → scoring 之间的隐式契约。

设计原则：
1. 内部字段用 Optional[float]，消费方无需手动解析
2. to_dict() 输出与旧 dict 结构完全一致（字符串值 + 'N/A'），
   确保 DB 缓存、LLM context 零变化
3. from_dict() 兼容旧 DB 缓存格式，实现无缝迁移
"""

from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List


# ============================================================
# 工具函数
# ============================================================

def _parse_pct(val) -> Optional[float]:
    """将百分比字符串/数值统一解析为 float，无效值返回 None。
    
    支持格式: "15.3%", "15.3", 15.3, "-5%", "N/A", None, ""
    """
    if val is None:
        return None
    if isinstance(val, (int, float)):
        import math
        if math.isnan(val):
            return None
        return float(val)
    if isinstance(val, str):
        s = val.strip().replace('%', '')
        if s in ('N/A', '', 'None', '无', '--', '-'):
            return None
        try:
            return float(s)
        except (ValueError, TypeError):
            return None
    return None


def _fmt_pct(val: Optional[float]) -> str:
    """将 float 还原为旧格式字符串（无 % 后缀，保持与 akshare 原始输出一致）。
    
    旧代码中 fetcher 存的是 str(latest.get(..., "N/A"))，
    akshare 返回的数值本身不带 % 符号，所以这里也不加。
    """
    if val is None:
        return "N/A"
    return str(val)


# ============================================================
# FinancialSummary — 财务摘要
# ============================================================

@dataclass
class FinancialSummary:
    """财务摘要数据（来自同花顺/东财 F10）
    
    所有百分比指标均为 float 类型（如 ROE=15.3 表示 15.3%），
    None 表示数据不可用。
    """
    roe: Optional[float] = None                # 净资产收益率 (%)
    debt_ratio: Optional[float] = None         # 资产负债率 (%)
    gross_margin: Optional[float] = None       # 销售毛利率 (%)
    net_profit_growth: Optional[float] = None  # 净利润同比增长率 (%)
    revenue_growth: Optional[float] = None     # 营业总收入同比增长率 (%)
    date: str = ""                             # 报告期
    source: str = ""                           # 数据来源 ("ths" / "em")
    
    @property
    def has_data(self) -> bool:
        """是否有有效财务数据"""
        return any(v is not None for v in [self.roe, self.debt_ratio, self.gross_margin,
                                            self.net_profit_growth, self.revenue_growth])
    
    def to_dict(self) -> Dict[str, Any]:
        """序列化为旧格式 dict（兼容 DB 缓存 + LLM context）"""
        return {
            "date": self.date,
            "roe": _fmt_pct(self.roe),
            "net_profit_growth": _fmt_pct(self.net_profit_growth),
            "revenue_growth": _fmt_pct(self.revenue_growth),
            "gross_margin": _fmt_pct(self.gross_margin),
            "debt_ratio": _fmt_pct(self.debt_ratio),
            "source": self.source,
        }
    
    @classmethod
    def from_dict(cls, d: dict) -> 'FinancialSummary':
        """从旧格式 dict 反序列化"""
        if not d or not isinstance(d, dict):
            return cls()
        return cls(
            roe=_parse_pct(d.get('roe')),
            debt_ratio=_parse_pct(d.get('debt_ratio')),
            gross_margin=_parse_pct(d.get('gross_margin')),
            net_profit_growth=_parse_pct(d.get('net_profit_growth')),
            revenue_growth=_parse_pct(d.get('revenue_growth')),
            date=str(d.get('date', '')),
            source=str(d.get('source', '')),
        )


# ============================================================
# ForecastData — 业绩预测
# ============================================================

@dataclass
class ForecastData:
    """业绩预测数据（来自同花顺）"""
    rating: str = ""                              # 分析师评级 ("买入"/"增持"/...)
    target_price: Optional[float] = None          # 目标价格 (元)
    avg_profit_change: Optional[float] = None     # 平均净利润变动幅 (%)
    
    @property
    def has_data(self) -> bool:
        """是否有有效预测数据"""
        return bool(self.rating and self.rating not in ('无', '', 'N/A')) or \
               self.target_price is not None or self.avg_profit_change is not None
    
    def to_dict(self) -> Dict[str, Any]:
        """序列化为旧格式 dict"""
        return {
            "rating": self.rating or "无",
            "target_price": str(self.target_price) if self.target_price is not None else "无",
            "avg_profit_change": _fmt_pct(self.avg_profit_change),
        }
    
    @classmethod
    def from_dict(cls, d: dict) -> 'ForecastData':
        """从旧格式 dict 反序列化"""
        if not d or not isinstance(d, dict):
            return cls()
        # target_price 旧格式可能是 "15.0" / "无" / float
        tp_raw = d.get('target_price', '无')
        tp = None
        if tp_raw not in ('无', '', 'N/A', None):
            try:
                tp = float(str(tp_raw).replace('元', '').strip())
            except (ValueError, TypeError):
                pass
        return cls(
            rating=str(d.get('rating', '无') or '无'),
            target_price=tp,
            avg_profit_change=_parse_pct(d.get('avg_profit_change')),
        )


# ============================================================
# ValuationSnapshot — 估值快照（供 check_valuation 使用）
# ============================================================

@dataclass
class ValuationSnapshot:
    """估值快照数据
    
    合并来自实时行情(PE/PB)、基本面(PEG/增长率)、
    历史数据(PE历史/行业PE中位数) 的估值信息。
    由 pipeline 一次性构建，传入 check_valuation。
    """
    pe: Optional[float] = None                    # 市盈率(动态)
    pb: Optional[float] = None                    # 市净率
    peg: Optional[float] = None                   # PEG
    total_mv: Optional[float] = None              # 总市值(元)
    industry_pe_median: Optional[float] = None    # 行业PE中位数
    pe_history: Optional[List[float]] = None      # PE(TTM)历史数据
    revenue_growth: Optional[float] = None        # 营收增速(%)，从 financial 提取
    net_profit_growth: Optional[float] = None     # 净利增速(%)，从 financial 提取
    
    def to_dict(self) -> Dict[str, Any]:
        """序列化为 dict（供调试/日志，非 DB 缓存路径）"""
        d = {}
        for attr in ('pe', 'pb', 'peg', 'total_mv', 'industry_pe_median',
                      'revenue_growth', 'net_profit_growth'):
            val = getattr(self, attr)
            if val is not None:
                d[attr] = val
        if self.pe_history:
            d['pe_history'] = self.pe_history
        return d


# ============================================================
# FundamentalData — 顶层容器
# ============================================================

@dataclass
class FundamentalData:
    """基本面数据顶层容器
    
    整合 financial(财务摘要) + forecast(业绩预测) + valuation(估值，pipeline 注入)。
    替代原先的 {"valuation": {}, "financial": {}, "forecast": {}} 裸 dict。
    """
    financial: FinancialSummary = field(default_factory=FinancialSummary)
    forecast: ForecastData = field(default_factory=ForecastData)
    valuation: Dict[str, Any] = field(default_factory=dict)  # 保持 dict 供 pipeline 灵活注入
    
    @property
    def has_financial(self) -> bool:
        return self.financial.has_data
    
    def to_dict(self) -> Dict[str, Any]:
        """序列化为旧格式 dict（与原 fundamental_data dict 完全一致）
        
        输出结构:
        {
            "valuation": {...},
            "financial": {"roe": "15.3", "debt_ratio": "45.0", ...},
            "forecast": {"rating": "买入", "target_price": "15.0", ...}
        }
        """
        return {
            "valuation": dict(self.valuation),  # 浅拷贝
            "financial": self.financial.to_dict(),
            "forecast": self.forecast.to_dict(),
        }
    
    @classmethod
    def from_dict(cls, d: dict) -> 'FundamentalData':
        """从旧格式 dict 反序列化（兼容 DB 缓存）
        
        Args:
            d: 旧格式 dict，结构为 {"valuation": {}, "financial": {}, "forecast": {}}
               也兼容空 dict 或 None
        """
        if not d or not isinstance(d, dict):
            return cls()
        return cls(
            financial=FinancialSummary.from_dict(d.get('financial', {})),
            forecast=ForecastData.from_dict(d.get('forecast', {})),
            valuation=dict(d.get('valuation', {}) or {}),
        )
