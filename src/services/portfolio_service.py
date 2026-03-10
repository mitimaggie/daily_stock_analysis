# -*- coding: utf-8 -*-
"""
持仓管理 & 监控服务

功能：
1. 持仓 CRUD（增删改查）
2. 关注股 CRUD
3. 持仓监控：拉取实时价格、计算ATR追踪止损、生成操作信号
4. 分时分析辅助（调用 intraday_fetcher + intraday_analyzer）
"""

import logging
from datetime import datetime, date
from typing import Optional, List, Dict, Any

import pandas as pd
from sqlalchemy import select, desc

from src.storage import DatabaseManager, Portfolio, PortfolioLog, Watchlist

logger = logging.getLogger(__name__)


def _ensure_daily_data(code: str, min_rows: int = 20) -> None:
    """确保 stock_daily 表有足够的日线数据供 ATR 计算。

    添加持仓时自动检查并补充日线数据，避免新股票因无历史数据导致 ATR 止损为 0。
    使用 DataFetcherManager 自动走优先级 fallback（ETF 由 baostock 接管）。
    """
    try:
        from src.storage import StockDaily
        from sqlalchemy import func
        db = DatabaseManager.get_instance()
        with db.get_session() as session:
            count = session.execute(
                select(func.count()).select_from(StockDaily).where(StockDaily.code == code)
            ).scalar() or 0
        if count >= min_rows:
            return

        from data_provider.base import DataFetcherManager
        manager = DataFetcherManager()
        df, source_name = manager.get_daily_data(code, days=120)
        if df is not None and not df.empty:
            saved = db.save_daily_data(df, code, data_source=source_name)
            logger.info("[portfolio] 自动拉取日线 %s: %d 条入库(source=%s)", code, saved, source_name)
        else:
            logger.warning("[portfolio] 自动拉取日线 %s 返回空数据，止损计算将不可用", code)
    except Exception as e:
        logger.warning("[portfolio] 自动拉取日线 %s 异常: %s", code, e)


# ─────────────────────────────────────────────
# 持仓 CRUD
# ─────────────────────────────────────────────

def get_ai_horizon_suggestion(code: str) -> Optional[str]:
    """从最近一次分析记录中提取 AI 建议的持仓周期，供前端自动预填。

    从 analysis_history.raw_result 里的 battle_plan.holding_horizon 提取。
    """
    try:
        import json
        from src.storage import AnalysisHistory
        from sqlalchemy import desc
        db = DatabaseManager.get_instance()
        with db.get_session() as session:
            rec = session.execute(
                select(AnalysisHistory)
                .where(AnalysisHistory.code == code)
                .order_by(desc(AnalysisHistory.created_at))
                .limit(1)
            ).scalar_one_or_none()
        if not rec or not rec.raw_result:
            return None
        raw = json.loads(rec.raw_result)
        horizon = (
            raw.get('dashboard', {}).get('battle_plan', {}).get('holding_horizon')
            or raw.get('battle_plan', {}).get('holding_horizon')
        )
        return horizon if horizon else None
    except Exception:
        return None


def add_portfolio(
    code: str,
    name: str,
    cost_price: float,
    shares: int = 0,
    entry_date: Optional[date] = None,
    notes: str = '',
    holding_horizon_label: Optional[str] = None,
) -> Dict[str, Any]:
    """新增持仓（已存在则更新成本价和数量）。
    name 为空时自动通过 baostock 查询股票名称。
    holding_horizon_label 为 None 时尝试从 AI 历史分析记录自动提取。
    """
    if not name or not name.strip():
        try:
            from data_provider.baostock_fetcher import BaostockFetcher
            fetcher = BaostockFetcher()
            name = fetcher.get_stock_name(code) or code
        except Exception:
            name = code

    if holding_horizon_label is None:
        holding_horizon_label = get_ai_horizon_suggestion(code)

    db = DatabaseManager.get_instance()
    with db.get_session() as session:
        existing = session.execute(
            select(Portfolio).where(Portfolio.code == code)
        ).scalar_one_or_none()

        if existing:
            existing.cost_price = cost_price
            existing.shares = shares
            existing.entry_date = entry_date or existing.entry_date
            existing.notes = notes or existing.notes
            existing.name = name or existing.name
            if holding_horizon_label:
                existing.holding_horizon_label = holding_horizon_label
            existing.updated_at = datetime.now()
            session.commit()
            session.refresh(existing)
            _ensure_daily_data(code)
            return existing.to_dict()
        else:
            record = Portfolio(
                code=code,
                name=name,
                cost_price=cost_price,
                shares=shares,
                entry_date=entry_date or date.today(),
                notes=notes,
                holding_horizon_label=holding_horizon_label,
            )
            session.add(record)
            session.commit()
            session.refresh(record)
            _ensure_daily_data(code)
            return record.to_dict()


