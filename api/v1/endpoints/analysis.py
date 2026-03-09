# -*- coding: utf-8 -*-
"""
===================================
股票分析接口
===================================

职责：
1. 提供 POST /api/v1/analysis/analyze 触发分析接口
2. 提供 GET /api/v1/analysis/status/{task_id} 查询任务状态接口
3. 提供 GET /api/v1/analysis/tasks 获取任务列表接口
4. 提供 GET /api/v1/analysis/tasks/stream SSE 实时推送接口

特性：
- 异步任务队列：分析任务异步执行，不阻塞请求
- 防重复提交：相同股票代码正在分析时返回 409
- SSE 实时推送：任务状态变化实时通知前端
"""

import asyncio
import json
import logging
from datetime import datetime
from typing import Optional, Union, Dict, Any

from fastapi import APIRouter, HTTPException, Depends, Query
from fastapi.responses import JSONResponse, StreamingResponse

from api.deps import get_config_dep
from api.v1.schemas.analysis import (
    AnalyzeRequest,
    AnalysisResultResponse,
    TaskAccepted,
    TaskStatus,
    TaskInfo,
    TaskListResponse,
    DuplicateTaskErrorResponse,
)
from api.v1.schemas.common import ErrorResponse
from api.v1.schemas.history import (
    AnalysisReport,
    ReportMeta,
    ReportSummary,
    ReportStrategy,
    ReportDetails,
    HoldingStrategy,
    QuantVsAi,
    KeyPriceLevel,
    TodaySnapshot,
    EntryConditions,
)
from src.config import Config
from src.services.task_queue import (
    get_task_queue,
    DuplicateTaskError,
    TaskStatus as TaskStatusEnum,
)

logger = logging.getLogger(__name__)

router = APIRouter()


# ============================================================
# POST /analyze - 触发股票分析
# ============================================================

@router.post(
    "/analyze",
    response_model=AnalysisResultResponse,
    responses={
        200: {"description": "分析完成（同步模式）", "model": AnalysisResultResponse},
        202: {"description": "分析任务已接受（异步模式）", "model": TaskAccepted},
        400: {"description": "请求参数错误", "model": ErrorResponse},
        409: {"description": "股票正在分析中，拒绝重复提交", "model": DuplicateTaskErrorResponse},
        500: {"description": "分析失败", "model": ErrorResponse},
    },
    summary="触发股票分析",
    description="启动 AI 智能分析任务，支持同步和异步模式。异步模式下相同股票代码不允许重复提交。"
)
def trigger_analysis(
        request: AnalyzeRequest,
        config: Config = Depends(get_config_dep)
) -> Union[AnalysisResultResponse, JSONResponse]:
    """
    触发股票分析
    
    启动 AI 智能分析任务，支持单只或多只股票批量分析
    
    流程：
    1. 校验请求参数
    2. 异步模式：检查重复 -> 提交任务队列 -> 返回 202
    3. 同步模式：直接执行分析 -> 返回 200
    
    Args:
        request: 分析请求参数
        config: 配置依赖
        
    Returns:
        AnalysisResultResponse: 分析结果（同步模式）
        TaskAccepted: 任务已接受（异步模式，返回 202）
        
    Raises:
        HTTPException: 400 - 请求参数错误
        HTTPException: 409 - 股票正在分析中
        HTTPException: 500 - 分析失败
    """
    # 校验请求参数
    stock_codes = []
    if request.stock_code:
        stock_codes.append(request.stock_code)
    if request.stock_codes:
        stock_codes.extend(request.stock_codes)

    if not stock_codes:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "validation_error",
                "message": "必须提供 stock_code 或 stock_codes 参数"
            }
        )

    # 去重
    stock_codes = list(dict.fromkeys(stock_codes))
    stock_code = stock_codes[0]  # 当前只处理第一个

    # 异步模式：使用任务队列
    if request.async_mode:
        return _handle_async_analysis(stock_code, request)

    # 同步模式：直接执行分析
    return _handle_sync_analysis(stock_code, request)


