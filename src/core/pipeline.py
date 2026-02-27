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
    from data_provider.fundamental_types import FundamentalData as _FD
    def get_fundamental_data(code): return _FD()

from data_provider.fundamental_types import FundamentalData, ValuationSnapshot
from data_provider.analysis_types import CapitalFlowData, SectorContext, QuoteExtra

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
from src.stock_analyzer.types import MarketRegime
from src.stock_analyzer.scoring import ScoringSystem
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
            seen_keys: set = set()
            idx = 1
            for n in fresh[:limit * 2]:  # 多取一些供去重后筛选
                title = (getattr(n, "title", "") or "").strip()
                snippet = (getattr(n, "snippet", "") or "").strip()
                source = (getattr(n, "source", "") or "").strip()
                # 去重键：同来源 + 标题前20字（避免同一事件不同措辞被重复注入）
                dedup_key = f"{source}|{title[:20]}"
                if dedup_key in seen_keys:
                    continue
                seen_keys.add(dedup_key)
                pub = getattr(n, "published_date", None)
                pub_str = f" ({pub})" if pub else ""
                head = f"{idx}. 【{source}】{title}{pub_str}".strip()
                lines.append(f"{head}\n{snippet}".strip())
                idx += 1
                if idx > limit:
                    break
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

        # === 预获取共享数据（每类数据只获取一次，供量化分析和 LLM context 共用）===
        fast_mode = getattr(self.config, 'fast_mode', False)

        # F10 基本面数据（只获取一次）
        fundamental_data = FundamentalData()
        if not fast_mode:
            try:
                fundamental_data = get_fundamental_data(code)
            except Exception:
                pass

        # 补充估值：从实时行情注入 PE/PB/总市值（写入 fundamental_data.valuation dict，供 LLM context 使用）
        if quote:
            val = fundamental_data.valuation  # dict，由 FundamentalData 保证非 None
            if getattr(quote, 'pe_ratio', None) is not None:
                val['pe'] = quote.pe_ratio
            if getattr(quote, 'pb_ratio', None) is not None:
                val['pb'] = quote.pb_ratio
            if getattr(quote, 'total_mv', None) is not None:
                val['total_mv'] = quote.total_mv
            # PEG = PE / 净利润增速（只计算一次）
            if 'peg' not in val:
                try:
                    pe = val.get('pe')
                    growth_val = fundamental_data.financial.net_profit_growth  # 已是 float 或 None
                    if pe and isinstance(pe, (int, float)) and pe > 0 and growth_val and growth_val > 0:
                        val['peg'] = round(pe / growth_val, 2)
                except (ValueError, TypeError, ZeroDivisionError):
                    pass

        # 筹码数据（只获取一次）
        chip_data = None
        chip_note = "未启用"
        if getattr(self.config, 'enable_chip_distribution', False) or getattr(self.config, 'chip_fetch_only_from_cache', False):
            chip_data = self.fetcher_manager.get_chip_distribution(code) if hasattr(self.fetcher_manager, 'get_chip_distribution') else None
            if chip_data:
                # 筹码缓存年龄告警：超过 48h 提示数据可能过时
                chip_age_note = ""
                try:
                    fetched_at = getattr(chip_data, 'fetched_at', None)
                    if fetched_at:
                        if isinstance(fetched_at, str):
                            fetched_at = datetime.fromisoformat(fetched_at)
                        age_hours = (datetime.now() - fetched_at).total_seconds() / 3600
                        if age_hours > 48:
                            chip_age_note = f"（注意：筹码数据已缓存 {age_hours:.0f} 小时，可能过时）"
                except Exception:
                    pass
                chip_note = f"见下数据{chip_age_note}"
            else:
                chip_note = "暂不可用（接口失败或未拉取）"

        # 板块相对强弱（只获取一次）
        sector_context = None
        try:
            _stock_pct = getattr(quote, 'change_pct', None) if quote else None
            sector_context = self.fetcher_manager.get_stock_sector_context(code, stock_pct_chg=_stock_pct)
        except Exception as e:
            logger.debug(f"[{code}] 板块上下文获取失败: {e}")

        # === 技术面量化分析 ===
        tech_report = "数据不足，无法进行技术分析"
        tech_report_llm = "数据不足"
        trend_analysis_dict = {}
        if daily_df is not None and not daily_df.empty:
            try:
                from src.stock_analyzer import StockTrendAnalyzer as _STA, MarketRegime
                # 检测市场环境（用于动态评分权重）
                idx_pct = 0.0
                snap = None
                if self._market_monitor:
                    try:
                        snap = self._market_monitor.get_market_snapshot()
                        for idx in snap.get('indices', []):
                            if idx.get('name') == '上证指数':
                                idx_pct = float(idx.get('change_pct', 0))
                                break
                    except Exception:
                        pass
                # 优先用真实指数K线判断大盘环境（上证+创业板综合）
                _idx_df = None
                try:
                    _sh_df = self.storage.get_index_kline("上证指数", days=120)
                    _cy_df = self.storage.get_index_kline("创业板指", days=120)
                    if not _sh_df.empty and not _cy_df.empty and len(_sh_df) >= 20:
                        # 合并上证+创业板的综合K线（等权平均，捕获成长股轮动）
                        import pandas as _pd
                        _merged = _sh_df.set_index('date').join(_cy_df.set_index('date'), how='inner', lsuffix='_sh', rsuffix='_cy')
                        if len(_merged) >= 20:
                            _idx_df = _pd.DataFrame({
                                'close': (_merged['close_sh'] + _merged['close_cy'] * 0.5) / 1.5,
                            })
                    elif not _sh_df.empty and len(_sh_df) >= 20:
                        _idx_df = _sh_df[['close']]
                except Exception:
                    pass
                regime, _ = _STA.detect_market_regime(daily_df, idx_pct, index_df=_idx_df)
                # 获取指数收益率序列（供 Beta 计算）
                idx_ret = None
                try:
                    idx_ret = self.storage.get_index_returns("上证指数", days=120)
                    if idx_ret.empty:
                        idx_ret = None
                except Exception:
                    pass
                # 构建估值快照（复用已获取的 fundamental_data，强类型替代裸 dict）
                _val_snap = ValuationSnapshot(
                    pe=getattr(quote, 'pe_ratio', None) if quote else None,
                    pb=getattr(quote, 'pb_ratio', None) if quote else None,
                    peg=fundamental_data.valuation.get('peg'),
                    revenue_growth=fundamental_data.financial.revenue_growth,
                    net_profit_growth=fundamental_data.financial.net_profit_growth,
                )
                # 行业PE中位数（用于相对估值判断）+ PE历史（P3估值分位数）
                try:
                    from data_provider.fundamental_fetcher import get_industry_pe_median, get_pe_history
                    if not fast_mode:
                        ind_pe = get_industry_pe_median(code)
                        if ind_pe and ind_pe > 0:
                            _val_snap.industry_pe_median = ind_pe
                        # P3: PE历史数据（用于估值分位数计算）
                        pe_hist = get_pe_history(code)
                        if pe_hist:
                            _val_snap.pe_history = pe_hist
                except Exception:
                    pass
                # 资金面数据（如有）+ 融资余额历史（P3情绪极端检测）
                _capital_flow = None
                try:
                    if hasattr(self.fetcher_manager, 'get_capital_flow'):
                        _capital_flow = self.fetcher_manager.get_capital_flow(code)
                    # P3: 融资余额历史（用于情绪极端检测）
                    # 注意：此接口每天需N次全市场请求，效率较低，仅在显式开启时使用
                    if _capital_flow and not fast_mode and getattr(self.config, 'enable_margin_history', False):
                        try:
                            from data_provider.fundamental_fetcher import get_margin_history
                            margin_hist = get_margin_history(code)
                            if margin_hist:
                                _capital_flow.margin_history = margin_hist
                        except Exception:
                            pass
                    # 注入日均成交额（万元），供资金面阈值相对化使用
                    if _capital_flow and daily_df is not None and len(daily_df) >= 20:
                        _avg_amount = (daily_df['close'] * daily_df['volume']).tail(20).mean()
                        if _avg_amount > 0:
                            _capital_flow.daily_avg_amount = round(_avg_amount / 10000, 2)  # 转为万元
                except Exception:
                    pass
                # 行情附加数据（换手率、52周高低、市值）
                _quote_extra = None
                if quote:
                    _qe = QuoteExtra(
                        turnover_rate=getattr(quote, 'turnover_rate', None),
                        high_52w=getattr(quote, 'high_52w', None),
                        low_52w=getattr(quote, 'low_52w', None),
                        total_mv=getattr(quote, 'total_mv', None),
                        circ_mv=getattr(quote, 'circ_mv', None),
                    )
                    if _qe.has_data:
                        _quote_extra = _qe
                # 改进4: 确定时间维度（auto模式下盘中用short，盘后用默认）
                _time_horizon = getattr(self.config, 'time_horizon', 'auto') or 'auto'
                if _time_horizon == 'auto':
                    _time_horizon = 'short' if is_market_intraday() else ''
                # 复用已获取的大盘快照供 P0 风控使用（snap 在上方已获取，有60s缓存）
                try:
                    _market_snap = snap if isinstance(snap, dict) and snap.get('success') else None
                except NameError:
                    _market_snap = None
                trend_result = self.trend_analyzer.analyze(daily_df, code, market_regime=regime, index_returns=idx_ret, valuation=_val_snap, capital_flow=_capital_flow, sector_context=sector_context, chip_data=chip_data, fundamental_data=fundamental_data, quote_extra=_quote_extra, time_horizon=_time_horizon, market_snapshot=_market_snap)
                if quote.price:
                    trend_result.current_price = quote.price
                # === P4-3: 资金面连续性检测（基于历史分析记录） ===
                try:
                    recent_analyses = self.storage.get_recent_analysis(code, days=5)
                    if len(recent_analyses) >= 3:
                        cf_scores = [r.get('capital_flow_score', 5) for r in recent_analyses[:3]]
                        if all(s >= 7 for s in cf_scores):
                            trend_result.signal_score = min(100, trend_result.signal_score + 2)
                            trend_result.score_breakdown['cf_continuity'] = 2
                            cf_note = "连续3日资金持续流入"
                            if trend_result.capital_flow_signal and trend_result.capital_flow_signal != "资金面数据正常":
                                trend_result.capital_flow_signal += f"；{cf_note}"
                            else:
                                trend_result.capital_flow_signal = cf_note
                            ScoringSystem.update_buy_signal(trend_result)
                            logger.info(f"[{code}] 资金面连续性: 近3日持续流入(scores={cf_scores}), +2")
                        elif all(s <= 3 for s in cf_scores):
                            trend_result.signal_score = max(0, trend_result.signal_score - 2)
                            trend_result.score_breakdown['cf_continuity'] = -2
                            cf_note = "连续3日资金持续流出"
                            if trend_result.capital_flow_signal and trend_result.capital_flow_signal != "资金面数据正常":
                                trend_result.capital_flow_signal += f"；{cf_note}"
                            else:
                                trend_result.capital_flow_signal = cf_note
                            ScoringSystem.update_buy_signal(trend_result)
                            logger.info(f"[{code}] 资金面连续性: 近3日持续流出(scores={cf_scores}), -2")
                except Exception as e:
                    logger.debug(f"[{code}] 资金面连续性检测跳过: {e}")
                tech_report = self.trend_analyzer.format_analysis(trend_result)
                tech_report_llm = self.trend_analyzer.format_for_llm(trend_result)
                trend_analysis_dict = trend_result.to_dict()
                trend_analysis_dict['market_regime'] = regime.value
                # 从量化结果回填板块数据（量化分析可能丰富了板块信息）
                if not sector_context or not (sector_context.sector_name if isinstance(sector_context, SectorContext) else sector_context.get('sector_name')):
                    if trend_analysis_dict.get('sector_name'):
                        sector_context = SectorContext(
                            sector_name=trend_analysis_dict.get('sector_name', ''),
                            sector_pct=trend_analysis_dict.get('sector_pct', 0),
                            relative=trend_analysis_dict.get('sector_relative', 0),
                        )
            except Exception as e:
                logger.error(f"[{code}] 技术分析生成失败: {e}")

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
            'chip': chip_data.to_dict() if hasattr(chip_data, 'to_dict') else chip_data,
            'chip_note': chip_note,
            'technical_analysis_report': tech_report,
            'technical_analysis_report_llm': tech_report_llm,
            'trend_analysis': trend_analysis_dict,
            'fundamental': fundamental_data.to_dict(),
            'history_summary': history_summary,
            'sector_context': sector_context.to_dict() if isinstance(sector_context, SectorContext) else sector_context,
            'is_intraday': is_market_intraday(),
            'market_phase': get_market_phase(),
            'analysis_time': datetime.now().strftime('%H:%M'),
        }
        context = self._enhance_context(context)
        return context

    def _enhance_context(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """增强 context：注入评分趋势+拐点检测 + 分时数据"""
        code = context.get('code', '')
        if not code:
            return context

        # 评分趋势+拐点
        try:
            score_trend = self.storage.get_score_trend(code, days=10)
            context['score_trend'] = score_trend
        except Exception as e:
            logger.debug(f"[{code}] 评分趋势获取失败: {e}")

        # 分时数据（仅盘中时获取，避免不必要的请求）
        if is_market_intraday():
            try:
                from data_provider.intraday_fetcher import analyze_intraday
                intraday = analyze_intraday(code, period="5")
                if intraday.get('available'):
                    context['intraday_analysis'] = intraday
            except Exception as e:
                logger.debug(f"[{code}] 分时数据获取失败: {e}")

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
        position_info: Optional[Dict[str, Any]] = None,
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
            # 第 3 层: Perplexity 实时搜索 (仅量价异常时触发，不再无条件调用)
            search_content = ""
            used_news_cache = False
            news_source = ""
            has_important_news = False   # 是否含有实质性重要公告
            fast_mode = getattr(self.config, 'fast_mode', False)

            # 层 1: Akshare 免费新闻（后台已抓取入库，含公告数据）
            akshare_news = self._get_cached_news_context(
                code, stock_name, hours=24, limit=10, provider='akshare', min_count=2
            )
            if akshare_news:
                search_content = akshare_news
                used_news_cache = True
                news_source = "akshare"
                # [fix3] 检测是否含实质性重要公告（高管增减持/业绩预告/监管函）
                has_important_news = "【重要公告】" in akshare_news
                if has_important_news:
                    logger.info(f"� [{stock_name}] 命中重要公告，将使用重量级模型分析")
                else:
                    logger.info(f"� [{stock_name}] 命中 Akshare 新闻缓存，跳过外部搜索")

            # 层 2: Perplexity 缓存（之前搜索过的结果）
            if not search_content:
                pplx_cache = self._get_cached_news_context(
                    code, stock_name, hours=6, limit=5, provider='perplexity'
                )
                if pplx_cache:
                    search_content = pplx_cache
                    used_news_cache = True
                    news_source = "perplexity_cache"
                    has_important_news = True  # Perplexity 内容视为实质性
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

            # [fix5] 量价异常检测：仅在涨停/跌停/成交量>2倍均量时触发 Perplexity
            _price_anomaly = False
            try:
                _today = context.get('today', {})
                _realtime = context.get('realtime', {})
                _pct_chg = float(_today.get('pct_chg') or _realtime.get('change_pct') or 0)
                _vol_today = float(_today.get('volume') or 0)
                # 用最近5日均量（从 trend_analysis 获取，降级到0）
                _trend_d = context.get('trend_analysis', {}) or {}
                _avg_vol_5d = float(_trend_d.get('avg_volume_5d') or _trend_d.get('volume_5d_avg') or 0)
                _vol_ratio = _vol_today / _avg_vol_5d if _avg_vol_5d > 0 else 0
                if abs(_pct_chg) >= 9.0 or _vol_ratio >= 2.0:
                    _price_anomaly = True
                    logger.info(
                        f"⚡ [{stock_name}] 量价异常检测: 涨跌幅{_pct_chg:+.1f}%, 量比{_vol_ratio:.1f}x → 允许 Perplexity"
                    )
            except Exception:
                pass

            # 层 3: Perplexity 实时搜索（仅量价异常或无任何缓存时触发）
            if not search_content and not fast_mode and self.search_service and _price_anomaly:
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
                                per_stock_qid = f"{self.query_id}_{code}" if self.query_id else None
                                self.storage.save_news_intel(
                                    code, stock_name, dimension="舆情", query=query, response=resp,
                                    query_context={"query_id": per_stock_qid, "query_source": self.query_source}
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

            # 改进7: 新闻时效性标注 - 在舆情内容前标注来源和时效
            if search_content and used_news_cache:
                timeliness_map = {
                    "akshare": "⏰ 以下新闻来自Akshare免费源(24h缓存)，可能非最新",
                    "perplexity_cache": "⏰ 以下新闻来自Perplexity缓存(6h内)，注意时效",
                    "cache_legacy": "⏰ 以下新闻来自历史缓存(6h内)，注意时效",
                }
                timeliness_note = timeliness_map.get(news_source, "")
                if timeliness_note:
                    search_content = f"{timeliness_note}\n\n{search_content}"

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
            # [fix3] 模型选择策略：
            # - 有重要公告（减持/业绩预告）或量价异常 → 重量级模型，深度分析
            # - 纯行业通稿 / 无新闻 / 普通缓存 → 轻量模型，节省成本
            use_light = not has_important_news and (used_news_cache or not search_content or not search_content.strip())
            if has_important_news:
                logger.info(f"🔬 [{stock_name}] 含重要公告，使用重量级模型深度分析")
            elif _price_anomaly:
                use_light = False
                logger.info(f"🔬 [{stock_name}] 量价异常，使用重量级模型深度分析")
            # === 3. 执行分析（带超时，默认 180 秒）===
            analysis_timeout = getattr(self.config, 'analysis_timeout_seconds', 180) or 180
            def _run_analyze():
                return self.analyzer.analyze(
                    context=context,
                    news_context=search_content,
                    role="trader",
                    market_overview=market_overview,
                    use_light_model=use_light,
                    position_info=position_info,
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

                # === 评分惯性因子：基于历史评分连续性修正 ===
                _score_trend = context.get('score_trend') or {}
                _cons_up = _score_trend.get('consecutive_up', 0)
                _cons_down = _score_trend.get('consecutive_down', 0)
                _inflection = _score_trend.get('inflection', '')
                _momentum_adj = 0

                if _cons_up >= 3:
                    _momentum_adj = 5      # 连续3+次上升：强势惯性
                elif _cons_up >= 2:
                    _momentum_adj = 3      # 连续2次上升：温和惯性
                elif _cons_down >= 3:
                    _momentum_adj = -5     # 连续3+次下降：弱势惯性
                elif _cons_down >= 2:
                    _momentum_adj = -3     # 连续2次下降：温和弱势

                # 拐点信号削弱惯性（趋势反转初期，不应延续旧惯性）
                if _inflection:
                    _momentum_adj = int(_momentum_adj * 0.3)

                if _momentum_adj != 0:
                    _old_score = result.sentiment_score
                    result.sentiment_score = max(0, min(100, result.sentiment_score + _momentum_adj))
                    # 同步更新 quant_score 变量（后续防守模式判定用）
                    quant_score = result.sentiment_score
                    logger.info(f"[{code}] 评分惯性因子: {_old_score} → {result.sentiment_score} "
                                f"(adj={_momentum_adj:+d}, 连升{_cons_up}/连降{_cons_down}, 拐点={_inflection or '无'})")
                    dashboard['score_momentum_adj'] = _momentum_adj

                # 新量化字段注入 dashboard（供 notification 渲染）
                # trend 本身就是 TrendAnalysisResult.to_dict() 的输出，直接复用
                dashboard['quant_extras'] = trend

                # 生成统一持仓者策略（供 PushPlus / Web / API 共用）
                # trend 是 dict（来自 _prepare_stock_context 中 trend_result.to_dict()），
                # generate_holding_strategy 需要属性访问，用 SimpleNamespace 包装
                from types import SimpleNamespace
                from src.stock_analyzer.risk_management import RiskManager as _RM
                _trend_obj = SimpleNamespace(**trend)
                _user_cost = float(position_info.get('cost_price', 0) or 0) if position_info else 0.0
                dashboard['holding_strategy'] = _RM.generate_holding_strategy(
                    _trend_obj, cost_price=_user_cost,
                )

                # === 场景识别+操作建议（generate_trade_advice）===
                # 需要真实的TrendAnalysisResult对象，从_prepare_stock_context中取
                _trend_result_obj = context.get('trend_result')
                if _trend_result_obj is not None:
                    _RM.generate_trade_advice(_trend_result_obj, position_info=position_info)
                    dashboard['trade_advice'] = {
                        'scenario_id':        _trend_result_obj.scenario_id,
                        'scenario_label':     _trend_result_obj.scenario_label,
                        'scenario_confidence': _trend_result_obj.scenario_confidence,
                        'expected_20d':       _trend_result_obj.scenario_expected_20d,
                        'win_rate':           _trend_result_obj.scenario_win_rate,
                        'advice_empty':       _trend_result_obj.trade_advice_empty,
                        'advice_holding':     _trend_result_obj.trade_advice_holding,
                        'position_pct':       _trend_result_obj.trade_advice_position_pct,
                        'turnover_percentile_confidence': getattr(_trend_result_obj, 'turnover_percentile_confidence', ''),
                        'turnover_percentile': getattr(_trend_result_obj, 'turnover_percentile', 0.5),
                    }

                # === 防守模式判定（复合条件） ===
                _qs = int(quant_score) if quant_score is not None else 50
                _as = result.llm_score if result.llm_score is not None else 50
                _ts = trend.get('trend_status', '')
                _sc = getattr(result, 'score_change', None) or 0
                _defense = (
                    (_qs < 50 and _as < 50)                           # 双引擎共识偏空
                    or _qs < 35                                        # 极弱信号
                    or (_ts in ('BEAR', 'STRONG_BEAR', 'bear', 'strong_bear') and _sc <= -10)  # 趋势恶化+评分骤降
                )
                dashboard['defense_mode'] = _defense
                result.dashboard = dashboard

                # 决策类型
                advice = result.operation_advice
                if '买' in advice or '加仓' in advice:
                    result.decision_type = 'buy'
                elif '卖' in advice or '减仓' in advice:
                    result.decision_type = 'sell'
                else:
                    result.decision_type = 'hold'

            # === 改进1: 今日变化对比 ===
            history = context.get('history_summary')
            if history and isinstance(history, dict) and history.get('score') is not None:
                result.is_first_analysis = False
                result.prev_score = history['score']
                result.score_change = result.sentiment_score - history['score']
                result.prev_advice = history.get('advice', '')
                result.prev_trend = history.get('trend', '')
                # 检测关键信号变化
                changes = []
                prev_signals = history.get('signals', {})
                curr_trend = context.get('trend_analysis', {})
                if prev_signals and curr_trend:
                    signal_pairs = [
                        ('trend_status', '趋势'),
                        ('macd_status', 'MACD'),
                        ('kdj_status', 'KDJ'),
                        ('rsi_status', 'RSI'),
                        ('volume_status', '量能'),
                        ('buy_signal', '信号'),
                    ]
                    for key, label in signal_pairs:
                        old_val = prev_signals.get(key, '')
                        new_val = curr_trend.get(key, '')
                        if old_val and new_val and old_val != new_val:
                            changes.append(f"{label}: {old_val}→{new_val}")
                # 评分变化也作为信号
                if result.score_change is not None and abs(result.score_change) >= 5:
                    arrow = '⬆️' if result.score_change > 0 else '⬇️'
                    changes.insert(0, f"{arrow}评分{result.prev_score}→{result.sentiment_score}({result.score_change:+d})")
                # 操作建议变化
                if result.prev_advice and result.operation_advice != result.prev_advice:
                    changes.append(f"建议: {result.prev_advice}→{result.operation_advice}")
                result.signal_changes = changes
            else:
                result.is_first_analysis = True

            # === 改进6: 量化 vs AI 分歧高亮 ===
            if result.llm_score is not None and result.sentiment_score is not None:
                divergence = abs(result.sentiment_score - result.llm_score)
                result.quant_ai_divergence = divergence
                if divergence >= 20:
                    q_label = f"量化{result.sentiment_score}分"
                    a_label = f"AI{result.llm_score}分"
                    q_dir = "看多" if result.sentiment_score >= 60 else ("看空" if result.sentiment_score <= 40 else "中性")
                    a_dir = "看多" if result.llm_score >= 60 else ("看空" if result.llm_score <= 40 else "中性")
                    result.divergence_alert = f"⚠️ 量化与AI严重分歧: {q_label}({q_dir}) vs {a_label}({a_dir})"
                    if result.llm_reasoning:
                        result.divergence_alert += f" | AI理由: {result.llm_reasoning[:60]}"
                elif divergence >= 15:
                    result.divergence_alert = f"📊 量化({result.sentiment_score}) vs AI({result.llm_score}) 存在分歧({divergence}分)"

            # === 改进3: 具体手数建议 ===
            portfolio_size = getattr(self.config, 'portfolio_size', 0) or 0
            if portfolio_size > 0 and result.current_price > 0:
                pct = 0
                if trend and isinstance(trend, dict):
                    pct = trend.get('suggested_position_pct', 0) or 0
                if pct > 0:
                    amount = portfolio_size * pct / 100
                    shares = int(amount / result.current_price / 100) * 100  # A股最小100股
                    if shares >= 100:
                        result.concrete_position = f"建议买入{shares}股(约{shares * result.current_price:.0f}元，占总资金{pct}%，总资金{portfolio_size/10000:.1f}万)"
                    else:
                        result.concrete_position = f"建议仓位{pct}%，但单价较高，最少需{100 * result.current_price:.0f}元买1手"

            # 注入当日行情快照到 dashboard（供 Web API 传给前端）
            today_kline = context.get('today', {})
            if today_kline:
                dashboard = getattr(result, 'dashboard', None) or {}
                dashboard['today_kline'] = today_kline
                result.dashboard = dashboard

            # 注入用户持仓信息到 dashboard，供前端计算盈亏
            if position_info:
                dashboard = getattr(result, 'dashboard', None) or {}
                dashboard['position_info'] = position_info

                # === 仓位精确化建议 ===
                _total_cap = float(position_info.get('total_capital', 0) or 0)
                _pos_amt = float(position_info.get('position_amount', 0) or 0)
                _trend = context.get('trend_analysis', {})
                _suggested_pct = _trend.get('suggested_position_pct', 0) if isinstance(_trend, dict) else 0
                _actual_pct = (_pos_amt / _total_cap * 100) if _total_cap > 0 and _pos_amt > 0 else None

                pos_diag = {
                    'actual_pct': round(_actual_pct, 1) if _actual_pct is not None else None,
                    'suggested_pct': _suggested_pct,
                    'action': None,       # "加仓" / "减仓" / "清仓" / "维持"
                    'delta_pct': None,    # 需要调整的百分比
                    'reason': '',
                }
                if _actual_pct is not None and _suggested_pct is not None:
                    if _suggested_pct == 0:
                        pos_diag['action'] = '清仓'
                        pos_diag['delta_pct'] = round(-_actual_pct, 1)
                        pos_diag['reason'] = '量化建议不宜持有'
                    elif _actual_pct > _suggested_pct * 1.5:
                        pos_diag['action'] = '减仓'
                        pos_diag['delta_pct'] = round(_suggested_pct - _actual_pct, 1)
                        pos_diag['reason'] = f'当前{_actual_pct:.1f}%超出建议{_suggested_pct}%的1.5倍'
                    elif _actual_pct < _suggested_pct * 0.5 and _suggested_pct > 0:
                        pos_diag['action'] = '加仓'
                        pos_diag['delta_pct'] = round(_suggested_pct - _actual_pct, 1)
                        pos_diag['reason'] = f'当前{_actual_pct:.1f}%低于建议{_suggested_pct}%的一半'
                    else:
                        pos_diag['action'] = '维持'
                        pos_diag['delta_pct'] = 0
                        pos_diag['reason'] = '仓位在合理范围内'

                dashboard['position_diagnosis'] = pos_diag
                result.dashboard = dashboard

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
                    report = self.notifier.generate_dashboard_report([result], position_info=position_info)
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
            # 改进5: 附加组合分析报告
            portfolio_text = getattr(self, '_portfolio_report_text', '')
            if portfolio_text:
                daily_report = daily_report + "\n\n" + portfolio_text
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

        # 5. 评分离散度检查（全部评分接近说明分析可能趋同）
        all_scores = [r.sentiment_score for r in results]
        if len(all_scores) >= 3:
            avg = sum(all_scores) / len(all_scores)
            max_diff = max(all_scores) - min(all_scores)
            if max_diff <= 10:
                warnings.append(
                    f"📊 评分趋同提醒: {total}只股票评分极差仅{max_diff}分（均值{avg:.0f}），"
                    f"可能存在分析趋同，建议关注个股差异化因素"
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

        # === Q1: 评分自适应校准 - 百分位排名 ===
        if len(results) >= 2:
            scores = sorted([r.sentiment_score for r in results], reverse=True)
            total = len(scores)
            for r in results:
                rank_pos = scores.index(r.sentiment_score) + 1
                percentile = (1 - (rank_pos - 1) / total) * 100
                r.score_percentile = round(percentile, 1)
                r.score_rank = f"第{rank_pos}/{total}，前{percentile:.0f}%"
                # 校准说明
                avg_score = sum(scores) / total
                if avg_score >= 70:
                    r.score_calibration_note = f"今日均分{avg_score:.0f}(偏高)，{r.sentiment_score}分仅为{'中等' if r.sentiment_score < avg_score + 5 else '突出'}水平"
                elif avg_score <= 40:
                    r.score_calibration_note = f"今日均分{avg_score:.0f}(偏低)，{r.sentiment_score}分已属{'较强' if r.sentiment_score > avg_score else '一般'}"

        # === Q9: 评分短板/优势分析 ===
        for r in results:
            trend_data = {}
            if r.dashboard and isinstance(r.dashboard, dict):
                trend_data = r.dashboard.get('quant_extras', {}) or {}
            breakdown = trend_data.get('score_breakdown', {})
            if breakdown:
                # 找短板：得分率最低的维度
                dim_labels = {'trend': '趋势', 'bias': '乖离', 'volume': '量能', 'support': '支撑', 'macd': 'MACD', 'rsi': 'RSI', 'kdj': 'KDJ'}
                base_dims = {k: breakdown.get(k, 0) for k in dim_labels if k in breakdown}
                if base_dims:
                    # 用各维度的权重来计算得分率
                    from src.stock_analyzer.scoring import ScoringSystem
                    default_w = ScoringSystem.REGIME_WEIGHTS.get(MarketRegime.SIDEWAYS, {})
                    dim_rates = {}
                    for k, v in base_dims.items():
                        max_w = default_w.get(k, 10)
                        if max_w > 0:
                            dim_rates[k] = v / max_w
                    if dim_rates:
                        weakest = min(dim_rates, key=dim_rates.get)
                        strongest = max(dim_rates, key=dim_rates.get)
                        w_rate = dim_rates[weakest]
                        s_rate = dim_rates[strongest]
                        r.score_weakness = f"{dim_labels.get(weakest, weakest)}({base_dims[weakest]}/{default_w.get(weakest, '?')})得分率{w_rate:.0%}，是主要短板"
                        r.score_strength = f"{dim_labels.get(strongest, strongest)}({base_dims[strongest]}/{default_w.get(strongest, '?')})得分率{s_rate:.0%}，是主要优势"

        # === 改进5: 持仓组合分析 ===
        if len(results) >= 2:
            try:
                from src.portfolio_analyzer import PortfolioAnalyzer
                portfolio_size = getattr(self.config, 'portfolio_size', 0) or 0
                portfolio_report = PortfolioAnalyzer.analyze(results, portfolio_size)
                portfolio_text = PortfolioAnalyzer.format_report(portfolio_report, portfolio_size)
                logger.info(f"📋 组合分析完成:\n{portfolio_text}")
                # 将组合报告注入最后一只股票的 risk_warning（或独立推送）
                # 这里选择在汇总推送中附加
                self._portfolio_report_text = portfolio_text
            except Exception as e:
                logger.debug(f"组合分析跳过: {e}")
                self._portfolio_report_text = ""
        else:
            self._portfolio_report_text = ""

        # === 改进2: 盘中预警监控（自动注册规则） ===
        if getattr(self.config, 'enable_alert_monitor', False) and results:
            try:
                from src.alert_monitor import AlertMonitor
                monitor = AlertMonitor(config=self.config)
                monitor.add_rules_from_analysis(results)
                interval = getattr(self.config, 'alert_interval_seconds', 300)
                logger.info(f"📢 盘中预警已注册 {len(monitor.rules)} 只股票，间隔{interval}s")
                # 非阻塞启动（在独立线程中运行）
                import threading
                t = threading.Thread(
                    target=monitor.run_loop,
                    kwargs={
                        'fetcher_manager': self.fetcher_manager,
                        'notifier': self.notifier,
                        'interval_seconds': interval,
                    },
                    daemon=True,
                    name="AlertMonitor"
                )
                t.start()
            except Exception as e:
                logger.debug(f"预警监控启动跳过: {e}")

        # 汇总推送 (如果没开单股推送) — 过滤掉分析失败的结果
        successful_results = [r for r in results if getattr(r, 'success', True)]
        if successful_results and send_notification and not dry_run and not single_stock_notify:
            self._send_notifications(successful_results)
            if len(successful_results) < len(results):
                failed_count = len(results) - len(successful_results)
                logger.warning(f"📊 推送报告已过滤 {failed_count} 只分析失败的股票")
            
        return results