"""
穷举场景回测：60只多样化主板股票
================================
分析7维信号组合（趋势×MACD×RSI×KDJ×量能×换手率×Bias）
输出所有n>=20的组合的收益统计，用于制定solid场景结论

用法：
    cd /Users/chengxidai/daily_stock_analysis
    python scripts/backtest_exhaustive.py
"""
import sys
import os
import pandas as pd
import numpy as np
import baostock as bs
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.backtest_improvements import calc_indicators, get_trend_status, get_macd_status

# ─────────────────────────────────────────────────────────────────────────────
# 60只多样化主板股票（覆盖行业/市值/风格）
# ─────────────────────────────────────────────────────────────────────────────
STOCKS = [
    # 原蓝筹9只
    '600519', '000858', '000333', '000002', '600036', '601318', '002415', '300059', '600900',
    # 原多样化15只
    '601088', '600019', '000895', '002304', '603288', '002557',
    '002594', '601127', '300750', '600276', '000538', '002916', '000001', '600016', '000568',
    # 补充：周期/资源
    '600028',  # 中国石化
    '601857',  # 中国石油
    '600362',  # 江西铜业
    '000039',  # 中集集团
    '601600',  # 中国铝业
    # 补充：科技/成长
    '002230',  # 科大讯飞
    '300014',  # 亿纬锂能
    '002475',  # 立讯精密
    '603501',  # 韦尔股份
    '688036',  # 传音控股
    # 补充：医药/生物
    '600196',  # 复星医药
    '000661',  # 长春高新
    '300122',  # 智飞生物
    '002558',  # 世荣兆业（中药）
    '600085',  # 同仁堂
    # 补充：消费/零售
    '600887',  # 伊利股份
    '002714',  # 牧原股份
    '601866',  # 中远海控（周期消费）
    '000725',  # 京东方A（电子消费）
    '002352',  # 顺丰控股
    # 补充：银行/金融
    '601328',  # 交通银行
    '000776',  # 广发证券
    '601688',  # 华泰证券
    '600030',  # 中信证券
    '600837',  # 海通证券
    # 补充：房地产/建筑
    '000069',  # 华侨城A
    '600048',  # 保利发展
    '601668',  # 中国建筑
    '000786',  # 北新建材
    # 补充：中小盘制造
    '300015',  # 爱尔眼科
    '002460',  # 赣锋锂业
    '300274',  # 阳光电源
    '601138',  # 工业富联
    '002049',  # 紫光国微
    # 补充：传统行业
    '600690',  # 海尔智家
    '000725',  # 京东方A
    '601166',  # 兴业银行
    '600009',  # 上海机场
    '601006',  # 大秦铁路
]

# 去重
STOCKS = list(dict.fromkeys(STOCKS))
HISTORY_DAYS = 600
FORWARD_WINDOWS = [5, 10, 20]
MIN_COMBO_N = 20  # 最低样本量要求


# ─────────────────────────────────────────────────────────────────────────────
# 数据获取
# ─────────────────────────────────────────────────────────────────────────────