def _handle_async_analysis(
    stock_code: str,
    request: AnalyzeRequest
) -> JSONResponse:
    """
    处理异步分析请求
    
    提交任务到队列，立即返回 202
    如果股票正在分析中，返回 409
    """
    task_queue = get_task_queue()
    
    try:
        # 提交任务（如果重复会抛出 DuplicateTaskError）
        position_info = request.position_info.model_dump() if request.position_info else None
        if position_info is None:
            try:
                from src.services.portfolio_service import get_position_info_for_analysis
                position_info = get_position_info_for_analysis(stock_code)
            except Exception:
                pass
        task_info = task_queue.submit_task(
            stock_code=stock_code,
            stock_name=None,  # 名称在分析过程中获取
            report_type=request.report_type,
            force_refresh=request.force_refresh,
            position_info=position_info,
            ab_variant=request.ab_variant,
        )
        
        # 返回 202 Accepted
        task_accepted = TaskAccepted(
            task_id=task_info.task_id,
            status="pending",
            message=f"分析任务已加入队列: {stock_code}"
        )
        return JSONResponse(
            status_code=202,
            content=task_accepted.model_dump()
        )
        
    except DuplicateTaskError as e:
        # 股票正在分析中，返回 409 Conflict
        error_response = DuplicateTaskErrorResponse(
            error="duplicate_task",
            message=str(e),
            stock_code=e.stock_code,
            existing_task_id=e.existing_task_id,
        )
        return JSONResponse(
            status_code=409,
            content=error_response.model_dump()
        )


def _handle_sync_analysis(
    stock_code: str,
    request: AnalyzeRequest
) -> AnalysisResultResponse:
    """
    处理同步分析请求
    
    直接执行分析，等待完成后返回结果
    """
    import uuid
    from src.services.analysis_service import AnalysisService
    
    query_id = uuid.uuid4().hex
    
    try:
        service = AnalysisService()
        position_info = request.position_info.model_dump() if request.position_info else None
        if position_info is None:
            try:
                from src.services.portfolio_service import get_position_info_for_analysis
                position_info = get_position_info_for_analysis(stock_code)
            except Exception:
                pass
        result = service.analyze_stock(
            stock_code=stock_code,
            report_type=request.report_type,
            force_refresh=request.force_refresh,
            query_id=query_id,
            send_notification=False,
            position_info=position_info,
            ab_variant=request.ab_variant,
        )

        if result is None:
            raise HTTPException(
                status_code=500,
                detail={
                    "error": "analysis_failed",
                    "message": f"分析股票 {stock_code} 失败"
                }
            )

        # 构建报告结构
        report_data = result.get("report", {})
        report = _build_analysis_report(
            report_data, query_id, stock_code, result.get("stock_name")
        )

        return AnalysisResultResponse(
            query_id=query_id,
            stock_code=result.get("stock_code", stock_code),
            stock_name=result.get("stock_name"),
            report=report.model_dump() if report else None,
            created_at=datetime.now().isoformat()
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"分析失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "error": "internal_error",
                "message": f"分析过程发生错误: {str(e)}"
            }
        )


# ============================================================
# GET /tasks - 获取任务列表
# ============================================================

@router.get(
    "/tasks",
    response_model=TaskListResponse,
    responses={
        200: {"description": "任务列表"},
    },
    summary="获取分析任务列表",
    description="获取当前所有分析任务，可按状态筛选"
)
def get_task_list(
    status: Optional[str] = Query(
        None,
        description="筛选状态：pending, processing, completed, failed（支持逗号分隔多个）"
    ),
    limit: int = Query(20, description="返回数量限制", ge=1, le=100),
) -> TaskListResponse:
    """
    获取分析任务列表
    
    Args:
        status: 状态筛选（可选）
        limit: 返回数量限制
        
    Returns:
        TaskListResponse: 任务列表响应
    """
    task_queue = get_task_queue()
    
    # 获取所有任务
    all_tasks = task_queue.list_all_tasks(limit=limit)
    
    # 状态筛选
    if status:
        status_list = [s.strip().lower() for s in status.split(",")]
        all_tasks = [t for t in all_tasks if t.status.value in status_list]
    
    # 统计信息
    stats = task_queue.get_task_stats()
    
    # 转换为 Schema
    task_infos = [
        TaskInfo(
            task_id=t.task_id,
            stock_code=t.stock_code,
            stock_name=t.stock_name,
            status=t.status.value,
            progress=t.progress,
            message=t.message,
            report_type=t.report_type,
            created_at=t.created_at.isoformat(),
            started_at=t.started_at.isoformat() if t.started_at else None,
            completed_at=t.completed_at.isoformat() if t.completed_at else None,
            error=t.error,
        )
        for t in all_tasks
    ]
    
    return TaskListResponse(
        total=stats["total"],
        pending=stats["pending"],
        processing=stats["processing"],
        tasks=task_infos,
    )


# ============================================================
# GET /tasks/stream - SSE 实时推送
# ============================================================