def remove_portfolio(code: str) -> bool:
    """删除持仓"""
    db = DatabaseManager.get_instance()
    with db.get_session() as session:
        record = session.execute(
            select(Portfolio).where(Portfolio.code == code)
        ).scalar_one_or_none()
        if record:
            session.delete(record)
            session.commit()
            return True
        return False


def list_portfolio() -> List[Dict[str, Any]]:
    """获取所有持仓"""
    db = DatabaseManager.get_instance()
    with db.get_session() as session:
        records = session.execute(
            select(Portfolio).order_by(Portfolio.created_at)
        ).scalars().all()
        return [r.to_dict() for r in records]


def get_portfolio(code: str) -> Optional[Dict[str, Any]]:
    """获取单只持仓"""
    db = DatabaseManager.get_instance()
    with db.get_session() as session:
        record = session.execute(
            select(Portfolio).where(Portfolio.code == code)
        ).scalar_one_or_none()
        return record.to_dict() if record else None


def get_position_info_for_analysis(code: str) -> Optional[Dict[str, Any]]:
    """
    获取适合注入分析流水线的持仓上下文。

    在 get_portfolio 基础上额外计算：
    - holding_days: 持仓天数（今日 - 买入日期）
    - position_amount: 持仓市值估算（成本价 × 股数）

    Returns:
        position_info dict，可直接传给 pipeline/analyzer；若无持仓返回 None。
    """
    record = get_portfolio(code)
    if not record:
        return None

    cost_price = float(record.get('cost_price') or 0)
    shares = int(record.get('shares') or 0)

    holding_days = None
    entry_date_str = record.get('entry_date')
    if entry_date_str:
        try:
            from datetime import date as _date
            entry = _date.fromisoformat(entry_date_str)
            holding_days = (_date.today() - entry).days
        except Exception:
            pass

    position_amount = cost_price * shares if cost_price > 0 and shares > 0 else 0

    return {
        'cost_price': cost_price,
        'shares': shares,
        'position_amount': position_amount,
        'holding_days': holding_days,
        'entry_date': entry_date_str,
        'notes': record.get('notes', ''),
    }


