# -*- coding: utf-8 -*-
"""
===================================
历史记录相关模型
===================================

职责：
1. 定义历史记录列表和详情模型
2. 定义分析报告完整模型
"""

from typing import Optional, List, Any

from pydantic import BaseModel, Field


class HistoryItem(BaseModel):
    """历史记录摘要（列表展示用）"""
    
    query_id: str = Field(..., description="分析记录唯一标识")
    stock_code: str = Field(..., description="股票代码")
    stock_name: Optional[str] = Field(None, description="股票名称")
    report_type: Optional[str] = Field(None, description="报告类型")
    sentiment_score: Optional[int] = Field(
        None, 
        description="情绪评分 (0-100)",
        ge=0,
        le=100
    )
    operation_advice: Optional[str] = Field(None, description="操作建议")
    created_at: Optional[str] = Field(None, description="创建时间")
    
    class Config:
        json_schema_extra = {
            "example": {
                "query_id": "abc123",
                "stock_code": "600519",
                "stock_name": "贵州茅台",
                "report_type": "detailed",
                "sentiment_score": 75,
                "operation_advice": "持有",
                "created_at": "2024-01-01T12:00:00"
            }
        }


class HistoryListResponse(BaseModel):
    """历史记录列表响应"""
    
    total: int = Field(..., description="总记录数")
    page: int = Field(..., description="当前页码")
    limit: int = Field(..., description="每页数量")
    items: List[HistoryItem] = Field(default_factory=list, description="记录列表")
    
    class Config:
        json_schema_extra = {
            "example": {
                "total": 100,
                "page": 1,
                "limit": 20,
                "items": []
            }
        }


class NewsIntelItem(BaseModel):
    """新闻情报条目"""

    title: str = Field(..., description="新闻标题")
    snippet: str = Field("", description="新闻摘要（最多50字）")
    url: str = Field(..., description="新闻链接")

    class Config:
        json_schema_extra = {
            "example": {
                "title": "公司发布业绩快报，营收同比增长 20%",
                "snippet": "公司公告显示，季度营收同比增长 20%...",
                "url": "https://example.com/news/123"
            }
        }


class NewsIntelResponse(BaseModel):
    """新闻情报响应"""

    total: int = Field(..., description="新闻条数")
    items: List[NewsIntelItem] = Field(default_factory=list, description="新闻列表")

    class Config:
        json_schema_extra = {
            "example": {
                "total": 2,
                "items": []
            }
        }


class ReportMeta(BaseModel):
    """报告元信息"""
    
    query_id: str = Field(..., description="分析记录唯一标识")
    stock_code: str = Field(..., description="股票代码")
    stock_name: Optional[str] = Field(None, description="股票名称")
    report_type: Optional[str] = Field(None, description="报告类型")
    created_at: Optional[str] = Field(None, description="创建时间")
    current_price: Optional[float] = Field(None, description="分析时股价")
    change_pct: Optional[float] = Field(None, description="分析时涨跌幅(%)")
    prev_score: Optional[int] = Field(None, description="上次分析评分")
    score_change: Optional[int] = Field(None, description="评分变化")


class PositionAdvice(BaseModel):
    """空仓/持仓分开展示"""
    no_position: Optional[str] = Field(None, description="空仓建议")
    has_position: Optional[str] = Field(None, description="持仓建议")


class QuantVsAi(BaseModel):
    """量化 vs AI 对比数据"""
    quant_score: Optional[int] = Field(None, description="量化评分")
    quant_advice: Optional[str] = Field(None, description="量化建议")
    ai_score: Optional[int] = Field(None, description="AI评分")
    ai_advice: Optional[str] = Field(None, description="AI建议")
    divergence_reason: Optional[str] = Field(None, description="分歧原因")


class KeyPriceLevel(BaseModel):
    """盘中关键价位"""
    price: float = Field(..., description="价位")
    type: str = Field(..., description="类型: stop_loss/buy/breakout/take_profit/support/resistance")
    action: str = Field(..., description="类型中文名")
    desc: str = Field(..., description="触发动作描述")
    priority: Optional[int] = Field(None, description="优先级")


class TodaySnapshot(BaseModel):
    """当日行情快照"""
    open: Optional[float] = Field(None, description="开盘价")
    high: Optional[float] = Field(None, description="最高价")
    low: Optional[float] = Field(None, description="最低价")
    close: Optional[float] = Field(None, description="收盘价")
    volume: Optional[float] = Field(None, description="成交量")
    amount: Optional[float] = Field(None, description="成交额")
    pct_chg: Optional[float] = Field(None, description="涨跌幅(%)")
    current_price: Optional[float] = Field(None, description="当前价")
    change_pct: Optional[float] = Field(None, description="涨跌幅(%)")
    volume_ratio: Optional[float] = Field(None, description="量比")
    turnover_rate: Optional[float] = Field(None, description="换手率(%)")