@router.get(
    "/tasks/stream",
    responses={
        200: {"description": "SSE 事件流", "content": {"text/event-stream": {}}},
    },
    summary="任务状态 SSE 流",
    description="通过 Server-Sent Events 实时推送任务状态变化"
)
async def task_stream():
    """
    SSE 任务状态流
    
    事件类型：
    - connected: 连接成功
    - task_created: 新任务创建
    - task_started: 任务开始执行
    - task_completed: 任务完成
    - task_failed: 任务失败
    - heartbeat: 心跳（每 30 秒）
    
    Returns:
        StreamingResponse: SSE 事件流
    """
    async def event_generator():
        task_queue = get_task_queue()
        event_queue: asyncio.Queue = asyncio.Queue()
        
        # 发送连接成功事件
        yield _format_sse_event("connected", {"message": "Connected to task stream"})
        
        # 发送当前进行中的任务
        pending_tasks = task_queue.list_pending_tasks()
        for task in pending_tasks:
            yield _format_sse_event("task_created", task.to_dict())
        
        # 订阅任务事件
        task_queue.subscribe(event_queue)
        
        try:
            while True:
                try:
                    # 等待事件，超时发送心跳
                    event = await asyncio.wait_for(event_queue.get(), timeout=30)
                    yield _format_sse_event(event["type"], event["data"])
                except asyncio.TimeoutError:
                    # 心跳
                    yield _format_sse_event("heartbeat", {
                        "timestamp": datetime.now().isoformat()
                    })
        except asyncio.CancelledError:
            # 客户端断开连接
            pass
        finally:
            task_queue.unsubscribe(event_queue)
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # 禁用 Nginx 缓冲
        }
    )


def _format_sse_event(event_type: str, data: Dict[str, Any]) -> str:
    """
    格式化 SSE 事件
    
    Args:
        event_type: 事件类型
        data: 事件数据
        
    Returns:
        SSE 格式字符串
    """
    return f"event: {event_type}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


# ============================================================
# GET /status/{task_id} - 查询单个任务状态
# ============================================================

@router.get(
    "/status/{task_id}",
    response_model=TaskStatus,
    responses={
        200: {"description": "任务状态"},
        404: {"description": "任务不存在", "model": ErrorResponse},
    },
    summary="查询分析任务状态",
    description="根据 task_id 查询单个任务的状态"
)
def get_analysis_status(task_id: str) -> TaskStatus:
    """
    查询分析任务状态
    
    优先从任务队列查询，如果不存在则从数据库查询历史记录
    
    Args:
        task_id: 任务 ID
        
    Returns:
        TaskStatus: 任务状态信息
        
    Raises:
        HTTPException: 404 - 任务不存在
    """
    # 1. 先从任务队列查询
    task_queue = get_task_queue()
    task = task_queue.get_task(task_id)
    
    if task:
        return TaskStatus(
            task_id=task.task_id,
            status=task.status.value,
            progress=task.progress,
            result=None,  # 进行中的任务没有结果
            error=task.error,
        )
    
    # 2. 从数据库查询已完成的记录
    try:
        from src.storage import DatabaseManager
        db = DatabaseManager.get_instance()
        records = db.get_analysis_history(query_id=task_id, limit=1)

        if records:
            record = records[0]
            return TaskStatus(
                task_id=task_id,
                status="completed",
                progress=100,
                result=AnalysisResultResponse(
                    query_id=task_id,
                    stock_code=record.code,
                    stock_name=record.name,
                    report=None,
                    created_at=record.created_at.isoformat() if record.created_at else datetime.now().isoformat()
                ),
                error=None
            )

    except Exception as e:
        logger.error(f"查询任务状态失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "error": "internal_error",
                "message": f"查询任务状态失败: {str(e)}"
            }
        )

    # 3. 任务不存在
    raise HTTPException(
        status_code=404,
        detail={
            "error": "not_found",
            "message": f"任务 {task_id} 不存在或已过期"
        }
    )


# ============================================================
# 辅助函数
# ============================================================

