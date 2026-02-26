"""
趋势状态 × 时间维度回测
================================
按 TrendStatus (STRONG_BULL/BULL/WEAK_BULL/CONSOLIDATION/WEAK_BEAR/BEAR/STRONG_BEAR)
分组，回测 5d / 10d / 20d 收益，评估中长期有效性。

用法：
    cd /Users/chengxidai/daily_stock_analysis
    python scripts/backtest_trend_midlong.py [--stocks 600519,000858,...] [--history 600]
"""
import sys
import os
import argparse
import pandas as pd
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.backtest_improvements import calc_indicators, get_trend_status, fetch_history
from src.stock_analyzer.types import TrendStatus
from src.storage import DatabaseManager


FORWARD_WINDOWS = [5, 10, 20]


def backtest_stock_trend(code: str, full_df: pd.DataFrame, min_history: int = 60):
    """滑动窗口，记录每日 trend_status + 5/10/20日后收益"""
    full_df = calc_indicators(full_df)
    records = []
    n = len(full_df)
    max_fwd = max(FORWARD_WINDOWS)

    for i in range(min_history, n - max_fwd):
        row = full_df.iloc[i]
        close_cur = float(row.get('close', 0) or 0)
        if close_cur <= 0:
            continue

        trend = get_trend_status(row)
        date_str = str(full_df.index[i]) if hasattr(full_df.index, 'freq') or \
                   isinstance(full_df.index, pd.DatetimeIndex) else \
                   str(full_df.iloc[i].get('date', i))

        rec = {'code': code, 'date': date_str, 'trend_status': trend.value}
        for fwd in FORWARD_WINDOWS:
            fut_close = float(full_df.iloc[i + fwd].get('close', close_cur) or close_cur)
            rec[f'ret_{fwd}d'] = round((fut_close - close_cur) / close_cur * 100, 2)
        records.append(rec)

    return records


def print_trend_stats(all_records: list):
    df = pd.DataFrame(all_records)
    if df.empty:
        print("无回测数据")
        return

    total = len(df)
    print(f"\n{'='*70}")
    print(f"趋势维度中长期回测  (总样本={total})")
    print(f"{'='*70}")

    # 整体基准
    for fwd in FORWARD_WINDOWS:
        col = f'ret_{fwd}d'
        bm = df[col].mean()
        print(f"  整体基准  {fwd}d均收益: {bm:+.2f}%")

    # 按trend_status分组
    order = [
        TrendStatus.STRONG_BULL.value,
        TrendStatus.BULL.value,
        TrendStatus.WEAK_BULL.value,
        TrendStatus.CONSOLIDATION.value,
        TrendStatus.WEAK_BEAR.value,
        TrendStatus.BEAR.value,
        TrendStatus.STRONG_BEAR.value,
    ]
    print(f"\n{'趋势状态':<16} {'样本':>5}  {'5d':>8}  {'10d':>8}  {'20d':>8}  {'5d胜率':>7}  {'20d胜率':>7}")
    print("-" * 70)

    bm5  = df['ret_5d'].mean()
    bm10 = df['ret_10d'].mean()
    bm20 = df['ret_20d'].mean()

    for ts_val in order:
        grp = df[df['trend_status'] == ts_val]
        if len(grp) < 5:
            continue
        r5  = grp['ret_5d'].mean()
        r10 = grp['ret_10d'].mean()
        r20 = grp['ret_20d'].mean()
        w5  = (grp['ret_5d'] > 0).mean() * 100
        w20 = (grp['ret_20d'] > 0).mean() * 100
        m5  = '✅' if r5  > bm5  else '⚠️'
        m20 = '✅' if r20 > bm20 else '⚠️'
        print(f"  {ts_val:<14} {len(grp):>5}  {m5}{r5:>+6.2f}%  {r10:>+7.2f}%  {m20}{r20:>+6.2f}%  {w5:>6.1f}%  {w20:>6.1f}%")

    # 牛市3档合并 vs 熊市3档合并
    bull_vals = {TrendStatus.STRONG_BULL.value, TrendStatus.BULL.value, TrendStatus.WEAK_BULL.value}
    bear_vals = {TrendStatus.STRONG_BEAR.value, TrendStatus.BEAR.value, TrendStatus.WEAK_BEAR.value}
    bull_grp = df[df['trend_status'].isin(bull_vals)]
    bear_grp = df[df['trend_status'].isin(bear_vals)]
    other_grp = df[~df['trend_status'].isin(bull_vals | bear_vals)]

    print(f"\n── 多头合并 vs 空头合并 ──")
    for label, grp in [("多头合计(BULL+)", bull_grp), ("空头合计(BEAR-)", bear_grp), ("盘整/整固", other_grp)]:
        if len(grp) == 0:
            continue
        r5  = grp['ret_5d'].mean()
        r10 = grp['ret_10d'].mean()
        r20 = grp['ret_20d'].mean()
        print(f"  {label:<18} {len(grp):>5}次  5d:{r5:+.2f}%  10d:{r10:+.2f}%  20d:{r20:+.2f}%")

    # STRONG_BULL深挖：各子周期
    print(f"\n── STRONG_BULL 深挖：分位数分布 ──")
    sb = df[df['trend_status'] == TrendStatus.STRONG_BULL.value]
    if len(sb) >= 10:
        for fwd in FORWARD_WINDOWS:
            col = f'ret_{fwd}d'
            q25 = sb[col].quantile(0.25)
            q50 = sb[col].quantile(0.50)
            q75 = sb[col].quantile(0.75)
            print(f"  {fwd}d  Q25={q25:+.2f}%  中位={q50:+.2f}%  Q75={q75:+.2f}%  均={sb[col].mean():+.2f}%")

    # 多头趋势中 MACD 状态子分组（如有）
    print(f"\n── 结论汇总 ──")
    if len(bull_grp) > 0 and len(bear_grp) > 0:
        diff5  = bull_grp['ret_5d'].mean()  - bear_grp['ret_5d'].mean()
        diff20 = bull_grp['ret_20d'].mean() - bear_grp['ret_20d'].mean()
        print(f"  多头 vs 空头  5d差: {diff5:+.2f}%  20d差: {diff20:+.2f}%")
        if diff5 > 0 and diff20 > 0:
            print("  ✅ 趋势方向区分度在短中长期均有效")
        elif diff20 > 0:
            print("  ✅ 趋势方向在中长期(20d)有效，短期噪声较大")
        else:
            print("  ⚠️ 趋势方向区分度不足，需检查均线参数")


def main():
    parser = argparse.ArgumentParser(description="趋势维度中长期回测")
    parser.add_argument('--stocks', default='600519,000858,000333,000002,600036,601318,002415,300059,600900',
                        help='逗号分隔的股票代码')
    parser.add_argument('--history', type=int, default=600, help='拉取历史天数')
    args = parser.parse_args()

    codes = [c.strip() for c in args.stocks.split(',')]
    db = DatabaseManager.get_instance()
    all_records = []

    for idx, code in enumerate(codes):
        print(f"\n[{idx+1}/{len(codes)}] {code} 获取 {args.history} 日历史数据...")
        try:
            df = fetch_history(code, args.history, db)
        except Exception as e:
            print(f"  ❌ 跳过 {code}: {e}")
            continue
        if len(df) < 80:
            print(f"  ❌ 跳过 {code}: 数据不足({len(df)}行)")
            continue
        records = backtest_stock_trend(code, df)
        print(f"  生成 {len(records)} 个样本点")
        all_records.extend(records)

    if all_records:
        print_trend_stats(all_records)
    else:
        print("无有效回测记录")


if __name__ == '__main__':
    main()
