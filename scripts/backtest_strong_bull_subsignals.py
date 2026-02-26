"""
STRONG_BULL 子信号深挖回测
================================
在强势多头(STRONG_BULL)趋势下，分析 MACD / RSI / KDJ / Volume / Bias
各子信号的 5d / 10d / 20d 收益，找出最有效的子信号组合。

用法：
    cd /Users/chengxidai/daily_stock_analysis
    python scripts/backtest_strong_bull_subsignals.py
"""
import sys
import os
import argparse
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.backtest_improvements import (
    calc_indicators, get_trend_status, get_macd_status, fetch_history
)
from src.stock_analyzer.types import TrendStatus, MACDStatus, RSIStatus, KDJStatus, VolumeStatus
from src.storage import DatabaseManager

FORWARD_WINDOWS = [5, 10, 20]


def get_rsi_status_simple(row, prev_row):
    rsi = float(row.get('RSI_12', 50) or 50)
    rsi_prev = float(prev_row.get('RSI_12', 50) or 50)
    if rsi > 70:
        return RSIStatus.OVERBOUGHT
    elif rsi > 60:
        return RSIStatus.STRONG_BUY
    elif rsi >= 40:
        return RSIStatus.NEUTRAL
    elif rsi >= 30:
        return RSIStatus.WEAK
    else:
        # 上穿+超卖区 = 金叉
        if rsi > rsi_prev and rsi_prev < 30:
            return RSIStatus.GOLDEN_CROSS_OVERSOLD
        return RSIStatus.OVERSOLD


def get_kdj_status_simple(row, prev_row):
    k = float(row.get('KDJ_K', 50) or 50)
    d = float(row.get('KDJ_D', 50) or 50)
    j = float(row.get('KDJ_J', 50) or 50)
    k_prev = float(prev_row.get('KDJ_K', 50) or 50)
    d_prev = float(prev_row.get('KDJ_D', 50) or 50)
    if j > 100:
        return KDJStatus.OVERBOUGHT
    elif j < 0:
        return KDJStatus.OVERSOLD
    # 金叉判断
    if k > d and k_prev <= d_prev:
        return KDJStatus.GOLDEN_CROSS_OVERSOLD if j < 20 else KDJStatus.GOLDEN_CROSS
    elif k < d and k_prev >= d_prev:
        return KDJStatus.DEATH_CROSS
    elif k > d:
        return KDJStatus.BULLISH
    elif k < d:
        return KDJStatus.BEARISH
    return KDJStatus.NEUTRAL


def get_volume_status_simple(row):
    vol = float(row.get('volume', 0) or 0)
    avg20 = float(row.get('VOL_AVG20', 0) or 0)
    close = float(row.get('close', 0) or 0)
    open_ = float(row.get('open', 0) or 0)
    if avg20 <= 0:
        return VolumeStatus.NORMAL
    ratio = vol / avg20
    up = close >= open_
    if ratio >= 1.5 and up:
        return VolumeStatus.HEAVY_VOLUME_UP
    elif ratio >= 1.5 and not up:
        return VolumeStatus.HEAVY_VOLUME_DOWN
    elif ratio <= 0.7 and up:
        return VolumeStatus.SHRINK_VOLUME_UP
    elif ratio <= 0.7 and not up:
        return VolumeStatus.SHRINK_VOLUME_DOWN
    return VolumeStatus.NORMAL


def get_bias_bucket(row):
    """将bias_ma5分组"""
    bias = float(row.get('BIAS_MA5', 0) or 0)
    bb_width = float(row.get('BB_WIDTH', 0) or 0)
    if bb_width > 0.01:
        half_bb_pct = bb_width * 50
        norm = bias / half_bb_pct
        if norm > 1.0:
            return 'bias_large_pos(>1σ)'
        elif norm > 0.5:
            return 'bias_mid_pos(0.5-1σ)'
        elif norm > 0:
            return 'bias_small_pos(0-0.5σ)'
        elif norm > -0.5:
            return 'bias_small_neg(-0.5-0σ)'
        elif norm > -1.0:
            return 'bias_mid_neg(-1-0.5σ)'
        else:
            return 'bias_large_neg(<-1σ)'
    # fallback
    if bias > 5:
        return 'bias_large_pos(>5)'
    elif bias > 2:
        return 'bias_mid_pos(2-5)'
    elif bias > 0:
        return 'bias_small_pos(0-2)'
    elif bias > -2:
        return 'bias_small_neg(-2-0)'
    elif bias > -5:
        return 'bias_mid_neg(-5--2)'
    else:
        return 'bias_large_neg(<-5)'


TREND_MAP = {
    'STRONG_BULL': TrendStatus.STRONG_BULL,
    'BULL':        TrendStatus.BULL,
    'WEAK_BULL':   TrendStatus.WEAK_BULL,
    'CONSOLIDATION': TrendStatus.CONSOLIDATION,
    'WEAK_BEAR':   TrendStatus.WEAK_BEAR,
    'BEAR':        TrendStatus.BEAR,
    'STRONG_BEAR': TrendStatus.STRONG_BEAR,
}


