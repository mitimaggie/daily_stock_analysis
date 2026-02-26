"""
补充回测：4个未验证信号（向量化重写，高性能版）
================================
1. 支撑位接近度 (support_score)
2. 斐波那契回撤位 (fibonacci_levels)
3. 换手率分位数 (turnover_quantile)  -- 需baostock turn字段
4. MACD+放量上涨组合在 BULL/WEAK_BULL 中的细分

用法：
    cd /Users/chengxidai/daily_stock_analysis
    python scripts/backtest_supplemental.py
"""
import sys
import os
import argparse
import pandas as pd
import numpy as np
import baostock as bs
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.backtest_improvements import calc_indicators, get_trend_status, get_macd_status
from src.stock_analyzer.types import TrendStatus, MACDStatus, VolumeStatus

FORWARD_WINDOWS = [5, 10, 20]
STOCKS = ['600519', '000858', '000333', '000002', '600036', '601318', '002415', '300059', '600900']
HISTORY_DAYS = 600


# ─────────────────────────────────────────────────────────────────────────────
# 数据获取（直接baostock，带turn字段）
# ─────────────────────────────────────────────────────────────────────────────

def fetch_with_turn(code: str, days: int = HISTORY_DAYS) -> pd.DataFrame:
    """直接从baostock拉取含换手率的历史数据"""
    end_dt = date.today()
    beg_dt = end_dt - timedelta(days=int(days * 1.6))
    prefix = 'sh' if code.startswith('6') else 'sz'
    bs_code = f'{prefix}.{code}'
    rs = bs.query_history_k_data_plus(
        bs_code,
        'date,open,high,low,close,volume,amount,pctChg,turn',
        start_date=beg_dt.strftime('%Y-%m-%d'),
        end_date=end_dt.strftime('%Y-%m-%d'),
        frequency='d', adjustflag='2'
    )
    data = []
    while rs.next():
        data.append(rs.get_row_data())
    if not data:
        return pd.DataFrame()
    df = pd.DataFrame(data, columns=rs.fields)
    df['date'] = pd.to_datetime(df['date'])
    for col in ['open', 'high', 'low', 'close', 'volume', 'amount', 'turn']:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')
    df = df.set_index('date').sort_index()
    return df.iloc[-days:]


# ─────────────────────────────────────────────────────────────────────────────
# 向量化批量特征计算
# ─────────────────────────────────────────────────────────────────────────────

def add_fwd_returns(df: pd.DataFrame) -> pd.DataFrame:
    """批量添加5/10/20日未来收益列"""
    close = df['close'].values.astype(float)
    n = len(close)
    for fwd in FORWARD_WINDOWS:
        ret = np.full(n, np.nan)
        ret[:n - fwd] = (close[fwd:] - close[:n - fwd]) / close[:n - fwd] * 100
        df[f'ret_{fwd}d'] = ret
    return df


def add_support_proximity(df: pd.DataFrame, window: int = 60) -> pd.DataFrame:
    """向量化支撑位接近度：用rolling min(low)近似支撑，MA20/MA60为动态支撑"""
    close = df['close'].astype(float)
    low = df['low'].astype(float)
    ma20 = df['MA20'].astype(float) if 'MA20' in df.columns else close.rolling(20).mean()
    ma60 = df['MA60'].astype(float) if 'MA60' in df.columns else close.rolling(60).mean()

    # 用rolling(window).min(low)近似近期支撑底（向量化）
    roll_low = low.rolling(window, min_periods=20).min()

    # 找到价格在支撑上方的距离
    # 支撑候选：roll_low、MA20、MA60 中低于当前价的最大值
    support = pd.concat([
        roll_low.where(roll_low < close),
        ma20.where(ma20 < close),
        ma60.where(ma60 < close),
    ], axis=1).max(axis=1)

    dist_pct = (close - support) / close * 100

    def classify(row):
        s, d = row['support'], row['dist']
        if pd.isna(s) or s <= 0:
            return 'above_all'
        if d < 2:
            return 'near(<2%)'
        elif d < 5:
            return 'mid(2-5%)'
        else:
            return 'far(>5%)'

    tmp = pd.DataFrame({'support': support, 'dist': dist_pct})
    df['support_proximity'] = tmp.apply(classify, axis=1)
    return df


def add_fib_proximity(df: pd.DataFrame, window: int = 60) -> pd.DataFrame:
    """向量化斐波那契回撤位接近度"""
    close = df['close'].astype(float).values
    high = df['high'].astype(float).values
    low = df['low'].astype(float).values
    n = len(close)
    fib_group = np.empty(n, dtype=object)
    fib_group[:] = 'no_data'

    FIB_LEVELS = [0.236, 0.382, 0.5, 0.618, 0.786]

    for i in range(window, n):
        seg_h = high[i - window:i]
        seg_l = low[i - window:i]
        sh = seg_h.max()
        sl = seg_l.min()
        rng = sh - sl
        if rng <= 0 or sh <= 0:
            continue
        cur = close[i]
        # fib回撤位（从高点向下）
        fib_prices = np.array([sh - rng * lvl for lvl in FIB_LEVELS])
        dists = np.abs(cur - fib_prices) / cur
        idx = dists.argmin()
        if dists[idx] <= 0.03:
            fib_group[i] = f'fib_{FIB_LEVELS[idx]:.3f}'
        else:
            fib_group[i] = 'no_fib'

    df['fib_level'] = fib_group
    return df