def _build_entry_conditions(
    strategy_data: Dict[str, Any],
    quant_extras: Dict[str, Any],
    current_price: Optional[float],
) -> Optional[Dict[str, Any]]:
    """从现有分析数据组装建仓条件

    Args:
        strategy_data: 策略数据（含 ideal_buy / secondary_buy / holding_strategy）
        quant_extras: 量化附加指标（volume_trend_3d 等）
        current_price: 当前股价

    Returns:
        建仓条件字典，或 None（数据不足时）
    """
    hs = strategy_data.get("holding_strategy") or {}

    ideal_buy_str = strategy_data.get("ideal_buy")
    secondary_buy_str = strategy_data.get("secondary_buy")

    price_low: Optional[float] = None
    price_high: Optional[float] = None

    for price_str in [secondary_buy_str, ideal_buy_str]:
        if price_str:
            try:
                val = float(''.join(c for c in str(price_str) if c.isdigit() or c == '.'))
                if price_low is None:
                    price_low = val
                else:
                    price_high = val
            except (ValueError, TypeError):
                pass

    if price_low and price_high and price_low > price_high:
        price_low, price_high = price_high, price_low

    current_vs: Optional[str] = None
    if price_high and current_price:
        if current_price > price_high:
            pct_above = (current_price - price_high) / price_high * 100
            current_vs = f"当前价高于入场区间{pct_above:.1f}%，耐心等回调"
        elif price_low and current_price < price_low:
            pct_below = (price_low - current_price) / price_low * 100
            current_vs = f"当前价低于入场区间{pct_below:.1f}%，关注是否企稳"
        else:
            current_vs = "当前价在入场区间内，可关注入场时机"

    conditions = []

    if price_low and current_price:
        threshold = price_high if price_high else price_low
        conditions.append({
            "label": "价格回调至支撑区间",
            "met": current_price <= threshold,
        })

    vol_trend = quant_extras.get("volume_trend_3d", "")
    conditions.append({
        "label": "缩量企稳确认",
        "met": "缩" in str(vol_trend),
    })

    conditions.append({
        "label": "所属概念热度上升",
        "met": False,
    })

    pos_pct = hs.get("entry_position_pct") or 20

    price_desc: Optional[str] = None
    if price_low and price_high:
        price_desc = f"{price_low:.2f} - {price_high:.2f} 元"
    elif price_low:
        price_desc = f"{price_low:.2f} 元附近"

    return {
        "price_range_low": price_low,
        "price_range_high": price_high,
        "price_range_desc": price_desc,
        "current_vs_entry": current_vs,
        "conditions": conditions,
        "suggested_position_pct": pos_pct,
        "summary": hs.get("entry_advice") or "等待价格回调至理想区间后择机入场",
    }


def _build_analysis_report(
        report_data: Dict[str, Any],
        query_id: str,
        stock_code: str,
        stock_name: Optional[str] = None
) -> AnalysisReport:
    """
    构建符合 API 规范的分析报告
    
    Args:
        report_data: 原始报告数据
        query_id: 查询 ID
        stock_code: 股票代码
        stock_name: 股票名称
        
    Returns:
        AnalysisReport: 结构化的分析报告
    """
    meta_data = report_data.get("meta", {})
    summary_data = report_data.get("summary", {})
    strategy_data = report_data.get("strategy", {})
    details_data = report_data.get("details", {})

    meta = ReportMeta(
        query_id=meta_data.get("query_id", query_id),
        stock_code=meta_data.get("stock_code", stock_code),
        stock_name=meta_data.get("stock_name", stock_name),
        report_type=meta_data.get("report_type", "detailed"),
        created_at=meta_data.get("created_at", datetime.now().isoformat()),
        current_price=meta_data.get("current_price"),
        change_pct=meta_data.get("change_pct"),
    )

    # 量化 vs AI 对比
    qva_data = summary_data.get("quant_vs_ai")
    quant_vs_ai = QuantVsAi(**qva_data) if qva_data and isinstance(qva_data, dict) else None

    summary = ReportSummary(
        analysis_summary=summary_data.get("analysis_summary"),
        operation_advice=summary_data.get("operation_advice"),
        trend_prediction=summary_data.get("trend_prediction"),
        sentiment_score=summary_data.get("sentiment_score"),
        sentiment_label=summary_data.get("sentiment_label"),
        quant_vs_ai=quant_vs_ai,
    )

    strategy = None
    if strategy_data:
        hs_data = strategy_data.get("holding_strategy")
        holding_strategy = None
        if hs_data and isinstance(hs_data, dict):
            holding_strategy = HoldingStrategy(**hs_data)
        # 盘中关键价位
        kpl_raw = strategy_data.get("key_price_levels", [])
        key_price_levels = None
        if kpl_raw and isinstance(kpl_raw, list):
            key_price_levels = [KeyPriceLevel(**item) for item in kpl_raw if isinstance(item, dict)]
        strategy = ReportStrategy(
            ideal_buy=strategy_data.get("ideal_buy"),
            secondary_buy=strategy_data.get("secondary_buy"),
            stop_loss=strategy_data.get("stop_loss"),
            stop_loss_intraday=strategy_data.get("stop_loss_intraday"),
            stop_loss_mid=strategy_data.get("stop_loss_mid"),
            take_profit=strategy_data.get("take_profit"),
            take_profit_mid=strategy_data.get("take_profit_mid"),
            risk_reward_ratio=strategy_data.get("risk_reward_ratio"),
            take_profit_plan=strategy_data.get("take_profit_plan"),
            key_price_levels=key_price_levels,
            holding_strategy=holding_strategy,
        )

    details = None
    if details_data:
        details = ReportDetails(
            news_content=details_data.get("news_summary") or details_data.get("news_content"),
            raw_result=details_data,
            context_snapshot=None
        )

    # 当日行情快照
    ts_data = report_data.get("today_snapshot")
    today_snapshot = TodaySnapshot(**ts_data) if ts_data and isinstance(ts_data, dict) else None

    # 建仓条件
    entry_conditions = None
    if strategy_data:
        try:
            raw_result = details_data.get("raw_result") if isinstance(details_data, dict) else details_data
            if isinstance(raw_result, dict):
                dashboard = raw_result.get("dashboard", {})
            else:
                dashboard = {}
            quant_extras = dashboard.get("quant_extras", {}) if isinstance(dashboard, dict) else {}
            cur_price = meta_data.get("current_price")
            ec_data = _build_entry_conditions(strategy_data, quant_extras, cur_price)
            if ec_data:
                entry_conditions = EntryConditions(**ec_data)
        except Exception as e:
            logger.debug(f"构建建仓条件失败: {e}")

    return AnalysisReport(
        meta=meta,
        summary=summary,
        strategy=strategy,
        today_snapshot=today_snapshot,
        details=details,
        entry_conditions=entry_conditions,
    )


