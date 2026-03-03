"""
历史信号回测 + IC分析（大样本版）
====================================
对61只股票600天K线，逐日计算技术因子，
以每日收盘后信号→T+1开盘价买入→T+5收盘价收益作为标准口径，
输出：
1. 各维度 Spearman IC（vs 5日收益）
2. 总评分分档单调性（7档）
3. 量能/KDJ/MACD反向信号分析

用法：
    cd /Users/chengxidai/daily_stock_analysis
    python scripts/backtest_historical_ic.py
"""
import sys
import os
import warnings
import logging
import pandas as pd
import numpy as np
from datetime import date
from typing import List, Dict, Optional

warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scipy import stats
from sqlalchemy import text
from src.storage import DatabaseManager
from src.stock_analyzer.indicators import TechnicalIndicators

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

STOCKS = [
    '600519', '000858', '000333', '000002', '600036', '601318', '002415', '300059', '600900',
    '601088', '600019', '000895', '002304', '603288', '002557',
    '002594', '601127', '300750', '600276', '000538', '002916', '000001', '600016', '000568',
    '600028', '601857', '600362', '000039', '601600',
    '002230', '300014', '002475', '603501', '688036',
    '600196', '000661', '300122', '600085',
    '600887', '002714', '601866', '000725', '002352',
    '601328', '000776', '601688', '600030', '600837',
    '000069', '600048', '601668', '000786',
    '300015', '002460', '300274', '601138', '002049',
    '600690', '601166', '600009', '601006',
]
STOCKS = list(dict.fromkeys(STOCKS))

# 信号采样：每只股票每10个交易日采样一次，避免20日收益期间的样本重叠
SAMPLE_INTERVAL = 10
# 最少需要多少天历史数据才计算（指标需要预热）
MIN_LOOKBACK = 60
# 最大持有期（需要多少天后续数据）
MAX_FORWARD = 22


def load_stock_data(db: DatabaseManager, code: str) -> Optional[pd.DataFrame]:
    """从 stock_daily 加载全量数据"""
    try:
        with db._engine.connect() as conn:
            df = pd.read_sql(text("""
                SELECT date, open, high, low, close, volume
                FROM stock_daily WHERE code=:code ORDER BY date ASC
            """), conn, params={'code': code})
        if df.empty or len(df) < MIN_LOOKBACK + 10:
            return None
        for col in ['open', 'high', 'low', 'close', 'volume']:
            df[col] = pd.to_numeric(df[col], errors='coerce')
        df['date'] = pd.to_datetime(df['date'])
        df = df.sort_values('date').dropna(subset=['close']).reset_index(drop=True)
        return df
    except Exception as e:
        logger.debug(f"加载 {code} 失败: {e}")
        return None


def calc_factors(df_with_indicators: pd.DataFrame, idx: int) -> Optional[Dict[str, float]]:
    """从预计算好的指标df中提取第idx行的各维度因子值"""
    if idx < MIN_LOOKBACK or idx >= len(df_with_indicators):
        return None
    row = df_with_indicators.iloc[idx]

    try:
        close = float(row['close'])
        ma5   = float(row.get('MA5', 0) or 0)
        ma10  = float(row.get('MA10', 0) or 0)
        ma20  = float(row.get('MA20', 0) or 0)
        ma60  = float(row.get('MA60', 0) or 0)

        if close <= 0 or ma20 <= 0:
            return None

        # 趋势因子：均线多头排列程度 (MA5-MA20)/MA20
        trend_factor = (ma5 - ma20) / ma20 * 100

        # 乖离率因子
        bias_factor = (close - ma20) / ma20 * 100

        # 量能因子：当日量/20日均量
        vol = float(row.get('volume', 0) or 0)
        vol_avg20_series = df_with_indicators['volume'].iloc[max(0, idx-19):idx+1].astype(float)
        vol_avg20 = float(vol_avg20_series.mean()) if len(vol_avg20_series) > 0 else 0
        volume_factor = (vol / vol_avg20) if vol_avg20 > 0 else 1.0

        # 支撑因子：价格相对MA20位置（越接近MA20且在上方=正支撑）
        support_factor = bias_factor  # 与乖离率共线，后续可改为支撑位距离

        # MACD柱状图
        macd_bar = float(row.get('MACD_BAR', row.get('MACD_hist', 0)) or 0)

        # RSI_12 连续值
        rsi12 = float(row.get('RSI_12', row.get('RSI', 50)) or 50)

        # KDJ J值
        j_val = float(row.get('J', row.get('KDJ_J', 50)) or 50)

        # 简化版总评分（连续值）：趋势+MACD+RSI位置的线性组合
        # 趋势权重40%，MACD权重25%，RSI偏离50程度权重20%，量能权重15%
        norm_trend  = max(0, min(1, (trend_factor + 5) / 10))
        norm_macd   = max(0, min(1, (macd_bar + 0.2) / 0.4))
        norm_rsi    = max(0, min(1, rsi12 / 100))
        norm_volume = max(0, min(2, volume_factor)) / 2
        composite_score = (
            norm_trend * 40 +
            norm_macd  * 25 +
            norm_rsi   * 20 +
            norm_volume * 15
        )  # 0~100范围

        return {
            'trend':     trend_factor,
            'bias':      bias_factor,
            'volume':    volume_factor,
            'support':   support_factor,
            'macd':      macd_bar,
            'rsi':       rsi12,
            'kdj':       j_val,
            'composite': composite_score,
        }
    except Exception as e:
        logger.debug(f"因子计算失败 idx={idx}: {e}")
        return None