def backtest_strong_bull(code: str, full_df: pd.DataFrame, min_history: int = 60,
                         target_trend: TrendStatus = TrendStatus.STRONG_BULL):
    full_df = calc_indicators(full_df)
    records = []
    n = len(full_df)
    max_fwd = max(FORWARD_WINDOWS)

    for i in range(min_history, n - max_fwd):
        row = full_df.iloc[i]
        prev_row = full_df.iloc[i - 1]
        close_cur = float(row.get('close', 0) or 0)
        if close_cur <= 0:
            continue

        trend = get_trend_status(row)
        if trend != target_trend:
            continue

        macd_status = get_macd_status(row, prev_row)
        rsi_status = get_rsi_status_simple(row, prev_row)
        kdj_status = get_kdj_status_simple(row, prev_row)
        vol_status = get_volume_status_simple(row)
        bias_bucket = get_bias_bucket(row)

        rec = {
            'code': code,
            'macd': macd_status.value,
            'rsi': rsi_status.value,
            'kdj': kdj_status.value,
            'volume': vol_status.value,
            'bias': bias_bucket,
        }
        for fwd in FORWARD_WINDOWS:
            fut_close = float(full_df.iloc[i + fwd].get('close', close_cur) or close_cur)
            rec[f'ret_{fwd}d'] = round((fut_close - close_cur) / close_cur * 100, 2)
        records.append(rec)

    return records


def print_subsignal_stats(all_records: list, trend_name: str = 'STRONG_BULL'):
    df = pd.DataFrame(all_records)
    if df.empty:
        print("无数据")
        return

    total = len(df)
    bm5  = df['ret_5d'].mean()
    bm10 = df['ret_10d'].mean()
    bm20 = df['ret_20d'].mean()

    print(f"\n{'='*72}")
    print(f"{trend_name} 子信号深挖  (总样本={total})")
    print(f"  基准: 5d={bm5:+.2f}%  10d={bm10:+.2f}%  20d={bm20:+.2f}%")
    print(f"{'='*72}")

    dims = [
        ('MACD', 'macd'),
        ('RSI',  'rsi'),
        ('KDJ',  'kdj'),
        ('量能', 'volume'),
        ('乖离率', 'bias'),
    ]

    for dim_name, col in dims:
        print(f"\n── {dim_name} 分组 ──")
        print(f"  {'状态':<32} {'样本':>5}  {'5d':>8}  {'10d':>8}  {'20d':>8}")
        print(f"  {'-'*65}")
        grp_df = df.groupby(col)
        rows = []
        for val, grp in grp_df:
            if len(grp) < 5:
                continue
            rows.append((val, len(grp), grp['ret_5d'].mean(), grp['ret_10d'].mean(), grp['ret_20d'].mean()))
        # 按20d收益降序
        rows.sort(key=lambda x: x[4], reverse=True)
        for val, cnt, r5, r10, r20 in rows:
            m5  = '✅' if r5  > bm5  else '  '
            m20 = '✅' if r20 > bm20 else '  '
            print(f"  {m5}{str(val):<30} {cnt:>5}  {r5:>+7.2f}%  {r10:>+7.2f}%  {m20}{r20:>+6.2f}%")

    # 最优组合：MACD金叉 + RSI中性/强势 + 放量上涨
    print(f"\n── 最优组合探索（STRONG_BULL内） ──")
    combos = [
        ('MACD金叉+放量上涨',
         df[(df['macd'].isin(['GOLDEN_CROSS', 'GOLDEN_CROSS_ZERO'])) & (df['volume'] == 'HEAVY_VOLUME_UP')]),
        ('MACD金叉+小负乖离',
         df[(df['macd'].isin(['GOLDEN_CROSS', 'GOLDEN_CROSS_ZERO'])) & df['bias'].str.contains('neg')]),
        ('MACD多头+KDJ金叉',
         df[(df['macd'] == 'BULLISH') & (df['kdj'].isin(['GOLDEN_CROSS', 'GOLDEN_CROSS_OVERSOLD']))]),
        ('RSI中性+放量上涨',
         df[(df['rsi'] == 'NEUTRAL') & (df['volume'] == 'HEAVY_VOLUME_UP')]),
        ('小负乖离+KDJ金叉',
         df[df['bias'].str.contains('neg') & df['kdj'].isin(['GOLDEN_CROSS', 'GOLDEN_CROSS_OVERSOLD'])]),
    ]
    for label, grp in combos:
        if len(grp) < 5:
            continue
        r5  = grp['ret_5d'].mean()
        r10 = grp['ret_10d'].mean()
        r20 = grp['ret_20d'].mean()
        m5  = '✅' if r5 > bm5 else '⚠️'
        m20 = '✅' if r20 > bm20 else '⚠️'
        print(f"  {m5}{m20} {label:<28} {len(grp):>4}次  5d:{r5:+.2f}%  10d:{r10:+.2f}%  20d:{r20:+.2f}%")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--stocks', default='600519,000858,000333,000002,600036,601318,002415,300059,600900')
    parser.add_argument('--history', type=int, default=600)
    parser.add_argument('--trend', default='STRONG_BULL',
                        choices=list(TREND_MAP.keys()),
                        help='目标趋势状态（默认STRONG_BULL）')
    args = parser.parse_args()

    target_trend = TREND_MAP[args.trend]
    codes = [c.strip() for c in args.stocks.split(',')]
    db = DatabaseManager.get_instance()
    all_records = []

    for idx, code in enumerate(codes):
        print(f"[{idx+1}/{len(codes)}] {code}...")
        try:
            df = fetch_history(code, args.history, db)
            records = backtest_strong_bull(code, df, target_trend=target_trend)
            print(f"  {args.trend}样本: {len(records)}")
            all_records.extend(records)
        except Exception as e:
            print(f"  ❌ 跳过: {e}")

    if all_records:
        print_subsignal_stats(all_records, trend_name=args.trend)
    else:
        print("无有效记录")


if __name__ == '__main__':
    main()