@router.get("/ab_compare")
async def ab_compare(
    code: Optional[str] = Query(None, description="按股票代码筛选（可选）"),
    days: int = Query(90, description="回看天数"),
    min_samples: int = Query(30, description="统计显著性最低样本数（低于此返回insufficient_data=true）"),
):
    """
    A/B 实验对比：量化+LLM(standard) vs 纯LLM(llm_only) 的胜率/收益率 + LLM增量价值评估。

    收口逻辑（min_samples=30守卡）：
    - 每个变体样本 ≥ 30 才给出 llm_incremental_value 判断
    - 低于 30 时返回 insufficient_data=true，不给出结论
    """
    from src.storage import DatabaseManager
    from sqlalchemy import text as _text

    db = DatabaseManager.get_instance()
    with db.get_session() as session:
        _days = int(days)
        _code_filter = f" AND code = '{code}'" if code else ""

        # 1. 回测数据（已回填5日涨跌）——按变体和买入方向分组
        backtest_rows = session.execute(_text(f"""
            SELECT
                ab_variant,
                operation_advice,
                COUNT(*) as n,
                ROUND(AVG(actual_pct_5d), 3) as avg_5d,
                ROUND(100.0 * SUM(CASE WHEN actual_pct_5d > 0 THEN 1 ELSE 0 END) / COUNT(*), 1) as win_rate_positive,
                ROUND(100.0 * SUM(CASE WHEN actual_pct_5d > 1 THEN 1 ELSE 0 END) / COUNT(*), 1) as win_rate_1pct,
                ROUND(100.0 * SUM(CASE WHEN actual_pct_5d <= -3 THEN 1 ELSE 0 END) / COUNT(*), 1) as big_loss_rate,
                ROUND(AVG(sentiment_score), 1) as avg_score
            FROM analysis_history
            WHERE backtest_filled=1 AND actual_pct_5d IS NOT NULL
              AND ab_variant IS NOT NULL
              AND created_at >= datetime('now', '-{_days} days')
              {_code_filter}
            GROUP BY ab_variant, operation_advice
            ORDER BY ab_variant, n DESC
        """)).fetchall()

        # 2. 总样本数（含未回填）
        total_rows = session.execute(_text(f"""
            SELECT ab_variant, COUNT(*) as n
            FROM analysis_history
            WHERE ab_variant IS NOT NULL
              AND created_at >= datetime('now', '-{_days} days')
              {_code_filter}
            GROUP BY ab_variant
        """)).fetchall()

        # 3. 评分与实际收益相关性（IC分析）
        ic_rows = session.execute(_text(f"""
            SELECT
                ab_variant,
                ROUND(
                    (COUNT(*) * SUM(sentiment_score * actual_pct_5d) - SUM(sentiment_score) * SUM(actual_pct_5d)) /
                    (SQRT((COUNT(*) * SUM(sentiment_score * sentiment_score) - SUM(sentiment_score) * SUM(sentiment_score)) *
                          (COUNT(*) * SUM(actual_pct_5d * actual_pct_5d) - SUM(actual_pct_5d) * SUM(actual_pct_5d))) + 1e-9),
                    4
                ) as ic,
                COUNT(*) as n
            FROM analysis_history
            WHERE backtest_filled=1 AND actual_pct_5d IS NOT NULL
              AND sentiment_score IS NOT NULL
              AND ab_variant IS NOT NULL
              AND created_at >= datetime('now', '-{_days} days')
              {_code_filter}
            GROUP BY ab_variant
        """)).fetchall()

    # 聚合回测数据（按变体汇总 bullish 建议子集）
    _BULLISH_ADVICES = ("买入", "加仓", "逢低")
    variant_stats: dict = {}
    for row in backtest_rows:
        variant, advice, n, avg5d, wr_pos, wr_1, big_loss, avg_sc = row
        if variant not in variant_stats:
            variant_stats[variant] = {"total_bt": 0, "bullish": {}, "all": {}}
        variant_stats[variant]["all"].setdefault("n", 0)
        variant_stats[variant]["all"]["n"] += n
        # 聚合看多信号
        is_bullish = any(k in (advice or "") for k in _BULLISH_ADVICES)
        if is_bullish:
            vs = variant_stats[variant]["bullish"]
            vs["n"] = vs.get("n", 0) + n
            vs["avg_5d_sum"] = vs.get("avg_5d_sum", 0) + (avg5d or 0) * n
            vs["win_sum"] = vs.get("win_sum", 0) + (wr_1 or 0) * n / 100
            vs["big_loss_sum"] = vs.get("big_loss_sum", 0) + (big_loss or 0) * n / 100

    total_data = {r[0]: r[1] for r in total_rows}
    ic_data = {r[0]: {"ic": r[1], "n": r[2]} for r in ic_rows}

    # 整理各变体摘要
    variant_summary: dict = {}
    for variant, vs in variant_stats.items():
        bull = vs["bullish"]
        bull_n = bull.get("n", 0)
        variant_summary[variant] = {
            "total_analyses": total_data.get(variant, 0),
            "backtest_n": vs["all"].get("n", 0),
            "bullish_n": bull_n,
            "insufficient_data": bull_n < min_samples,
            "bullish_avg_5d": round(bull["avg_5d_sum"] / bull_n, 3) if bull_n > 0 else None,
            "bullish_win_rate_1pct": round(bull["win_sum"] / bull_n * 100, 1) if bull_n > 0 else None,
            "bullish_big_loss_rate": round(bull["big_loss_sum"] / bull_n * 100, 1) if bull_n > 0 else None,
            "ic": ic_data.get(variant, {}).get("ic"),
        }

    # LLM 增量价值判断
    std = variant_summary.get("standard", {})
    llm = variant_summary.get("llm_only", {})
    insufficient = std.get("insufficient_data", True) or llm.get("insufficient_data", True)

    llm_incremental: dict = {"insufficient_data": insufficient}
    if not insufficient:
        delta_return = round((std.get("bullish_avg_5d") or 0) - (llm.get("bullish_avg_5d") or 0), 3)
        delta_wr = round((std.get("bullish_win_rate_1pct") or 0) - (llm.get("bullish_win_rate_1pct") or 0), 1)
        delta_ic = round((std.get("ic") or 0) - (llm.get("ic") or 0), 4)
        llm_adds_value = delta_return > 0 and delta_wr > 0
        llm_incremental = {
            "insufficient_data": False,
            "delta_bullish_avg_5d": delta_return,
            "delta_win_rate_1pct": delta_wr,
            "delta_ic": delta_ic,
            "verdict": "✅ 量化+LLM框架优于纯LLM" if llm_adds_value else "❌ 纯LLM表现不弱于量化+LLM，建议扩大样本再评估",
            "recommendation": (
                "维持standard框架，量化信号有正贡献" if llm_adds_value
                else "考虑扩大llm_only实验比例至50%，继续收集数据"
            ),
            "min_samples_met": min_samples,
        }

    return {
        "days": days,
        "min_samples": min_samples,
        "code_filter": code,
        "variant_summary": variant_summary,
        "llm_incremental_value": llm_incremental,
        "raw_by_advice": [
            {"variant": r[0], "advice": r[1], "n": r[2], "avg_5d": r[3],
             "win_rate_positive": r[4], "win_rate_1pct": r[5], "big_loss_rate": r[6]}
            for r in backtest_rows
        ],
        "note": (
            "standard=量化+LLM；llm_only=纯LLM无量化数据。"
            f"llm_incremental_value需每变体≥{min_samples}条回填样本才给结论。"
            "backtest需5个交易日后自动回填。"
        ),
    }