def get_portfolio_sector_risk(current_code: str) -> Optional[Dict[str, Any]]:
    """
    计算持仓组合的板块集中度风险，并判断当前股票是否处于集中板块中。

    思路：
    1. 从 portfolio 表获取所有持仓股票代码
    2. 对每只股票，查询最近一条 analysis_history 中的 sector_context，提取板块名
    3. 按板块分组，统计各板块持股数
    4. 返回当前股票所在板块 + 同板块其他持仓 + 集中度告警

    Returns:
        {
            'current_sector': '白酒Ⅱ',
            'portfolio_sector_map': {'白酒Ⅱ': ['000858', '600519'], ...},
            'same_sector_peers': ['600519'],        # 同板块其他持仓（不含自己）
            'concentration_warning': '⚠️ 已持有同板块 1 只: 600519',  # 或 None
        }
        若无持仓或无板块数据返回 None。
    """
    try:
        from sqlalchemy import text as _text
        db = DatabaseManager.get_instance()

        # 1. 获取所有持仓代码
        with db.get_session() as session:
            rows = session.execute(_text("SELECT code FROM portfolio")).fetchall()
        all_codes = [r[0] for r in rows]
        if not all_codes:
            return None

        # 2. 对每只股票取最近一条 sector_context
        sector_map: Dict[str, str] = {}  # code -> sector_name
        with db.get_session() as session:
            for code in all_codes:
                row = session.execute(_text(
                    "SELECT json_extract(context_snapshot, '$.sector_context') "
                    "FROM analysis_history "
                    "WHERE code=:code AND context_snapshot IS NOT NULL "
                    "ORDER BY created_at DESC LIMIT 1"
                ), {"code": code}).fetchone()
                if row and row[0]:
                    import json as _json
                    sc = _json.loads(row[0]) if isinstance(row[0], str) else row[0]
                    sname = sc.get('sector_name') if isinstance(sc, dict) else None
                    if sname:
                        sector_map[code] = sname

        if not sector_map:
            return None

        # 3. 按板块分组
        portfolio_sector_map: Dict[str, list] = {}
        for code, sector in sector_map.items():
            portfolio_sector_map.setdefault(sector, []).append(code)

        # 4. 当前股票的板块
        current_sector = sector_map.get(current_code)

        same_sector_peers = []
        concentration_warning = None
        if current_sector:
            peers = [c for c in portfolio_sector_map.get(current_sector, []) if c != current_code]
            same_sector_peers = peers
            if peers:
                concentration_warning = (
                    f"⚠️ 板块集中风险: 已持有同属「{current_sector}」板块的 {len(peers)} 只股票: "
                    f"{', '.join(peers)}。同板块持仓集中，面临板块系统性风险。"
                )

        return {
            'current_sector': current_sector,
            'portfolio_sector_map': portfolio_sector_map,
            'same_sector_peers': same_sector_peers,
            'concentration_warning': concentration_warning,
        }
    except Exception as e:
        import logging as _log
        _log.getLogger(__name__).debug(f"get_portfolio_sector_risk({current_code}) failed: {e}")
        return None


# ─────────────────────────────────────────────
# 关注股 CRUD
# ─────────────────────────────────────────────

def _resolve_stock_name(code: str) -> str:
    """当 name 为空时，从本地数据库或数据源解析股票名称。优先本地，避免额外网络请求。

    查找顺序：
    1. analysis_history 表（最近一条记录）
    2. AkshareFetcher 实时行情接口（含 name）
    3. 失败则返回空字符串

    Note: stock_daily 表无 name 列，故仅查 analysis_history。
    """
    if not code or not str(code).strip():
        return ''
    from src.storage import AnalysisHistory
    db = DatabaseManager.get_instance()
    with db.get_session() as session:
        rec = session.execute(
            select(AnalysisHistory)
            .where(AnalysisHistory.code == code)
            .order_by(desc(AnalysisHistory.created_at))
            .limit(1)
        ).scalar_one_or_none()
        if rec and rec.name and str(rec.name).strip():
            return str(rec.name).strip()
    try:
        from data_provider.akshare_fetcher import AkshareFetcher
        fetcher = AkshareFetcher()
        quote = fetcher.get_realtime_quote(code)
        if quote and quote.name and str(quote.name).strip():
            return str(quote.name).strip()
    except Exception:
        pass
    return ''


def add_watchlist(code: str, name: str, notes: str = '') -> Dict[str, Any]:
    """新增关注股（已存在则仅更新备注）。

    当传入的 name 为空时，自动从 analysis_history 或 AkshareFetcher 实时行情解析股票名称填充。
    """
    effective_name = (name or '').strip()
    if not effective_name:
        effective_name = _resolve_stock_name(code)

    db = DatabaseManager.get_instance()
    with db.get_session() as session:
        existing = session.execute(
            select(Watchlist).where(Watchlist.code == code)
        ).scalar_one_or_none()

        if existing:
            existing.name = effective_name or existing.name
            existing.notes = notes or existing.notes
            existing.updated_at = datetime.now()
            session.commit()
            session.refresh(existing)
            return existing.to_dict()
        else:
            record = Watchlist(code=code, name=effective_name, notes=notes)
            session.add(record)
            session.commit()
            session.refresh(record)
            return record.to_dict()


