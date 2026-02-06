# src/analyzer_service.py
# -*- coding: utf-8 -*-
"""
===================================
A股自选股智能分析系统 - 分析服务层 (并发增强版)
===================================

职责：
1. 封装核心分析逻辑，支持多调用方（CLI、WebUI、Bot）
2. 提供清晰的API接口，不依赖于命令行参数
3. 支持依赖注入，便于测试和扩展
4. 统一管理分析流程和配置
5. [新增] 多线程并发控制，最大化利用 API 额度
"""

import uuid
import time
import logging
from typing import List, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

from src.analyzer import AnalysisResult
from src.config import get_config, Config
from src.notification import NotificationService
from src.enums import ReportType
from src.core.pipeline import StockAnalysisPipeline
from src.core.market_review import run_market_review

logger = logging.getLogger(__name__)

def analyze_stock(
    stock_code: str,
    config: Config = None,
    full_report: bool = False,
    notifier: Optional[NotificationService] = None
) -> Optional[AnalysisResult]:
    """
    分析单只股票
    
    Args:
        stock_code: 股票代码
        config: 配置对象（可选，默认使用单例）
        full_report: 是否生成完整报告
        notifier: 通知服务（可选）
        
    Returns:
        分析结果对象
    """
    if config is None:
        config = get_config()
    
    # 创建分析流水线
    # 注意：每次调用都创建新实例，天然线程安全
    pipeline = StockAnalysisPipeline(
        config=config,
        query_id=uuid.uuid4().hex,
        query_source="cli"
    )
    
    # 使用通知服务（如果提供）
    if notifier:
        pipeline.notifier = notifier
    
    # 根据full_report参数设置报告类型
    report_type = ReportType.FULL if full_report else ReportType.SIMPLE
    
    try:
        # 运行单只股票分析
        result = pipeline.process_single_stock(
            code=stock_code,
            skip_analysis=False,
            single_stock_notify=notifier is not None,
            report_type=report_type
        )
        return result
    except Exception as e:
        logger.error(f"❌ 分析股票 {stock_code} 时发生未捕获异常: {e}")
        return None

def analyze_stocks(
    stock_codes: List[str],
    config: Config = None,
    full_report: bool = False,
    notifier: Optional[NotificationService] = None
) -> List[AnalysisResult]:
    """
    【并发优化版】分析多只股票
    
    Args:
        stock_codes: 股票代码列表
        config: 配置对象
        full_report: 是否生成完整报告
        notifier: 通知服务
        
    Returns:
        分析结果列表
    """
    if config is None:
        config = get_config()
    
    results = []
    total_stocks = len(stock_codes)
    
    # === 🚀 并发参数配置 ===
    # Google Gemini 免费版限制约 15 RPM (虽然写的是 RPM，但有时候是按每分钟请求数算的)
    # 设置 3 个线程并行，既能提速，又不容易被封。
    MAX_WORKERS = 3
    
    logger.info(f"⚡️ 启动并发分析模式，目标: {total_stocks} 只股票，并发线程数: {MAX_WORKERS}")
    
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_code = {}
        
        # 1. 提交任务
        for i, code in enumerate(stock_codes):
            # 提交任务到线程池
            future = executor.submit(analyze_stock, code, config, full_report, notifier)
            future_to_code[future] = code
            
            # === 🚦 关键限流 ===
            # 虽然开了多线程，但不能瞬间把请求全发出去，否则会触发 HTTP 429。
            # 间隔 1.5 秒提交一个，保证请求是均匀分布的。
            # 3个线程 * 1.5s间隔 = API请求非常平滑
            time.sleep(1.5)
            
            if (i + 1) % 5 == 0:
                logger.info(f"已提交 {i + 1}/{total_stocks} 个分析任务...")

        # 2. 获取结果 (按完成顺序)
        for future in as_completed(future_to_code):
            code = future_to_code[future]
            try:
                result = future.result()
                if result:
                    results.append(result)
                    logger.info(f"✅ [{len(results)}/{total_stocks}] 完成分析: {code} {result.name}")
                else:
                    logger.warning(f"⚠️ [{len(results)}/{total_stocks}] 分析返回空值: {code}")
            except Exception as exc:
                logger.error(f"❌ 股票 {code} 线程执行异常: {exc}")

    logger.info("🎉 所有并发任务执行完毕")
    return results

def perform_market_review(
    config: Config = None,
    notifier: Optional[NotificationService] = None
) -> Optional[str]:
    """
    执行大盘复盘
    """
    if config is None:
        config = get_config()
    
    pipeline = StockAnalysisPipeline(
        config=config,
        query_id=uuid.uuid4().hex,
        query_source="cli"
    )
    
    review_notifier = notifier or pipeline.notifier
    
    return run_market_review(
        notifier=review_notifier,
        analyzer=pipeline.analyzer,
        search_service=pipeline.search_service
    )