@router.get("/ic_analysis")
async def ic_analysis(
    days: int = Query(180, description="回看天数"),
    variant: str = Query("standard", description="A/B变体：standard 或 llm_only"),
    window_days: int = Query(14, description="滚动IC窗口（天），默认14天双周"),
):
    """
    IC稳定性分析：滚动窗口IC时间序列 + ICIR + IC t-stat + IC衰减分析。

    ICIR = IC.mean() / IC.std()
    IC t-stat = IC.mean() / (IC.std() / sqrt(n_periods))  —— 判断IC是否显著异于0
    IC衰减：1d/3d/5d/10d持有期分别计算IC，分析信号半衰期
    """
    import math
    from src.storage import DatabaseManager
    from sqlalchemy import text as _text

    db = DatabaseManager.get_instance()
    with db.get_session() as session:
        _days = int(days)
        _variant = variant.replace("'", "")

        # 取所有回填完整的样本（含多周期 + alpha）
        rows = session.execute(_text(f"""
            SELECT
                date(created_at) as trade_date,
                strftime('%Y-W%W', created_at) as week_label,
                sentiment_score,
                actual_pct_5d,
                actual_pct_1d,
                actual_pct_3d,
                actual_pct_10d,
                actual_pct_20d,
                alpha_5d,
                alpha_10d
            FROM analysis_history
            WHERE backtest_filled=1
              AND actual_pct_5d IS NOT NULL
              AND sentiment_score IS NOT NULL
              AND ab_variant = '{_variant}'
              AND created_at >= datetime('now', '-{_days} days')
            ORDER BY created_at ASC
        """)).fetchall()

    if not rows:
        return {
            "variant": variant, "days": days, "n_total": 0,
            "error": "无回填样本，请等待5个交易日后数据自动回填",
        }

    # 辅助：计算两个序列的Pearson相关
    def pearson_ic(xs, ys):
        n = len(xs)
        if n < 5:
            return None
        mx = sum(xs) / n
        my = sum(ys) / n
        num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
        denom = (
            math.sqrt(sum((x - mx) ** 2 for x in xs)) *
            math.sqrt(sum((y - my) ** 2 for y in ys))
        )
        return round(num / denom, 4) if denom > 1e-9 else None

    # 1. 全样本 IC（各持有期 + alpha）
    # col_idx: 3=5d, 4=1d, 5=3d, 6=10d, 7=20d, 8=alpha_5d, 9=alpha_10d
    decay_ic = {}
    for hold_label, col_idx in [("1d", 4), ("3d", 5), ("5d", 3), ("10d", 6), ("20d", 7)]:
        valid_pairs = [(float(r[2]), float(r[col_idx])) for r in rows if r[col_idx] is not None]
        if valid_pairs:
            sc = [p[0] for p in valid_pairs]
            rt = [p[1] for p in valid_pairs]
            decay_ic[hold_label] = {"ic": pearson_ic(sc, rt), "n": len(valid_pairs)}
        else:
            decay_ic[hold_label] = {"ic": None, "n": 0, "note": "待回填或数据不足"}

    # IC vs alpha（超额收益）对比
    alpha_ic = {}
    for alpha_label, col_idx in [("alpha_5d", 8), ("alpha_10d", 9)]:
        valid_pairs = [(float(r[2]), float(r[col_idx])) for r in rows if r[col_idx] is not None]
        if valid_pairs:
            sc = [p[0] for p in valid_pairs]
            rt = [p[1] for p in valid_pairs]
            avg_alpha = round(sum(rt) / len(rt), 3)
            alpha_ic[alpha_label] = {
                "ic": pearson_ic(sc, rt),
                "n": len(valid_pairs),
                "avg_alpha": avg_alpha,
                "avg_alpha_note": (
                    "✅ 策略持续超越基准" if avg_alpha > 0
                    else "⚠️ 策略尚未超越基准，建议检查选股逻辑"
                )
            }
        else:
            alpha_ic[alpha_label] = {"ic": None, "n": 0, "note": "待回填"}

    # 2. 滚动窗口 IC 时间序列（按 window_days 天分组）
    from collections import defaultdict
    week_buckets: dict = defaultdict(lambda: {"scores": [], "ret5d": []})
    for r in rows:
        wk = r[1]  # week_label
        if r[2] is not None and r[3] is not None:
            week_buckets[wk]["scores"].append(float(r[2]))
            week_buckets[wk]["ret5d"].append(float(r[3]))

    rolling_ic_series = []
    for wk in sorted(week_buckets.keys()):
        sc = week_buckets[wk]["scores"]
        rt = week_buckets[wk]["ret5d"]
        ic_val = pearson_ic(sc, rt)
        rolling_ic_series.append({"week": wk, "ic": ic_val, "n": len(sc)})

    # 3. ICIR + t-stat（仅使用样本≥5的周）
    valid_ics = [p["ic"] for p in rolling_ic_series if p["ic"] is not None and p["n"] >= 5]
    icir = None
    ic_tstat = None
    ic_mean = None
    ic_std = None
    if len(valid_ics) >= 3:
        ic_mean = round(sum(valid_ics) / len(valid_ics), 4)
        var = sum((x - ic_mean) ** 2 for x in valid_ics) / (len(valid_ics) - 1)
        ic_std = round(math.sqrt(var), 4)
        if ic_std > 1e-9:
            icir = round(ic_mean / ic_std, 3)
            ic_tstat = round(ic_mean / (ic_std / math.sqrt(len(valid_ics))), 3)

    # ICIR 解读
    def icir_verdict(ir):
        if ir is None:
            return "样本期数不足（需≥3期），无法评估"
        if ir >= 1.5:
            return "✅ 极强稳定 (ICIR≥1.5)，信号质量机构级别"
        if ir >= 0.8:
            return "✅ 稳定可用 (ICIR 0.8-1.5)，符合量化策略上线标准"
        if ir >= 0.5:
            return "⚠️ 中等稳定 (ICIR 0.5-0.8)，可用但需持续监控IC衰减"
        if ir >= 0.3:
            return "⚠️ 弱稳定 (ICIR 0.3-0.5)，信号噪声较大，建议组合多因子"
        return "❌ 不稳定 (ICIR<0.3)，IC均值被高方差稀释，策略可靠性存疑"

    # 5. 当前 ICGuard 状态（近21日，与pipeline注入一致）
    from datetime import date as _date, timedelta as _td
    _cutoff_21d = (_date.today() - _td(days=21)).isoformat()
    with db.get_session() as _s21:
        _guard_rows = _s21.execute(_text(f"""
            SELECT MAX(sentiment_score) as score, actual_pct_5d
            FROM analysis_history
            WHERE backtest_filled=1
              AND actual_pct_5d IS NOT NULL
              AND sentiment_score IS NOT NULL
              AND ab_variant = '{_variant}'
              AND created_at >= '{_cutoff_21d}'
            GROUP BY code, DATE(created_at)
            ORDER BY DATE(created_at) ASC
        """)).fetchall()
    _MIN_IC_SAMPLES = 20
    current_ic_guard = None
    if len(_guard_rows) >= _MIN_IC_SAMPLES:
        _sc21 = [float(r[0]) for r in _guard_rows]
        _rt21 = [float(r[1]) for r in _guard_rows]
        _n21 = len(_guard_rows)
        _mx21 = sum(_sc21) / _n21
        _my21 = sum(_rt21) / _n21
        _num21 = sum((s - _mx21) * (r - _my21) for s, r in zip(_sc21, _rt21))
        _ds21 = math.sqrt(sum((s - _mx21) ** 2 for s in _sc21))
        _dr21 = math.sqrt(sum((r - _my21) ** 2 for r in _rt21))
        _denom21 = _ds21 * _dr21
        _ic21 = round(_num21 / _denom21, 4) if _denom21 > 1e-9 else 0.0
        _t21 = round(abs(_ic21) * math.sqrt(_n21), 3)
        _sig21 = _t21 >= 1.5  # ~90% 置信

        if not _sig21:
            _qlevel, _qdesc = "normal", f"✅ 信号IC={_ic21:.3f}(t={_t21:.2f})，统计上不显著，守卫不触发。"
        elif _ic21 >= 0.20:
            _qlevel, _qdesc = "strong", f"✅ 信号强(IC={_ic21:.3f}, t={_t21:.2f})，量化评分预测能力充足。"
        elif _ic21 >= 0.10:
            _qlevel, _qdesc = "moderate", f"⚠️ 信号中等(IC={_ic21:.3f}, t={_t21:.2f})，适当降仓。"
        elif _ic21 >= 0.0:
            _qlevel, _qdesc = "weak", f"⚠️ 信号较弱(IC={_ic21:.3f}, t={_t21:.2f})，控制在半仓以内。"
        else:
            _qlevel, _qdesc = "negative", (
                f"🔴 信号反转(IC={_ic21:.3f}, t={_t21:.2f})！评分预测能力弱，"
                "建议缩小仓位至1/3+收紧止损。"
            )
        current_ic_guard = {
            "ic": _ic21,
            "n": _n21,
            "t_stat": _t21,
            "statistically_significant": _sig21,
            "quality_level": _qlevel,
            "quality_desc": _qdesc,
            "guard_active": _sig21 and _qlevel in ("weak", "negative"),
            "guard_action": (
                "⛔ 仓位减半 + 止损收紧 (当前批次分析已触发ICGuard)" if (_sig21 and _qlevel == "negative")
                else "⚠️ 控制半仓以内" if (_sig21 and _qlevel == "weak")
                else None
            ),
        }

    return {
        "variant": variant,
        "days": days,
        "n_total": len(rows),
        "n_valid_periods": len(valid_ics),
        "overall": {
            "ic_mean": ic_mean,
            "ic_std": ic_std,
            "icir": icir,
            "ic_tstat": ic_tstat,
            "icir_verdict": icir_verdict(icir),
            "ic_tstat_significant": (abs(ic_tstat) > 1.96) if ic_tstat else None,
        },
        "ic_decay": decay_ic,
        "alpha_ic": alpha_ic,
        "current_ic_guard": current_ic_guard,
        "rolling_ic_series": rolling_ic_series,
        "note": (
            f"ICIR={icir}：IC.mean/IC.std，衡量信号跨时间稳定性。"
            "IC衰减分析显示信号在不同持有期的有效性。"
            f"t-stat>1.96表示IC均值在95%置信区间内显著非零。"
        ),
    }
