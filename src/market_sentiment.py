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

import json
import logging
import re
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple

import pandas as pd

logger = logging.getLogger(__name__)

# 内存缓存（L1 层）
_sentiment_cache: Dict[str, object] = {'data': None, 'ts': 0.0}


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


def _is_market_open() -> bool:
    """判断当前是否在A股交易时段（9:30-15:00 工作日）"""
    try:
        now = datetime.now()
        if now.weekday() >= 5:
            return False
        t = now.hour * 60 + now.minute
        return 570 <= t <= 900  # 9:30=570, 15:00=900
    except Exception:
        return False


def _get_limit_threshold(code: str, name: str) -> Tuple[float, float]:
    """返回 (涨停阈值%, 跌停阈值%)，按板块和 ST 状态区分"""
    is_st = 'ST' in name.upper()
    if code.startswith(('30', '68')):       # 创业板/科创板（ST也是±20%）
        return (19.8, -19.8)
    elif code.startswith(('8', '4')):       # 北交所
        return (29.5, -29.5)
    else:                                    # 主板
        if is_st:
            return (4.9, -4.9)              # 主板ST ±5%
        return (9.9, -9.9)


def _derive_limit_from_spot() -> Optional[MarketSentiment]:
    """Level 2: 从全市场行情数据推算涨跌停家数（向量化）"""
    import akshare as ak

    df = ak.stock_zh_a_spot_em()
    if df is None or df.empty:
        return None

    code_col = df['代码'].astype(str)
    name_col = df['名称'].astype(str)
    pct_col = pd.to_numeric(df.get('涨跌幅', pd.Series(dtype=float)), errors='coerce').fillna(0.0)

    is_st = name_col.str.upper().str.contains('ST', na=False)
    is_cy_kc = code_col.str.startswith(('30', '68'))
    is_bj = code_col.str.startswith(('8', '4'))
    is_main_st = ~is_cy_kc & ~is_bj & is_st
    is_main_normal = ~is_cy_kc & ~is_bj & ~is_st

    up_thresh = pd.Series(9.9, index=df.index)
    down_thresh = pd.Series(-9.9, index=df.index)
    up_thresh[is_cy_kc] = 19.8
    down_thresh[is_cy_kc] = -19.8
    up_thresh[is_bj] = 29.5
    down_thresh[is_bj] = -29.5
    up_thresh[is_main_st] = 4.9
    down_thresh[is_main_st] = -4.9

    limit_up = int((pct_col >= up_thresh).sum())
    limit_down = int((pct_col <= down_thresh).sum())
    up_count = int((pct_col > 0).sum())
    down_count = int((pct_col < 0).sum())
    flat_count = int((pct_col == 0).sum())

    total = up_count + down_count + flat_count
    up_gt5_pct = round((pct_col > 5).sum() / total * 100, 2) if total > 0 else 0.0
    down_gt5_pct = round((pct_col < -5).sum() / total * 100, 2) if total > 0 else 0.0

    sentiment = MarketSentiment(
        limit_up_count=limit_up,
        limit_down_count=limit_down,
        up_count=up_count,
        down_count=down_count,
        flat_count=flat_count,
        up_gt5_pct=up_gt5_pct,
        down_gt5_pct=down_gt5_pct,
    )
    sentiment.temperature = calc_sentiment_temperature(
        limit_up=limit_up, limit_down=limit_down,
        up_count=up_count, down_count=down_count,
        up_gt5_pct=up_gt5_pct, broken_rate=0,
    )
    sentiment.temperature_label = get_temperature_label(sentiment.temperature)
    return sentiment


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
            logger.warning("市场情绪获取超时(12s)，10分钟内不再重试")
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
                        logger.warning(f"获取{name}失败(attempt {attempt+1})，{delay}s后重试: {e}")
                        _time.sleep(delay)
                    else:
                        logger.warning(f"获取{name}失败: {e}")
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
        logger.warning(f"_fetch_market_sentiment_inner失败: {e}")
        return None