def remove_watchlist(code: str) -> bool:
    """删除关注股"""
    db = DatabaseManager.get_instance()
    with db.get_session() as session:
        record = session.execute(
            select(Watchlist).where(Watchlist.code == code)
        ).scalar_one_or_none()
        if record:
            session.delete(record)
            session.commit()
            return True
        return False


def list_watchlist(sort_by: str = 'score') -> List[Dict[str, Any]]:
    """获取所有关注股（支持按评分排序）"""
    db = DatabaseManager.get_instance()
    with db.get_session() as session:
        records = session.execute(
            select(Watchlist).order_by(Watchlist.created_at)
        ).scalars().all()
        items = [r.to_dict() for r in records]

    if sort_by == 'score':
        items.sort(key=lambda x: (x.get('last_score') or 0), reverse=True)
    elif sort_by == 'change':
        items.sort(key=lambda x: (x.get('score_change') or 0), reverse=True)

    return items


def update_watchlist_analysis(code: str, score: int, advice: str, summary: str) -> bool:
    """分析完成后更新关注股的评分快照"""
    db = DatabaseManager.get_instance()
    with db.get_session() as session:
        record = session.execute(
            select(Watchlist).where(Watchlist.code == code)
        ).scalar_one_or_none()
        if not record:
            return False
        record.prev_score = record.last_score
        record.last_score = score
        record.last_advice = advice
        record.last_summary = summary
        record.last_analyzed_at = datetime.now()
        record.updated_at = datetime.now()
        session.commit()
        return True


# ─────────────────────────────────────────────
# 持仓监控核心
# ─────────────────────────────────────────────

def _get_realtime_price(code: str) -> Optional[float]:
    """获取实时价格（复用 AkshareFetcher 的统一实时行情接口）"""
    try:
        from data_provider.akshare_fetcher import AkshareFetcher
        fetcher = AkshareFetcher()
        quote = fetcher.get_realtime_quote(code)
        if quote and quote.price:
            return float(quote.price)
    except Exception:
        pass
    return None


def _get_kline_df(code: str) -> Optional[pd.DataFrame]:
    """获取历史日线K线（用于ATR计算）"""
    try:
        from src.storage import DatabaseManager, StockDaily
        db = DatabaseManager.get_instance()
        with db.get_session() as session:
            rows = session.execute(
                select(StockDaily)
                .where(StockDaily.code == code)
                .order_by(desc(StockDaily.date))
                .limit(60)
            ).scalars().all()
        if not rows:
            return None
        data = [{
            'date': r.date, 'open': r.open, 'high': r.high,
            'low': r.low, 'close': r.close, 'volume': r.volume,
        } for r in rows]
        df = pd.DataFrame(data).sort_values('date').reset_index(drop=True)
        return df
    except Exception as e:
        logger.warning(f"[portfolio] 获取K线失败 {code}: {e}")
        return None


def _push_stop_loss_alert(
    code: str,
    name: str,
    current_price: float,
    atr_stop: float,
    pnl_pct: float,
    reasons: List[str],
) -> None:
    """向 PushPlus 和 Web 通知推送止损警报（非阻塞，失败静默忽略）"""
    try:
        title = f"🔴 止损警报：{name}({code})"
        reasons_text = '\n'.join(f'- {r}' for r in reasons)
        content = (
            f"## {title}\n\n"
            f"**当前价格**：{current_price:.2f}\n"
            f"**ATR止损线**：{atr_stop:.2f}\n"
            f"**浮盈/亏**：{pnl_pct:+.1f}%\n\n"
            f"**触发原因**：\n{reasons_text}\n\n"
            f"⚠️ 建议立即检查是否需要止损出场。"
        )
        from src.notification import NotificationManager
        nm = NotificationManager.get_instance()
        nm.send_to_pushplus(content=content, title=title)
    except Exception as e:
        logger.debug(f"[portfolio] 止损推送失败（非致命）: {e}")