def fetch_with_turn(code: str) -> pd.DataFrame:
    end_dt = date.today()
    beg_dt = end_dt - timedelta(days=int(HISTORY_DAYS * 1.6))
    prefix = 'sh' if code.startswith(('6', '9')) else 'sz'
    rs = bs.query_history_k_data_plus(
        f'{prefix}.{code}',
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
    return df.set_index('date').sort_index().iloc[-HISTORY_DAYS:]


# ─────────────────────────────────────────────────────────────────────────────
# 信号分类函数
# ─────────────────────────────────────────────────────────────────────────────

def get_rsi_group(row, prev_row):
    rsi = float(row.get('RSI_12', 50) or 50)
    rsi_prev = float(prev_row.get('RSI_12', 50) or 50)
    if rsi > rsi_prev and rsi_prev <= 30:
        return 'oversold_cross'
    if rsi > 70:
        return 'overbought'
    elif rsi > 60:
        return 'strong'
    elif rsi >= 40:
        return 'neutral'
    elif rsi >= 30:
        return 'weak'
    else:
        return 'oversold'


def get_kdj_group(row, prev_row):
    k = float(row.get('KDJ_K', 50) or 50)
    d = float(row.get('KDJ_D', 50) or 50)
    j = float(row.get('KDJ_J', 50) or 50)
    k_prev = float(prev_row.get('KDJ_K', 50) or 50)
    d_prev = float(prev_row.get('KDJ_D', 50) or 50)
    if k > d and k_prev <= d_prev:
        return 'golden_cross_os' if j < 20 else 'golden_cross'
    elif k < d and k_prev >= d_prev:
        return 'death_cross'
    if j > 100:
        return 'overbought'
    elif j < 0:
        return 'oversold'
    elif k > d:
        return 'bullish'
    elif k < d:
        return 'bearish'
    return 'neutral'


def get_bias_group(row):
    bias = float(row.get('BIAS_MA5', 0) or 0)
    bb_width = float(row.get('BB_WIDTH', 0) or 0)
    if bb_width > 0.01:
        half_bb = bb_width * 50
        nb = bias / half_bb if half_bb > 0 else 0
        if nb > 1.0:
            return 'high_pos'
        elif nb > 0:
            return 'low_pos'
        elif nb >= -1.0:
            return 'low_neg'
        else:
            return 'high_neg'
    if bias > 5:
        return 'high_pos'
    elif bias > 0:
        return 'low_pos'
    elif bias >= -5:
        return 'low_neg'
    else:
        return 'high_neg'


def get_vol_group(row):
    avg20 = float(row.get('VOL_AVG20', 0) or 0)
    vol = float(row.get('volume', 0) or 0)
    close = float(row.get('close', 0) or 0)
    open_ = float(row.get('open', 0) or 0)
    if avg20 <= 0:
        return 'normal'
    ratio = vol / avg20
    up = close >= open_
    if ratio >= 1.5 and up:
        return 'heavy_up'
    elif ratio >= 1.5:
        return 'heavy_down'
    elif ratio <= 0.7 and up:
        return 'shrink_up'
    elif ratio <= 0.7:
        return 'shrink_down'
    return 'normal'


def get_turn_group(arr, i, window=60):
    hist = arr[max(0, i - window):i]
    hist = hist[~np.isnan(hist) & (hist > 0)]
    if len(hist) < 10 or np.isnan(arr[i]) or arr[i] <= 0:
        return 'no_data'
    p = (hist < arr[i]).mean() * 100
    if p >= 90:
        return 'very_high'
    elif p >= 70:
        return 'high'
    elif p >= 30:
        return 'normal'
    elif p >= 10:
        return 'low'
    else:
        return 'very_low'


# ─────────────────────────────────────────────────────────────────────────────
# 单股处理
# ─────────────────────────────────────────────────────────────────────────────

def process_stock(code: str) -> list:
    df = fetch_with_turn(code)
    if len(df) < 80:
        return []

    df = calc_indicators(df)
    close = df['close'].values.astype(float)
    n = len(close)

    # 批量计算未来收益
    rets = {}
    for fwd in FORWARD_WINDOWS:
        ret = np.full(n, np.nan)
        ret[:n - fwd] = (close[fwd:] - close[:n - fwd]) / close[:n - fwd] * 100
        rets[fwd] = ret

    turn_arr = df['turn'].astype(float).values if 'turn' in df.columns else np.full(n, np.nan)
    rows = df.reset_index(drop=False)

    records = []
    for i in range(60, n - max(FORWARD_WINDOWS)):
        r5 = rets[5][i]
        r10 = rets[10][i]
        r20 = rets[20][i]
        if np.isnan(r5) or np.isnan(r20):
            continue

        row = rows.iloc[i]
        prev = rows.iloc[i - 1]

        records.append({
            'trend':   get_trend_status(row).value,
            'macd':    get_macd_status(row, prev).value,
            'rsi':     get_rsi_group(row, prev),
            'kdj':     get_kdj_group(row, prev),
            'bias':    get_bias_group(row),
            'vol':     get_vol_group(row),
            'turn':    get_turn_group(turn_arr, i),
            'ret_5d':  round(r5, 2),
            'ret_10d': round(r10, 2),
            'ret_20d': round(r20, 2),
            'code':    code,
        })
    return records


# ─────────────────────────────────────────────────────────────────────────────
# 输出函数
# ─────────────────────────────────────────────────────────────────────────────

def print_combo_table(df: pd.DataFrame, dims: list, title: str, min_n: int = MIN_COMBO_N):
    bm5 = df['ret_5d'].mean()
    bm20 = df['ret_20d'].mean()
    total = len(df)
    print(f"\n{'='*80}")
    print(f"  {title}  总样本={total}  基准: 5d={bm5:+.2f}%  20d={bm20:+.2f}%")
    print(f"{'='*80}")

    grouped = df.groupby(dims)
    rows = []
    for keys, g in grouped:
        if len(g) < min_n:
            continue
        rows.append((*keys, len(g), g['ret_5d'].mean(), g['ret_10d'].mean(), g['ret_20d'].mean()))

    rows.sort(key=lambda x: x[-1], reverse=True)  # 按20d排序

    header = '  ' + '  '.join(f'{d:<12}' for d in dims) + f'  {"n":>5}  {"5d":>8}  {"10d":>8}  {"20d":>8}'
    print(header)
    print('  ' + '-' * (len(header) - 2))

    for row in rows:
        keys = row[:len(dims)]
        n, r5, r10, r20 = row[len(dims):]
        flag5 = '✅' if r5 > bm5 else '  '
        flag20 = '✅' if r20 > bm20 else '  '
        key_str = '  '.join(f'{str(k):<12}' for k in keys)
        print(f"  {flag5}{flag20}{key_str}  {n:>5}  {r5:>+7.2f}%  {r10:>+7.2f}%  {r20:>+7.2f}%")

    print(f"\n  共 {len(rows)} 个组合（n>={min_n}），{len([r for r in rows if r[-1] > bm20])} 个跑赢基准")


def save_results_csv(df: pd.DataFrame, dims: list, filename: str, min_n: int = 10):
    grouped = df.groupby(dims)
    rows = []
    for keys, g in grouped:
        if len(g) < min_n:
            continue
        rows.append({
            **{d: k for d, k in zip(dims, keys if isinstance(keys, tuple) else (keys,))},
            'n': len(g),
            'ret_5d': round(g['ret_5d'].mean(), 2),
            'ret_10d': round(g['ret_10d'].mean(), 2),
            'ret_20d': round(g['ret_20d'].mean(), 2),
            'win_rate_20d': round((g['ret_20d'] > 0).mean() * 100, 1),
        })
    out = pd.DataFrame(rows).sort_values('ret_20d', ascending=False)
    out_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'docs', filename)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    out.to_csv(out_path, index=False, encoding='utf-8-sig')
    print(f"\n  ✅ 结果已保存: {out_path}")
    return out