def fetch_market_sentiment_with_fallback() -> Optional[MarketSentiment]:
    """三级 fallback 获取市场情绪

    Level 1: akshare 涨停池（已有逻辑，数据最全）
    Level 2: 全市场行情推算（无连板/炸板数据）
    Level 3: Perplexity 简报解析
    """
    # Level 1: akshare 涨停池
    sentiment = fetch_market_sentiment()
    if sentiment:
        sentiment._source = 'akshare_zt_pool'  # type: ignore[attr-defined]
        return sentiment

    # Level 2: 全市场行情推算
    try:
        sentiment = _derive_limit_from_spot()
        if sentiment:
            sentiment._source = 'spot_derived'  # type: ignore[attr-defined]
            logger.info("市场情绪: Level 2 全市场行情推算成功")
            return sentiment
    except Exception as e:
        logger.warning(f"市场情绪 Level 2 推算失败: {e}")

    # Level 3: Perplexity 简报解析
    sentiment = parse_sentiment_from_briefing()
    if sentiment:
        sentiment._source = 'perplexity_briefing'  # type: ignore[attr-defined]
    return sentiment


def get_market_sentiment_cached(db: Optional[object] = None) -> Optional[MarketSentiment]:
    """带三级缓存的市场情绪获取（L1 内存 → L2 DB → L3 网络 fallback）

    Args:
        db: DatabaseManager 实例，传 None 时自动获取
    """
    now = time.time()

    # L1 内存缓存
    l1_ttl = 300 if _is_market_open() else 1800  # 盘中5min，盘后30min
    if _sentiment_cache.get('data') and (now - _sentiment_cache.get('ts', 0)) < l1_ttl:
        return _sentiment_cache['data']  # type: ignore[return-value]

    # 确保 db 实例
    if db is None:
        try:
            from src.storage import DatabaseManager
            db = DatabaseManager.get_instance()
        except Exception:
            db = None

    # L2 DB 缓存
    if db is not None:
        try:
            from src.config import get_config
            config = get_config()
            today_str = datetime.now().strftime('%Y-%m-%d')
            cached_json = db.get_data_cache('limit_pool', today_str,
                                            ttl_hours=config.cache_ttl_sentiment_db_hours)
            if cached_json:
                data = json.loads(cached_json)
                fields = {k: v for k, v in data.items()
                          if k in MarketSentiment.__dataclass_fields__}
                sentiment = MarketSentiment(**fields)
                _sentiment_cache.update({'data': sentiment, 'ts': now})
                logger.debug("[市场情绪] L2 DB缓存命中")
                return sentiment
        except Exception as e:
            logger.debug(f"[市场情绪] L2 DB缓存读取失败: {e}")

    # L3 网络（三级 fallback）
    sentiment = fetch_market_sentiment_with_fallback()
    if sentiment:
        # 写入 DB
        if db is not None:
            try:
                today_str = datetime.now().strftime('%Y-%m-%d')
                save_data = asdict(sentiment)
                save_data['source'] = getattr(sentiment, '_source', 'unknown')
                save_data['fetched_at'] = datetime.now().isoformat()
                db.save_data_cache('limit_pool', today_str,
                                   json.dumps(save_data, ensure_ascii=False))
            except Exception as e:
                logger.debug(f"[市场情绪] DB写入失败: {e}")
        # 写入内存缓存
        _sentiment_cache.update({'data': sentiment, 'ts': now})

    return sentiment


def calc_temperature_deviation(today_temp: int, db: Optional[object] = None,
                               n: int = 10) -> Optional[float]:
    """计算今日温度相对近N日的偏离度（标准差倍数）

    Args:
        today_temp: 今日情绪温度 (0-100)
        db: DatabaseManager 实例
        n: 需要的历史样本数
    Returns:
        偏离度（正数=偏热，负数=偏冷），样本不足返回 None
    """
    if db is None:
        try:
            from src.storage import DatabaseManager
            db = DatabaseManager.get_instance()
        except Exception:
            return None

    recent: list = []
    for offset in range(1, n + 5):
        d = (datetime.now() - timedelta(days=offset)).strftime('%Y-%m-%d')
        try:
            cached = db.get_data_cache('limit_pool', d, ttl_hours=9999)  # type: ignore[union-attr]
        except Exception:
            continue
        if cached:
            try:
                recent.append(json.loads(cached).get('temperature', 50))
            except (json.JSONDecodeError, TypeError):
                continue
        if len(recent) >= n:
            break

    if len(recent) < 5:
        return None

    mean_t = sum(recent) / len(recent)
    std_t = (sum((x - mean_t) ** 2 for x in recent) / len(recent)) ** 0.5
    if std_t < 1:
        return None
    return round((today_temp - mean_t) / std_t, 2)