def _generate_monitor_signal(
    code: str,
    cost_price: float,
    current_price: float,
    atr_stop: float,
    pnl_pct: float,
    stop_pnl_pct: float,
    intraday_info: Dict[str, Any],
) -> Dict[str, Any]:
    """
    根据价格、ATR止损、分时信号生成操作建议

    信号优先级：
    1. 止损触发 → stop_loss（最高优先级）
    2. 分时主力出货 + 浮盈>5% → reduce（减仓）
    3. 尾盘放量拉升 → add_watch（加仓关注）
    4. 其他 → hold
    """
    signal = 'hold'
    reasons = []

    stop_triggered = current_price <= atr_stop and atr_stop > 0

    if stop_triggered:
        signal = 'stop_loss'
        reasons.append(f'🔴 价格{current_price:.2f}跌破ATR止损线{atr_stop:.2f}，建议止损')
    else:
        # 分时信号辅助判断
        intraday_signal = intraday_info.get('monitor_signal', '')
        if intraday_signal == 'distribute' and pnl_pct > 5:
            signal = 'reduce'
            reasons.append(f'🟡 分时主力出货特征（量比放大+价格高位震荡），浮盈{pnl_pct:.1f}%，建议减仓50%')
        elif intraday_signal == 'pullback_rally':
            signal = 'hold'
            reasons.append(f'🟢 尾盘放量拉升，持有信号增强')
        elif pnl_pct < -7:
            signal = 'stop_loss'
            reasons.append(f'🔴 浮亏{abs(pnl_pct):.1f}%超过7%硬止损阈值，建议止损')
        else:
            reasons.append(f'⚪ 持仓稳定，浮盈{pnl_pct:+.1f}%，ATR止损线{atr_stop:.2f}（锁住浮盈{stop_pnl_pct:+.1f}%）')

    return {
        'signal': signal,
        'reasons': reasons,
        'signal_text': '止损' if signal == 'stop_loss' else ('减仓' if signal == 'reduce' else ('加仓观察' if signal == 'add_watch' else '持有')),
    }


def _analyze_intraday_for_monitor(code: str) -> Dict[str, Any]:
    """
    为持仓监控生成分时信号（主力行为判断）

    Returns 精简版信号：
    - monitor_signal: "distribute"（出货）/ "pullback_rally"（尾盘拉升）/ ""
    - vwap: float
    - vwap_position: str
    - intraday_trend: str
    - volume_distribution: str
    """
    try:
        from data_provider.intraday_fetcher import analyze_intraday
        base = analyze_intraday(code, period='5')

        result = {
            'monitor_signal': '',
            'vwap': base.get('intraday_vwap', 0),
            'vwap_position': base.get('vwap_position', ''),
            'intraday_trend': base.get('intraday_trend', ''),
            'volume_distribution': base.get('volume_distribution', ''),
            'momentum': base.get('momentum', ''),
            'summary': base.get('summary', ''),
        }

        now_h = datetime.now().hour
        now_m = datetime.now().minute

        # 尾盘（14:30后）量价判断
        if now_h >= 14 and now_m >= 30:
            if base.get('volume_distribution') == '尾盘放量' and base.get('intraday_trend') == '分时上攻':
                result['monitor_signal'] = 'pullback_rally'
            elif base.get('volume_distribution') == '尾盘放量' and base.get('intraday_trend') == '分时下跌':
                result['monitor_signal'] = 'distribute'
        # 全天：加速下跌 + 早盘/尾盘放量 → 主力出货特征
        elif base.get('momentum') == '加速下跌' and base.get('volume_distribution') in ('早盘放量', '尾盘放量'):
            result['monitor_signal'] = 'distribute'

        return result
    except Exception as e:
        logger.debug(f"[portfolio intraday] {code} 分时分析失败: {e}")
        return {'monitor_signal': '', 'vwap': 0, 'vwap_position': '', 'intraday_trend': '', 'volume_distribution': '', 'momentum': '', 'summary': ''}


