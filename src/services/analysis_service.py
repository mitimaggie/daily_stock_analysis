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
        send_notification: bool = True,
        position_info: Optional[Dict[str, Any]] = None,
        ab_variant: str = "standard",
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
            
            # 注入板块集中度风险（从持仓组合中计算）
            try:
                from src.services.portfolio_service import get_portfolio_sector_risk
                sector_risk = get_portfolio_sector_risk(stock_code)
                if sector_risk and sector_risk.get('concentration_warning'):
                    if position_info is None:
                        position_info = {}
                    position_info = dict(position_info)
                    position_info['sector_concentration_warning'] = sector_risk['concentration_warning']
                    position_info['portfolio_sector_map'] = sector_risk.get('portfolio_sector_map', {})
            except Exception as _e:
                logger.debug(f"板块集中度计算失败: {_e}")

            # 执行分析
            result = pipeline.process_single_stock(
                code=stock_code,
                skip_analysis=False,
                single_stock_notify=send_notification,
                report_type=rt,
                position_info=position_info,
                ab_variant=ab_variant,
            )
            
            if result is None:
                logger.warning(f"分析股票 {stock_code} 返回空结果")
                return None

            # A/B 自动配对：standard 分析完后，后台异步触发 no_skills 对照实验（测试 Skills 框架效益）
            # standard_3call 对照由手动触发（测试多调用效益，成本较高）
            if ab_variant == 'standard' and getattr(config, 'ab_auto_pair', False):
                import threading
                def _run_pair():
                    try:
                        import time
                        time.sleep(120)  # 错开 120 秒，等主分析批次完成后再启动，避免并发冲击 Gemini API
                        pair_pipeline = StockAnalysisPipeline(
                            config=config,
                            query_id=f"{query_id}_no_skills",
                            query_source="ab_auto"
                        )
                        pair_pipeline.process_single_stock(
                            code=stock_code,
                            skip_analysis=False,
                            single_stock_notify=False,
                            report_type=rt,
                            position_info=position_info,
                            ab_variant='no_skills',
                        )
                        logger.info(f"[AB] no_skills 配对分析完成: {stock_code}")
                    except Exception as e:
                        logger.warning(f"[AB] no_skills 配对分析失败: {stock_code}: {e}")
                threading.Thread(target=_run_pair, daemon=True, name=f"ab_pair_{stock_code}").start()

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
        
        # 持仓建议文字（优先级：场景化建议 > 持仓策略文本 > quant_extras > AI核心结论）
        dashboard = getattr(result, "dashboard", None) or {}
        core = dashboard.get("core_conclusion") or {}
        pos_advice = core.get("position_advice") or {}
        hs = dashboard.get("holding_strategy") or {}
        qe_tmp = dashboard.get("quant_extras") or {}
        ta = dashboard.get("trade_advice") or {}  # 场景化操作建议（最高优先级）
        # 空仓者：优先 trade_advice.advice_empty → holding_strategy.entry_advice → quant_extras → AI
        no_position = (
            ta.get("advice_empty", "")
            or hs.get("entry_advice", "")
            or qe_tmp.get("advice_for_empty", "")
            or pos_advice.get("no_position", "")
        )
        entry_pct = ta.get("position_pct", 0) or hs.get("entry_position_pct", 0) or qe_tmp.get("suggested_position_pct", 0) or 0
        # 持仓者：优先 trade_advice.advice_holding → holding_strategy.advice → quant_extras → AI
        has_position_advice = (
            ta.get("advice_holding", "")
            or hs.get("advice", "")
            or qe_tmp.get("advice_for_holding", "")
            or pos_advice.get("has_position", "")
        )
        position_advice = {
            "no_position": no_position,
            "has_position": has_position_advice,
            "trade_advice": ta,  # 完整场景数据，供前端展示
        }
        
        # 内部量化分（用于信号一致性等内部逻辑，保留不变）
        _quant_score_internal = getattr(result, "sentiment_score", 50)
        # 对外展示分：LLM 的分为主，量化分仅作参考对比
        llm_score = getattr(result, "llm_score", None)
        score = llm_score if llm_score is not None else _quant_score_internal
        sentiment_label = self._get_sentiment_label(score)
        
        # 持仓者策略直接从 pipeline 注入的 dashboard.holding_strategy 获取
        holding_strategy = dashboard.get("holding_strategy")
        
        # === 量化 vs AI 对比数据 ===
        quant_extras = dashboard.get("quant_extras") or {}
        llm_advice = getattr(result, "llm_advice", "") or ""
        llm_reasoning = getattr(result, "llm_reasoning", "") or ""
        # 量化技术信号分（signal_score）—— 仅供对比展示，不作为主决策分
        _quant_signal_score = (
            quant_extras.get("signal_score")
            or quant_extras.get("signalScore")
            or _quant_score_internal
        )
        # 计算量化技术信号 vs AI 分歧
        _divergence = abs(_quant_signal_score - score) if score is not None else 0
        _divergence_alert = ""
        if _divergence >= 20:
            q_dir = "看多" if _quant_signal_score >= 60 else ("看空" if _quant_signal_score <= 40 else "中性")
            a_dir = "看多" if score >= 60 else ("看空" if score <= 40 else "中性")
            _divergence_alert = (
                f"⚠️ 技术信号({_quant_signal_score}分/{q_dir}) 与 AI研判({score}分/{a_dir}) 方向不一致，"
                f"请结合基本面和市场情绪综合判断"
            )
            if llm_reasoning:
                _divergence_alert += f" | AI理由: {llm_reasoning[:80]}"
        elif _divergence >= 10:
            _divergence_alert = f"技术信号({_quant_signal_score}) vs AI研判({score}) 存在一定差异（{_divergence}分）"
        quant_vs_ai = {
            "quant_score": _quant_signal_score,
            "quant_advice": getattr(result, "operation_advice", ""),
            "ai_score": score,
            "ai_advice": llm_advice,
            "divergence_reason": llm_reasoning,
            "divergence": _divergence,
            "divergence_alert": _divergence_alert,
        }
        
        # === 盘中关键价位（从 quant_extras.intraday_watchlist） ===
        key_price_levels = quant_extras.get("intraday_watchlist", [])
        
        # === 当日行情快照 ===
        today_snapshot = {}
        # today_kline 从 result 的 context 不直接可用，从 dashboard 注入
        today_kline = dashboard.get("today_kline") or {}
        if today_kline:
            today_snapshot = today_kline
        # 补充实时数据
        today_snapshot["current_price"] = getattr(result, "current_price", 0) or 0
        today_snapshot["change_pct"] = getattr(result, "change_pct", None)
        today_snapshot["volume_ratio"] = quant_extras.get("volume_ratio", None)
        today_snapshot["turnover_rate"] = quant_extras.get("turnover_rate", None)
        
        # === 分批止盈计划 ===
        take_profit_plan = quant_extras.get("take_profit_plan", "")
        risk_reward_ratio = quant_extras.get("risk_reward_ratio", None)
        
        # === 持仓时间维度建议（短线/中线/长线）===
        holding_horizon = dashboard.get("holding_horizon") or {}
        
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
                "quant_vs_ai": quant_vs_ai,
            },
            "strategy": {
                "ideal_buy": str(sniper_points["ideal_buy"]) if sniper_points.get("ideal_buy") is not None else None,
                "secondary_buy": str(sniper_points["secondary_buy"]) if sniper_points.get("secondary_buy") is not None else None,
                "stop_loss": str(sniper_points["stop_loss"]) if sniper_points.get("stop_loss") is not None else None,
                "stop_loss_intraday": str(sniper_points["stop_loss_intraday"]) if sniper_points.get("stop_loss_intraday") is not None else None,
                "stop_loss_mid": str(sniper_points["stop_loss_mid"]) if sniper_points.get("stop_loss_mid") is not None else None,
                "take_profit": str(sniper_points["take_profit"]) if sniper_points.get("take_profit") is not None else None,
                "take_profit_mid": str(sniper_points["take_profit_mid"]) if sniper_points.get("take_profit_mid") is not None else None,
                "risk_reward_ratio": risk_reward_ratio,
                "take_profit_plan": take_profit_plan,
                "key_price_levels": key_price_levels,
                "holding_strategy": holding_strategy,
                "holding_horizon": holding_horizon,
            },
            "today_snapshot": today_snapshot,
            "details": {
                "news_summary": getattr(result, "news_summary", "") or "",
                "technical_analysis": getattr(result, "technical_analysis", "") or "",
                "fundamental_analysis": getattr(result, "fundamental_analysis", "") or "",
                "risk_warning": getattr(result, "risk_warning", "") or "",
                "dashboard": dashboard,
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