def add_turnover_quantile(df: pd.DataFrame, window: int = 60) -> pd.DataFrame:
    """向量化换手率分位数"""
    if 'turn' not in df.columns:
        df['turnover_group'] = 'no_data'
        return df

    turn = df['turn'].astype(float)

    def rank_pct(s):
        """当日换手率在近window日的分位数"""
        arr = s.values
        n = len(arr)
        result = np.full(n, np.nan)
        for i in range(window, n):
            hist = arr[i - window:i]
            hist = hist[~np.isnan(hist) & (hist > 0)]
            if len(hist) < 10 or np.isnan(arr[i]) or arr[i] <= 0:
                continue
            result[i] = (hist < arr[i]).mean() * 100
        return result

    pcts = rank_pct(turn)

    def classify(p):
        if np.isnan(p):
            return 'no_data'
        if p >= 90:
            return 'very_high(>90th)'
        elif p >= 70:
            return 'high(70-90th)'
        elif p >= 30:
            return 'normal(30-70th)'
        elif p >= 10:
            return 'low(10-30th)'
        else:
            return 'very_low(<10th)'

    df['turnover_group'] = [classify(p) for p in pcts]
    return df


def add_trend_macd_vol(df: pd.DataFrame) -> pd.DataFrame:
    """向量化趋势/MACD/量能状态"""
    trends, macds, vols = [], [], []
    rows = df.reset_index(drop=False)
    for i in range(len(rows)):
        row = rows.iloc[i]
        prev_row = rows.iloc[i - 1] if i > 0 else row
        trends.append(get_trend_status(row).value)
        macds.append(get_macd_status(row, prev_row).value)
        avg20 = float(row.get('VOL_AVG20', 0) or 0)
        vol = float(row.get('volume', 0) or 0)
        close = float(row.get('close', 0) or 0)
        open_ = float(row.get('open', 0) or 0)
        if avg20 > 0:
            ratio = vol / avg20
            up = close >= open_
            if ratio >= 1.5 and up:
                vs = VolumeStatus.HEAVY_VOLUME_UP.value
            elif ratio >= 1.5:
                vs = VolumeStatus.HEAVY_VOLUME_DOWN.value
            elif ratio <= 0.7 and up:
                vs = VolumeStatus.SHRINK_VOLUME_UP.value
            elif ratio <= 0.7:
                vs = VolumeStatus.SHRINK_VOLUME_DOWN.value
            else:
                vs = VolumeStatus.NORMAL.value
        else:
            vs = VolumeStatus.NORMAL.value
        vols.append(vs)
    df['trend'] = trends
    df['macd'] = macds
    df['volume_status'] = vols
    return df


# ─────────────────────────────────────────────────────────────────────────────
# 单股批量回测
# ─────────────────────────────────────────────────────────────────────────────

def backtest_stock(code: str) -> dict:
    """一次性计算该股所有信号特征和未来收益，返回各信号的record列表"""
    df = fetch_with_turn(code)
    if len(df) < 80:
        print(f"  {code}: 数据不足 ({len(df)}行)，跳过")
        return {}

    df = calc_indicators(df)
    df = add_fwd_returns(df)
    df = add_support_proximity(df)
    df = add_fib_proximity(df)
    df = add_turnover_quantile(df)
    df = add_trend_macd_vol(df)

    # 过滤掉无未来收益的行
    valid = df.dropna(subset=['ret_5d', 'ret_10d', 'ret_20d'])
    valid = valid.iloc[60:]  # 跳过前min_history行

    print(f"  {code}: 有效={len(valid)}行")
    return {
        'support':  valid[['support_proximity', 'ret_5d', 'ret_10d', 'ret_20d']].copy(),
        'fib':      valid[['fib_level', 'ret_5d', 'ret_10d', 'ret_20d']].copy(),
        'turnover': valid[['turnover_group', 'trend', 'ret_5d', 'ret_10d', 'ret_20d']].copy(),
        'macd_vol': valid[valid['trend'].isin(['多头排列', '弱势多头'])][
                        ['trend', 'macd', 'volume_status', 'ret_5d', 'ret_10d', 'ret_20d']
                    ].copy(),
    }


# ─────────────────────────────────────────────────────────────────────────────
# 打印函数
# ─────────────────────────────────────────────────────────────────────────────