class ReportSummary(BaseModel):
    """报告概览区"""
    
    analysis_summary: Optional[str] = Field(None, description="关键结论")
    operation_advice: Optional[str] = Field(None, description="操作建议")
    trend_prediction: Optional[str] = Field(None, description="趋势预测")
    sentiment_score: Optional[int] = Field(
        None, 
        description="情绪评分 (0-100)",
        ge=0,
        le=100
    )
    sentiment_label: Optional[str] = Field(None, description="情绪标签")
    position_advice: Optional[PositionAdvice] = Field(None, description="空仓/持仓分开展示")
    quant_vs_ai: Optional[QuantVsAi] = Field(None, description="量化 vs AI 对比")


class HoldingStrategy(BaseModel):
    """统一持仓者策略（供 PushPlus / Web / API 共用）"""
    
    # 推荐止损
    recommended_stop: Optional[float] = Field(None, description="推荐止损价位")
    recommended_stop_type: Optional[str] = Field(None, description="推荐止损类型: trailing/mid/short")
    recommended_stop_reason: Optional[str] = Field(None, description="推荐理由")
    # 推荐止盈
    recommended_target: Optional[float] = Field(None, description="推荐止盈目标")
    recommended_target_type: Optional[str] = Field(None, description="推荐止盈类型: short/mid")
    # 所有量化锚点
    stop_loss_short: Optional[float] = Field(None, description="短线止损 (1.0 ATR)")
    stop_loss_mid: Optional[float] = Field(None, description="中线止损 (1.5 ATR)")
    trailing_stop: Optional[float] = Field(None, description="移动止盈线 (Parabolic SAR)")
    target_short: Optional[float] = Field(None, description="短线止盈目标")
    target_mid: Optional[float] = Field(None, description="中线止盈目标 (第一阻力位)")
    # 综合建议
    advice: Optional[str] = Field(None, description="持仓综合建议文本")
    # 空仓入场参考
    entry_stop_loss: Optional[float] = Field(None, description="入场止损价")
    entry_position_pct: Optional[int] = Field(None, description="建议入场仓位(%)")
    entry_advice: Optional[str] = Field(None, description="空仓建议")


class EntryConditionItem(BaseModel):
    """建仓条件项"""
    label: str = Field(..., description="条件描述")
    met: bool = Field(False, description="是否已满足")


class EntryConditions(BaseModel):
    """建仓条件（未持仓时展示）"""
    price_range_low: Optional[float] = Field(None, description="理想入场区间下限")
    price_range_high: Optional[float] = Field(None, description="理想入场区间上限")
    price_range_desc: Optional[str] = Field(None, description="价格区间描述（如'19元附近'）")
    current_vs_entry: Optional[str] = Field(None, description="当前价相对入场区间位置描述")
    conditions: List[EntryConditionItem] = Field(default_factory=list, description="触发条件列表")
    suggested_position_pct: Optional[int] = Field(None, description="建议首次仓位(%)")
    summary: Optional[str] = Field(None, description="一句话建仓建议")


class ReportStrategy(BaseModel):
    """策略点位区"""
    
    ideal_buy: Optional[str] = Field(None, description="理想买入价")
    secondary_buy: Optional[str] = Field(None, description="第二买入价")
    stop_loss: Optional[str] = Field(None, description="止损价")
    stop_loss_intraday: Optional[str] = Field(None, description="日内止损")
    stop_loss_mid: Optional[str] = Field(None, description="中线止损")
    take_profit: Optional[str] = Field(None, description="短线止盈")
    take_profit_mid: Optional[str] = Field(None, description="中线止盈")
    risk_reward_ratio: Optional[float] = Field(None, description="风险收益比")
    take_profit_plan: Optional[str] = Field(None, description="分批止盈计划")
    key_price_levels: Optional[List[KeyPriceLevel]] = Field(None, description="盘中关键价位")
    holding_strategy: Optional[HoldingStrategy] = Field(None, description="持仓者专用策略")


class ReportDetails(BaseModel):
    """报告详情区"""
    
    news_content: Optional[str] = Field(None, description="新闻摘要")
    raw_result: Optional[Any] = Field(None, description="原始分析结果（JSON）")
    context_snapshot: Optional[Any] = Field(None, description="分析时上下文快照（JSON）")


class AnalysisReport(BaseModel):
    """完整分析报告"""
    
    meta: ReportMeta = Field(..., description="元信息")
    summary: ReportSummary = Field(..., description="概览区")
    strategy: Optional[ReportStrategy] = Field(None, description="策略点位区")
    today_snapshot: Optional[TodaySnapshot] = Field(None, description="当日行情快照")
    details: Optional[ReportDetails] = Field(None, description="详情区")
    entry_conditions: Optional[EntryConditions] = Field(None, description="建仓条件（未持仓时）")
    
    class Config:
        json_schema_extra = {
            "example": {
                "meta": {
                    "query_id": "abc123",
                    "stock_code": "600519",
                    "stock_name": "贵州茅台",
                    "report_type": "detailed",
                    "created_at": "2024-01-01T12:00:00"
                },
                "summary": {
                    "analysis_summary": "技术面向好，建议持有",
                    "operation_advice": "持有",
                    "trend_prediction": "看多",
                    "sentiment_score": 75,
                    "sentiment_label": "乐观"
                },
                "strategy": {
                    "ideal_buy": "1800.00",
                    "secondary_buy": "1750.00",
                    "stop_loss": "1700.00",
                    "take_profit": "2000.00"
                },
                "details": None
            }
        }