def _extract_limit_count(text: str, keyword: str) -> Optional[int]:
    """多模式正则提取数字（涨停/跌停/炸板家数）"""
    patterns = [
        rf'{keyword}[：:]\s*(\d+)\s*家',
        rf'{keyword}[：:]?\s*(\d+)\s*家',
        rf'{keyword}[约达共]?\s*(\d+)\s*[家只]',
        rf'{keyword}\D{{0,5}}(\d+)',
    ]
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            val = int(m.group(1))
            if 0 <= val <= 5300:
                return val
    return None


def parse_sentiment_from_briefing() -> Optional['MarketSentiment']:
    """从已缓存的 Perplexity 简报中解析涨停/跌停数量，构造 MarketSentiment 对象。
    当 akshare 接口被封/超时时作为 score_market_sentiment_adj 的 fallback。

    解析目标：涨停XX家、跌停XX家、炸板XX家（可选）
    Returns: MarketSentiment（温度已计算），或 None（解析失败）
    """
    try:
        from src.storage import DatabaseManager
        from src.config import get_config
        config = get_config()
        today = datetime.now().strftime('%Y-%m-%d')
        text = DatabaseManager.get_instance().get_data_cache(
            'market_sentiment_briefing', today,
            ttl_hours=config.cache_ttl_briefing_hours,
        )
        if not text:
            return None

        limit_up = _extract_limit_count(text, '涨停') or 0
        limit_down = _extract_limit_count(text, '跌停') or 0
        broken = _extract_limit_count(text, '炸板') or 0

        if limit_up == 0 and limit_down == 0:
            return None

        s = MarketSentiment()
        s.limit_up_count = limit_up
        s.limit_down_count = limit_down
        s.broken_limit_count = broken
        total_touched = limit_up + broken
        if total_touched > 0:
            s.broken_limit_rate = broken / total_touched * 100

        s.temperature = calc_sentiment_temperature(
            limit_up=limit_up, limit_down=limit_down,
            up_count=0, down_count=0,  # 无全量涨跌家数，只用涨停维度
            up_gt5_pct=0, broken_rate=s.broken_limit_rate
        )
        logger.debug(f"[市场情绪] 简报解析: 涨停{limit_up}跌停{limit_down}炸板{broken} → 温度{s.temperature}")
        return s
    except Exception as e:
        logger.debug(f"[市场情绪] 简报解析失败: {e}")
        return None


_BRIEFING_SYSTEM_PROMPT = (
    "你是一位A股量化交易员助手。请用【严格固定格式】输出今日A股收盘情绪快照。\n\n"
    "格式（逐行填数字，无数据填0）：\n"
    "成交额:XX亿\n"
    "涨停:XX家 跌停:XX家 炸板:XX家\n"
    "涨跌:涨XX家 跌XX家 平XX家\n"
    "情绪:一句话\n"
    "北向:净流入XX亿或净流出XX亿\n\n"
    "【硬规则】每行开头关键词和冒号不可修改，数字处填具体数字。"
    "不要分析原因，不要超过100字。非交易日只输出\"今日非交易日\"。"
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
            try:
                from src.config import get_config
                _briefing_ttl = get_config().cache_ttl_briefing_hours
            except Exception:
                _briefing_ttl = 6.0
            cached = db.get_data_cache(_DB_TYPE, _DB_KEY, ttl_hours=_briefing_ttl)
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
