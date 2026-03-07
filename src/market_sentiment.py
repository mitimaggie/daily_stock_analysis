# -*- coding: utf-8 -*-
"""
市场情绪温度计模块 (Q5)

量化A股赚钱效应，比大盘指数更能反映散户实际体感：
- 涨停家数 vs 跌停家数
- 涨幅>5%的股票占比
- 连板股数量
- 炸板率
- 情绪温度 (0-100)
"""

import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class MarketSentiment:
    """市场情绪快照"""
    # 涨跌停数据
    limit_up_count: int = 0       # 涨停家数
    limit_down_count: int = 0     # 跌停家数
    # 涨跌分布
    up_gt5_pct: float = 0.0      # 涨幅>5%的股票占比(%)
    down_gt5_pct: float = 0.0    # 跌幅>5%的股票占比(%)
    up_count: int = 0            # 上涨家数
    down_count: int = 0          # 下跌家数
    flat_count: int = 0          # 平盘家数
    # 连板数据
    continuous_limit_count: int = 0  # 连板股数量(>=2板)
    highest_board: int = 0       # 最高连板数
    # 炸板率
    broken_limit_count: int = 0  # 炸板家数(曾涨停后打开)
    broken_limit_rate: float = 0.0  # 炸板率(%)
    # 综合情绪温度 (0-100)
    temperature: int = 50        # 50=中性, >70=贪婪, <30=恐惧
    temperature_label: str = "中性"  # 极度恐惧/恐惧/中性/贪婪/极度贪婪
    # 文本描述
    summary: str = ""

    def to_context_string(self) -> str:
        """生成供LLM和推送使用的文本"""
        lines = [
            f"🌡️ 市场情绪温度: {self.temperature}/100 ({self.temperature_label})",
            f"涨停{self.limit_up_count}家 跌停{self.limit_down_count}家 | 上涨{self.up_count} 下跌{self.down_count} 平盘{self.flat_count}",
        ]
        if self.up_gt5_pct > 0 or self.down_gt5_pct > 0:
            lines.append(f"涨>5%占比{self.up_gt5_pct:.1f}% 跌>5%占比{self.down_gt5_pct:.1f}%")
        if self.continuous_limit_count > 0:
            lines.append(f"连板股{self.continuous_limit_count}只(最高{self.highest_board}板)")
        if self.broken_limit_count > 0:
            lines.append(f"炸板{self.broken_limit_count}家(炸板率{self.broken_limit_rate:.0f}%)")
        if self.summary:
            lines.append(self.summary)
        return "\n".join(lines)


def calc_sentiment_temperature(limit_up: int, limit_down: int,
                                up_count: int, down_count: int,
                                up_gt5_pct: float = 0,
                                broken_rate: float = 0) -> int:
    """
    计算情绪温度 (0-100)
    
    核心逻辑：
    - 涨停/跌停比 (权重40%)
    - 涨跌家数比 (权重30%)
    - 涨幅>5%占比 (权重20%)
    - 炸板率反向 (权重10%)
    """
    # 1. 涨跌停比 (0-100)
    total_limit = limit_up + limit_down
    if total_limit > 0:
        limit_score = limit_up / total_limit * 100
    else:
        limit_score = 50

    # 2. 涨跌家数比 (0-100)
    total_stocks = up_count + down_count
    if total_stocks > 0:
        advance_score = up_count / total_stocks * 100
    else:
        advance_score = 50

    # 3. 涨幅>5%占比 (0-100, 映射: 0%->30, 5%->50, 15%->80, 30%->100)
    gt5_score = min(100, 30 + up_gt5_pct * 2.3)

    # 4. 炸板率反向 (0-100, 炸板率高=情绪差)
    broken_score = max(0, 100 - broken_rate * 2)

    # 加权
    temperature = int(
        limit_score * 0.4 +
        advance_score * 0.3 +
        gt5_score * 0.2 +
        broken_score * 0.1
    )
    return max(0, min(100, temperature))


def get_temperature_label(temp: int) -> str:
    """温度标签"""
    if temp >= 80:
        return "极度贪婪"
    elif temp >= 65:
        return "贪婪"
    elif temp >= 45:
        return "中性"
    elif temp >= 25:
        return "恐惧"
    else:
        return "极度恐惧"


_SENTIMENT_FAIL_TS: float = 0.0
_SENTIMENT_FAIL_BACKOFF: float = 600.0  # 10分钟内失败不重试