def _get_beta_from_analysis(code: str) -> float:
    """从最近一次分析记录中提取 Beta 系数，找不到时降级为 1.0。"""
    try:
        import json
        from src.storage import AnalysisHistory
        db = DatabaseManager.get_instance()
        with db.get_session() as session:
            rec = session.execute(
                select(AnalysisHistory)
                .where(AnalysisHistory.code == code)
                .order_by(desc(AnalysisHistory.created_at))
                .limit(1)
            ).scalar_one_or_none()
        if not rec or not rec.raw_result:
            logger.debug("[beta] %s 无分析记录，使用默认 beta=1.0", code)
            return 1.0
        raw = json.loads(rec.raw_result)
        beta = (raw.get('dashboard', {}).get('quant_extras', {}).get('beta_vs_index')
                or 1.0)
        return float(beta)
    except Exception:
        logger.debug("[beta] %s 获取 beta 失败，使用默认 1.0", code)
        return 1.0


def _process_single_holding(holding) -> Optional[Dict[str, Any]]:
    """处理单只持仓的实时监控：拉取价格、计算ATR止损、生成操作信号、写回数据库。"""
    from src.stock_analyzer.risk_management import RiskManager

    code = holding.code
    cost_price = holding.cost_price
    current_price = _get_realtime_price(code)

    if current_price is None:
        return {
            'code': code,
            'name': holding.name,
            'cost_price': cost_price,
            'current_price': None,
            'signal': 'unknown',
            'signal_text': '数据获取失败',
            'reasons': ['⚪ 无法获取实时价格'],
            'atr_stop': holding.atr_stop_loss,
            'pnl_pct': None,
        }

    beta = _get_beta_from_analysis(code)
    df = _get_kline_df(code)
    atr_result = RiskManager.calc_atr_trailing_stop(
        df=df,
        cost_price=cost_price,
        current_price=current_price,
        prev_atr_stop=holding.atr_stop_loss,
        prev_highest=holding.highest_price,
        beta=beta,
    ) if df is not None else {
        'atr': 0, 'atr_stop': holding.atr_stop_loss or 0,
        'highest_price': current_price, 'stop_triggered': False,
        'pnl_pct': (current_price - cost_price) / cost_price * 100 if cost_price > 0 else 0,
        'stop_pnl_pct': 0,
        'phase': 'protect_cost',
    }

    _now = datetime.now()
    _h, _m = _now.hour, _now.minute
    is_intraday = (
        (_h == 9 and _m >= 30) or
        (_h == 10) or
        (_h == 11 and _m < 30) or
        (13 <= _h < 15)
    )
    intraday_info = _analyze_intraday_for_monitor(code) if is_intraday else {}

    signal_info = _generate_monitor_signal(
        code=code,
        cost_price=cost_price,
        current_price=current_price,
        atr_stop=atr_result['atr_stop'],
        pnl_pct=atr_result['pnl_pct'],
        stop_pnl_pct=atr_result['stop_pnl_pct'],
        intraday_info=intraday_info,
    )

    prev_signal = holding.last_signal or ''
    new_signal = signal_info['signal']
    if new_signal == 'stop_loss' and prev_signal != 'stop_loss':
        _push_stop_loss_alert(
            code=code,
            name=holding.name,
            current_price=current_price,
            atr_stop=atr_result['atr_stop'],
            pnl_pct=atr_result['pnl_pct'],
            reasons=signal_info['reasons'],
        )
        try:
            add_portfolio_log(
                code=code,
                action='stop_exit',
                price=current_price,
                reason=f"ATR止损触发 止损线:{atr_result['atr_stop']:.2f}",
                triggered_by='stop_loss',
            )
        except Exception:
            pass

    db = DatabaseManager.get_instance()
    with db.get_session() as session:
        record = session.execute(
            select(Portfolio).where(Portfolio.code == code)
        ).scalar_one_or_none()
        if record:
            record.atr_stop_loss = atr_result['atr_stop']
            record.highest_price = atr_result['highest_price']
            record.last_signal = signal_info['signal']
            record.last_signal_reason = '\n'.join(signal_info['reasons'])
            record.last_monitored_at = datetime.now()
            session.commit()

    return {
        'code': code,
        'name': holding.name,
        'cost_price': cost_price,
        'shares': holding.shares,
        'entry_date': holding.entry_date.isoformat() if holding.entry_date else None,
        'current_price': current_price,
        'pnl_pct': atr_result['pnl_pct'],
        'atr': atr_result['atr'],
        'atr_stop': atr_result['atr_stop'],
        'highest_price': atr_result['highest_price'],
        'stop_pnl_pct': atr_result['stop_pnl_pct'],
        'signal': signal_info['signal'],
        'signal_text': signal_info['signal_text'],
        'reasons': signal_info['reasons'],
        'intraday': intraday_info,
        'last_monitored_at': datetime.now().isoformat(),
    }


