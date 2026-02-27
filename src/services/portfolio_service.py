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

from src.storage import DatabaseManager, Portfolio, Watchlist

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# 持仓 CRUD
# ─────────────────────────────────────────────

def add_portfolio(
    code: str,
    name: str,
    cost_price: float,
    shares: int = 0,
    entry_date: Optional[date] = None,
    notes: str = '',
) -> Dict[str, Any]:
    """新增持仓（已存在则更新成本价和数量）"""
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
            existing.updated_at = datetime.now()
            session.commit()
            session.refresh(existing)
            return existing.to_dict()
        else:
            record = Portfolio(
                code=code,
                name=name,
                cost_price=cost_price,
                shares=shares,
                entry_date=entry_date or date.today(),
                notes=notes,
            )
            session.add(record)
            session.commit()
            session.refresh(record)
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


# ─────────────────────────────────────────────
# 关注股 CRUD
# ─────────────────────────────────────────────

def add_watchlist(code: str, name: str, notes: str = '') -> Dict[str, Any]:
    """新增关注股（已存在则仅更新备注）"""
    db = DatabaseManager.get_instance()
    with db.get_session() as session:
        existing = session.execute(
            select(Watchlist).where(Watchlist.code == code)
        ).scalar_one_or_none()

        if existing:
            existing.name = name or existing.name
            existing.notes = notes or existing.notes
            existing.updated_at = datetime.now()
            session.commit()
            session.refresh(existing)
            return existing.to_dict()
        else:
            record = Watchlist(code=code, name=name, notes=notes)
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
    """获取实时价格（复用现有 realtime 接口）"""
    try:
        from data_provider.akshare_fetcher import AkshareFetcher
        fetcher = AkshareFetcher()
        quote = fetcher.get_realtime_quote(code)
        if quote and quote.price:
            return float(quote.price)
    except Exception:
        pass
    try:
        from data_provider.efinance_fetcher import EfinanceFetcher
        fetcher = EfinanceFetcher()
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


def monitor_portfolio() -> List[Dict[str, Any]]:
    """
    遍历所有持仓，获取实时价格、更新ATR止损、生成信号

    每次调用后将最新止损价和信号写回数据库。
    """
    from src.stock_analyzer.risk_management import RiskManager

    db = DatabaseManager.get_instance()
    with db.get_session() as session:
        holdings = session.execute(select(Portfolio)).scalars().all()
        holdings_list = [h for h in holdings]

    results = []

    for holding in holdings_list:
        code = holding.code
        cost_price = holding.cost_price
        current_price = _get_realtime_price(code)

        if current_price is None:
            results.append({
                'code': code,
                'name': holding.name,
                'cost_price': cost_price,
                'current_price': None,
                'signal': 'unknown',
                'signal_text': '数据获取失败',
                'reasons': ['⚪ 无法获取实时价格'],
                'atr_stop': holding.atr_stop_loss,
                'pnl_pct': None,
            })
            continue

        # 获取K线计算ATR追踪止损
        df = _get_kline_df(code)
        atr_result = RiskManager.calc_atr_trailing_stop(
            df=df,
            cost_price=cost_price,
            current_price=current_price,
            prev_atr_stop=holding.atr_stop_loss,
            prev_highest=holding.highest_price,
        ) if df is not None else {
            'atr': 0, 'atr_stop': holding.atr_stop_loss or 0,
            'highest_price': current_price, 'stop_triggered': False,
            'pnl_pct': (current_price - cost_price) / cost_price * 100 if cost_price > 0 else 0,
            'stop_pnl_pct': 0,
        }

        # 盘中获取分时信号
        is_intraday = 9 <= datetime.now().hour < 15
        intraday_info = _analyze_intraday_for_monitor(code) if is_intraday else {}

        # 生成操作信号
        signal_info = _generate_monitor_signal(
            code=code,
            cost_price=cost_price,
            current_price=current_price,
            atr_stop=atr_result['atr_stop'],
            pnl_pct=atr_result['pnl_pct'],
            stop_pnl_pct=atr_result['stop_pnl_pct'],
            intraday_info=intraday_info,
        )

        # 写回数据库
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

        results.append({
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
        })

    return results