def fetch_market_sentiment() -> Optional[MarketSentiment]:
    """
    获取市场情绪数据（从akshare获取涨跌停统计）
    
    Returns:
        MarketSentiment 或 None
    """
    import time as _time
    global _SENTIMENT_FAIL_TS
    if (_time.time() - _SENTIMENT_FAIL_TS) < _SENTIMENT_FAIL_BACKOFF:
        return None
    try:
        from concurrent.futures import ThreadPoolExecutor, TimeoutError as _FuturesTimeout
        _ex = ThreadPoolExecutor(max_workers=1)
        try:
            result = _ex.submit(_fetch_market_sentiment_inner).result(timeout=12)
        except _FuturesTimeout:
            logger.debug("市场情绪获取超时(12s)，10分钟内不再重试")
            _SENTIMENT_FAIL_TS = _time.time()
            return None
        finally:
            _ex.shutdown(wait=False)
        if result is None:
            _SENTIMENT_FAIL_TS = _time.time()
        return result
    except Exception as e:
        logger.warning(f"获取市场情绪失败: {e}")
        _SENTIMENT_FAIL_TS = _time.time()
        return None


def _fetch_market_sentiment_inner() -> Optional[MarketSentiment]:
    """内部实现，由 fetch_market_sentiment 的超时线程调用"""
    try:
        import akshare as ak
        
        sentiment = MarketSentiment()
        
        import time as _time

        def _retry_call(fn, name: str, max_retries: int = 2, delay: float = 2.0):
            """SSL/连接错误自动重试（最多 max_retries 次，间隔 delay 秒）"""
            last_err = None
            for attempt in range(max_retries):
                try:
                    return fn()
                except Exception as e:
                    last_err = e
                    err_str = str(e).lower()
                    is_transient = any(k in err_str for k in ('ssl', 'connection', 'remote end', 'eof', 'timeout', 'tls'))
                    if is_transient and attempt < max_retries - 1:
                        logger.debug(f"获取{name}失败(attempt {attempt+1})，{delay}s后重试: {e}")
                        _time.sleep(delay)
                    else:
                        logger.debug(f"获取{name}失败: {e}")
                        return None
            return None

        # 获取涨跌停统计
        df_limit = _retry_call(lambda: ak.stock_zt_pool_em(date=None), "涨停池")
        if df_limit is not None and not df_limit.empty:
            sentiment.limit_up_count = len(df_limit)
            if '连板数' in df_limit.columns:
                boards = df_limit['连板数'].astype(int)
                sentiment.continuous_limit_count = int((boards >= 2).sum())
                sentiment.highest_board = int(boards.max()) if len(boards) > 0 else 0

        df_dt = _retry_call(lambda: ak.stock_zt_pool_dtgc_em(date=None), "跌停池")
        if df_dt is not None and not df_dt.empty:
            sentiment.limit_down_count = len(df_dt)

        # 炸板数据
        df_zb = _retry_call(lambda: ak.stock_zt_pool_zbgc_em(date=None), "炸板池")
        if df_zb is not None and not df_zb.empty:
            sentiment.broken_limit_count = len(df_zb)
            total_touched = sentiment.limit_up_count + sentiment.broken_limit_count
            if total_touched > 0:
                sentiment.broken_limit_rate = sentiment.broken_limit_count / total_touched * 100

        # 涨跌家数：优先复用 akshare_fetcher 已缓存的全市场数据，避免重复下载
        df_market = None
        try:
            from data_provider.akshare_fetcher import _realtime_cache
            import time as _tc
            if (_realtime_cache.get('data') is not None and
                    _tc.time() - _realtime_cache.get('timestamp', 0) < _realtime_cache.get('ttl', 1200)):
                df_market = _realtime_cache['data']
        except Exception:
            pass
        if df_market is not None and not df_market.empty:
            if '涨跌幅' in df_market.columns:
                pct_col = df_market['涨跌幅'].astype(float)
                sentiment.up_count = int((pct_col > 0).sum())
                sentiment.down_count = int((pct_col < 0).sum())
                sentiment.flat_count = int((pct_col == 0).sum())
                total = len(pct_col)
                if total > 0:
                    sentiment.up_gt5_pct = (pct_col > 5).sum() / total * 100
                    sentiment.down_gt5_pct = (pct_col < -5).sum() / total * 100

        # 计算情绪温度
        sentiment.temperature = calc_sentiment_temperature(
            sentiment.limit_up_count, sentiment.limit_down_count,
            sentiment.up_count, sentiment.down_count,
            sentiment.up_gt5_pct, sentiment.broken_limit_rate
        )
        sentiment.temperature_label = get_temperature_label(sentiment.temperature)

        # 生成摘要
        if sentiment.temperature >= 70:
            sentiment.summary = "🔥 市场情绪高涨，赚钱效应强，但需警惕过热回调"
        elif sentiment.temperature >= 55:
            sentiment.summary = "📈 市场情绪偏暖，赚钱效应尚可，可积极参与"
        elif sentiment.temperature >= 40:
            sentiment.summary = "😐 市场情绪中性，赚钱效应一般，精选个股"
        elif sentiment.temperature >= 25:
            sentiment.summary = "📉 市场情绪偏冷，亏钱效应明显，控制仓位"
        else:
            sentiment.summary = "❄️ 市场极度恐惧，多数股票下跌，建议空仓观望"

        return sentiment

    except ImportError:
        logger.debug("akshare未安装，跳过市场情绪获取")
        return None
    except Exception as e:
        logger.debug(f"_fetch_market_sentiment_inner失败: {e}")
        return None


