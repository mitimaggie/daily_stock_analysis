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

# 全局标记：防止多个 pipeline 实例同时启动 shareholder 预热线程（libmini_racer 不支持并发）
import threading as _threading
_shareholder_warmup_lock = _threading.Lock()
_shareholder_warmup_done = _threading.Event()

# 宏观情报内存缓存：防止多个并发 pipeline 实例同时触发 Perplexity（thundering herd）
# TTL=1800s(30min)，超过则重新拉取
_macro_intel_mem_cache: dict = {'data': None, 'ts': 0.0}
_macro_intel_mem_lock = _threading.Lock()

class StockAnalysisPipeline:
    """
    股票分析流水线 (最终完整修复版)
    适配 main.py 的 config 传参调用方式，包含两阶段执行和防封号逻辑
    """
    def __init__(self, config, max_workers=1, query_id=None, query_source="cli", save_context_snapshot=True, source_message=None, **kwargs):
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

        # 搜索服务启用时，确保并发不超过 2（防 Perplexity 429）
        if has_search_key:
            self.max_workers = min(max_workers, 2)
            logger.info(f"🕵️  [深度模式] 搜索服务已启用，并发限制为: {self.max_workers}")
        else:
            self.max_workers = max_workers
            logger.info(f"🚀 [模式] 并发数: {self.max_workers}（默认1=串行/防封禁，需提速请用 --workers N）")

        # 大盘监控：用于个股分析时的「仓位上限/前置滤网」（大盘定仓位，个股定方向）
        self._market_monitor = market_monitor
        if self._market_monitor:
            logger.info("📊 [大盘监控] 已启用，个股分析将注入大盘环境作为前置滤网")
        else:
            logger.warning("📊 [大盘监控] 未加载，个股分析将不注入大盘环境（请检查 data_provider.market_monitor 与 akshare）")

        # P3: 后台预热 shareholder_fetcher 增减持缓存，避免首次分析延迟
        # 使用全局锁确保只有一个线程执行（libmini_racer 不支持并发，多 pipeline 并发时会崩溃）
        if not _shareholder_warmup_done.is_set() and _shareholder_warmup_lock.acquire(blocking=False):
            try:
                import threading
                from data_provider.shareholder_fetcher import _refresh_insider_cache

                def _warmup_with_flag():
                    try:
                        _refresh_insider_cache()
                    finally:
                        _shareholder_warmup_done.set()
                        _shareholder_warmup_lock.release()

                _warmup_thread = threading.Thread(target=_warmup_with_flag, daemon=True, name="shareholder-warmup")
                _warmup_thread.start()
                logger.info("🔄 [股东数据] 后台预热线程已启动（增减持全量缓存）")
            except Exception as _warm_e:
                _shareholder_warmup_lock.release()
                logger.debug(f"[股东数据] 后台预热跳过: {_warm_e}")
        else:
            logger.debug("🔄 [股东数据] 预热已在执行中，跳过重复启动")

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

    @staticmethod
    def _score_skills(context: dict) -> dict:
        """
        Skills 评分模型：为三个A股特有框架各打分(0-10)，返回主副框架推荐。
        A股驱动顺序：政策 > 流动性 > 资金面 > 基本面（与美股相反）

        框架说明：
          policy_tailwind      - 政策顺风框架：板块是否处于政策明确支持期
          northbound_smart     - 北向聪明钱框架：外资方向 vs 国内散户情绪背离
          ashare_growth_value  - A股成长价值框架：A股溢价修正后的PEG + 成长性验证

        Returns:
            {
              'primary': str,           # 主框架 skill name 或 'default'
              'secondary': str|None,    # 副框架 skill name 或 None
              'primary_score': int,     # 主框架得分
              'secondary_score': int,   # 副框架得分（0=无副框架）
              'scores': dict,           # {policy_tailwind: x, northbound_smart: x, ashare_growth_value: x}
              'convergent': bool,       # True=双框架同向（增强模式），False=分歧（压力测试模式）
            }
        """
        try:
            trend = context.get('trend_analysis') or {}
            regime = trend.get('market_regime', 'sideways')

            sec = context.get('sector_context') or {}
            sector_5d = sec.get('sector_5d_pct')
            sector_name = sec.get('sector_name', '')

            f10 = context.get('fundamental') or {}
            fin = f10.get('financial') or {}
            val = f10.get('valuation') or {}
            growth_rev = fin.get('revenue_growth')
            growth_net = fin.get('net_profit_growth')
            pe = val.get('pe')
            peg = val.get('peg')
            total_mv = val.get('total_mv')  # 万元
            industry_pe = val.get('industry_pe_median')

            north = context.get('northbound_holding') or {}
            north_pct = north.get('holding_pct_a', 0) or 0
            north_chg = north.get('shares_change', 0) or 0

            news_intel = context.get('news_intel') or {}
            news_text = str(news_intel.get('summary') or news_intel.get('content') or '')

            daily_df = context.get('daily_df')

            # ── 政策顺风框架 (policy_tailwind) ─────────────────────
            # A股是政策市：政策支持期 → 可放宽仓位；政策收紧期 → 无论技术面多好都减仓
            p_score = 0
            _policy_support_kw = {'政策支持', '专项债', '补贴', '工信部', '发改委', '国家队', '央企', '国家战略',
                                   '产业政策', '重点支持', '财政补贴', '政策红利', '利好政策', '两会'}
            _policy_restrict_kw = {'监管收紧', '整顿', '反垄断', '防止资本', '整改', '处罚', '罚款', '调查',
                                    '违规', '暂停', '禁止', '叫停', '清查'}
            has_policy_support = any(kw in news_text for kw in _policy_support_kw)
            has_policy_restrict = any(kw in news_text for kw in _policy_restrict_kw)
            if has_policy_support and not has_policy_restrict:
                p_score += 4
            elif has_policy_support and has_policy_restrict:
                p_score += 1
            _policy_sectors = {'半导体', '人工智能', 'AI', '机器人', '新能源', '光伏', '储能', '军工',
                                '航天', '北斗', '信创', '国产替代', '大数据', '数字经济', '碳中和',
                                '核电', '高端装备', '专精特新'}
            if any(s in sector_name for s in _policy_sectors):
                p_score += 3
            if isinstance(sector_5d, (int, float)) and sector_5d >= 5:
                p_score += 2  # 板块强势，可能有政策催化
            if regime in ('bull', 'recovery'):
                p_score += 1
            p_score = min(p_score, 10)

            # ── 北向聪明钱框架 (northbound_smart) ──────────────────
            # 外资是最好的"聪明钱"代理：外资增持+国内看空=逆向做多；外资减持+国内看多=警惕出货
            n_score = 0
            if isinstance(north_pct, (int, float)) and north_pct >= 2.0:
                n_score += 3  # 外资持股占比≥2%，有明显表态
            elif isinstance(north_pct, (int, float)) and north_pct >= 1.0:
                n_score += 1
            if isinstance(north_chg, (int, float)):
                if north_chg > 0:
                    n_score += 3  # 外资净增持
                elif north_chg < 0:
                    n_score -= 2  # 外资净减持，降分
            _bluechip_sectors = {'银行', '证券', '保险', '白酒', '消费', '医药', '食品饮料', '家电', '新能源车'}
            if any(s in sector_name for s in _bluechip_sectors):
                n_score += 2  # 外资偏好板块
            if daily_df is not None and len(daily_df) >= 20:
                try:
                    ret_20d = (daily_df['close'].iloc[-1] / daily_df['close'].iloc[-20] - 1) * 100
                    if north_chg > 0 and ret_20d < -10:
                        n_score += 2  # 外资在股价下跌时加仓=高置信逆向信号
                except Exception:
                    pass
            n_score = max(0, min(n_score, 10))

            # ── A股成长价值框架 (ashare_growth_value) ──────────────
            # A股对成长股有30-50%溢价（流动性溢价+散户资金），PEG阈值修正为1.5
            g_score = 0
            rev = growth_rev if isinstance(growth_rev, (int, float)) else growth_net
            if isinstance(rev, (int, float)) and rev > 25:
                g_score += 3  # 净利润/营收增速>25%，成长性明确
            elif isinstance(rev, (int, float)) and rev > 15:
                g_score += 1
            if isinstance(total_mv, (int, float)) and total_mv > 0:
                mv_bn = total_mv / 10000  # 转为亿元
                if mv_bn < 50:
                    g_score += 3  # 小市值，成长空间大
                elif mv_bn < 150:
                    g_score += 2
            if isinstance(peg, (int, float)) and 0 < peg < 1.5:
                g_score += 2  # A股修正PEG阈值1.5（非美股的1.0）
            if isinstance(pe, (int, float)) and isinstance(industry_pe, (int, float)) and industry_pe > 0:
                rel_pe = pe / industry_pe
                if 0.7 < rel_pe < 1.2:
                    g_score += 1  # 估值相对合理（不过贵也不过便宜）
            if isinstance(north_pct, (int, float)) and 0 <= north_pct < 1.5:
                g_score += 1  # 外资持仓低=未被充分发现，成长股早期特征
            g_score = min(g_score, 10)

            scores = {'policy_tailwind': p_score, 'northbound_smart': n_score, 'ashare_growth_value': g_score}

            # 主框架：最高分且≥5
            ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
            primary, primary_score = ranked[0]
            if primary_score < 5:
                return {
                    'primary': 'default', 'secondary': None,
                    'primary_score': 0, 'secondary_score': 0,
                    'scores': scores, 'convergent': False,
                }

            # 副框架：第二高分且≥5
            secondary, secondary_score = ranked[1]
            has_secondary = secondary_score >= 5

            # 收敛性判断（两个框架是否指向同一交易方向）
            # policy_tailwind + northbound_smart = A股最强收敛（政策+外资双确认）
            # policy_tailwind + ashare_growth_value = 收敛（政策催化+成长双确认）
            # northbound_smart + ashare_growth_value = 分歧（外资聪明钱逻辑 vs 散户成长逻辑可能冲突）
            convergent = False
            if has_secondary:
                _converge_pairs = {
                    ('policy_tailwind', 'northbound_smart'),
                    ('northbound_smart', 'policy_tailwind'),
                    ('policy_tailwind', 'ashare_growth_value'),
                    ('ashare_growth_value', 'policy_tailwind'),
                }
                convergent = (primary, secondary) in _converge_pairs

            return {
                'primary': primary,
                'secondary': secondary if has_secondary else None,
                'primary_score': primary_score,
                'secondary_score': secondary_score if has_secondary else 0,
                'scores': scores,
                'convergent': convergent,
            }
        except Exception:
            pass
        return {'primary': 'default', 'secondary': None, 'primary_score': 0, 'secondary_score': 0, 'scores': {}, 'convergent': False}

    @staticmethod
    def _select_skill(context: dict) -> str:
        """向后兼容包装，调用评分模型返回主框架名称"""
        return Pipeline._score_skills(context)['primary']

    @staticmethod
    def _detect_scene(context: dict, position_info: Optional[Dict[str, Any]] = None) -> str:
        """
        检测当前分析场景，决定 Flash/Pro 使用哪套角色和问题框架。

        场景优先级（从高到低）：
          crisis > profit_take > post_mortem > entry > holding
        """
        try:
            has_position = bool(position_info and any(
                position_info.get(k) for k in ('cost_price', 'position_amount', 'total_capital')
            ))
            if not has_position:
                return 'entry'

            cost_price = float(position_info.get('cost_price') or 0)
            current_price = float(context.get('price') or 0)

            pnl_pct = 0.0
            if cost_price > 0 and current_price > 0:
                pnl_pct = (current_price - cost_price) / cost_price * 100

            # post_mortem：有止损退出日志（通过 context 标记）
            if context.get('_scene_override') == 'post_mortem':
                return 'post_mortem'

            # crisis：止损触发 or 当日大幅下跌（需要盘中数据支持）
            intraday = context.get('intraday_analysis') or {}
            intraday_chg = intraday.get('price_change_pct', 0) or 0
            atr_stop = position_info.get('atr_stop') or 0
            if (
                (isinstance(intraday_chg, (int, float)) and intraday_chg < -7)
                or (atr_stop > 0 and current_price > 0 and current_price < atr_stop)
            ):
                return 'crisis'

            # profit_take：浮盈 > 15% 或超过目标价
            target_price = float(position_info.get('target_price') or 0)
            if pnl_pct >= 15 or (target_price > 0 and current_price >= target_price * 0.9):
                return 'profit_take'

            return 'holding'
        except Exception:
            pass
        return 'holding'

    @staticmethod
    def _build_profit_take_plan(context: dict, position_info: dict) -> Optional[dict]:
        """
        分阶段止盈退出计划（profit_take 场景专用）。

        输入数据（全部从 context 和 position_info 取，无外部 API 调用）：
          - cost_price, current_price, target_price, atr_stop, highest_price, atr
          - daily_df → 计算 ATR（若 position_info 未提供）
          - trend_analysis → short/mid resistance levels

        退出计划三阶段：
          Stage 1 (1/3 仓位): 第一个关键压力位或 +1*ATR，设时间限制（5个交易日内）
          Stage 2 (1/3 仓位): 第二个关键压力位或 +2.5*ATR
          Stage 3 (底仓 1/3): ATR追踪止损 — 用 highest_price - 1.5*ATR 保护浮盈

        Returns:
            None if cost_price or price missing, else dict with staged exit levels
        """
        try:
            cost_price = float(position_info.get('cost_price') or 0)
            current_price = float(context.get('price') or 0)
            if cost_price <= 0 or current_price <= 0:
                return None

            pnl_pct = (current_price - cost_price) / cost_price * 100
            target_price = float(position_info.get('target_price') or 0)

            # ── ATR 值获取（三层降级）────────────────────────────────────────
            atr_val = float(position_info.get('atr') or 0)
            if atr_val <= 0:
                # 从 daily_df 计算14日ATR
                daily_df = context.get('daily_df')
                try:
                    import pandas as pd
                    if daily_df is not None and hasattr(daily_df, '__len__') and len(daily_df) >= 14:
                        df = daily_df.tail(20).copy()
                        df['tr'] = pd.concat([
                            df['high'] - df['low'],
                            (df['high'] - df['close'].shift(1)).abs(),
                            (df['low'] - df['close'].shift(1)).abs(),
                        ], axis=1).max(axis=1)
                        atr_val = float(df['tr'].tail(14).mean())
                except Exception:
                    pass
            if atr_val <= 0:
                # 最终降级：用1.5%作为ATR估算（蓝筹）
                atr_val = current_price * 0.015

            # ── 关键压力位（从 trend_analysis 提取）──────────────────────────
            trend = context.get('trend_analysis') or {}
            take_profit_short = float(trend.get('take_profit_short') or 0)
            take_profit_mid = float(trend.get('take_profit_mid') or 0)
            # 也接受来自 position_info 的目标价
            if target_price > current_price:
                take_profit_mid = take_profit_mid or target_price

            # ── 三阶段止盈价位计算 ────────────────────────────────────────────
            # Stage 1: 优先用量化压力位，否则用 +1*ATR
            stage1_price = take_profit_short if take_profit_short > current_price else round(current_price + atr_val, 2)
            stage1_pct = round((stage1_price - cost_price) / cost_price * 100, 1)

            # Stage 2: 优先用中期压力位，否则用 +2.5*ATR
            stage2_price = take_profit_mid if (take_profit_mid > stage1_price) else round(current_price + 2.5 * atr_val, 2)
            stage2_pct = round((stage2_price - cost_price) / cost_price * 100, 1)

            # Stage 3: ATR追踪止损（以最高价为基准）
            highest_price = float(position_info.get('highest_price') or current_price)
            atr_stop_existing = float(position_info.get('atr_stop') or 0)
            stage3_trailing = atr_stop_existing if atr_stop_existing > 0 else round(highest_price - 1.5 * atr_val, 2)
            stage3_locked_pct = round((stage3_trailing - cost_price) / cost_price * 100, 1) if cost_price > 0 else 0.0

            # ── 动态紧迫感（基于当前浮盈水位）───────────────────────────────
            if pnl_pct >= 30:
                urgency = 'HIGH'
                urgency_note = f'浮盈{pnl_pct:.1f}%，建议加快减仓节奏，不要贪顶'
            elif pnl_pct >= 20:
                urgency = 'MEDIUM'
                urgency_note = f'浮盈{pnl_pct:.1f}%，可按计划分批止盈'
            else:
                urgency = 'LOW'
                urgency_note = f'浮盈{pnl_pct:.1f}%，刚触及止盈触发线，保持追踪'

            return {
                'current_price': current_price,
                'cost_price': cost_price,
                'pnl_pct': round(pnl_pct, 1),
                'atr': round(atr_val, 3),
                'atr_trailing_stop': stage3_trailing,
                'highest_price': round(highest_price, 2),
                'urgency': urgency,
                'urgency_note': urgency_note,
                'stages': [
                    {
                        'stage': 1,
                        'label': '第一批 (1/3仓)',
                        'exit_price': stage1_price,
                        'exit_pct': stage1_pct,
                        'condition': f'价格触及 {stage1_price:.2f}，或5个交易日内动量衰减',
                        'source': 'resistance' if take_profit_short > current_price else 'atr_1x',
                    },
                    {
                        'stage': 2,
                        'label': '第二批 (1/3仓)',
                        'exit_price': stage2_price,
                        'exit_pct': stage2_pct,
                        'condition': f'价格触及 {stage2_price:.2f}，或出现量价背离',
                        'source': 'target_price' if (take_profit_mid > stage1_price) else 'atr_2.5x',
                    },
                    {
                        'stage': 3,
                        'label': '底仓 (1/3仓)',
                        'exit_price': stage3_trailing,
                        'exit_pct': stage3_locked_pct,
                        'condition': f'ATR追踪止损 {stage3_trailing:.2f}（已锁住{stage3_locked_pct:+.1f}%浮盈）',
                        'source': 'atr_trailing',
                    },
                ],
            }
        except Exception as _e:
            logger.debug(f"[ProfitTakePlan] 计算失败: {_e}")
            return None

    def _get_macro_intel(self, save_to_db: bool = False, portfolio_sectors: list = None) -> Optional[str]:
        """
        获取宏观情报文本（含6大维度）。先查内存缓存（TTL=30min），再查 news_intel DB 缓存（TTL=4h），
        未命中则调用 Perplexity，结果落库。内存锁防止多个并发 pipeline 实例重复调用（thundering herd）。
        """
        import time as _time
        MACRO_CODE = "__MACRO__"
        MACRO_TTL_HOURS = 4
        MACRO_MEM_TTL = 1800  # 30分钟内存缓存

        # 0. 快速检查内存缓存（无锁读，过期才加锁）
        _now = _time.time()
        if _macro_intel_mem_cache['data'] is not None and (_now - _macro_intel_mem_cache['ts']) < MACRO_MEM_TTL:
            logger.debug("🌐 [宏观情报] 命中内存缓存，跳过 Perplexity")
            return _macro_intel_mem_cache['data']

        # 加锁后再检查一次内存缓存（防止等锁期间其他线程已更新）
        with _macro_intel_mem_lock:
            _now2 = _time.time()
            if _macro_intel_mem_cache['data'] is not None and (_now2 - _macro_intel_mem_cache['ts']) < MACRO_MEM_TTL:
                logger.debug("🌐 [宏观情报] 命中内存缓存（锁内二次检查），跳过 Perplexity")
                return _macro_intel_mem_cache['data']

            # 1. 查 DB 缓存
            try:
                items = self.storage.get_recent_news(MACRO_CODE, days=1, limit=1, provider="perplexity")
                if items:
                    from datetime import timedelta
                    cutoff = datetime.now() - timedelta(hours=MACRO_TTL_HOURS)
                    fresh = [n for n in items if getattr(n, "fetched_at", None) and n.fetched_at >= cutoff]
                    if fresh:
                        logger.info("🌐 [宏观情报] 命中缓存，复用已有宏观研报")
                        _result = getattr(fresh[0], "snippet", None) or getattr(fresh[0], "title", None)
                        if _result:
                            _macro_intel_mem_cache.update({'data': _result, 'ts': _time.time()})
                        return _result
            except Exception as e:
                logger.debug(f"[宏观情报] 缓存读取失败: {e}")

            # 2. 缓存未命中，调用 Perplexity
            if not self.search_service:
                logger.debug("[宏观情报] search_service 未配置，跳过")
                return None
            if not getattr(self.search_service, 'provider', None):
                return None

            try:
                logger.info("🌐 [宏观情报] 调用 Perplexity 获取6维宏观研报...")
                resp = self.search_service.search_macro_context(portfolio_sectors=portfolio_sectors)
                if resp and getattr(resp, 'success', False) and resp.results:
                    content = resp.results[0].snippet or resp.results[0].title or ""
                    if content and save_to_db:
                        try:
                            self.storage.save_news_intel(
                                MACRO_CODE, "宏观情报", dimension="macro_context",
                                query="宏观6维研报", response=resp,
                                query_context={"query_source": "macro_batch"}
                            )
                        except Exception as _e:
                            logger.debug(f"[宏观情报] 落库跳过: {_e}")
                    if content:
                        _macro_intel_mem_cache.update({'data': content, 'ts': _time.time()})
                    logger.info("🌐 [宏观情报] 获取成功，已注入全批次")
                    return content
                else:
                    reason = getattr(resp, 'error', '未知') if resp else '响应为空'
                    logger.warning(f"🌐 [宏观情报] Perplexity 返回失败: {reason}")
            except Exception as e:
                logger.warning(f"🌐 [宏观情报] 搜索异常: {e}")
            return None

    def _classify_macro_regime(self, macro_intel_text: str) -> Optional[Dict[str, Any]]:
        """
        用 Gemini flash 将宏观情报文本分类为 BULL/NEUTRAL/BEAR/CRISIS。
        结果缓存在 data_cache (TTL=4h)，避免每次批量重复调用。
        失败时静默返回 None，主流程无感降级。
        """
        CACHE_TYPE = "macro_regime"
        CACHE_KEY = "global"
        REGIME_TTL_HOURS = 4.0

        # 1. 查缓存
        try:
            cached_json = self.storage.get_data_cache(CACHE_TYPE, CACHE_KEY, ttl_hours=REGIME_TTL_HOURS)
            if cached_json:
                import json as _json
                data = _json.loads(cached_json)
                logger.info(f"🌐 [Regime] 命中缓存: {data.get('regime')} (confidence={data.get('confidence')})")
                return data
        except Exception as _e:
            logger.debug(f"[Regime] 缓存读取失败: {_e}")

        # 2. 缓存未命中，调用 Gemini flash
        _gemini_model = getattr(self.analyzer, '_model', None) if self.analyzer else None
        if not _gemini_model:
            return None

        classify_prompt = (
            "请根据以下宏观情报，将当前A股市场宏观状态分类为以下四种之一：\n"
            "- BULL（经济扩张/流动性充裕/政策宽松）\n"
            "- NEUTRAL（经济平稳/政策中性）\n"
            "- BEAR（经济收缩/流动性收紧/政策收紧）\n"
            "- CRISIS（系统性风险/金融危机/极度恐慌）\n\n"
            f"宏观情报摘要：\n{macro_intel_text[:1500]}\n\n"
            "只输出JSON，格式：{\"regime\": \"BULL|NEUTRAL|BEAR|CRISIS\", \"confidence\": 0.0-1.0, \"rationale\": \"一句话理由\"}"
        )
        try:
            resp = _gemini_model.generate_content(classify_prompt)
            raw = (resp.text or "").strip()
            import json as _json, re as _re
            m = _re.search(r'\{.*?\}', raw, _re.DOTALL)
            if not m:
                return None
            data = _json.loads(m.group())
            if data.get('regime') not in ('BULL', 'NEUTRAL', 'BEAR', 'CRISIS'):
                return None
            self.storage.save_data_cache(CACHE_TYPE, CACHE_KEY, _json.dumps(data, ensure_ascii=False))
            logger.info(f"🌐 [Regime] 分类成功: {data['regime']} (confidence={data.get('confidence')}) — {data.get('rationale', '')[:60]}")
            return data
        except Exception as e:
            logger.debug(f"[Regime] 分类失败(降级): {e}")
            return None

    def _compute_ic_quality_guard(self) -> Optional[Dict[str, Any]]:
        """计算当前周期滚动 IC，感知信号质量退化。

        Returns:
            dict with keys: ic, n, period, quality_level, quality_desc
            quality_level: 'strong' / 'moderate' / 'weak' / 'negative'
        """
        import math
        try:
            with self.storage.get_session() as session:
                from sqlalchemy import text as _text
                rows = session.execute(_text("""
                    SELECT MAX(sentiment_score) as score, actual_pct_5d
                    FROM analysis_history
                    WHERE backtest_filled=1
                      AND actual_pct_5d IS NOT NULL
                      AND sentiment_score IS NOT NULL
                      AND created_at >= datetime('now', '-21 days')
                    GROUP BY code, DATE(created_at)
                    ORDER BY DATE(created_at) ASC
                """)).fetchall()

            if not rows or len(rows) < 20:
                logger.debug(f"[ICGuard] 样本不足({len(rows) if rows else 0}<20)，跳过守卫")
                return None
            # t统计增强显著性检验（|↓|×√n ≥ 1.5，即大约邠90%置信区间）：不达标则返回结果但不触发守卫

            scores = [float(r[0]) for r in rows]
            rets = [float(r[1]) for r in rows]
            n = len(rows)
            mx = sum(scores) / n
            my = sum(rets) / n
            num = sum((s - mx) * (r - my) for s, r in zip(scores, rets))
            denom_s = math.sqrt(sum((s - mx) ** 2 for s in scores))
            denom_r = math.sqrt(sum((r - my) ** 2 for r in rets))
            denom = denom_s * denom_r
            ic = round(num / denom, 4) if denom > 1e-9 else 0.0

            t_stat = abs(ic) * math.sqrt(n)
            statistically_significant = t_stat >= 1.5  # ~90% 置信区间

            if not statistically_significant:
                level, desc = "normal", ""
            elif ic >= 0.20:
                level, desc = "strong", ""
            elif ic >= 0.10:
                level, desc = "moderate", f"⚠️ 近21日信号中等(IC={ic:.2f}, t={t_stat:.2f})，请适当降低仓位，严格执行止损。"
            elif ic >= 0.0:
                level, desc = "weak", f"⚠️ 近21日信号较弱(IC={ic:.2f}, t={t_stat:.2f})，建议控制在半仓以内，优先等待信号增强再入场。"
            else:
                level, desc = "negative", (
                    f"🔴 近21日信号反转(IC={ic:.2f}, t={t_stat:.2f})！当前量化评分预测能力弱，"
                    "建议：①缩小仓位至1/3以内；②执行更紧的止损（当前止损价上移0.5-1%）；"
                    "③优先等待IC转正（连续5日）后再新增头寸。"
                )

            guard = {"ic": ic, "n": n, "t_stat": round(t_stat, 3), "period": "近21日", "quality_level": level, "quality_desc": desc}
            logger.info(f"📊 [ICGuard] 近21日滚动IC={ic:.4f}（n={n}），quality={level}")
            return guard
        except Exception as e:
            logger.debug(f"[ICGuard] 计算失败: {e}")
            return None

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
        import re as _re
        _raw_name = (quote.name or '').strip()
        _raw_name = _re.sub(r'\s*\(\d{6}\)\s*$', '', _raw_name)
        stock_name = _re.sub(r'\s+', '', _raw_name).strip()
        
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

        # 数据可用性追踪：记录各模块获取失败，后续注入 LLM prompt 告知缺口
        _missing_data: list = []

        # F10 基本面数据（只获取一次）
        fundamental_data = FundamentalData()
        if not fast_mode:
            try:
                fundamental_data = get_fundamental_data(code)
            except Exception as _e:
                logger.warning(f"[{code}] F10基本面数据获取失败: {_e}")
                _missing_data.append("F10基本面/财务数据（接口失败，PE/PB/营收/利润均不可用）")

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
            _missing_data.append("板块相对强弱（无法判断个股vs板块强弱）")

        # === 技术面量化分析 ===
        tech_report = "数据不足，无法进行技术分析"
        tech_report_llm = "数据不足"
        kline_narrative = ""
        trend_analysis_dict = {}
        trend_result_obj = None
        _ind_pe_for_context = None
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
                regime, _ = _STA.detect_market_regime(daily_df, idx_pct)
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
                _ind_pe_for_context = None
                try:
                    from data_provider.fundamental_fetcher import get_industry_pe_median, get_pe_history
                    if not fast_mode:
                        ind_pe = get_industry_pe_median(code)
                        if ind_pe and ind_pe > 0:
                            _val_snap.industry_pe_median = ind_pe
                            _ind_pe_for_context = ind_pe
                        # P3: PE历史数据（用于估值分位数计算）
                        pe_hist = get_pe_history(code)
                        if pe_hist:
                            _val_snap.pe_history = pe_hist
                except Exception as _e:
                    logger.debug(f"[{code}] 行业PE/PE历史获取失败: {_e}")
                    _missing_data.append("行业PE中位数/PE历史分位（相对估值无法判断）")
                # 资金面数据（如有）+ 融资余额历史（P3情绪极端检测）
                _capital_flow = None
                try:
                    if hasattr(self.fetcher_manager, 'get_capital_flow'):
                        _capital_flow = self.fetcher_manager.get_capital_flow(code)
                    # P3: 融资余额历史（用于情绪极端检测）
                    # 已优化为批量缓存，同日期全市场数据只拉取一次，开销可接受
                    if _capital_flow and not fast_mode and getattr(self.config, 'enable_margin_history', True):
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
                except Exception as _e:
                    logger.warning(f"[{code}] 资金流向数据获取失败: {_e}")
                    _missing_data.append("资金流向/主力净流入（无法判断机构买卖意图）")
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
                trend_result_obj = trend_result
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
                try:
                    from src.stock_analyzer.kline_narrator import KlineNarrator
                    kline_narrative = KlineNarrator.describe(trend_result, daily_df)
                except Exception as _e:
                    kline_narrative = ""
                    logger.debug(f"[{code}] K线叙事生成失败: {_e}")
                    _missing_data.append("K线形态叙事（无法用文字描述K线形态）")
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
            logger.debug(f"[{code}] 获取历史摘要失败: {e}")
            _missing_data.append("历史分析记忆（无法参考上次判断")

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

        # 日线数据缺失时，技术分析全部不可用
        if daily_df is None or daily_df.empty:
            _missing_data.append("K线日线数据（无法进行任何技术分析，量化评分不可用）")

        # 历史预测准确率（≥3条有效回填记录才统计）
        prediction_accuracy = None
        try:
            prediction_accuracy = self.storage.get_prediction_accuracy(code, days=90)
        except Exception as _pa_e:
            logger.debug(f"[{code}] 历史准确率获取跳过: {_pa_e}")

        # P3: 股东资金博弈数据（高管增减持 + 限售解禁 + 回购）
        _insider_data = {}
        _unlock_data = {}
        _repurchase_data = {}
        if not fast_mode:
            try:
                from data_provider.shareholder_fetcher import get_insider_changes, get_upcoming_unlock, get_repurchase_summary
                _insider_data = get_insider_changes(code, days_back=90)
                _unlock_data = get_upcoming_unlock(code, days_ahead=180)
                _repurchase_data = get_repurchase_summary(code)
            except Exception as _se:
                logger.debug(f"[{code}] 股东数据获取跳过: {_se}")

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
            'kline_narrative': kline_narrative,
            'trend_analysis': trend_analysis_dict,
            'trend_result': trend_result_obj,
            'daily_df': daily_df,
            'fundamental': fundamental_data.to_dict(),
            'history_summary': history_summary,
            'sector_context': sector_context.to_dict() if isinstance(sector_context, SectorContext) else sector_context,
            'is_intraday': is_market_intraday(),
            'market_phase': get_market_phase(),
            'analysis_time': datetime.now().strftime('%H:%M'),
            'data_availability': _missing_data,
            'prediction_accuracy': prediction_accuracy,
            'insider_changes': _insider_data,
            'upcoming_unlock': _unlock_data,
            'repurchase': _repurchase_data,
            'price_range_52w': (lambda df: {
                'high': float(df.tail(min(250, len(df)))['high'].max()),
                'low': float(df.tail(min(250, len(df)))['low'].min()),
                'n_days': min(250, len(df)),
            } if df is not None and not df.empty and len(df) >= 20 else {})(daily_df),
        }
        # 注入行业PE中位数供f10_str相对估值展示
        if _ind_pe_for_context and isinstance(context.get('fundamental', {}).get('valuation'), dict):
            context['fundamental']['valuation']['industry_pe_median'] = _ind_pe_for_context
        context = self._enhance_context(context)
        return context

    def _enhance_context(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """增强 context：注入评分趋势+拐点检测 + 分时数据"""
        code = context.get('code', '')
        if not code:
            return context
        fast_mode = getattr(self.config, 'fast_mode', False)

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

        # P2c: 同行业横截面评分排名（需 sector_name 已在 analysis_history 中积累）
        try:
            _sec_ctx = context.get('sector_context') or {}
            _sec_name = _sec_ctx.get('sector_name') if isinstance(_sec_ctx, dict) else None
            if _sec_name:
                peer_data = self.storage.get_sector_peer_scores(_sec_name, days=7, min_peers=10)
                if peer_data:
                    context['peer_ranking'] = peer_data
        except Exception as e:
            logger.debug(f"[{code}] 同行业排名获取失败: {e}")

        # 持仓周期胜率统计（短线/中线分类依据）
        try:
            horizon_stats = self.storage.get_holding_horizon_stats(code, days=90, min_samples=5)
            if horizon_stats:
                context['holding_horizon_stats'] = horizon_stats
        except Exception as e:
            logger.debug(f"[{code}] 持仓周期胜率获取失败: {e}")

        # P4: 北向资金个股持股数据（每日数据，TTL=6h，串行调用不封禁）
        if not fast_mode:
            try:
                from data_provider.akshare_fetcher import get_northbound_holding
                north_data = get_northbound_holding(code)
                if north_data:
                    context['northbound_holding'] = north_data
            except Exception as e:
                logger.debug(f"[{code}] 北向资金持股数据获取失败: {e}")

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
        market_overview_override: Optional[str] = None,
        position_info: Optional[Dict[str, Any]] = None,
        ab_variant: str = 'standard',
        macro_intel: Optional[str] = None,
        portfolio_beta: Optional[Dict[str, Any]] = None,
        macro_regime: Optional[Dict[str, Any]] = None,
        max_dd_guard: Optional[Dict[str, Any]] = None,
        ic_quality_guard: Optional[Dict[str, Any]] = None,
        sector_exposure: Optional[Dict[str, Any]] = None,
    ) -> Optional[AnalysisResult]:
        """处理单只股票的核心逻辑"""
        try:
            context = self._prepare_stock_context(code)
            if not context: return None
            stock_name = context['stock_name']
            self._log(f"[{code}] {stock_name} 开始分析 (variant={ab_variant})")

            # P2a-2/P2b/P3b/P9a: 注入组合Beta/Regime/MaxDD/ICGuard到context（供analyzer.py渲染到prompt）
            if portfolio_beta:
                context['portfolio_beta'] = portfolio_beta
            if macro_regime:
                context['macro_regime'] = macro_regime
            if max_dd_guard:
                context['max_dd_guard'] = max_dd_guard
            if ic_quality_guard:
                context['ic_quality_guard'] = ic_quality_guard
            if sector_exposure:
                context['sector_exposure'] = sector_exposure

            # A/B 实验：llm_only 变体移除量化评分/信号结论，但保留 K 线叙事（让 LLM 自行解读走势）
            if ab_variant == 'llm_only':
                context['technical_analysis_report_llm'] = ''   # 去掉 RSI/MACD 数值 + 评分 + 买卖信号结论
                context['trend_analysis'] = {}                  # 去掉量化 signal_score/buy_signal
                context['technical_analysis_report'] = ''       # 去掉结构化技术报告
                # kline_narrative 保留：让 LLM 自己读 K 线故事，不给它预算好的结论
            
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
            # 盘中2h TTL（新闻更新快）；盘后10h TTL（覆盖隔夜到次日开盘）
            _pplx_ttl = 2 if is_market_intraday() else 10
            if not search_content:
                pplx_cache = self._get_cached_news_context(
                    code, stock_name, hours=_pplx_ttl, limit=5, provider='perplexity'
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

            # 层 3: Perplexity 实时搜索（无缓存时每次触发，fast_mode 除外）
            if not search_content and not fast_mode and self.search_service:
                sleep_time = random.uniform(2.0, 5.0)
                time.sleep(sleep_time)

                logger.info(f"🔎 [{stock_name}] 无缓存新闻，调用 Perplexity 搜索 (延迟 {sleep_time:.1f}s)...")
                try:
                    if hasattr(self.search_service, 'search_comprehensive_intel'):
                        _sec_name = (context.get('sector_context') or {}).get('sector_name') if isinstance(context.get('sector_context'), dict) else None
                        _intraday = context.get('is_intraday', False)
                        resp = self.search_service.search_comprehensive_intel(
                            code, stock_name,
                            sector_name=_sec_name,
                            is_intraday=_intraday,
                        )
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

            # 宏观情报注入：批量路径由 run() 预取传入；单股 API 路径从 DB 缓存读取（TTL=4h）
            _macro = macro_intel
            if _macro is None:
                try:
                    _macro = self._get_macro_intel(save_to_db=True)
                except Exception:
                    pass
            if _macro:
                macro_prefix = "\n\n---\n## 宏观环境情报（Perplexity）\n"
                market_overview = (market_overview or "") + macro_prefix + _macro

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
            # Skills 评分模型 + 场景检测
            _skill_meta = self._score_skills(context)
            _selected_skill = _skill_meta['primary']
            _scene = self._detect_scene(context, position_info)
            logger.info(f"[{stock_name}] Skill评分: {_skill_meta['scores']} | 主框架={_selected_skill}({_skill_meta['primary_score']}) | 场景={_scene}")
            if _skill_meta.get('secondary'):
                logger.info(f"[{stock_name}] 副框架={_skill_meta['secondary']}({_skill_meta['secondary_score']}) | 收敛={_skill_meta['convergent']}")
            # 将 skill_meta 和 scene 注入 context 供 analyzer 使用
            context['_skill_meta'] = _skill_meta
            context['_scene'] = _scene

            # 止盈场景：计算分阶段退出计划并注入 context
            _profit_take_plan = None
            if _scene == 'profit_take' and position_info:
                _profit_take_plan = self._build_profit_take_plan(context, position_info)
                if _profit_take_plan:
                    context['_profit_take_plan'] = _profit_take_plan
                    logger.info(f"[{stock_name}] 止盈计划已生成: urgency={_profit_take_plan['urgency']} pnl={_profit_take_plan['pnl_pct']}%")
            analysis_timeout = getattr(self.config, 'analysis_timeout_seconds', 180) or 180
            def _run_analyze():
                return self.analyzer.analyze(
                    context=context,
                    news_context=search_content,
                    role="trader",
                    market_overview=market_overview,
                    use_light_model=use_light,
                    position_info=position_info,
                    skill=_selected_skill,
                    ab_variant=ab_variant,
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

            # ===== 后处理层: 量化信号驱动 operation_advice，LLM 是最终决策者（可否决）=====
            # 注: sentiment_score 内部仍用量化分做一致性检查，对外展示由 analysis_service 转换为 LLM 分
            trend = context.get('trend_analysis', {})
            if trend and isinstance(trend, dict):
                quant_score = trend.get('signal_score')
                quant_signal = trend.get('buy_signal')
                # 保留 LLM 的原始评分和建议作为参考
                # llm_score/llm_advice 可能由 _parse_response 从 JSON 直接解析；
                # 若 LLM 没显式返回，则用当前评分/建议作为 fallback（确保 llm_score/llm_advice 有初始值）
                if result.llm_score is None and result.sentiment_score is not None:
                    result.llm_score = result.sentiment_score
                if not result.llm_advice and result.operation_advice and result.operation_advice != '观望':
                    result.llm_advice = result.operation_advice
                # 如果 LLM 什么都没返回（sentiment_score 默认50），且 llm_score 仍为 50，标记来源
                # 确保 llm_advice 有值
                if not result.llm_advice and result.operation_advice:
                    result.llm_advice = result.operation_advice
                # 量化提供初始 operation_advice 和 sentiment_score（内部评分，供一致性检查和 LLM 否决机制使用）
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
                # P3: 资金面与量化信号冲突检测
                _cf_signal = trend.get('capital_flow_signal', '') or ''
                _sig_score = trend.get('signal_score', 0) or 0
                _is_tech_bullish = _sig_score >= 78
                _is_cf_outflow = any(kw in _cf_signal for kw in ('流出', '净流出', '持续流出'))
                if _is_tech_bullish and _is_cf_outflow:
                    dashboard['capital_conflict_warning'] = f"技术面看多（{_sig_score}分）但主力资金净流出，信号存在矛盾，需谨慎"
                else:
                    dashboard.pop('capital_conflict_warning', None)
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

                # === P3: Skill 信息记录 ===
                dashboard['skill_used'] = getattr(result, 'skill_used', _selected_skill)
                dashboard['skill_scores'] = _skill_meta.get('scores', {})
                dashboard['skill_secondary'] = _skill_meta.get('secondary')
                dashboard['skill_convergent'] = _skill_meta.get('convergent', False)
                dashboard['analysis_scene'] = _scene
                if getattr(result, 'skill_analysis', None):
                    dashboard['skill_analysis'] = result.skill_analysis
                if _profit_take_plan:
                    dashboard['profit_take_plan'] = _profit_take_plan

                # === P3 增强3: 心理陷阱预警（纯规则，不调用 AI）===
                _behavioral_warning = ""
                try:
                    _score_scores = _score_trend.get('scores', [])
                    _cur_score = result.sentiment_score
                    _has_pos = bool(position_info and any(
                        position_info.get(k) for k in ('cost_price', 'position_amount', 'total_capital')
                    ))
                    _cost_price = float(position_info.get('cost_price', 0) or 0) if position_info else 0.0
                    _cur_price = float(context.get('price') or 0)
                    _stop_loss = 0.0
                    try:
                        _sniper = dashboard.get('battle_plan', {}).get('sniper_points', {})
                        _stop_loss = float(_sniper.get('stop_loss') or 0)
                    except Exception:
                        pass

                    # 规则1: 追高偏差 - 连续上升≥3次且当日涨幅>2%
                    _today_pct = float(context.get('today', {}).get('pct_chg') or
                                       context.get('realtime', {}).get('change_pct') or 0)
                    if _cons_up >= 3 and _today_pct > 2:
                        _behavioral_warning = (
                            f"⚠️ 连续{_cons_up}日评分上升，股价今日已涨{_today_pct:.1f}%，"
                            f"追高风险上升——建议等回踩确认而非直接追市价"
                        )
                    # 规则2: 厌损偏差 - 持仓且浮亏已超过止损线
                    elif _has_pos and _cost_price > 0 and _cur_price > 0 and _stop_loss > 0:
                        _pnl_pct = (_cur_price - _cost_price) / _cost_price * 100
                        if _pnl_pct < 0 and _cur_price < _stop_loss:
                            _behavioral_warning = (
                                f"⚠️ 当前浮亏{abs(_pnl_pct):.1f}%，价格已跌破止损线{_stop_loss:.2f}，"
                                f"未执行止损——持续持有将扩大损失，建议严格执行"
                            )
                    # 规则3: 处置效应 - 评分从高位回落且持仓浮盈>10%
                    elif _has_pos and _cost_price > 0 and _cur_price > 0:
                        _pnl_pct = (_cur_price - _cost_price) / _cost_price * 100
                        _score_change_val = _score_trend.get('score_change', 0) or 0
                        _prev_score_for_check = _cur_score - _score_change_val
                        if _prev_score_for_check >= 80 and _cur_score < 70 and _pnl_pct > 10:
                            _behavioral_warning = (
                                f"⚠️ 评分从高位回落（{_prev_score_for_check}→{_cur_score}），"
                                f"但持有浮盈{_pnl_pct:.1f}%——考虑部分止盈，避免浮盈变浮亏"
                            )
                    # 规则4: 亏损加仓陷阱 - 持仓浮亏>=8%但仍建议买入/加仓
                    elif _has_pos and _cost_price > 0 and _cur_price > 0:
                        _pnl_pct_check = (_cur_price - _cost_price) / _cost_price * 100
                        _advice_now = result.operation_advice or ''
                        if _pnl_pct_check <= -8 and _advice_now in ('买入', '加仓'):
                            _behavioral_warning = (
                                f"⚠️【亏损加仓陷阱】当前浮亏{abs(_pnl_pct_check):.1f}%，"
                                f"此时{_advice_now}违反资金管理纪律（越陷越深风险极高）。"
                                f"建议先确认止损线{_stop_loss:.2f}是否仍有效，再决定是否继续持仓。"
                                if _stop_loss > 0 else
                                f"⚠️【亏损加仓陷阱】当前浮亏{abs(_pnl_pct_check):.1f}%，"
                                f"此时{_advice_now}违反资金管理纪律（越陷越深风险极高）。"
                                f"建议设定明确止损位，避免无限被套。"
                            )
                    # 规则5: 踏空焦虑 - 评分偏低但无持仓
                    elif not _has_pos and _cur_score < 50:
                        _behavioral_warning = (
                            f"💡 当前评分{_cur_score}分，不是好的买入时机，"
                            f"观望不等于踏空——等待评分>70的信号再入场"
                        )
                    # 规则5: 犹豫不决 - 近3次均为"观望"
                    if not _behavioral_warning and len(_score_scores) >= 3:
                        _recent_advices = [s.get('advice', '') for s in _score_scores[-3:]]
                        if all('观望' in (a or '') for a in _recent_advices):
                            _behavioral_warning = (
                                f"💡 已连续{len(_recent_advices)}次分析结果为观望——"
                                f"若逻辑没有改变，等待明确触发信号比频繁分析更有价值"
                            )
                except Exception as _be:
                    logger.debug(f"[{code}] 心理陷阱预警计算失败(非致命): {_be}")

                if _behavioral_warning:
                    result.behavioral_warning = _behavioral_warning
                    dashboard['behavioral_warning'] = _behavioral_warning
                # 补充序列化 _conflict_warnings（动态属性不在 dataclass fields 里）
                _tr_obj = context.get('trend_result')
                if _tr_obj is not None and hasattr(_tr_obj, '_conflict_warnings') and _tr_obj._conflict_warnings:
                    dashboard['quant_extras']['signal_conflicts'] = _tr_obj._conflict_warnings

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

                # === 持仓时间维度建议（短线/中线/长线）===
                _trend_result_for_horizon = context.get('trend_result')
                if _trend_result_for_horizon is not None:
                    try:
                        dashboard['holding_horizon'] = _RM.generate_holding_horizon(_trend_result_for_horizon)
                    except Exception as _hh_e:
                        logger.debug(f"[{code}] 持仓时间维度计算失败(非致命): {_hh_e}")

                # === 场景识别+操作建议（generate_trade_advice）===
                # 需要真实的TrendAnalysisResult对象，从_prepare_stock_context中取
                _trend_result_obj = context.get('trend_result')
                if _trend_result_obj is not None:
                    _RM.generate_trade_advice(_trend_result_obj, position_info=position_info)
                    # 用持仓成本重新生成盘中关键价位（持仓时显示成本线/加仓点）
                    _cp_pi = float(position_info.get('cost_price', 0) or 0) if position_info else 0.0
                    if _cp_pi > 0:
                        try:
                            _daily_df_ctx = context.get('daily_df')
                            if _daily_df_ctx is not None:
                                _RM.generate_intraday_watchlist(_trend_result_obj, _daily_df_ctx, cost_price=_cp_pi)
                                trend['intraday_watchlist'] = _trend_result_obj.intraday_watchlist
                        except Exception as _e:
                            logger.debug(f"[{code}] 持仓盘中价位重生成失败: {_e}")
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

                # === P1-3: AI-量化融合分数机制 ===
                # 量化分数已由 quant_score 决定，LLM 给出独立判断（llm_score/llm_advice）
                # 融合逻辑：方向一致 → 置信度加分（最多+5），严重分歧 → 降档（最多-5）
                _llm_s = result.llm_score if result.llm_score is not None else _qs
                _llm_adv = (result.llm_advice or '').strip()
                _quant_adv = (result.operation_advice or '').strip()

                def _is_bullish(adv: str) -> bool:
                    return any(k in adv for k in ('买入', '加仓', '强烈买入', '激进买入'))

                def _is_bearish(adv: str) -> bool:
                    return any(k in adv for k in ('卖出', '减仓', '清仓', '强烈卖出'))

                _quant_bull = _is_bullish(_quant_adv)
                _quant_bear = _is_bearish(_quant_adv)
                _llm_bull = _is_bullish(_llm_adv)
                _llm_bear = _is_bearish(_llm_adv)

                _fusion_adj = 0
                _fusion_note = ''
                # 方向一致：双引擎共振，置信度加成
                if _quant_bull and _llm_bull:
                    _score_diff = abs(_qs - _llm_s)
                    if _score_diff <= 15:
                        _fusion_adj = 5   # 量化+AI双看多且评分接近：强共振
                        _fusion_note = f'AI-量化双看多共振(+5, AI评分{_llm_s})'
                    else:
                        _fusion_adj = 3   # 方向一致但分数差距较大：温和共振
                        _fusion_note = f'AI-量化方向一致(+3, AI评分{_llm_s})'
                elif _quant_bear and _llm_bear:
                    _fusion_adj = -5  # 双空：降档信号更可靠
                    _fusion_note = f'AI-量化双看空(-5, AI评分{_llm_s})'
                # 严重分歧：一个看多一个看空
                elif (_quant_bull and _llm_bear) or (_quant_bear and _llm_bull):
                    _fusion_adj = -5
                    _fusion_note = f'⚠️ AI-量化严重分歧(-5，量化:{_quant_adv} vs AI:{_llm_adv})'
                # 温和分歧：一个中性一个极端
                elif _quant_bull and not _llm_bull and not _llm_bear and _llm_s < _qs - 20:
                    _fusion_adj = -3
                    _fusion_note = f'量化看多但AI偏中性(-3, AI评分{_llm_s})'

                if _fusion_adj != 0:
                    _old = result.sentiment_score
                    result.sentiment_score = max(0, min(100, result.sentiment_score + _fusion_adj))
                    logger.info(f"[{code}] AI-量化融合: {_old}→{result.sentiment_score} ({_fusion_note})")
                    dashboard['ai_quant_fusion'] = {
                        'adj': _fusion_adj,
                        'note': _fusion_note,
                        'quant_score': _qs,
                        'llm_score': _llm_s,
                    }
                    # 融合后评分变化可能触发买卖信号更新
                    from src.stock_analyzer.scoring import ScoringSystem as _SS
                    _trend_result_for_fusion = context.get('trend_result')
                    if _trend_result_for_fusion is not None:
                        _trend_result_for_fusion.signal_score = result.sentiment_score
                        _SS.update_buy_signal(_trend_result_for_fusion)
                        result.operation_advice = _trend_result_for_fusion.buy_signal.value

                result.dashboard = dashboard

                # 信号一致性检查：评分 < 78 给出"买入"属内部矛盾，强制降为"观望"
                # 回测依据（2026-03）：sentiment_score 65-77 + 买入 → 5日胜率24.2%，avg-1.19%，负期望
                #                      sentiment_score >=78 + 买入 → 5日胜率76.3%，avg+6.49%，强正期望
                _final_score = result.sentiment_score or 0
                if _final_score < 78 and (result.operation_advice or '').strip() == '买入':
                    logger.info(f"[{code}] 一致性覆盖: 买入@{_final_score}分 → 观望（低分买入负期望，回测24.2%胜率）")
                    result.operation_advice = '观望'
                    if result.llm_advice == '买入':
                        result.llm_advice = '观望'

                # LLM降级否决权：量化看多但LLM明确保守（观望/持有）→ 降为观望
                # 回测依据（2026-02，45条分歧记录）：
                #   量化买入+LLM观望 → 4条，0%胜率，avg-4.06%（茅台连降两次、中远海特）
                #   量化买入+LLM持有 → 3条，33%胜率，avg-0.65%（江苏神通）
                #   案例：LLM识别"PE高估+主力撤离+盈亏比极差"→ 量化技术面无法捕获此类基本面/资金风险
                #   风险：1条误判（华明装备+5.12%，LLM持有+量化买入）
                _llm_conservative = any(k in _llm_adv for k in ('观望', '等待', '持有'))
                if _quant_bull and _llm_conservative and (result.operation_advice or '').strip() == '买入':
                    logger.info(
                        f"[{code}] LLM降级否决: 量化{_quant_adv}+LLM保守({_llm_adv}) → 观望"
                        f"（基本面/资金风险，回测0-33%胜率avg-0.65~-4.06%）"
                    )
                    result.operation_advice = '观望'

                # === 持仓感知建议重映射 ===
                # 未持仓时，"清仓"/"减仓"/"持有" 对空仓者无意义，统一映射为 "观望"
                # 持仓时，买入类信号映射为更贴切的 "加仓"
                _has_pos_for_advice = bool(position_info and any(
                    position_info.get(k) for k in ('cost_price', 'position_amount', 'total_capital')
                ))
                _cur_adv = (result.operation_advice or '').strip()
                if not _has_pos_for_advice:
                    _no_pos_map = {'清仓': '观望', '减仓': '观望', '持有': '观望'}
                    _remapped = _no_pos_map.get(_cur_adv)
                    if _remapped:
                        logger.debug(f"[{code}] 空仓建议重映射: {_cur_adv} → {_remapped}")
                        result.operation_advice = _remapped

                # 决策类型
                advice = result.operation_advice
                if '买' in advice or '加仓' in advice:
                    result.decision_type = 'buy'
                elif '卖' in advice or '减仓' in advice:
                    result.decision_type = 'sell'
                else:
                    result.decision_type = 'hold'

            # === 市场策略蓝图：后处理规则引擎（硬约束覆盖，优先级高于所有信号）===
            # 在 LLM+量化+仓位重映射全部完成后，根据宏观 Regime/MaxDD Guard 施加最终约束
            try:
                from src.core.regime_rules import apply_regime_constraints
                apply_regime_constraints(
                    result=result,
                    macro_regime=macro_regime,
                    max_dd_guard=max_dd_guard,
                )
            except Exception as _rre:
                logger.debug(f"[RegimeRules] 规则引擎跳过: {_rre}")

            # === 改进1: 今日变化对比 ===
            history = context.get('history_summary')
            if history and isinstance(history, dict) and history.get('score') is not None:
                result.is_first_analysis = False
                result.prev_score = history['score']
                # 使用 llm_score 做对比（与前端展示分一致）；llm_score 此时可能还未设定，保底用 sentiment_score
                _cur_display_score = result.llm_score if result.llm_score is not None else result.sentiment_score
                result.score_change = _cur_display_score - history['score']
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
                    changes.insert(0, f"{arrow}评分{result.prev_score}→{_cur_display_score}({result.score_change:+d})")
                # 操作建议变化
                if result.prev_advice and result.operation_advice != result.prev_advice:
                    changes.append(f"建议: {result.prev_advice}→{result.operation_advice}")
                result.signal_changes = changes
            else:
                result.is_first_analysis = True

            # === 改进6: 技术信号 vs AI研判分歧高亮 ===
            _sig_score_for_div = trend.get('signal_score') if trend and isinstance(trend, dict) else None
            if result.llm_score is not None and _sig_score_for_div is not None:
                divergence = abs(_sig_score_for_div - result.llm_score)
                result.quant_ai_divergence = divergence
                if divergence >= 20:
                    q_label = f"技术信号{_sig_score_for_div}分"
                    a_label = f"AI{result.llm_score}分"
                    q_dir = "看多" if _sig_score_for_div >= 60 else ("看空" if _sig_score_for_div <= 40 else "中性")
                    a_dir = "看多" if result.llm_score >= 60 else ("看空" if result.llm_score <= 40 else "中性")
                    result.divergence_alert = f"⚠️ 技术信号与AI研判方向不一致: {q_label}({q_dir}) vs {a_label}({a_dir})"
                    if result.llm_reasoning:
                        result.divergence_alert += f" | AI理由: {result.llm_reasoning[:60]}"
                elif divergence >= 15:
                    result.divergence_alert = f"📊 技术信号({_sig_score_for_div}) vs AI研判({result.llm_score}) 存在差异({divergence}分)"

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
                _sector_name_save = None
                try:
                    _sc_ctx = context.get('sector_context') or {}
                    _sector_name_save = _sc_ctx.get('sector_name') if isinstance(_sc_ctx, dict) else None
                except Exception:
                    pass
                _save_ab_variant = ('flash_pro' if getattr(result, 'flash_used', False) and ab_variant == 'standard' else ab_variant)
                self.storage.save_analysis_history(result=result, query_id=per_stock_query_id, report_type=report_type.value if hasattr(report_type, 'value') else str(report_type), news_content=search_content, context_snapshot=context if self.save_context_snapshot else None, ab_variant=_save_ab_variant, sector_name=_sector_name_save)
                # 同步 sector_name 到持仓表（供行业敞口分析使用）
                if _sector_name_save and position_info:
                    try:
                        from src.storage import Portfolio
                        from sqlalchemy import select as _select
                        with self.storage.get_session() as _ps:
                            _holding = _ps.execute(_select(Portfolio).where(Portfolio.code == code)).scalar_one_or_none()
                            if _holding and _holding.sector_name != _sector_name_save:
                                _holding.sector_name = _sector_name_save
                                _ps.commit()
                    except Exception:
                        pass
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

        # 6. 危机联动检测（2+持仓同日进入 crisis 场景 = 系统性风险信号）
        crisis_stocks = []
        for r in results:
            scene = None
            if r.dashboard and isinstance(r.dashboard, dict):
                scene = r.dashboard.get('analysis_scene')
            if scene == 'crisis':
                crisis_stocks.append(r.name or r.code)
        if len(crisis_stocks) >= 2:
            warnings.append(
                f"🚨 组合危机联动警告: {len(crisis_stocks)}只持仓同日触发危机检测"
                f"（{', '.join(crisis_stocks)}），"
                f"可能存在系统性风险，建议全组合降仓20-30%，重新评估大盘环境"
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

        # === 阶段1.5：保存今日指数数据（供 Beta 计算） + 宏观情报预取 ===
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

        # 宏观情报：全批次只取一次，结果落库缓存（TTL=4h），所有股票共享
        # 注入持仓板块，让宏观研报聚焦相关传导
        _portfolio_sectors: list = []
        try:
            from src.services.portfolio_service import list_portfolio
            _portfolio = list_portfolio()
            if _portfolio:
                _seen = set()
                for _h in _portfolio:
                    _sn = (_h.get('sector_name') or _h.get('sector_context', {}) or {}).get('sector_name', '') if isinstance(_h, dict) else ''
                    if _sn and _sn not in _seen:
                        _portfolio_sectors.append(_sn)
                        _seen.add(_sn)
        except Exception as _pe:
            logger.debug(f"[宏观情报] 获取持仓板块失败(降级为通用查询): {_pe}")
        macro_intel_once: Optional[str] = self._get_macro_intel(save_to_db=True, portfolio_sectors=_portfolio_sectors or None)

        # P2b: 宏观 Regime 分类（全批次一次，TTL=4h）
        macro_regime_once: Optional[Dict[str, Any]] = None
        if macro_intel_once:
            try:
                macro_regime_once = self._classify_macro_regime(macro_intel_once)
            except Exception as _rge:
                logger.debug(f"[Regime] 分类跳过: {_rge}")

        # P2a-2: 组合 Beta 计算（全批次一次，TTL=1h 内存缓存）
        portfolio_beta_once: Optional[Dict[str, Any]] = None
        try:
            if _portfolio:
                from src.services.portfolio_risk_service import calculate_portfolio_beta
                portfolio_beta_once = calculate_portfolio_beta(_portfolio)
        except Exception as _be:
            logger.debug(f"[Beta] 计算跳过: {_be}")

        # P3a: 组合 MaxDD 检查（全批次一次，决定保守等级）
        max_dd_guard_once: Optional[Dict[str, Any]] = None
        try:
            if _portfolio:
                from src.services.portfolio_risk_service import calculate_portfolio_drawdown
                max_dd_guard_once = calculate_portfolio_drawdown(_portfolio)
        except Exception as _dde:
            logger.debug(f"[MaxDD] 计算跳过: {_dde}")

        # P9a: 信号质量守卫 — 计算当前周期滚动 IC，感知信号退化
        ic_quality_guard_once: Optional[Dict[str, Any]] = None
        try:
            ic_quality_guard_once = self._compute_ic_quality_guard()
        except Exception as _icge:
            logger.debug(f"[ICGuard] 计算跳过: {_icge}")

        # 行业敞口守卫 — 检测组合行业集中风险
        sector_exposure_once: Optional[Dict[str, Any]] = None
        try:
            if _portfolio:
                from src.services.portfolio_risk_service import calculate_sector_exposure
                sector_exposure_once = calculate_sector_exposure(_portfolio)
        except Exception as _see:
            logger.debug(f"[SectorExposure] 计算跳过: {_see}")

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

        # ╔══════════════════════════════════════════════════════════════════════╗
        # ║  ⚠️  反封禁警告：严禁随意增大 max_workers 或在此处新增外部 API 调用  ║
        # ║  每个 worker 线程都会触发：akshare(资金流/F10) + efinance(今日资金流)  ║
        # ║  默认 max_workers=1（串行，防封禁最安全）。如需提高并发：              ║
        # ║  1. 先确认 rate_limiter.py 已设置对应数据源的限速                        ║
        # ║  2. CLI 用 --workers N 传入（N 建议 ≤2），不得修改此处默认属性      ║
        # ╚══════════════════════════════════════════════════════════════════════╝
        with ThreadPoolExecutor(max_workers=workers) as executor:
            future_to_code = {
                executor.submit(
                    self.process_single_stock, 
                    code, 
                    skip_analysis=dry_run, 
                    single_stock_notify=single_stock_notify and send_notification, 
                    report_type=report_type, 
                    market_overview_override=market_overview_once,
                    macro_intel=macro_intel_once,
                    portfolio_beta=portfolio_beta_once,
                    macro_regime=macro_regime_once,
                    max_dd_guard=max_dd_guard_once,
                    ic_quality_guard=ic_quality_guard_once,
                    sector_exposure=sector_exposure_once,
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
            score_to_rank = {}
            for i, s in enumerate(scores):
                if s not in score_to_rank:
                    score_to_rank[s] = i + 1
            for r in results:
                rank_pos = score_to_rank.get(r.sentiment_score, total)
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
                    # 用各维度的权重来计算得分率（使用实际 regime 权重，与评分时一致）
                    from src.stock_analyzer.scoring import ScoringSystem
                    _regime_str = trend_data.get('market_regime', '')
                    _regime_for_w = MarketRegime.SIDEWAYS
                    try:
                        if _regime_str:
                            _regime_for_w = MarketRegime(_regime_str)
                    except (ValueError, KeyError):
                        pass
                    default_w = ScoringSystem.REGIME_WEIGHTS.get(_regime_for_w, ScoringSystem.REGIME_WEIGHTS.get(MarketRegime.SIDEWAYS, {}))
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