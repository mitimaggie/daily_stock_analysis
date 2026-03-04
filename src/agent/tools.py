# -*- coding: utf-8 -*-
"""
Agent 工具层 - 封装数据获取、分析、搜索能力供 LLM function calling 使用
"""

import logging
from datetime import datetime
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

_shared_mgr = None


def _get_mgr():
    global _shared_mgr
    if _shared_mgr is None:
        from data_provider.base import DataFetcherManager
        _shared_mgr = DataFetcherManager()
    return _shared_mgr


def get_realtime_quote(stock_code: str) -> Dict[str, Any]:
    """获取股票实时行情（价格、涨跌幅、成交量等）"""
    try:
        mgr = _get_mgr()
        q = mgr.get_realtime_quote(stock_code)
        if not q:
            return {"error": f"无法获取 {stock_code} 实时行情"}
        return {
            "stock_code": stock_code,
            "price": getattr(q, 'price', None),
            "change_pct": getattr(q, 'change_pct', None),
            "volume": getattr(q, 'volume', None),
            "amount": getattr(q, 'amount', None),
            "high": getattr(q, 'high', None),
            "low": getattr(q, 'low', None),
            "open": getattr(q, 'open', None),
            "prev_close": getattr(q, 'prev_close', None),
            "turnover_rate": getattr(q, 'turnover_rate', None),
            "volume_ratio": getattr(q, 'volume_ratio', None),
            "name": getattr(q, 'name', stock_code),
        }
    except Exception as e:
        logger.warning(f"get_realtime_quote({stock_code}) failed: {e}")
        return {"error": str(e)}


def get_daily_history(stock_code: str, days: int = 60) -> Dict[str, Any]:
    """获取股票近N日历史K线数据摘要（均线、趋势、成交量变化）"""
    try:
        mgr = _get_mgr()
        df, source = mgr.get_daily_data(stock_code, days=days)
        if df is None or df.empty:
            return {"error": f"无法获取 {stock_code} 历史数据"}

        df = df.tail(days)
        latest = df.iloc[-1]
        prev = df.iloc[-2] if len(df) > 1 else latest

        # 计算均线
        close = df['close']
        ma5 = close.tail(5).mean()
        ma10 = close.tail(10).mean()
        ma20 = close.tail(20).mean()
        ma60 = close.tail(60).mean() if len(df) >= 60 else None

        # 成交量变化
        vol_avg5 = df['volume'].tail(5).mean()
        vol_avg20 = df['volume'].tail(20).mean()
        vol_ratio = vol_avg5 / vol_avg20 if vol_avg20 > 0 else None

        # 涨跌幅
        price_change_20d = (float(latest['close']) / float(df.iloc[-20]['close']) - 1) * 100 if len(df) >= 20 else None

        return {
            "stock_code": stock_code,
            "data_source": source,
            "days_available": len(df),
            "latest_date": str(latest['date']),
            "latest_close": float(latest['close']),
            "latest_volume": float(latest.get('volume', 0)),
            "ma5": round(float(ma5), 2),
            "ma10": round(float(ma10), 2),
            "ma20": round(float(ma20), 2),
            "ma60": round(float(ma60), 2) if ma60 is not None else None,
            "price_above_ma5": float(latest['close']) > float(ma5),
            "price_above_ma20": float(latest['close']) > float(ma20),
            "vol_ratio_5d_vs_20d": round(float(vol_ratio), 2) if vol_ratio else None,
            "price_change_20d_pct": round(float(price_change_20d), 2) if price_change_20d is not None else None,
        }
    except Exception as e:
        logger.warning(f"get_daily_history({stock_code}) failed: {e}")
        return {"error": str(e)}


def get_chip_distribution(stock_code: str) -> Dict[str, Any]:
    """获取股票筹码分布（获利盘比例、平均成本、集中度）"""
    try:
        mgr = _get_mgr()
        chip = mgr.get_chip_distribution(stock_code)
        if not chip:
            return {"error": f"无法获取 {stock_code} 筹码数据（可能未启用或缓存未就绪）"}
        return {
            "stock_code": stock_code,
            "date": chip.date,
            "profit_ratio": chip.profit_ratio,
            "avg_cost": chip.avg_cost,
            "cost_90_low": chip.cost_90_low,
            "cost_90_high": chip.cost_90_high,
            "concentration_90": chip.concentration_90,
            "cost_70_low": chip.cost_70_low,
            "cost_70_high": chip.cost_70_high,
            "concentration_70": chip.concentration_70,
        }
    except Exception as e:
        logger.warning(f"get_chip_distribution({stock_code}) failed: {e}")
        return {"error": str(e)}