# ─────────────────────────────────────────────────────────────────────────────
# 主函数
# ─────────────────────────────────────────────────────────────────────────────

def main():
    print(f"=== 穷举场景回测：{len(STOCKS)} 只股票 ===\n")

    lg = bs.login()
    print(f"baostock: {lg.error_msg}\n")

    all_records = []
    for idx, code in enumerate(STOCKS):
        print(f"[{idx+1:02d}/{len(STOCKS)}] {code}...", end=' ', flush=True)
        try:
            recs = process_stock(code)
            all_records.extend(recs)
            print(f"n={len(recs)}")
        except Exception as e:
            print(f"❌ {e}")

    bs.logout()

    df = pd.DataFrame(all_records)
    # 过滤掉换手率无数据
    df_with_turn = df[df['turn'] != 'no_data'].copy()

    print(f"\n总样本: {len(df)}  含换手率: {len(df_with_turn)}")
    print(f"股票: {df['code'].nunique()} 只")

    bm5 = df['ret_5d'].mean()
    bm10 = df['ret_10d'].mean()
    bm20 = df['ret_20d'].mean()
    print(f"基准: 5d={bm5:+.2f}%  10d={bm10:+.2f}%  20d={bm20:+.2f}%")

    # ── 核心输出1：趋势 × 换手率 × 量能（3维，最可信）
    print_combo_table(df_with_turn, ['trend', 'turn', 'vol'], "【核心3维】趋势 × 换手率 × 量能")
    save_results_csv(df_with_turn, ['trend', 'turn', 'vol'], 'backtest_3d_trend_turn_vol.csv', min_n=15)

    # ── 核心输出2：趋势 × MACD × 换手率（3维）
    print_combo_table(df_with_turn, ['trend', 'macd', 'turn'], "【核心3维】趋势 × MACD × 换手率")
    save_results_csv(df_with_turn, ['trend', 'macd', 'turn'], 'backtest_3d_trend_macd_turn.csv', min_n=15)

    # ── 核心输出3：趋势 × RSI × 换手率（3维）
    print_combo_table(df_with_turn, ['trend', 'rsi', 'turn'], "【核心3维】趋势 × RSI × 换手率")
    save_results_csv(df_with_turn, ['trend', 'rsi', 'turn'], 'backtest_3d_trend_rsi_turn.csv', min_n=15)

    # ── 核心输出4：趋势 × 量能 × Bias（3维）
    print_combo_table(df, ['trend', 'vol', 'bias'], "【核心3维】趋势 × 量能 × Bias（全样本）")
    save_results_csv(df, ['trend', 'vol', 'bias'], 'backtest_3d_trend_vol_bias.csv', min_n=20)

    # ── 核心输出5：4维（趋势 × MACD × 换手率 × 量能）
    print_combo_table(df_with_turn, ['trend', 'macd', 'turn', 'vol'], "【4维】趋势 × MACD × 换手率 × 量能", min_n=15)
    save_results_csv(df_with_turn, ['trend', 'macd', 'turn', 'vol'], 'backtest_4d_trend_macd_turn_vol.csv', min_n=10)

    # ── 单维汇总
    print("\n\n=== 单维收益汇总 ===")
    for dim in ['trend', 'macd', 'rsi', 'kdj', 'vol', 'turn', 'bias']:
        src = df_with_turn if dim == 'turn' else df
        print(f"\n-- {dim} --")
        for val, g in src.groupby(dim):
            if len(g) < 20:
                continue
            flag = '✅' if g['ret_20d'].mean() > bm20 else '  '
            print(f"  {flag}{str(val):<20} n={len(g):5d}  5d={g['ret_5d'].mean():+.2f}%  20d={g['ret_20d'].mean():+.2f}%")


if __name__ == '__main__':
    main()
