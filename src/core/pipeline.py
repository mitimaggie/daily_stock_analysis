# -*- coding: utf-8 -*-
import logging
import time
import random
import os
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Any
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as FuturesTimeoutError

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

# 尝试导入 大盘监控 (Market Monitor) — 个股分析时作为「仓位上限/前置滤网」
def _load_market_monitor():
    try:
        from data_provider.market_monitor import market_monitor
        return market_monitor
    except ImportError:
        try:
            import sys
            from pathlib import Path
            root = Path(__file__).resolve().parents[2]
            if str(root) not in sys.path:
                sys.path.insert(0, str(root))
            from data_provider.market_monitor import market_monitor
            return market_monitor
        except ImportError:
            return None

market_monitor = _load_market_monitor()

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

        # 阶段一预取缓存：避免阶段二重复拉取/重复拼接
        # 结构：{ code: {"df": <DataFrame>, "quote": <RealtimeQuote>} }
        self._prefetch_cache: Dict[str, Dict[str, Any]] = {}
        
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

        # 大盘监控：用于个股分析时的「仓位上限/前置滤网」（大盘定仓位，个股定方向）
        self._market_monitor = market_monitor
        if self._market_monitor:
            logger.info("📊 [大盘监控] 已启用，个股分析将注入大盘环境作为前置滤网")
        else:
            logger.warning("📊 [大盘监控] 未加载，个股分析将不注入大盘环境（请检查 data_provider.market_monitor 与 akshare）")

    def fetch_and_save_stock_data(self, code: str) -> (bool, str, Any, Any):
        """获取数据并落库，保证下次可做「历史+实时」拼接。

        返回: (success, msg, df, quote)
        """
        try:
            # 120天数据用于计算趋势（有历史则 DB+实时缝合，无历史则全量抓取）
            df = self.fetcher_manager.get_merged_data(code, days=120)
            if df is None or df.empty:
                return False, "获取数据为空", None, None
            # 写入/更新日线到 DB，后续 run 才能用历史做缝合，技术面才和现实一致
            try:
                n = self.storage.save_daily_data(df, code, data_source="pipeline")
                if n > 0:
                    logger.debug(f"[{code}] 日线落库新增 {n} 条")
            except Exception as e:
                logger.warning(f"[{code}] 日线落库失败(继续分析): {e}")
            quote = self.fetcher_manager.get_realtime_quote(code)
            if not quote:
                return False, "实时行情获取失败", df, None
            return True, "Success", df, quote
        except Exception as e:
            return False, str(e), None, None

    def _get_cached_news_context(self, code: str, stock_name: str, hours: int = 6, limit: int = 5) -> str:
        """优先复用 news_intel 缓存，命中则减少外部搜索与 token。"""
        try:
            items = self.storage.get_recent_news(code, days=1, limit=limit)
            if not items:
                return ""
            cutoff = datetime.now() - timedelta(hours=hours)
            fresh = [n for n in items if getattr(n, "fetched_at", None) and n.fetched_at >= cutoff]
            if not fresh:
                return ""
            lines = []
            for i, n in enumerate(fresh[:limit]):
                title = (getattr(n, "title", "") or "").strip()
                snippet = (getattr(n, "snippet", "") or "").strip()
                source = (getattr(n, "source", "") or "").strip()
                pub = getattr(n, "published_date", None)
                pub_str = f" ({pub})" if pub else ""
                head = f"{i+1}. 【{source}】{title}{pub_str}".strip()
                body = snippet
                lines.append(f"{head}\n{body}".strip())
            return "\n".join(lines) if lines else ""
        except Exception:
            return ""

    def _prepare_stock_context(self, code: str) -> Optional[Dict[str, Any]]:
        """准备 AI 分析所需的上下文数据"""
        prefetched = self._prefetch_cache.get(code) if hasattr(self, "_prefetch_cache") else None
        quote = (prefetched or {}).get("quote") or self.fetcher_manager.get_realtime_quote(code)
        if not quote:
            logger.warning(f"[{code}] 无法获取实时行情，跳过")
            return None
        stock_name = quote.name
        
        try:
            cache_df = (prefetched or {}).get("df")
            if cache_df is not None:
                daily_df = cache_df
            else:
                daily_df = self.fetcher_manager.get_merged_data(code, days=120)
                # 单股/API 路径无 prefetch，拿到数据后落库，下次同一只股可直接用 DB 缓存
                if daily_df is not None and not daily_df.empty:
                    try:
                        self.storage.save_daily_data(daily_df, code, data_source="pipeline")
                    except Exception as e:
                        logger.debug(f"[{code}] 日线落库失败(继续分析): {e}")
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

        # 筹码数据（先查 DB/内存缓存；失败时明确标记「暂不可用」避免模型瞎编）
        chip_data = {}
        chip_note = "未启用"
        if getattr(self.config, 'enable_chip_distribution', False) or getattr(self.config, 'chip_fetch_only_from_cache', False):
            chip = self.fetcher_manager.get_chip_distribution(code) if hasattr(self.fetcher_manager, 'get_chip_distribution') else None
            if chip:
                chip_data = chip.to_dict()
                chip_note = "见下数据"
            else:
                chip_note = "暂不可用（接口失败或未拉取）"
        
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

        # 当日/昨日 K 线（供推送中的「当日行情」快照用）
        today_row = {}
        yesterday_row = {}
        context_date = ''
        if daily_df is not None and not daily_df.empty and len(daily_df) >= 1:
            try:
                keys = ['open', 'high', 'low', 'close', 'volume', 'amount', 'pct_chg', 'date']
                last = daily_df.iloc[-1]
                today_row = {k: last[k] for k in keys if k in last.index}
                context_date = str(today_row.get('date', ''))
                if len(daily_df) >= 2:
                    prev = daily_df.iloc[-2]
                    yesterday_row = {k: prev[k] for k in keys if k in prev.index}
            except Exception:
                pass

        context = {
            'code': code,
            'stock_name': stock_name,
            'date': context_date,
            'today': today_row,
            'yesterday': yesterday_row,
            'price': quote.price,
            'realtime': quote.to_dict(),
            'chip': chip_data,
            'chip_note': chip_note,
            'technical_analysis_report': tech_report,
            'fundamental': fundamental_data,
            'history_summary': history_summary
        }
        return context

    def _log(self, msg: str, *args, **kwargs) -> None:
        """带 query_id 的日志前缀，便于链路追踪"""
        prefix = f"[query_id={self.query_id}] " if self.query_id else ""
        logger.info(prefix + msg, *args, **kwargs)

    def process_single_stock(
        self,
        code: str,
        skip_analysis: bool = False,
        single_stock_notify: bool = False,
        report_type: ReportType = ReportType.SIMPLE,
        skip_data_fetch: bool = False,
        market_overview_override: Optional[str] = None,
    ) -> Optional[AnalysisResult]:
        """处理单只股票的核心逻辑"""
        try:
            context = self._prepare_stock_context(code)
            if not context: return None
            stock_name = context['stock_name']
            self._log(f"[{code}] {stock_name} 开始分析")
            
            if skip_analysis:
                logger.info(f"[{code}] Dry-run 模式，跳过 AI 分析")
                return AnalysisResult(code=code, name=stock_name, reasoning="Dry Run 测试", operation_advice="观望", sentiment_score=50, trend_prediction="测试", success=True)

            # === 1. 搜索舆情 (增加随机延迟防封号) ===
            search_content = ""
            used_news_cache = False
            # 1) 优先复用 DB 缓存（命中则不外部搜索、不 sleep）
            cached = self._get_cached_news_context(code, stock_name)
            if cached:
                search_content = cached
                used_news_cache = True
                logger.info(f"♻️  [{stock_name}] 命中舆情缓存，跳过外部搜索")
            # 2) 无缓存再走外部搜索
            elif self.search_service:
                # 随机休眠 2.0 - 5.0 秒
                sleep_time = random.uniform(2.0, 5.0)
                time.sleep(sleep_time)
                
                logger.info(f"🔎 [{stock_name}] 正在侦查舆情 (延迟 {sleep_time:.1f}s)...")
                try:
                    query = f"{stock_name} ({code}) 近期重大利好利空消息 机构观点 研报"
                    if hasattr(self.search_service, 'search_stock_news'):
                        resp = self.search_service.search_stock_news(code, stock_name)
                    else:
                        resp = self.search_service.search(query)
                        
                    if resp and getattr(resp, 'success', False): 
                        search_content = resp.to_context()
                        # 舆情落库，便于后续复用与审计
                        if getattr(resp, 'results', None):
                            try:
                                self.storage.save_news_intel(
                                    code, stock_name, dimension="舆情", query=query, response=resp,
                                    query_context={"query_id": self.query_id, "query_source": self.query_source}
                                )
                            except Exception as e:
                                logger.debug(f"[{stock_name}] 舆情落库跳过: {e}")
                except Exception as e:
                    logger.warning(f"[{stock_name}] 搜索服务异常: {e}")

            # === 2. 获取大盘环境（前置滤网：大盘定仓位上限，个股逻辑定买卖方向）===
            market_overview = market_overview_override
            if market_overview is None and self._market_monitor:
                try:
                    snapshot = self._market_monitor.get_market_snapshot()
                    if snapshot.get('success'):
                        vol = snapshot.get('total_volume', 'N/A')
                        indices = snapshot.get('indices', [])
                        idx_str = " / ".join([f"{i['name']} {i['change_pct']}%" for i in indices])
                        market_overview = f"今日两市成交额: {vol}亿。指数表现: {idx_str}。"
                        logger.info(f"📊 [{stock_name}] 大盘环境已注入（滤网）: 成交额{vol}亿 | {idx_str}")
                except Exception as e:
                    logger.warning(f"[{stock_name}] 获取大盘数据微瑕: {e}")

            self._log(f"🤖 [{stock_name}] 调用 LLM 进行分析...")
            # 无舆情时也用轻量模型，省成本
            use_light = used_news_cache or (not search_content or not search_content.strip())
            # === 3. 执行分析（带超时，默认 180 秒）===
            analysis_timeout = getattr(self.config, 'analysis_timeout_seconds', 180) or 180
            def _run_analyze():
                return self.analyzer.analyze(
                    context=context,
                    news_context=search_content,
                    role="trader",
                    market_overview=market_overview,
                    use_light_model=use_light,
                )
            try:
                with ThreadPoolExecutor(max_workers=1) as ex:
                    fut = ex.submit(_run_analyze)
                    result = fut.result(timeout=analysis_timeout)
            except FuturesTimeoutError:
                logger.warning(f"[{stock_name}] 分析超时 ({analysis_timeout}s)，跳过")
                return None
            except Exception as e:
                logger.exception(f"[{stock_name}] 分析异常: {e}")
                return None
            
            if not result: return None
            self._log(f"[分析完成] {stock_name}: 建议-{result.operation_advice}, 评分-{result.sentiment_score}")
            
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
            # 同时保存一份 .txt 到本地，不改变 PushPlus 等推送逻辑
            from pathlib import Path
            reports_dir = Path(__file__).resolve().parents[2] / "reports"
            reports_dir.mkdir(parents=True, exist_ok=True)
            txt_name = f"report_{time.strftime('%Y%m%d')}.txt"
            txt_path = reports_dir / txt_name
            with open(txt_path, "w", encoding="utf-8") as f:
                f.write(daily_report)
            logger.info(f"日报已保存为 txt: {txt_path}")
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
                success, msg, df, quote = self.fetch_and_save_stock_data(code)
                
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
                    # 缓存阶段一结果，阶段二复用避免重复取数/拼接
                    if df is not None and quote is not None:
                        self._prefetch_cache[code] = {"df": df, "quote": quote}
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

        # 阶段二：大盘快照只取一次（更快、更一致），传入每只股票
        market_overview_once: Optional[str] = None
        if self._market_monitor:
            try:
                snapshot = self._market_monitor.get_market_snapshot()
                if snapshot.get("success"):
                    vol = snapshot.get('total_volume', 'N/A')
                    indices = snapshot.get('indices', [])
                    idx_str = " / ".join([f"{i['name']} {i['change_pct']}%" for i in indices])
                    market_overview_once = f"今日两市成交额: {vol}亿。指数表现: {idx_str}。"
                    logger.info(f"📊 [阶段二] 大盘快照已获取（全局复用）: 成交额{vol}亿 | {idx_str}")
            except Exception as e:
                logger.warning(f"📊 [阶段二] 获取大盘快照失败(降级为逐股/不注入): {e}")

        with ThreadPoolExecutor(max_workers=workers) as executor:
            future_to_code = {
                executor.submit(
                    self.process_single_stock, 
                    code, 
                    skip_analysis=dry_run, 
                    single_stock_notify=single_stock_notify and send_notification, 
                    report_type=report_type, 
                    skip_data_fetch=True,
                    market_overview_override=market_overview_once
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