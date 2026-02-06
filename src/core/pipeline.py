# -*- coding: utf-8 -*-
import logging
import time
import random
import os
from typing import List, Dict, Optional, Any
from concurrent.futures import ThreadPoolExecutor, as_completed

# === 导入数据模块 (保持健壮性) ===
try:
    from data_provider import DataFetcherManager
except ImportError:
    try:
        from data_provider.base import DataFetcherManager
    except ImportError:
        # 尝试从 src 导入
        from src.data_provider.base import DataFetcherManager

# 尝试导入 F10 数据获取器
try:
    from data_provider.fundamental_fetcher import get_fundamental_data
except ImportError:
    def get_fundamental_data(code): return {}

# 尝试导入 大盘监控 (Market Monitor)
try:
    from data_provider.market_monitor import market_monitor
except ImportError:
    market_monitor = None

# === 内部模块导入 ===
from src.stock_analyzer import StockTrendAnalyzer
from src.analyzer import GeminiAnalyzer, AnalysisResult
from src.notification import NotificationService
from src.storage import DatabaseManager  
from src.search_service import SearchService
from src.enums import ReportType

logger = logging.getLogger(__name__)

class StockAnalysisPipeline:
    """
    股票分析流水线 (最终完整修复版)
    适配 main.py 的 config 传参调用方式，包含两阶段执行和防封号逻辑
    """
    def __init__(self, config, max_workers=3, query_id=None, query_source="cli", save_context_snapshot=True, source_message=None, **kwargs):
        """
        初始化 - 严格适配 main.py 的调用方式
        """
        self.config = config
        self.query_id = query_id
        self.query_source = query_source
        self.save_context_snapshot = save_context_snapshot
        self.source_message = source_message
        
        # === 1. 默认顺序执行（workers=1），避免多线程日志交错 ===
        if max_workers is None:
            max_workers = 1
            
        # === 2. 初始化各个服务组件 ===
        self.fetcher_manager = DataFetcherManager()
        self.trend_analyzer = StockTrendAnalyzer()
        
        # 初始化 LLM (直接从 config 读取 key)
        self.analyzer = GeminiAnalyzer(api_key=config.gemini_api_key)
        
        # 初始化 通知服务
        self.notifier = NotificationService(source_message=source_message)
        
        # 初始化 数据库
        self.storage = DatabaseManager() 
        
        # === 3. 初始化搜索服务 & 智能流控 ===
        self.search_service = None
        has_search_key = False
        
        # 检查是否配置了任何一种搜索 Key
        if (config.bocha_api_keys or config.tavily_api_keys or 
            config.serpapi_keys or os.getenv("PERPLEXITY_API_KEY")):
            
            self.search_service = SearchService(
                bocha_keys=config.bocha_api_keys,
                tavily_keys=config.tavily_api_keys,
                serpapi_keys=config.serpapi_keys
            )
            has_search_key = True

        # 如果启用了搜索，强制限制并发数，防止 429 错误
        if has_search_key:
            self.max_workers = min(max_workers, 2)
            logger.info(f"🕵️  [深度模式] 搜索服务已启用，并发限制为: {self.max_workers}")
        else:
            self.max_workers = max_workers
            logger.info(f"🚀 [极速模式] 纯本地分析，并发数: {self.max_workers}")

    def fetch_and_save_stock_data(self, code: str) -> (bool, str):
        """获取数据辅助函数"""
        try:
            # 120天数据用于计算趋势
            df = self.fetcher_manager.get_merged_data(code, days=120)
            if df is None or df.empty:
                return False, "获取数据为空"
            quote = self.fetcher_manager.get_realtime_quote(code)
            if not quote:
                return False, "实时行情获取失败"
            return True, "Success"
        except Exception as e:
            return False, str(e)

    def _prepare_stock_context(self, code: str) -> Optional[Dict[str, Any]]:
        """准备 AI 分析所需的上下文数据"""
        quote = self.fetcher_manager.get_realtime_quote(code)
        if not quote:
            logger.warning(f"[{code}] 无法获取实时行情，跳过")
            return None
        stock_name = quote.name
        
        try:
            daily_df = self.fetcher_manager.get_merged_data(code, days=120)
        except Exception as e:
            logger.warning(f"[{code}] 获取合并数据失败: {e}")
            daily_df = None

        tech_report = "数据不足，无法进行技术分析"
        if daily_df is not None and not daily_df.empty:
            try:
                trend_result = self.trend_analyzer.analyze(daily_df, code)
                if quote.price:
                    trend_result.current_price = quote.price
                tech_report = self.trend_analyzer.format_analysis(trend_result)
            except Exception as e:
                logger.error(f"[{code}] 技术分析生成失败: {e}")

        # 筹码数据
        chip_data = {}
        if getattr(self.config, 'enable_chip_distribution', False):
            if hasattr(self.fetcher_manager, '_chip_cache') and code in self.fetcher_manager._chip_cache:
                chip_data = self.fetcher_manager._chip_cache[code].to_dict()
        
        # F10 基本面数据
        fundamental_data = {}
        try:
            fundamental_data = get_fundamental_data(code)
        except Exception as e:
            pass

        # 历史记忆
        history_summary = None
        try:
            history_summary = self.storage.get_last_analysis_summary(code)
        except Exception as e:
            pass

        context = {
            'code': code,
            'stock_name': stock_name,
            'price': quote.price,
            'realtime': quote.to_dict(),
            'chip': chip_data,
            'technical_analysis_report': tech_report,
            'fundamental': fundamental_data,
            'history_summary': history_summary
        }
        return context

    def process_single_stock(self, code: str, skip_analysis: bool = False, single_stock_notify: bool = False, report_type: ReportType = ReportType.SIMPLE, skip_data_fetch: bool = False) -> Optional[AnalysisResult]:
        """处理单只股票的核心逻辑"""
        try:
            context = self._prepare_stock_context(code)
            if not context: return None
            stock_name = context['stock_name']
            
            if skip_analysis:
                logger.info(f"[{code}] Dry-run 模式，跳过 AI 分析")
                return AnalysisResult(code=code, name=stock_name, reasoning="Dry Run 测试", operation_advice="观望", sentiment_score=50, trend_prediction="测试", success=True)

            # === 1. 搜索舆情 (增加随机延迟防封号) ===
            search_content = ""
            if self.search_service:
                # 随机休眠 2.0 - 5.0 秒
                sleep_time = random.uniform(2.0, 5.0)
                time.sleep(sleep_time)
                
                logger.info(f"🔎 [{stock_name}] 正在侦查舆情 (延迟 {sleep_time:.1f}s)...")
                try:
                    # 兼容不同接口调用方式
                    if hasattr(self.search_service, 'search_stock_news'):
                        resp = self.search_service.search_stock_news(code, stock_name)
                    else:
                        query = f"{stock_name} ({code}) 近期重大利好利空消息 机构观点 研报"
                        resp = self.search_service.search(query)
                        
                    if resp and getattr(resp, 'success', False): 
                        search_content = resp.to_context()
                except Exception as e:
                    logger.warning(f"[{stock_name}] 搜索服务异常: {e}")

            # === 2. 获取大盘环境 ===
            market_overview = None
            if market_monitor:
                try:
                    snapshot = market_monitor.get_market_snapshot()
                    if snapshot.get('success'):
                        vol = snapshot.get('total_volume', 'N/A')
                        indices = snapshot.get('indices', [])
                        # 格式化: "上证指数 +1.2% / 深证成指 -0.5%"
                        idx_str = " / ".join([f"{i['name']} {i['change_pct']}%" for i in indices])
                        market_overview = f"今日两市成交额: {vol}亿。指数表现: {idx_str}。"
                except Exception as e:
                    logger.warning(f"[{stock_name}] 获取大盘数据微瑕: {e}")

            logger.info(f"🤖 [{stock_name}] 调用 LLM 进行分析...")
            
            # === 3. 执行分析 ===
            result = self.analyzer.analyze(
                context=context, 
                news_context=search_content, 
                role="trader",
                market_overview=market_overview 
            )
            
            if not result: return None
            logger.info(f"\n[分析完成] {stock_name}: 建议-{result.operation_advice}, 评分-{result.sentiment_score}")
            
            try:
                self.storage.save_analysis_history(result=result, query_id=self.query_id, report_type=report_type.value if hasattr(report_type, 'value') else str(report_type), news_content=search_content, context_snapshot=context if self.save_context_snapshot else None)
            except Exception as e:
                logger.error(f"保存分析历史失败: {e}")
            
            if single_stock_notify and self.notifier.is_available():
                try:
                    report = self.notifier.generate_single_stock_report(result)
                    self.notifier.send(report)
                except Exception as e:
                    logger.warning(f"[{code}] 推送失败: {e}")
            return result
        except Exception as e:
            logger.exception(f"[{code}] 处理过程中发生未知错误: {e}")
            return None

    def _send_notifications(self, results: List[AnalysisResult]):
        logger.info("正在生成汇总日报...")
        try:
            daily_report = self.notifier.generate_dashboard_report(results)
            self.notifier.send(daily_report)
            self.notifier.save_report_to_file(daily_report)
        except Exception as e:
            logger.error(f"汇总推送失败: {e}")

    def run(self, stock_codes: Optional[List[str]] = None, dry_run: bool = False, send_notification: bool = True) -> List[AnalysisResult]:
        """
        主执行入口 (由 main.py 调用)
        """
        start_time = time.time()
        if stock_codes is None:
            self.config.refresh_stock_list()
            stock_codes = self.config.stock_list
        if not stock_codes:
            logger.error("未配置自选股列表")
            return []
        
        total_stocks = len(stock_codes)
        logger.info(f"===== 启动分析任务: 共 {total_stocks} 只股票 =====")

        # === 阶段一：串行获取数据 ===
        logger.info("🐢 阶段一：串行获取数据 (防封控 & 预加载)...")
        valid_stocks = [] 
        
        for i, code in enumerate(stock_codes):
            try:
                success, msg = self.fetch_and_save_stock_data(code)
                
                # 尝试预取筹码数据（避开交易高峰）
                try:
                    import datetime
                    now = datetime.datetime.now()
                    # 简单判断非交易时间才大量预取
                    is_trading = ((now.hour == 9 and now.minute >= 15) or (9 < now.hour < 15))
                    if not is_trading:
                        if hasattr(self.fetcher_manager, 'get_chip_distribution'):
                            self.fetcher_manager.get_chip_distribution(code)
                except Exception:
                    pass 

                if success:
                    valid_stocks.append(code)
                    logger.info(f"[{i+1}/{total_stocks}] ✅ {code} 数据就绪")
                    # 串行阶段也稍微休息一下，防止数据源封IP
                    if not dry_run:
                        time.sleep(0.5)
                else:
                    logger.warning(f"[{i+1}/{total_stocks}] ❌ {code} 数据失败: {msg}")
                
            except Exception as e:
                logger.error(f"[{code}] 数据预取异常: {e}")

        # === 阶段二：并发分析 ===
        workers = self.max_workers if self.max_workers is not None else 1
        logger.info(f"🐰 阶段二：开启 {workers} 线程进行 AI 并发分析（多线程时日志会交错，若需顺序输出请使用 --workers 1）...")
        single_stock_notify = getattr(self.config, 'single_stock_notify', False)
        report_type = ReportType.FULL if getattr(self.config, 'report_type', 'simple') == 'full' else ReportType.SIMPLE
        results: List[AnalysisResult] = []
        
        if not valid_stocks:
            logger.error("没有获取到任何有效数据，终止分析")
            return []

        with ThreadPoolExecutor(max_workers=workers) as executor:
            future_to_code = {
                executor.submit(
                    self.process_single_stock, 
                    code, 
                    skip_analysis=dry_run, 
                    single_stock_notify=single_stock_notify and send_notification, 
                    report_type=report_type, 
                    skip_data_fetch=True
                ): code for code in valid_stocks
            }
            
            for future in as_completed(future_to_code):
                code = future_to_code[future]
                try:
                    res = future.result()
                    if res: results.append(res)
                except Exception as e:
                    logger.error(f"[{code}] AI 分析任务失败: {e}")
        
        logger.info(f"===== 分析完成，总耗时 {time.time() - start_time:.2f}s =====")
        
        # 汇总推送 (如果没开单股推送)
        if results and send_notification and not dry_run and not single_stock_notify:
            self._send_notifications(results)
            
        return results