_BRIEFING_SYSTEM_PROMPT = (
    "你是一位A股量化交易员助手，每日收盘后出具简洁的市场情绪日报。\n"
    "【输出格式（100字以内，严格简短）】\n"
    "- 成交额：XX亿（与昨日相比是放量/缩量）\n"
    "- 涨跌家数：涨XX跌XX平XX，涨停XX家，跌停XX家\n"
    "- 市场情绪：一句话定性（如\"做多情绪偏暖\"，\"恐慷踩踏\"，\"中性震荡\"）\n"
    "- 主力资金：北向/南向/ETF净流入或流出多少亿（如有）\n"
    "严格只给数字和结论，不要分析原因，不要超过150字。如没有当日数据则说\"暂无今日数据\""
)


def fetch_market_sentiment_briefing(force_refresh: bool = False) -> Optional[str]:
    """通过 Perplexity 获取当日市场情绪简报（两市成交额/涨跌家数/资金动向），
    结果缓存4小时到 SQLite，供 pipeline 注入 LLM 上下文。
    
    Returns:
        str: 简报文字，如 "成交额9800亿，涨1823跌1621平402，涨停47家，情绪中性偏暖，北向净流入8亿。"
        None: Perplexity未配置或获取失败
    """
    import time as _t
    from datetime import datetime
    _DB_TYPE = 'market_sentiment_briefing'
    _DB_KEY = datetime.now().strftime('%Y-%m-%d')

    try:
        from src.storage import DatabaseManager
        db = DatabaseManager.get_instance()

        if not force_refresh:
            cached = db.get_data_cache(_DB_TYPE, _DB_KEY, ttl_hours=4.0)
            if cached:
                logger.debug(f"[市场情绪简报] 命中缓存: {cached[:60]}...")
                return cached
    except Exception:
        db = None

    try:
        import os
        pplx_key = os.getenv("PERPLEXITY_API_KEY")
        if not pplx_key:
            logger.debug("[市场情绪简报] 未配置 PERPLEXITY_API_KEY，跳过")
            return None

        from src.search_service import PerplexitySearchProvider
        provider = PerplexitySearchProvider([pplx_key])
        today = datetime.now().strftime("%Y年%m月%d日")
        query = f"{today} A股市场今日行情：两市成交额、涨跌家数、涨停跌停数量、北向资金净流入"
        resp = provider.search(query, model="sonar", system_prompt_override=_BRIEFING_SYSTEM_PROMPT)

        if resp.success and resp.results:
            import re as _re
            content = _re.sub(r'\[\d+\]', '', resp.results[0].snippet).strip()
            if db:
                try:
                    db.save_data_cache(_DB_TYPE, _DB_KEY, content)
                except Exception:
                    pass
            logger.info(f"[市场情绪简报] 获取成功: {content[:80]}...")
            return content
        else:
            logger.debug(f"[市场情绪简报] Perplexity 返回失败: {resp.error_message}")
            return None
    except Exception as e:
        logger.debug(f"[市场情绪简报] 异常: {e}")
        return None
