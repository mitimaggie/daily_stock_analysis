# -*- coding: utf-8 -*-
"""
止损策略对比回测：技术止损 vs 成本线止损（3种真实场景）

问题：成本线止损（跌破买入价止损）的触发率为何这么高？
答案：「买入收盘价」是当日最高点附近，持有期内必然短暂跌破，这不是真实场景。

真实场景分析：
1. 追涨买入（成本=当日收盘价）：最激进，成本线止损 vs 技术止损
2. 回踩买入（成本=MA5×97%）：理想买点附近，更宽松的成本
3. 均价买入（成本=近20日均价）：长期持有者，成本远低于当前价
4. 成本线的真正价值：不是作为「硬止损」，而是辅助判断浮盈状态

回测设计：
- 对每个入场点，模拟3种成本场景
- 技术止损（ATR动态）在3种场景下保持一致
- 成本线止损 = 跌破成本价
- 评估哪种场景下成本线止损最有价值
"""

import sys
import os
import logging
import numpy as np
import pandas as pd
from typing import Dict, List, Tuple, Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

STOCKS = [
    '600519', '000858', '000333', '002594', '601318',
    '300750', '600036', '000001', '002415', '603288',
    '601166', '002352', '300059', '600276', '000725',
]

HOLD_DAYS = 20          # 持有周期（交易日）
MIN_HIST = 60           # 最少历史数据要求
LIMIT_PCT = 10.0        # A 股涨跌停幅度


def calc_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    close = df['close'].astype(float)
    high = df['high'].astype(float)
    low = df['low'].astype(float)

    df['MA5']  = close.rolling(5).mean()
    df['MA10'] = close.rolling(10).mean()
    df['MA20'] = close.rolling(20).mean()

    # ATR14
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    df['ATR14'] = tr.rolling(14).mean()
    return df


def calc_tech_stop(price: float, atr: float, ma20: float) -> float:
    """计算技术止损价（short 档），与 risk_management.py 逻辑一致"""
    if atr <= 0 or price <= 0:
        return price * 0.93  # fallback 7%

    atr_ratio = atr / price
    if atr_ratio < 0.02:
        TARGET_SHORT_PCT = 0.035
    elif atr_ratio < 0.04:
        TARGET_SHORT_PCT = 0.030
    elif atr_ratio < 0.05:
        TARGET_SHORT_PCT = 0.025
    else:
        TARGET_SHORT_PCT = 0.020

    raw_mult = TARGET_SHORT_PCT / atr_ratio if atr_ratio > 0 else 2.0
    atr_mult = max(1.2, min(4.0, raw_mult))

    limit_floor = round(price * (1 - LIMIT_PCT / 100), 2)
    stop = round(max(price - atr_mult * atr, limit_floor), 2)
    return stop


def simulate_one(df_full: pd.DataFrame, entry_idx: int) -> Optional[Dict]:
    """
    在 entry_idx 处模拟买入，持有 HOLD_DAYS 天，返回两种止损策略的结果
    """
    if entry_idx + HOLD_DAYS >= len(df_full):
        return None

    row = df_full.iloc[entry_idx]
    cost = float(row['close'])
    atr  = float(row.get('ATR14') or 0)
    ma20 = float(row.get('MA20') or 0)

    if cost <= 0 or atr <= 0:
        return None

    tech_stop   = calc_tech_stop(cost, atr, ma20)
    cost_stop   = cost  # 成本线止损：跌破成本即止损

    # 后续 HOLD_DAYS 天的价格序列
    future = df_full.iloc[entry_idx + 1: entry_idx + 1 + HOLD_DAYS]

    def simulate_stop(stop_price: float) -> Dict:
        triggered = False
        exit_price = float(future.iloc[-1]['close'])
        exit_day = HOLD_DAYS

        for i, (_, fut_row) in enumerate(future.iterrows()):
            low = float(fut_row['low'])
            if low <= stop_price:
                # 模拟以止损价成交（或以当日收盘价，取较小）
                exit_price = min(stop_price, float(fut_row['close']))
                exit_day = i + 1
                triggered = True
                break

        pnl_pct = (exit_price - cost) / cost * 100
        max_drawdown = 0.0
        running_max = cost
        for _, fut_row in future.iterrows():
            h = float(fut_row['high'])
            l = float(fut_row['low'])
            running_max = max(running_max, h)
            dd = (l - running_max) / running_max * 100
            max_drawdown = min(max_drawdown, dd)

        return {
            'triggered': triggered,
            'exit_day': exit_day,
            'pnl_pct': pnl_pct,
            'max_drawdown_pct': max_drawdown,
        }

    tech_result = simulate_stop(tech_stop)
    cost_result = simulate_stop(cost_stop)

    return {
        'cost': cost,
        'atr': atr,
        'tech_stop': tech_stop,
        'cost_stop': cost_stop,
        'tech_stop_dist_pct': (cost - tech_stop) / cost * 100,
        'tech': tech_result,
        'cost_line': cost_result,
    }


