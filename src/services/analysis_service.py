# -*- coding: utf-8 -*-
"""
===================================
分析服务层
===================================

职责：
1. 封装股票分析逻辑
2. 调用 analyzer 和 pipeline 执行分析
3. 保存分析结果到数据库
"""

import logging
import uuid
from typing import Optional, Dict, Any

from src.repositories.analysis_repo import AnalysisRepository

logger = logging.getLogger(__name__)


class AnalysisService:
    """
    分析服务
    
    封装股票分析相关的业务逻辑
    """
    
    def __init__(self):
        """初始化分析服务"""
        self.repo = AnalysisRepository()
    
    def analyze_stock(
        self,
        stock_code: str,
        report_type: str = "detailed",
        force_refresh: bool = False,
        query_id: Optional[str] = None,
        send_notification: bool = True
    ) -> Optional[Dict[str, Any]]:
        """
        执行股票分析
        
        Args:
            stock_code: 股票代码
            report_type: 报告类型 (simple/detailed)
            force_refresh: 是否强制刷新
            query_id: 查询 ID（可选）
            send_notification: 是否发送通知（API 触发默认发送）
            
        Returns:
            分析结果字典，包含:
            - stock_code: 股票代码
            - stock_name: 股票名称
            - report: 分析报告
        """
        try:
            # 导入分析相关模块
            from src.config import get_config
            from src.core.pipeline import StockAnalysisPipeline
            from src.enums import ReportType
            
            # 生成 query_id
            if query_id is None:
                query_id = uuid.uuid4().hex
            
            # 获取配置
            config = get_config()
            
            # 创建分析流水线
            pipeline = StockAnalysisPipeline(
                config=config,
                query_id=query_id,
                query_source="api"
            )
            
            # 确定报告类型
            rt = ReportType.FULL if report_type == "detailed" else ReportType.SIMPLE
            
            # 执行分析
            result = pipeline.process_single_stock(
                code=stock_code,
                skip_analysis=False,
                single_stock_notify=send_notification,
                report_type=rt
            )
            
            if result is None:
                logger.warning(f"分析股票 {stock_code} 返回空结果")
                return None
            
            # 构建响应
            return self._build_analysis_response(result, query_id)
            
        except Exception as e:
            logger.error(f"分析股票 {stock_code} 失败: {e}", exc_info=True)
            return None
    
    def _build_analysis_response(
        self, 
        result: Any, 
        query_id: str
    ) -> Dict[str, Any]:
        """
        构建分析响应
        
        Args:
            result: AnalysisResult 对象
            query_id: 查询 ID
            
        Returns:
            格式化的响应字典
        """
        # 获取狙击点位
        sniper_points = {}
        if hasattr(result, 'get_sniper_points'):
            sniper_points = result.get_sniper_points() or {}
        
        # 持仓建议（空仓/持仓分开展示）
        dashboard = getattr(result, "dashboard", None) or {}
        core = dashboard.get("core_conclusion") or {}
        pos_advice = core.get("position_advice") or {}
        position_advice = {
            "no_position": pos_advice.get("no_position", ""),
            "has_position": pos_advice.get("has_position", ""),
        }
        
        # 计算情绪标签（兼容无 sentiment_score）
        score = getattr(result, "sentiment_score", 50)
        sentiment_label = self._get_sentiment_label(score)
        
        # 构建报告结构（全部 getattr 兼容本仓库 AnalysisResult 字段）
        report = {
            "meta": {
                "query_id": query_id,
                "stock_code": getattr(result, "code", ""),
                "stock_name": getattr(result, "name", ""),
                "report_type": "detailed",
                "current_price": getattr(result, "current_price", 0) or 0,
                "change_pct": getattr(result, "change_pct", None),
            },
            "summary": {
                "analysis_summary": getattr(result, "analysis_summary", "") or "",
                "operation_advice": getattr(result, "operation_advice", ""),
                "trend_prediction": getattr(result, "trend_prediction", ""),
                "sentiment_score": score,
                "sentiment_label": sentiment_label,
                "position_advice": position_advice,
            },
            "strategy": {
                "ideal_buy": sniper_points.get("ideal_buy"),
                "secondary_buy": sniper_points.get("secondary_buy"),
                "stop_loss": sniper_points.get("stop_loss"),
                "take_profit": sniper_points.get("take_profit"),
            },
            "details": {
                "news_summary": getattr(result, "news_summary", "") or "",
                "technical_analysis": getattr(result, "technical_analysis", "") or "",
                "fundamental_analysis": getattr(result, "fundamental_analysis", "") or "",
                "risk_warning": getattr(result, "risk_warning", "") or "",
            }
        }
        
        return {
            "stock_code": getattr(result, "code", ""),
            "stock_name": getattr(result, "name", ""),
            "report": report,
        }
    
    @staticmethod
    def _get_sentiment_label(score: int) -> str:
        from src.services import get_sentiment_label
        return get_sentiment_label(score)
