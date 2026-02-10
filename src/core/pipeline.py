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


class MarketPhase:
    """A 股市场阶段，盘中分析时需区分"""
    PRE_MARKET = "pre_market"          # 盘前 (< 9:30)
    MORNING_SESSION = "morning"        # 上午交易 (9:30-11:30)
    LUNCH_BREAK = "lunch_break"        # 午休 (11:30-13:00)，价格冻结
    AFTERNOON_SESSION = "afternoon"    # 下午交易 (13:00-15:00)
    POST_MARKET = "post_market"        # 盘后 (>= 15:00)


def get_market_phase() -> str:
    """返回当前 A 股市场阶段"""
    now = datetime.now()
    t = now.hour * 60 + now.minute  # 转分钟方便比较
    if t < 9 * 60 + 30:
        return MarketPhase.PRE_MARKET
    if t < 11 * 60 + 30:
        return MarketPhase.MORNING_SESSION
    if t < 13 * 60:
        return MarketPhase.LUNCH_BREAK
    if t < 15 * 60:
        return MarketPhase.AFTERNOON_SESSION
    return MarketPhase.POST_MARKET


def is_market_intraday() -> bool:
    """判断当前是否为 A 股盘中（含午休，因为尚未收盘）"""
    phase = get_market_phase()
    return phase in (MarketPhase.MORNING_SESSION, MarketPhase.LUNCH_BREAK, MarketPhase.AFTERNOON_SESSION)