def get_analysis_context(query_id: str) -> Dict[str, Any]:
    """获取已有分析报告的完整上下文（评分、建议、技术指标等）"""
    try:
        from src.storage import DatabaseManager
        from src.services.history_service import HistoryService
        db = DatabaseManager()
        svc = HistoryService(db)
        report = svc.get_history_detail(query_id)
        if not report:
            return {"error": f"报告 {query_id} 不存在"}

        meta = report.get("meta") or {}
        summary = report.get("summary") or {}
        strategy = report.get("strategy") or {}
        details = report.get("details") or {}
        raw = details.get("raw_result") or {}
        dashboard = raw.get("dashboard") or {} if isinstance(raw, dict) else {}
        qe = dashboard.get("quant_extras") or {}

        result = {
            "stock_code": meta.get("stock_code"),
            "stock_name": meta.get("stock_name"),
            "report_time": meta.get("created_at"),
            "current_price": meta.get("current_price"),
            "sentiment_score": summary.get("sentiment_score"),
            "sentiment_label": summary.get("sentiment_label"),
            "operation_advice": summary.get("operation_advice"),
            "trend_prediction": summary.get("trend_prediction"),
            "analysis_summary": summary.get("analysis_summary"),
            "ideal_buy": strategy.get("ideal_buy"),
            "stop_loss": strategy.get("stop_loss"),
            "take_profit": strategy.get("take_profit"),
            "trend_status": qe.get("trend_status"),
            "buy_signal": qe.get("buy_signal"),
            "macd_status": qe.get("macd_status"),
            "kdj_status": qe.get("kdj_status"),
            "rsi_status": qe.get("rsi_status"),
            "volume_status": qe.get("volume_status"),
            "risk_factors": qe.get("risk_factors", []),
            "resonance_signals": qe.get("resonance_signals", []),
        }
        return {k: v for k, v in result.items() if v is not None}
    except Exception as e:
        logger.warning(f"get_analysis_context({query_id}) failed: {e}")
        return {"error": str(e)}


def search_stock_news(stock_code: str, stock_name: str = "") -> Dict[str, Any]:
    """搜索股票最新新闻、公告、机构动向（使用 Perplexity AI）"""
    try:
        from src.search_service import get_search_service
        svc = get_search_service()
        if not svc.provider:
            return {"error": "搜索服务未配置（需要 PERPLEXITY_API_KEY）"}

        query = f"{stock_name or stock_code} 股票 最新公告 机构动向 近期新闻"
        resp = svc.search(query)
        if not resp.success:
            return {"error": resp.error_message}
        return {
            "stock_code": stock_code,
            "query": query,
            "content": resp.to_context(max_results=5),
            "provider": resp.provider,
        }
    except Exception as e:
        logger.warning(f"search_stock_news({stock_code}) failed: {e}")
        return {"error": str(e)}


def get_stock_name(stock_code: str) -> str:
    """根据股票代码获取股票名称"""
    try:
        mgr = _get_mgr()
        # 尝试通过实时行情获取名称
        q = mgr.get_realtime_quote(stock_code)
        if q and getattr(q, 'name', None):
            return q.name
    except Exception:
        pass
    return stock_code


# ============ 工具注册表 ============

TOOL_DEFINITIONS = [
    {
        "name": "get_realtime_quote",
        "description": "获取股票实时行情，包括当前价格、涨跌幅、成交量、换手率等。适合回答'现在多少钱'、'今天涨了多少'等问题。",
        "parameters": {
            "type": "object",
            "properties": {
                "stock_code": {
                    "type": "string",
                    "description": "股票代码，如 600519、000001、AAPL"
                }
            },
            "required": ["stock_code"]
        }
    },
    {
        "name": "get_daily_history",
        "description": "获取股票近期历史K线数据摘要，包括均线（MA5/10/20/60）、成交量变化、近20日涨跌幅。适合回答趋势、均线排列等问题。",
        "parameters": {
            "type": "object",
            "properties": {
                "stock_code": {
                    "type": "string",
                    "description": "股票代码"
                },
                "days": {
                    "type": "integer",
                    "description": "获取天数，默认60天",
                    "default": 60
                }
            },
            "required": ["stock_code"]
        }
    },
    {
        "name": "get_chip_distribution",
        "description": "获取股票筹码分布数据，包括获利盘比例、平均成本、90%/70%筹码集中区间。适合分析套牢盘、支撑压力位。",
        "parameters": {
            "type": "object",
            "properties": {
                "stock_code": {
                    "type": "string",
                    "description": "股票代码"
                }
            },
            "required": ["stock_code"]
        }
    },
    {
        "name": "get_analysis_context",
        "description": "获取已生成的分析报告详情，包括量化评分、AI建议、技术指标、止损止盈点位等。需要提供报告ID（query_id）。",
        "parameters": {
            "type": "object",
            "properties": {
                "query_id": {
                    "type": "string",
                    "description": "分析报告的唯一ID（query_id）"
                }
            },
            "required": ["query_id"]
        }
    },
    {
        "name": "search_stock_news",
        "description": "搜索股票最新新闻、公告、机构调研、增减持等情报。适合回答'最近有什么消息'、'机构怎么看'等问题。",
        "parameters": {
            "type": "object",
            "properties": {
                "stock_code": {
                    "type": "string",
                    "description": "股票代码"
                },
                "stock_name": {
                    "type": "string",
                    "description": "股票名称（可选，提高搜索精度）",
                    "default": ""
                }
            },
            "required": ["stock_code"]
        }
    },
]

TOOL_FUNCTIONS = {
    "get_realtime_quote": get_realtime_quote,
    "get_daily_history": get_daily_history,
    "get_chip_distribution": get_chip_distribution,
    "get_analysis_context": get_analysis_context,
    "search_stock_news": search_stock_news,
}

TOOL_DISPLAY_NAMES = {
    "get_realtime_quote": "获取实时行情",
    "get_daily_history": "获取历史K线",
    "get_chip_distribution": "分析筹码分布",
    "get_analysis_context": "读取分析报告",
    "search_stock_news": "搜索最新情报",
}