def print_section(title, df, group_col, min_n=5):
    if df.empty:
        print(f"  (无数据)")
        return

    bm5  = df['ret_5d'].mean()
    bm10 = df['ret_10d'].mean()
    bm20 = df['ret_20d'].mean()
    total = len(df)
    print(f"\n{'='*68}")
    print(f"  {title}  (总样本={total})")
    print(f"  基准: 5d={bm5:+.2f}%  10d={bm10:+.2f}%  20d={bm20:+.2f}%")
    print(f"{'='*68}")
    print(f"  {'分组':<28} {'样本':>5}  {'5d':>8}  {'10d':>8}  {'20d':>8}")
    print(f"  {'-'*60}")

    rows = []
    for val, grp in df.groupby(group_col):
        if len(grp) < min_n:
            continue
        rows.append((val, len(grp), grp['ret_5d'].mean(), grp['ret_10d'].mean(), grp['ret_20d'].mean()))
    rows.sort(key=lambda x: x[4], reverse=True)

    for val, cnt, r5, r10, r20 in rows:
        m5  = '✅' if r5  > bm5  else '  '
        m20 = '✅' if r20 > bm20 else '  '
        print(f"  {m5}{str(val):<26} {cnt:>5}  {r5:>+7.2f}%  {r10:>+7.2f}%  {m20}{r20:>+6.2f}%")


def print_turnover_by_trend(df):
    """换手率分位数 × 趋势状态 交叉分析"""
    if df.empty:
        return
    bm5  = df['ret_5d'].mean()
    bm20 = df['ret_20d'].mean()
    print(f"\n── 换手率分位数 × 趋势 交叉表（20d均收益）──")
    pivot = df.pivot_table(
        values='ret_20d', index='turnover_group', columns='trend',
        aggfunc='mean'
    )
    print(pivot.round(2).to_string())
    print(f"\n  （基准20d={bm20:+.2f}%）")


def print_macd_vol_combo_df(df: pd.DataFrame):
    """MACD+放量组合详细分析"""
    if df.empty:
        print("  (无数据)")
        return

    bm5  = df['ret_5d'].mean()
    bm20 = df['ret_20d'].mean()
    total = len(df)

    print(f"\n{'='*68}")
    print(f"  MACD × 量能 细分（BULL + WEAK_BULL）总样本={total}")
    print(f"  基准: 5d={bm5:+.2f}%  20d={bm20:+.2f}%")
    print(f"{'='*68}")

    # 趋势内分组
    for trend_val in ['多头排列', '弱势多头']:
        grp_t = df[df['trend'] == trend_val]
        if len(grp_t) < 5:
            continue
        t_bm5  = grp_t['ret_5d'].mean()
        t_bm20 = grp_t['ret_20d'].mean()
        print(f"\n  ── {trend_val} (n={len(grp_t)}, 基准5d={t_bm5:+.2f}% 20d={t_bm20:+.2f}%) ──")
        print(f"  {'MACD':<18} {'量能':<16} {'样本':>4}  {'5d':>7}  {'20d':>7}")
        print(f"  {'-'*55}")

        combo_rows = []
        for (m, v), g in grp_t.groupby(['macd', 'volume_status']):
            if len(g) < 3:
                continue
            combo_rows.append((m, v, len(g), g['ret_5d'].mean(), g['ret_20d'].mean()))
        combo_rows.sort(key=lambda x: x[4], reverse=True)

        for m, v, cnt, r5, r20 in combo_rows:
            m5_flag  = '✅' if r5  > t_bm5  else '  '
            m20_flag = '✅' if r20 > t_bm20 else '  '
            print(f"  {m5_flag}{m20_flag}{m:<16} {v:<14} {cnt:>4}  {r5:>+6.2f}%  {r20:>+6.2f}%")


# ─────────────────────────────────────────────────────────────────────────────
# 主函数
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="补充回测：支撑位/斐波那契/换手率/MACD×放量")
    parser.add_argument('--stocks', default=','.join(STOCKS))
    args = parser.parse_args()

    codes = [c.strip() for c in args.stocks.split(',')]

    all_support = []
    all_fib = []
    all_turnover = []
    all_macd_vol = []

    lg = bs.login()
    print(f"baostock 登录: {lg.error_msg}")

    for idx, code in enumerate(codes):
        print(f"[{idx+1}/{len(codes)}] {code}...")
        try:
            result = backtest_stock(code)
        except Exception as e:
            print(f"  ❌ 跳过: {e}")
            continue
        if not result:
            continue
        all_support.append(result['support'])
        all_fib.append(result['fib'])
        all_turnover.append(result['turnover'])
        all_macd_vol.append(result['macd_vol'])

    bs.logout()

    support_df  = pd.concat(all_support,  ignore_index=True) if all_support  else pd.DataFrame()
    fib_df      = pd.concat(all_fib,      ignore_index=True) if all_fib      else pd.DataFrame()
    turnover_df = pd.concat(all_turnover, ignore_index=True) if all_turnover else pd.DataFrame()
    macd_vol_df = pd.concat(all_macd_vol, ignore_index=True) if all_macd_vol else pd.DataFrame()

    print_section("支撑位接近度", support_df, 'support_proximity')
    print_section("斐波那契回撤位", fib_df, 'fib_level')
    print_section("换手率分位数", turnover_df, 'turnover_group')
    print_turnover_by_trend(turnover_df)
    if not macd_vol_df.empty:
        print_macd_vol_combo_df(macd_vol_df)


if __name__ == '__main__':
    main()