def is_market_trading() -> bool:
    """判断当前是否正在交易（不含午休）"""
    phase = get_market_phase()
    return phase in (MarketPhase.MORNING_SESSION, MarketPhase.AFTERNOON_SESSION)


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

    def _get_cached_news_context(self, code: str, stock_name: str, hours: int = 6,
                                  limit: int = 5, provider: str = None,
                                  min_count: int = 1) -> str:
        """
        从 news_intel 缓存中获取新闻上下文。

        Args:
            code: 股票代码
            stock_name: 股票名称（仅用于日志）
            hours: 缓存时间窗口（小时）
            limit: 最多返回条数
            provider: 数据来源过滤（'akshare', 'perplexity', None=不限）
            min_count: 最少命中条数，低于此数视为未命中

        Returns:
            格式化的新闻上下文字符串，未命中返回空字符串
        """
        try:
            items = self.storage.get_recent_news(code, days=1, limit=limit, provider=provider)
            if not items:
                return ""
            cutoff = datetime.now() - timedelta(hours=hours)
            fresh = [n for n in items if getattr(n, "fetched_at", None) and n.fetched_at >= cutoff]
            if len(fresh) < min_count:
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
        tech_report_llm = "数据不足"
        trend_analysis_dict = {}
        if daily_df is not None and not daily_df.empty:
            try:
                from src.stock_analyzer import StockTrendAnalyzer as _STA, MarketRegime
                # 检测市场环境（用于动态评分权重）
                idx_pct = 0.0
                if self._market_monitor:
                    try:
                        snap = self._market_monitor.get_market_snapshot()
                        for idx in snap.get('indices', []):
                            if idx.get('name') == '上证指数':
                                idx_pct = float(idx.get('change_pct', 0))
                                break
                    except Exception:
                        pass
                regime = _STA.detect_market_regime(daily_df, idx_pct)
                # 获取指数收益率序列（供 Beta 计算）
                idx_ret = None
                try:
                    idx_ret = self.storage.get_index_returns("上证指数", days=120)
                    if idx_ret.empty:
                        idx_ret = None
                except Exception:
                    pass
                # 构建估值快照（从实时行情提取 PE/PB，从 F10 缓存提取 PEG）
                _valuation = {}
                if quote:
                    if getattr(quote, 'pe_ratio', None) is not None:
                        _valuation['pe'] = quote.pe_ratio
                    if getattr(quote, 'pb_ratio', None) is not None:
                        _valuation['pb'] = quote.pb_ratio
                # 尝试从 F10 缓存获取 PEG（缓存命中免网络请求）
                try:
                    _f10_cached = get_fundamental_data(code) if not getattr(self.config, 'fast_mode', False) else {}
                    if _f10_cached:
                        _f10_val = _f10_cached.get('valuation', {}) or {}
                        if 'peg' in _f10_val:
                            _valuation['peg'] = _f10_val['peg']
                        elif _valuation.get('pe') and _valuation['pe'] > 0:
                            growth_str = _f10_cached.get('financial', {}).get('net_profit_growth', 'N/A')
                            if growth_str not in ('N/A', '', '0', None):
                                try:
                                    growth_val = float(str(growth_str).replace('%', ''))
                                    if growth_val > 0:
                                        _valuation['peg'] = round(_valuation['pe'] / growth_val, 2)
                                except (ValueError, TypeError):
                                    pass
                except Exception:
                    pass
                # 资金面数据（如有）
                _capital_flow = {}
                try:
                    if hasattr(self.fetcher_manager, 'get_capital_flow'):
                        _capital_flow = self.fetcher_manager.get_capital_flow(code) or {}
                except Exception:
                    pass
                trend_result = self.trend_analyzer.analyze(daily_df, code, market_regime=regime, index_returns=idx_ret, valuation=_valuation or None, capital_flow=_capital_flow or None)
                if quote.price:
                    trend_result.current_price = quote.price
                tech_report = self.trend_analyzer.format_analysis(trend_result)
                tech_report_llm = self.trend_analyzer.format_for_llm(trend_result)
                trend_analysis_dict = trend_result.to_dict()
                trend_analysis_dict['market_regime'] = regime.value
            except Exception as e:
                logger.error(f"[{code}] 技术分析生成失败: {e}")

        # 筹码数据（先查 DB/内存缓存；失败时明确标记「暂不可用」避免模型瞎编）
        chip_data = {}
        chip_note = "未启用"
        if getattr(self.config, 'enable_chip_distribution', False) or getattr(self.config, 'chip_fetch_only_from_cache', False):
            chip = self.fetcher_manager.get_chip_distribution(code) if hasattr(self.fetcher_manager, 'get_chip_distribution') else None
            if chip:
                chip_data = chip.to_dict()
                # 筹码缓存年龄告警：超过 48h 提示数据可能过时
                chip_age_note = ""
                try:
                    fetched_at = getattr(chip, 'fetched_at', None) or chip_data.get('fetched_at')
                    if fetched_at:
                        from datetime import datetime as _dt
                        if isinstance(fetched_at, str):
                            fetched_at = _dt.fromisoformat(fetched_at)
                        age_hours = (datetime.now() - fetched_at).total_seconds() / 3600
                        if age_hours > 48:
                            chip_age_note = f"（注意：筹码数据已缓存 {age_hours:.0f} 小时，可能过时）"
                except Exception:
                    pass
                chip_note = f"见下数据{chip_age_note}"
            else:
                chip_note = "暂不可用（接口失败或未拉取）"
        
        # F10 基本面数据（快速模式跳过，日内不变，用缓存即可）
        fundamental_data = {}
        fast_mode = getattr(self.config, 'fast_mode', False)
        if not fast_mode:
            try:
                fundamental_data = get_fundamental_data(code)
            except Exception as e:
                pass
        # 补充估值：从实时行情注入 PE/PB/总市值（供基本面判断贵/便宜）
        if quote:
            val = fundamental_data.setdefault('valuation', {}) or {}
            if not isinstance(val, dict):
                fundamental_data['valuation'] = val = {}
            if getattr(quote, 'pe_ratio', None) is not None:
                val['pe'] = quote.pe_ratio
            if getattr(quote, 'pb_ratio', None) is not None:
                val['pb'] = quote.pb_ratio
            if getattr(quote, 'total_mv', None) is not None:
                val['total_mv'] = quote.total_mv

            # PEG = PE / 净利润增速（此处两者都已可用，比 fundamental_fetcher 里更可靠）
            if 'peg' not in val:
                try:
                    pe = val.get('pe')
                    growth_str = fundamental_data.get('financial', {}).get('net_profit_growth', 'N/A')
                    if pe and isinstance(pe, (int, float)) and pe > 0 and growth_str not in ('N/A', '', '0', None):
                        growth_val = float(str(growth_str).replace('%', ''))
                        if growth_val > 0:
                            val['peg'] = round(pe / growth_val, 2)
                except (ValueError, TypeError, ZeroDivisionError):
                    pass

        # 板块相对强弱
        sector_context = None
        try:
            stock_pct = getattr(quote, 'change_pct', None) if quote else None
            sector_context = self.fetcher_manager.get_stock_sector_context(code, stock_pct_chg=stock_pct)
        except Exception as e:
            logger.debug(f"[{code}] 板块上下文获取失败: {e}")

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
            'technical_analysis_report_llm': tech_report_llm,
            'trend_analysis': trend_analysis_dict,
            'fundamental': fundamental_data,
            'history_summary': history_summary,
            'sector_context': sector_context,
            'is_intraday': is_market_intraday(),
            'market_phase': get_market_phase(),
            'analysis_time': datetime.now().strftime('%H:%M'),
        }
        context = self._enhance_context(context)
        return context

    def _enhance_context(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """增强 context：预留扩展点，未来可注入额外结构化信息"""
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
                return AnalysisResult(code=code, name=stock_name, sentiment_score=50, trend_prediction="测试", operation_advice="观望", analysis_summary="Dry Run 测试", success=True)

            # === 1. 三层舆情获取 ===
            # 第 1 层: Akshare 免费新闻缓存 (后台定时抓取，24h 窗口，>=2 条命中)
            # 第 2 层: Perplexity 缓存 (6h 窗口)
            # 第 3 层: Perplexity 实时搜索 (最后手段)
            search_content = ""
            used_news_cache = False
            news_source = ""
            fast_mode = getattr(self.config, 'fast_mode', False)

            # 层 1: Akshare 免费新闻（后台已抓取入库）
            akshare_news = self._get_cached_news_context(
                code, stock_name, hours=24, limit=10, provider='akshare', min_count=2
            )
            if akshare_news:
                search_content = akshare_news
                used_news_cache = True
                news_source = "akshare"
                logger.info(f"📰 [{stock_name}] 命中 Akshare 新闻缓存，跳过外部搜索")

            # 层 2: Perplexity 缓存（之前搜索过的结果）
            if not search_content:
                pplx_cache = self._get_cached_news_context(
                    code, stock_name, hours=6, limit=5, provider='perplexity'
                )
                if pplx_cache:
                    search_content = pplx_cache
                    used_news_cache = True
                    news_source = "perplexity_cache"
                    logger.info(f"♻️  [{stock_name}] 命中 Perplexity 缓存，跳过外部搜索")

            # 层 2.5: 不限 provider 的通用缓存（兼容旧数据）
            if not search_content:
                any_cache = self._get_cached_news_context(code, stock_name, hours=6, limit=5)
                if any_cache:
                    search_content = any_cache
                    used_news_cache = True
                    news_source = "cache_legacy"
                    logger.info(f"♻️  [{stock_name}] 命中舆情缓存，跳过外部搜索")

            # 快速模式：即使无缓存也不搜索
            if not search_content and fast_mode:
                logger.info(f"⚡ [{stock_name}] 快速模式，跳过外部搜索")
                used_news_cache = True

            # 层 3: Perplexity 实时搜索（最后手段）
            if not search_content and not fast_mode and self.search_service:
                sleep_time = random.uniform(2.0, 5.0)
                time.sleep(sleep_time)

                logger.info(f"🔎 [{stock_name}] 无缓存新闻，调用 Perplexity 搜索 (延迟 {sleep_time:.1f}s)...")
                try:
                    if hasattr(self.search_service, 'search_comprehensive_intel'):
                        resp = self.search_service.search_comprehensive_intel(code, stock_name)
                    elif hasattr(self.search_service, 'search_stock_news'):
                        resp = self.search_service.search_stock_news(code, stock_name)
                    else:
                        resp = self.search_service.search(f"{stock_name} ({code}) 近期重大利好利空消息 机构观点 研报")

                    if resp and getattr(resp, 'success', False):
                        search_content = resp.to_context()
                        news_source = "perplexity_live"
                        query = f"{stock_name} ({code}) 综合分析 风险 业绩 行业"
                        if getattr(resp, 'results', None):
                            try:
                                self.storage.save_news_intel(
                                    code, stock_name, dimension="舆情", query=query, response=resp,
                                    query_context={"query_id": self.query_id, "query_source": self.query_source}
                                )
                            except Exception as e:
                                logger.debug(f"[{stock_name}] 舆情落库跳过: {e}")
                        else:
                            logger.warning(f"⚠️  [{stock_name}] Perplexity 返回空结果")
                    else:
                        reason = getattr(resp, 'error', '未知') if resp else '响应为空'
                        logger.warning(f"⚠️  [{stock_name}] Perplexity 搜索失败 (原因: {reason})")
                except Exception as e:
                    logger.warning(f"[{stock_name}] 搜索服务异常: {e}")

            if not search_content and not fast_mode:
                logger.info(f"📭 [{stock_name}] 无舆情数据，将仅基于技术面+基本面分析")

            # === 2. 获取大盘环境（前置滤网：大盘定仓位上限，个股逻辑定买卖方向）===
            # 盘中模式：若大盘快照由上层传入但市场仍在交易，刷新一次以获取最新数据
            market_overview = market_overview_override
            if market_overview is not None and is_market_trading() and self._market_monitor:
                try:
                    snapshot = self._market_monitor.get_market_snapshot()  # 内部有 60s 缓存，不会打爆接口
                    if snapshot.get('success'):
                        vol = snapshot.get('total_volume', 'N/A')
                        indices = snapshot.get('indices', [])
                        idx_str = " / ".join([f"{i['name']} {i['change_pct']}%" for i in indices])
                        market_overview = f"今日两市成交额: {vol}亿。指数表现: {idx_str}。（以上为**盘中数据**，截至当前。）"
                except Exception:
                    pass  # 刷新失败则沿用上层传入的旧快照
            if market_overview is None and self._market_monitor:
                try:
                    snapshot = self._market_monitor.get_market_snapshot()
                    if snapshot.get('success'):
                        vol = snapshot.get('total_volume', 'N/A')
                        indices = snapshot.get('indices', [])
                        idx_str = " / ".join([f"{i['name']} {i['change_pct']}%" for i in indices])
                        market_overview = f"今日两市成交额: {vol}亿。指数表现: {idx_str}。"
                        if is_market_intraday():
                            market_overview += "（以上为**盘中数据**，非收盘；成交额与涨跌幅均为截至当前。）"
                        logger.info(f"📊 [{stock_name}] 大盘环境已注入（滤网）: 成交额{vol}亿 | {idx_str}")
                except Exception as e:
                    logger.warning(f"[{stock_name}] 获取大盘数据微瑕: {e}")

            # 分析前延迟（可配置，用于等待数据落定或降低 API 压力）
            delay = getattr(self.config, 'analysis_delay', 0) or 0
            if delay > 0:
                time.sleep(delay)
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

            # ===== Quant Override: 硬决策由量化模型主导，LLM 意见保留作参考 =====
            trend = context.get('trend_analysis', {})
            if trend and isinstance(trend, dict):
                quant_score = trend.get('signal_score')
                quant_signal = trend.get('buy_signal')
                # 保留 LLM 的原始评分和建议作为参考
                # llm_score/llm_advice 可能由 _parse_response 从 JSON 直接解析；
                # 若 LLM 没显式返回，则用 LLM 的 sentiment_score/operation_advice 作为 fallback（量化覆盖前）
                if result.llm_score is None and result.sentiment_score is not None:
                    result.llm_score = result.sentiment_score
                if not result.llm_advice and result.operation_advice and result.operation_advice != '观望':
                    result.llm_advice = result.operation_advice
                # 如果 LLM 什么都没返回（sentiment_score 默认50），且 llm_score 仍为 50，标记来源
                # 确保 llm_advice 有值
                if not result.llm_advice and result.operation_advice:
                    result.llm_advice = result.operation_advice
                # 量化模型覆盖主决策
                if quant_score is not None:
                    result.sentiment_score = int(quant_score)
                if quant_signal:
                    result.operation_advice = str(quant_signal)
                # 止损/买点：用量化锚点覆盖 LLM 输出
                dashboard = result.dashboard or {}
                battle = dashboard.get('battle_plan', {})
                sniper = battle.get('sniper_points', {})
                if trend.get('stop_loss_short'):
                    sniper['stop_loss'] = trend['stop_loss_short']
                if trend.get('ideal_buy_anchor'):
                    sniper['ideal_buy'] = trend['ideal_buy_anchor']
                if trend.get('stop_loss_intraday'):
                    sniper['stop_loss_intraday'] = trend['stop_loss_intraday']
                if trend.get('stop_loss_mid'):
                    sniper['stop_loss_mid'] = trend['stop_loss_mid']
                battle['sniper_points'] = sniper
                dashboard['battle_plan'] = battle
                result.dashboard = dashboard
                # 仓位
                if trend.get('suggested_position_pct') is not None:
                    # 写入 dashboard 供报告使用
                    core = dashboard.get('core_conclusion', {})
                    pos = core.get('position_advice', {})
                    pct = trend['suggested_position_pct']
                    if pct == 0:
                        pos['no_position'] = "不建议介入"
                    else:
                        pos['no_position'] = f"建议仓位 {pct}%"
                    core['position_advice'] = pos
                    dashboard['core_conclusion'] = core

                # 止盈点位注入
                if trend.get('take_profit_short'):
                    sniper['take_profit'] = trend['take_profit_short']
                if trend.get('take_profit_mid'):
                    sniper['take_profit_mid'] = trend['take_profit_mid']

                # 新量化字段注入 dashboard（供 notification 渲染）
                quant_extras = {
                    'valuation_verdict': trend.get('valuation_verdict', ''),
                    'valuation_downgrade': trend.get('valuation_downgrade', 0),
                    'pe_ratio': trend.get('pe_ratio', 0),
                    'pb_ratio': trend.get('pb_ratio', 0),
                    'peg_ratio': trend.get('peg_ratio', 0),
                    'valuation_score': trend.get('valuation_score', 0),
                    'trading_halt': trend.get('trading_halt', False),
                    'trading_halt_reason': trend.get('trading_halt_reason', ''),
                    'capital_flow_score': trend.get('capital_flow_score', 0),
                    'capital_flow_signal': trend.get('capital_flow_signal', ''),
                    'beginner_summary': trend.get('beginner_summary', ''),
                    'take_profit_short': trend.get('take_profit_short', 0),
                    'take_profit_mid': trend.get('take_profit_mid', 0),
                    'take_profit_trailing': trend.get('take_profit_trailing', 0),
                    'take_profit_plan': trend.get('take_profit_plan', ''),
                    'resonance_count': trend.get('resonance_count', 0),
                    'resonance_signals': trend.get('resonance_signals', []),
                    'resonance_bonus': trend.get('resonance_bonus', 0),
                    'risk_reward_ratio': trend.get('risk_reward_ratio', 0),
                    'risk_reward_verdict': trend.get('risk_reward_verdict', ''),
                    'volatility_20d': trend.get('volatility_20d', 0),
                    'max_drawdown_60d': trend.get('max_drawdown_60d', 0),
                }
                dashboard['quant_extras'] = quant_extras

                # 决策类型
                advice = result.operation_advice
                if '买' in advice or '加仓' in advice:
                    result.decision_type = 'buy'
                elif '卖' in advice or '减仓' in advice:
                    result.decision_type = 'sell'
                else:
                    result.decision_type = 'hold'

            # 标注分析时间戳（盘中多次分析时可区分）
            result.analysis_time = datetime.now().strftime('%H:%M')
            self._log(f"[分析完成] {stock_name}: 建议-{result.operation_advice}, 评分-{result.sentiment_score} (时间={result.analysis_time})")
            
            try:
                # 每只股票用独立的 query_id（batch_id + code），确保 WebUI 历史记录能正确定位
                per_stock_query_id = f"{self.query_id}_{code}" if self.query_id else None
                self.storage.save_analysis_history(result=result, query_id=per_stock_query_id, report_type=report_type.value if hasattr(report_type, 'value') else str(report_type), news_content=search_content, context_snapshot=context if self.save_context_snapshot else None)
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

    def _check_portfolio_risk(self, results: List[AnalysisResult]) -> List[str]:
        """
        组合风控检查：板块集中度 + 方向一致性 + 总仓位上限
        返回风控告警列表（空列表=无告警）
        """
        warnings = []
        if len(results) < 2:
            return warnings

        # 1. 板块集中度检查
        sector_map = {}  # sector_name -> [stock_names]
        for r in results:
            # 从 context snapshot 或 dashboard 中提取板块信息
            sector = None
            if r.dashboard and isinstance(r.dashboard, dict):
                sector = r.dashboard.get('sector_name')
            if not sector:
                # 尝试从 market_snapshot 获取
                snap = r.market_snapshot or {}
                sector = snap.get('sector_name')
            if sector:
                sector_map.setdefault(sector, []).append(r.name or r.code)

        for sector, stocks in sector_map.items():
            if len(stocks) >= 2:
                ratio = len(stocks) / len(results) * 100
                if ratio >= 50:
                    warnings.append(
                        f"⚠️ 板块集中风险: {sector}板块占比{ratio:.0f}% ({', '.join(stocks)})，"
                        f"建议分散至不同行业，避免板块性系统风险"
                    )

        # 2. 方向一致性检查（全部同向看多/看空的风险）
        buy_count = sum(1 for r in results if r.decision_type == 'buy')
        sell_count = sum(1 for r in results if r.decision_type == 'sell')
        total = len(results)

        if buy_count == total and total >= 3:
            warnings.append(
                f"⚠️ 全仓看多风险: 全部{total}只股票均建议买入，"
                f"需警惕系统性风险（大盘回调时可能全线亏损）"
            )
        elif sell_count == total and total >= 3:
            warnings.append(
                f"💡 全仓看空信号: 全部{total}只股票均建议卖出/观望，"
                f"市场可能处于弱势，建议降低整体仓位"
            )

        # 3. 总仓位上限检查
        total_position = 0
        for r in results:
            # 从 dashboard 中获取量化建议仓位
            trend = getattr(r, 'market_snapshot', {}) or {}
            pos = 0
            if r.dashboard and isinstance(r.dashboard, dict):
                core = r.dashboard.get('core_conclusion', {})
                pos_advice = core.get('position_advice', {})
                pos_str = pos_advice.get('no_position', '')
                if '仓位' in str(pos_str):
                    try:
                        import re
                        m = re.search(r'(\d+)%', str(pos_str))
                        if m:
                            pos = int(m.group(1))
                    except Exception:
                        pass
            total_position += pos

        if total_position > 80:
            warnings.append(
                f"⚠️ 总仓位过高: 建议总仓位{total_position}%超过80%上限，"
                f"请降低部分个股仓位或减少持股数量"
            )

        # 4. 高相关性检查（同涨跌幅 > 相关阈值的股票）
        scores = [(r.name or r.code, r.sentiment_score) for r in results]
        high_score = [name for name, s in scores if s >= 70]
        low_score = [name for name, s in scores if s <= 30]

        if len(high_score) >= 3:
            warnings.append(
                f"📊 多股同时高分: {', '.join(high_score)} 评分均≥70，"
                f"检查是否属于同一板块/概念，避免集中踩雷"
            )

        return warnings

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
                    # 串行阶段也稍微休息一下，防止数据源封IP（快速模式缩短）
                    if not dry_run:
                        time.sleep(0.2 if getattr(self.config, 'fast_mode', False) else 0.5)
                else:
                    logger.warning(f"[{i+1}/{total_stocks}] ❌ {code} 数据失败: {msg}")
                
            except Exception as e:
                logger.error(f"[{code}] 数据预取异常: {e}")

        # === 阶段1.5：保存今日指数数据（供 Beta 计算） ===
        if self._market_monitor:
            try:
                snap = self._market_monitor.get_market_snapshot()
                if snap.get('success'):
                    for idx in snap.get('indices', []):
                        name = idx.get('name', '')
                        close_val = float(idx.get('close', 0))
                        pct = float(idx.get('change_pct', 0))
                        if name and close_val > 0:
                            self.storage.save_index_daily(name, close_val, pct)
            except Exception as e:
                logger.debug(f"保存指数日线跳过: {e}")

        # === 阶段二：并发分析 ===
        # 预取实时行情（批量预热，可选）
        if valid_stocks and hasattr(self.fetcher_manager, 'prefetch_realtime_quotes'):
            try:
                self.fetcher_manager.prefetch_realtime_quotes(valid_stocks)
            except Exception as e:
                logger.debug(f"prefetch_realtime_quotes 跳过: {e}")
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
                    if is_market_intraday():
                        market_overview_once += "（以上为**盘中数据**，非收盘；成交额与涨跌幅均为截至当前。）"
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

        # === 阶段三：组合风控检查 ===
        if len(results) >= 2:
            try:
                risk_warnings = self._check_portfolio_risk(results)
                if risk_warnings:
                    logger.warning("⚠️ 【组合风控告警】")
                    for w in risk_warnings:
                        logger.warning(f"  {w}")
                    # 将风控告警注入每只股票的 risk_warning 字段
                    warning_text = "\n".join(risk_warnings)
                    for r in results:
                        existing = r.risk_warning or ""
                        r.risk_warning = f"{existing}\n【组合风控】{warning_text}".strip()
            except Exception as e:
                logger.debug(f"组合风控检查跳过: {e}")

        # 汇总推送 (如果没开单股推送)
        if results and send_notification and not dry_run and not single_stock_notify:
            self._send_notifications(results)
            
        return results