def run_backtest_ic():
    db = DatabaseManager()

    print("=" * 65)
    print("历史信号回测 + IC分析（大样本）")
    print(f"股票池: {len(STOCKS)} 只，采样间隔: {SAMPLE_INTERVAL} 交易日")
    print("=" * 65)
    print()

    all_rows = []

    for code in STOCKS:
        df = load_stock_data(db, code)
        if df is None:
            continue

        # 预计算全部技术指标
        try:
            df_ind = TechnicalIndicators.calculate_all(df.copy())
        except Exception as e:
            logger.debug(f"{code} calculate_all 失败: {e}")
            continue

        n = len(df_ind)
        # 逐日采样（每SAMPLE_INTERVAL天采一个信号点）
        for idx in range(MIN_LOOKBACK, n - 6, SAMPLE_INTERVAL):
            # 需要足够的后续数据（T+1~T+22）
            if idx + MAX_FORWARD >= n:
                break
            t1_open = float(df_ind.iloc[idx + 1].get('open', 0) or 0)
            if t1_open <= 0:
                continue

            # 计算5/10/20日收益
            def _pct(fwd_idx):
                c = float(df_ind.iloc[min(idx + fwd_idx, n-1)]['close'] or 0)
                return (c - t1_open) / t1_open * 100 if c > 0 and t1_open > 0 else np.nan

            pct_5d  = _pct(5)
            pct_10d = _pct(10)
            pct_20d = _pct(20)

            if np.isnan(pct_5d):
                continue

            # 提取因子值
            factors = calc_factors(df_ind, idx)
            if factors is None:
                continue

            all_rows.append({
                'code':      code,
                'date':      df_ind.iloc[idx]['date'],
                'pct_5d':    pct_5d,
                'pct_10d':   pct_10d,
                'pct_20d':   pct_20d,
                **factors,
            })

    df_all = pd.DataFrame(all_rows)
    print(f"总样本量: {len(df_all)} 条（来自 {df_all['code'].nunique()} 只股票）\n")

    if len(df_all) < 50:
        print("⚠️  样本量不足50，结果不可靠")
        return

    dims = ['trend', 'bias', 'volume', 'macd', 'rsi', 'kdj', 'composite']
    dim_labels = {
        'trend':     '趋势(MA5-MA20/MA20)',
        'bias':      '乖离率(close-MA20)',
        'volume':    '量能比(vol/ma20)',
        'macd':      'MACD柱状图',
        'rsi':       'RSI_12',
        'kdj':       'KDJ_J值',
        'composite': '合成评分(线性)',
    }

    print("=" * 75)
    print("Spearman IC（各因子 vs 5/10/20日收益）")
    print("|IC|>0.06 显著  p<0.05 统计可靠  ***p<0.01  **p<0.05")
    print("=" * 75)
    print(f"{'维度':<22} {'5日IC':>9} {'10日IC':>9} {'20日IC':>9} {'趋势':<12} 判断")
    print("-" * 75)

    ic_results = {}
    for dim in dims:
        factor = df_all[dim].values
        valid5  = ~np.isnan(factor) & ~np.isnan(df_all['pct_5d'].values)  & np.isfinite(factor)
        valid10 = ~np.isnan(factor) & ~np.isnan(df_all['pct_10d'].values) & np.isfinite(factor)
        valid20 = ~np.isnan(factor) & ~np.isnan(df_all['pct_20d'].values) & np.isfinite(factor)
        if valid5.sum() < 30:
            continue
        ic5,  p5  = stats.spearmanr(factor[valid5],  df_all['pct_5d'].values[valid5])
        ic10, p10 = stats.spearmanr(factor[valid10], df_all['pct_10d'].values[valid10])
        ic20, p20 = stats.spearmanr(factor[valid20], df_all['pct_20d'].values[valid20])

        def _sig(p): return '***' if p < 0.01 else '**' if p < 0.05 else '*' if p < 0.1 else ''
        def _fmt(ic, p): return f"{ic:+.4f}{_sig(p)}"

        # 判断IC随时间是否上升（技术因子应对更长期更有效）
        trend_str = '↑升' if ic20 > ic5 + 0.01 else '↓降' if ic5 > ic20 + 0.01 else '→平'

        if ic20 >= 0.06 and p20 < 0.05:
            judge = '✅ 20日显著正向'
        elif ic20 >= 0.03:
            judge = '🟡 20日弱正'
        elif ic20 <= -0.06 and p20 < 0.05:
            judge = '🔴 20日显著反向'
        elif ic5 <= -0.06 and p5 < 0.05:
            judge = '� 5日显著反向'
        else:
            judge = '⚪ 无效'

        label = dim_labels.get(dim, dim)
        print(f"{label:<22} {_fmt(ic5,p5):>9} {_fmt(ic10,p10):>9} {_fmt(ic20,p20):>9} {trend_str:<12} {judge}")
        ic_results[dim] = {'ic5': ic5, 'ic10': ic10, 'ic20': ic20, 'p5': p5, 'p10': p10, 'p20': p20}

    print()

    # 合成评分分档单调性
    print("=" * 65)
    print("合成评分分档 vs 5日收益单调性")
    print("=" * 65)
    q = df_all['composite'].quantile([0.2, 0.4, 0.6, 0.8]).values
    df_all['score_q'] = pd.cut(df_all['composite'],
                                bins=[-np.inf, q[0], q[1], q[2], q[3], np.inf],
                                labels=['Q1(最低)', 'Q2', 'Q3', 'Q4', 'Q5(最高)'])
    print(f"{'分位档':<12} {'样本数':>6} {'平均收益':>10} {'胜率':>8} {'夏普':>8}")
    print("-" * 50)
    for lbl in ['Q1(最低)', 'Q2', 'Q3', 'Q4', 'Q5(最高)']:
        sub = df_all[df_all['score_q'] == lbl]['pct_5d']
        if len(sub) == 0:
            continue
        avg = sub.mean()
        win = (sub > 0).mean() * 100
        sharpe = (sub.mean() / sub.std() * np.sqrt(50)) if sub.std() > 0 else 0
        print(f"{lbl:<12} {len(sub):>6} {avg:>+10.2f}% {win:>7.0f}% {sharpe:>8.2f}")

    print()

    # 分年度IC稳定性（用20日收益）
    print("=" * 65)
    print("各年度IC稳定性（vs 20日收益，trend / rsi / volume 三因子）")
    print("=" * 65)
    df_all['year'] = pd.to_datetime(df_all['date']).dt.year
    print(f"{'年份':<8} {'样本数':>6} {'trend20':>10} {'rsi20':>10} {'vol20':>10} {'macd20':>10}")
    print("-" * 58)
    for yr in sorted(df_all['year'].unique()):
        sub = df_all[df_all['year'] == yr].dropna(subset=['pct_20d'])
        if len(sub) < 20:
            continue
        r20 = sub['pct_20d'].values
        ic_t  = stats.spearmanr(sub['trend'].values,  r20)[0]
        ic_r  = stats.spearmanr(sub['rsi'].values,    r20)[0]
        ic_v  = stats.spearmanr(sub['volume'].values, r20)[0]
        ic_m  = stats.spearmanr(sub['macd'].values,   r20)[0]
        print(f"{yr:<8} {len(sub):>6} {ic_t:>10.4f} {ic_r:>10.4f} {ic_v:>10.4f} {ic_m:>10.4f}")

    print()
    print("=" * 65)
    print("改进建议（基于大样本IC，优先看20日）")
    print("=" * 65)
    for dim, res in ic_results.items():
        ic20 = res['ic20']
        ic5  = res['ic5']
        p20  = res['p20']
        label = dim_labels.get(dim, dim)
        if ic20 <= -0.06 and p20 < 0.05:
            print(f"⚠️  {label}（IC20={ic20:.4f}, p={p20:.3f}）：显著反向，建议大幅降权或反转逻辑")
        elif ic20 <= -0.03:
            print(f"📉 {label}（IC20={ic20:.4f}）：弱反向，建议适当降权")
        elif ic20 >= 0.06 and p20 < 0.05:
            print(f"💡 {label}（IC20={ic20:.4f}, p={p20:.3f}）：显著正向，建议提高权重")
        elif ic5 <= -0.06 and res['p5'] < 0.05:
            print(f"⚠️  {label}（IC5={ic5:.4f}）：5日反向信号，短线不应依赖此因子")


if __name__ == '__main__':
    run_backtest_ic()