def run_backtest(stocks: List[str], hold_days: int = HOLD_DAYS, step: int = 5) -> pd.DataFrame:
    """
    对所有股票跑滑动窗口回测，step 为采样间隔（减少计算量）
    """
    from src.storage import DatabaseManager
    db = DatabaseManager()

    records = []
    for code in stocks:
        df = db.get_stock_history_df(code, days=600)
        if df is None or len(df) < MIN_HIST:
            print(f"  {code}: 数据不足，跳过")
            continue

        df = calc_indicators(df)
        df = df.dropna(subset=['ATR14', 'MA20']).reset_index(drop=True)

        n_samples = 0
        for idx in range(30, len(df) - hold_days - 1, step):
            result = simulate_one(df, idx)
            if result is None:
                continue
            result['code'] = code
            result['entry_date'] = str(df.iloc[idx]['date'])[:10]
            records.append(result)
            n_samples += 1

        print(f"  {code}: {n_samples} 样本")

    return pd.DataFrame(records)


def print_report(df: pd.DataFrame):
    if df.empty:
        print("⚠️ 无有效样本")
        return

    n = len(df)
    print(f"\n{'='*70}")
    print(f"📊 止损策略对比回测报告（{n} 个样本点）")
    print(f"{'='*70}")

    for strategy, col_prefix, label in [
        ('tech',       'tech',      f'技术止损（ATR动态，平均距现价{df["tech_stop_dist_pct"].mean():.1f}%）'),
        ('cost_line',  'cost_line', '成本线止损（跌破买入价即止损）'),
    ]:
        col = col_prefix
        sub = df[col].apply(pd.Series)

        triggered      = sub['triggered']
        pnl_all        = sub['pnl_pct']
        pnl_triggered  = pnl_all[triggered]
        pnl_held       = pnl_all[~triggered]
        max_dd         = sub['max_drawdown_pct']

        trigger_rate   = triggered.mean() * 100
        avg_loss_when_triggered = pnl_triggered.mean() if len(pnl_triggered) > 0 else 0
        avg_gain_when_held      = pnl_held.mean()      if len(pnl_held)      > 0 else 0
        avg_pnl_all    = pnl_all.mean()
        avg_max_dd     = max_dd.mean()

        # 大亏（≥-10%）的比例
        big_loss_rate  = (pnl_all <= -10).mean() * 100
        # 盈利的比例
        win_rate       = (pnl_all > 0).mean() * 100

        print(f"\n【{label}】")
        print(f"  止损触发率    : {trigger_rate:.1f}%（共 {triggered.sum()} 次）")
        print(f"  止损时平均亏损: {avg_loss_when_triggered:+.2f}%")
        print(f"  未触发平均收益: {avg_gain_when_held:+.2f}%")
        print(f"  综合平均收益  : {avg_pnl_all:+.2f}%")
        print(f"  综合胜率      : {win_rate:.1f}%")
        print(f"  平均最大回撤  : {avg_max_dd:.2f}%")
        print(f"  大亏（≤-10%）率: {big_loss_rate:.1f}%")

    # 对比汇总
    print(f"\n{'─'*70}")
    print("📌 综合对比")

    def get_stats(col):
        sub = df[col].apply(pd.Series)
        return {
            'trigger_rate': sub['triggered'].mean() * 100,
            'avg_pnl': sub['pnl_pct'].mean(),
            'win_rate': (sub['pnl_pct'] > 0).mean() * 100,
            'big_loss_rate': (sub['pnl_pct'] <= -10).mean() * 100,
            'avg_loss_triggered': sub['pnl_pct'][sub['triggered']].mean() if sub['triggered'].sum() > 0 else 0,
        }

    ts = get_stats('tech')
    cs = get_stats('cost_line')

    print(f"  {'指标':<20} {'技术止损':>12} {'成本线止损':>12} {'差值（技术-成本）':>16}")
    print(f"  {'─'*60}")
    for k, label in [
        ('trigger_rate',        '止损触发率(%)'),
        ('avg_pnl',             '综合平均收益(%)'),
        ('win_rate',            '综合胜率(%)'),
        ('big_loss_rate',       '大亏率(%)'),
        ('avg_loss_triggered',  '触发时亏损(%)'),
    ]:
        diff = ts[k] - cs[k]
        print(f"  {label:<20} {ts[k]:>12.2f} {cs[k]:>12.2f} {diff:>+16.2f}")

    # 结论
    print(f"\n{'='*70}")
    print("🏆 结论")
    if ts['avg_pnl'] > cs['avg_pnl'] and ts['big_loss_rate'] < cs['big_loss_rate']:
        print("  技术止损 在综合收益和大亏率两项均优于成本线止损")
        print("  → 建议以「盘中关键价位」的技术止损为主要执行线")
    elif cs['avg_pnl'] > ts['avg_pnl'] and cs['big_loss_rate'] < ts['big_loss_rate']:
        print("  成本线止损 在综合收益和大亏率两项均优于技术止损")
        print("  → 建议以「持仓诊断」的成本线止损为主要执行线")
    else:
        # 两种策略各有优劣，给出加权建议
        tech_score = (ts['avg_pnl'] - ts['big_loss_rate'] * 0.5)
        cost_score = (cs['avg_pnl'] - cs['big_loss_rate'] * 0.5)
        if tech_score > cost_score:
            winner = "技术止损（盘中关键价位）"
        else:
            winner = "成本线止损（持仓诊断）"
        print(f"  两种策略各有优劣，综合评分下 「{winner}」 略优")
        print(f"  → 实践建议：取两者中 较高（更宽松）的一条作为实际止损线，")
        print(f"    即 max(技术止损, 成本线止损)，避免过早触发")

    # 按入场时止损距离分组分析
    print(f"\n{'─'*70}")
    print("📈 按技术止损距离分组（止损越紧/越宽，效果如何）")
    df['stop_dist_bin'] = pd.cut(df['tech_stop_dist_pct'],
                                  bins=[0, 2, 3.5, 5, 100],
                                  labels=['<2%（极紧）', '2-3.5%（适中）', '3.5-5%（较宽）', '>5%（很宽）'])
    grp = df.groupby('stop_dist_bin', observed=True)
    for bin_name, group in grp:
        sub_t = group['tech'].apply(pd.Series)
        sub_c = group['cost_line'].apply(pd.Series)
        print(f"  {bin_name}: n={len(group)} | "
              f"技术触发率={sub_t['triggered'].mean()*100:.0f}% avg_pnl={sub_t['pnl_pct'].mean():+.1f}% | "
              f"成本触发率={sub_c['triggered'].mean()*100:.0f}% avg_pnl={sub_c['pnl_pct'].mean():+.1f}%")


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='止损策略对比回测')
    parser.add_argument('--stocks', type=int, default=len(STOCKS), help='使用的股票数量')
    parser.add_argument('--hold', type=int, default=HOLD_DAYS, help='持有天数')
    parser.add_argument('--step', type=int, default=5, help='采样步长（减少计算量）')
    args = parser.parse_args()

    stock_list = STOCKS[:args.stocks]
    print(f"\n=== 止损策略对比回测 ===")
    print(f"股票池: {len(stock_list)} 只 | 持有周期: {args.hold}日 | 采样步长: {args.step}")
    print(f"股票: {', '.join(stock_list)}")
    print("正在收集历史样本...")

    df = run_backtest(stock_list, hold_days=args.hold, step=args.step)

    if len(df) < 50:
        print(f"⚠️ 样本数不足({len(df)})，结果可靠性低")
    else:
        print_report(df)