def monitor_portfolio() -> List[Dict[str, Any]]:
    """
    遍历所有持仓，获取实时价格、更新ATR止损、生成信号。

    使用 ThreadPoolExecutor 并行处理，max_workers=3 避免触发数据源限流。
    每次调用后将最新止损价和信号写回数据库。
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    db = DatabaseManager.get_instance()
    with db.get_session() as session:
        holdings = session.execute(select(Portfolio)).scalars().all()
        holdings_list = [h for h in holdings]

    if not holdings_list:
        return []

    results = []
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {executor.submit(_process_single_holding, item): item for item in holdings_list}
        for future in as_completed(futures):
            item = futures[future]
            try:
                result = future.result(timeout=25)
                if result:
                    results.append(result)
            except Exception as e:
                logger.warning("监控处理失败 %s: %s", item.code, e)

    return results


# ─────────────────────────────────────────────
# 持仓操作日志
# ─────────────────────────────────────────────

def add_portfolio_log(
    code: str,
    action: str,
    price: Optional[float] = None,
    shares: Optional[int] = None,
    reason: str = '',
    triggered_by: str = 'manual',
) -> Dict[str, Any]:
    """记录一条持仓操作日志。
    action: buy/add/reduce/stop_exit/take_profit/manual
    triggered_by: manual/monitor_ai/stop_loss
    """
    db = DatabaseManager.get_instance()
    with db.get_session() as session:
        log = PortfolioLog(
            code=code,
            action=action,
            price=price,
            shares=shares,
            reason=reason,
            triggered_by=triggered_by,
        )
        session.add(log)
        session.commit()
        session.refresh(log)
        return log.to_dict()


def list_portfolio_logs(code: str, limit: int = 50) -> List[Dict[str, Any]]:
    """查询指定股票的操作日志（最新 limit 条）"""
    from sqlalchemy import desc
    db = DatabaseManager.get_instance()
    with db.get_session() as session:
        logs = session.execute(
            select(PortfolioLog)
            .where(PortfolioLog.code == code)
            .order_by(desc(PortfolioLog.created_at))
            .limit(limit)
        ).scalars().all()
        return [log.to_dict() for log in logs]


def update_portfolio_horizon(
    code: str,
    holding_horizon_label: str,
) -> bool:
    """手动更新持仓周期标签"""
    db = DatabaseManager.get_instance()
    with db.get_session() as session:
        record = session.execute(
            select(Portfolio).where(Portfolio.code == code)
        ).scalar_one_or_none()
        if not record:
            return False
        record.holding_horizon_label = holding_horizon_label
        record.updated_at = datetime.now()
        session.commit()
        return True


# ─────────────────────────────────────────────
# P5: 再分析日期提醒
# ─────────────────────────────────────────────

import re as _re

_HORIZON_TO_DAYS = [
    (r'短线.*?(\d+)[^\d]*(\d+).*?交易日', lambda m: int(m.group(2))),
    (r'短线.*?(\d+)[^\d]*(\d+).*?日',     lambda m: int(m.group(2))),
    (r'中线.*?(\d+)[^\d]*(\d+).*?周',     lambda m: int(m.group(2)) * 7),
    (r'中线.*?(\d+)[^\d]*(\d+).*?月',     lambda m: int(m.group(2)) * 30),
    (r'长线.*?(\d+).*?月',                lambda m: int(m.group(1)) * 30),
    (r'(\d+).*?-.*?(\d+).*?交易日',       lambda m: int(m.group(2))),
    (r'(\d+).*?-.*?(\d+).*?日',           lambda m: int(m.group(2))),
    (r'(\d+).*?-.*?(\d+).*?周',           lambda m: int(m.group(2)) * 7),
    (r'(\d+).*?-.*?(\d+).*?月',           lambda m: int(m.group(2)) * 30),
]


def _parse_horizon_days(horizon_label: str) -> Optional[int]:
    """从持仓周期字符串中解析建议天数（取区间上限）。"""
    if not horizon_label:
        return None
    for pattern, extractor in _HORIZON_TO_DAYS:
        m = _re.search(pattern, horizon_label)
        if m:
            try:
                return max(1, extractor(m))
            except Exception:
                pass
    return None


def update_next_review_date(code: str, horizon_label: Optional[str] = None) -> Optional[str]:
    """
    根据持仓周期标签计算并写入下次再分析日期。
    自动从 AI 历史分析记录提取，也可传入 horizon_label 覆盖。
    返回计算出的日期字符串（YYYY-MM-DD），或 None。
    """
    from datetime import date, timedelta
    label = horizon_label or get_ai_horizon_suggestion(code)
    if not label:
        return None
    days = _parse_horizon_days(label)
    if not days:
        return None

    db = DatabaseManager.get_instance()
    with db.get_session() as session:
        record = session.execute(
            select(Portfolio).where(Portfolio.code == code)
        ).scalar_one_or_none()
        if not record:
            return None
        base_date = record.entry_date or date.today()
        review_date = base_date + timedelta(days=days)
        record.next_review_at = review_date
        if label and not record.holding_horizon_label:
            record.holding_horizon_label = label
        record.updated_at = datetime.now()
        session.commit()
        return review_date.isoformat()


def run_review_reminder_job() -> None:
    """
    每日定时任务：检查持仓中到期/即将到期的再分析提醒，
    通过 PushPlus 和 Web 推送通知。
    """
    from datetime import date, timedelta
    today = date.today()
    tomorrow = today + timedelta(days=1)

    db = DatabaseManager.get_instance()
    with db.get_session() as session:
        holdings = session.execute(select(Portfolio)).scalars().all()
        due = [
            h for h in holdings
            if h.next_review_at and h.next_review_at <= tomorrow
        ]

    if not due:
        logger.debug("[review_reminder] 今日无到期再分析提醒")
        return

    lines = []
    for h in due:
        overdue = (today - h.next_review_at).days if h.next_review_at <= today else 0
        overdue_str = f"（已过期{overdue}天）" if overdue > 0 else "（明日到期）"
        lines.append(f"- **{h.name}({h.code})**：{h.holding_horizon_label or '未知周期'} {overdue_str}")

    title = f"📅 持仓复盘提醒：{len(due)} 只股到期"
    content = f"## {title}\n\n" + "\n".join(lines) + "\n\n⏰ 建议今日重新运行完整分析，更新持仓决策。"
    try:
        from src.notification import NotificationManager
        nm = NotificationManager.get_instance()
        nm.send_to_pushplus(content=content, title=title)
        logger.info(f"[review_reminder] 推送 {len(due)} 只到期再分析提醒")
    except Exception as e:
        logger.warning(f"[review_reminder] 推送失败: {e}")
