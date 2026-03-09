# -*- coding: utf-8 -*-
"""
震荡市背离专项回测：半分法 vs Swing Point
==========================================
对比两种背离检测算法在震荡市中的表现，输出收益分布、胜率、盈亏比。

震荡市定义：ADX < 20 且 20日振幅 < 8%（Strategist 建议用 AND）
回测区间：2024-01-02 ~ 2025-06-30
入场价：信号日 T+1 开盘价
持有期：5日 / 10日

用法：
    cd /Users/chengxidai/daily_stock_analysis
    python scripts/backtest_divergence_sideways.py
"""
import sys
import os
import logging
import warnings
from datetime import date
from typing import List, Dict, Any, Tuple, Optional

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.stock_analyzer.indicators import TechnicalIndicators
from src.storage import DatabaseManager

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s'
)
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

START_DATE = '2024-01-02'
END_DATE = '2025-06-30'
PRE_BUFFER_DAYS = 120


# ─── 震荡市判定 ──────────────────────────────────────────────

def is_sideways_market(df: pd.DataFrame, idx: int) -> bool:
    """ADX < 20 且 20日振幅 < 8%（AND 连接，只保留"真震荡"）"""
    if idx < 20:
        return False
    adx_val = df['ADX'].iloc[idx]
    window_20 = df.iloc[idx - 19: idx + 1]
    high_max = window_20['high'].max()
    low_min = window_20['low'].min()
    close_mean = window_20['close'].mean()
    if close_mean <= 0:
        return False
    amplitude = (high_max - low_min) / close_mean * 100
    return adx_val < 20 and amplitude < 8


# ─── 半分法背离检测（复刻 analyzer._analyze_rsi 和 scoring_pattern 的逻辑）───

def detect_divergence_half_split(
    df: pd.DataFrame,
    idx: int,
    indicator_col: str = 'RSI_12',
    window: int = 30,
    price_thr: float = 1.01,
    indicator_thr: float = 3.0,
) -> Dict[str, bool]:
    """半分法背离检测，在 df 的 idx 位置向前看 window 根 K 线。"""
    result = {'top_divergence': False, 'bottom_divergence': False}
    if idx < window - 1:
        return result

    tail = df.iloc[idx - window + 1: idx + 1]
    if len(tail) < window or indicator_col not in tail.columns:
        return result

    half = window // 2
    first_half = tail.head(half)
    second_half = tail.tail(half)

    price_high_prev = float(first_half['high'].max())
    price_high_recent = float(second_half['high'].max())
    ind_high_prev = float(first_half[indicator_col].max())
    ind_high_recent = float(second_half[indicator_col].max())

    price_low_prev = float(first_half['low'].min())
    price_low_recent = float(second_half['low'].min())
    ind_low_prev = float(first_half[indicator_col].min())
    ind_low_recent = float(second_half[indicator_col].min())

    if (price_high_recent > price_high_prev * price_thr
            and ind_high_recent < ind_high_prev - indicator_thr):
        result['top_divergence'] = True
    if (price_low_recent < price_low_prev * (2 - price_thr)
            and ind_low_recent > ind_low_prev + indicator_thr):
        result['bottom_divergence'] = True

    return result


# ─── Swing Point 背离检测（包装 indicators.py 的新函数）───

def detect_divergence_swing_at_idx(
    df: pd.DataFrame,
    idx: int,
    indicator_col: str = 'RSI_12',
    swing_n: int = 3,
    lookback: int = 60,
    price_min_pct: float = 1.0,
    indicator_min_diff: float = 3.0,
) -> Dict[str, bool]:
    """在 df 的 idx 位置，用 swing point 检测背离。

    截取 df[:idx+1] 以模拟"只看到当前及之前数据"。
    但 swing point 需要右侧 n 根来确认极值，
    所以最后 n 根 K 线内的极值不会被检测到，
    这符合实际：极值需要右侧确认才成立。
    """
    result = {'top_divergence': False, 'bottom_divergence': False}
    end = idx + 1
    start = max(0, end - lookback - swing_n)
    sub_df = df.iloc[start:end].copy()

    if len(sub_df) < 2 * swing_n + 1 or indicator_col not in sub_df.columns:
        return result

    det = TechnicalIndicators.detect_divergence_swing(
        sub_df,
        indicator_col=indicator_col,
        swing_n=swing_n,
        lookback=lookback,
        price_min_pct=price_min_pct,
        indicator_min_diff=indicator_min_diff,
    )
    result['top_divergence'] = det['top_divergence']
    result['bottom_divergence'] = det['bottom_divergence']
    return result


# ─── 计算持有期收益 ──────────────────────────────────────────

def calc_forward_returns(
    df: pd.DataFrame, signal_idx: int, hold_days: List[int] = [5, 10]
) -> Dict[str, Optional[float]]:
    """以 signal_idx 的 T+1 开盘价为入场价，计算 hold_days 后的收益率（%）。"""
    ret: Dict[str, Optional[float]] = {}
    entry_idx = signal_idx + 1
    if entry_idx >= len(df):
        for d in hold_days:
            ret[f'ret_{d}d'] = None
        return ret

    entry_price = float(df['open'].iloc[entry_idx])
    if entry_price <= 0:
        for d in hold_days:
            ret[f'ret_{d}d'] = None
        return ret

    for d in hold_days:
        exit_idx = entry_idx + d
        if exit_idx >= len(df):
            ret[f'ret_{d}d'] = None
        else:
            exit_price = float(df['close'].iloc[exit_idx])
            ret[f'ret_{d}d'] = (exit_price - entry_price) / entry_price * 100
    return ret


# ─── 主回测逻辑 ──────────────────────────────────────────────

def run_backtest() -> pd.DataFrame:
    db = DatabaseManager.get_instance()
    records: List[Dict[str, Any]] = []
    swing_ns = [3, 5]

    total = len(STOCKS)
    for si, code in enumerate(STOCKS):
        logger.info(f"[{si+1}/{total}] 处理 {code} ...")
        df = db.get_stock_history_df(code, days=800)
        if df.empty or len(df) < 150:
            logger.warning(f"  {code} 数据不足 ({len(df)} 行)，跳过")
            continue

        df = TechnicalIndicators.calculate_all(df)

        df['date_str'] = df['date'].dt.strftime('%Y-%m-%d')
        start_mask = df['date_str'] >= START_DATE
        end_mask = df['date_str'] <= END_DATE
        valid_indices = df.index[start_mask & end_mask].tolist()

        if not valid_indices:
            logger.warning(f"  {code} 在回测区间内无数据，跳过")
            continue

        sideways_count = 0
        has_obv = 'OBV' in df.columns
        has_j = 'J' in df.columns

        for idx in valid_indices:
            if not is_sideways_market(df, idx):
                continue
            sideways_count += 1
            sim_date = df['date_str'].iloc[idx]

            half_rsi = detect_divergence_half_split(
                df, idx, 'RSI_12', window=30, price_thr=1.01, indicator_thr=3.0)
            half_macd_dif = detect_divergence_half_split(
                df, idx, 'MACD_DIF', window=30, price_thr=1.01, indicator_thr=0.0)
            half_obv = detect_divergence_half_split(
                df, idx, 'OBV', window=20, price_thr=1.01, indicator_thr=0.0) if has_obv else {'top_divergence': False, 'bottom_divergence': False}
            half_kdj = detect_divergence_half_split(
                df, idx, 'J', window=30, price_thr=1.01, indicator_thr=5.0) if has_j else {'top_divergence': False, 'bottom_divergence': False}

            fwd = calc_forward_returns(df, idx, [5, 10])

            for sn in swing_ns:
                swing_rsi = detect_divergence_swing_at_idx(
                    df, idx, 'RSI_12', swing_n=sn, lookback=60,
                    price_min_pct=1.0, indicator_min_diff=3.0)
                swing_macd = detect_divergence_swing_at_idx(
                    df, idx, 'MACD_DIF', swing_n=sn, lookback=60,
                    price_min_pct=1.0, indicator_min_diff=0.0)
                swing_obv = detect_divergence_swing_at_idx(
                    df, idx, 'OBV', swing_n=sn, lookback=60,
                    price_min_pct=1.0, indicator_min_diff=0.0) if has_obv else {'top_divergence': False, 'bottom_divergence': False}
                swing_kdj = detect_divergence_swing_at_idx(
                    df, idx, 'J', swing_n=sn, lookback=60,
                    price_min_pct=1.0, indicator_min_diff=5.0) if has_j else {'top_divergence': False, 'bottom_divergence': False}

                for div_type in ['top', 'bottom']:
                    key = f'{div_type}_divergence'
                    half_rsi_hit = half_rsi[key]
                    half_macd_hit = half_macd_dif[key]
                    swing_rsi_hit = swing_rsi[key]
                    swing_macd_hit = swing_macd[key]
                    half_obv_hit = half_obv[key]
                    swing_obv_hit = swing_obv[key]
                    half_kdj_hit = half_kdj[key]
                    swing_kdj_hit = swing_kdj[key]

                    if not (half_rsi_hit or half_macd_hit or swing_rsi_hit or swing_macd_hit
                            or half_obv_hit or swing_obv_hit or half_kdj_hit or swing_kdj_hit):
                        continue

                    rec = {
                        'code': code,
                        'date': sim_date,
                        'div_type': div_type,
                        'swing_n': sn,
                        'half_rsi': half_rsi_hit,
                        'half_macd': half_macd_hit,
                        'half_obv': half_obv_hit,
                        'half_kdj': half_kdj_hit,
                        'swing_rsi': swing_rsi_hit,
                        'swing_macd': swing_macd_hit,
                        'swing_obv': swing_obv_hit,
                        'swing_kdj': swing_kdj_hit,
                        'ret_5d': fwd.get('ret_5d'),
                        'ret_10d': fwd.get('ret_10d'),
                        'adx': float(df['ADX'].iloc[idx]),
                        'close': float(df['close'].iloc[idx]),
                    }
                    records.append(rec)

        logger.info(f"  {code}: 震荡市日数={sideways_count}, 信号记录={sum(1 for r in records if r['code'] == code)}")

    return pd.DataFrame(records)


# ─── 统计分析 ──────────────────────────────────────────────

def calc_stats(series: pd.Series) -> Dict[str, float]:
    """计算收益统计指标"""
    valid = series.dropna()
    if len(valid) == 0:
        return {'count': 0, 'mean': 0, 'median': 0, 'std': 0, 'q25': 0, 'q75': 0,
                'win_rate': 0, 'profit_loss_ratio': 0}
    wins = valid[valid > 0]
    losses = valid[valid < 0]
    avg_win = wins.mean() if len(wins) > 0 else 0
    avg_loss = abs(losses.mean()) if len(losses) > 0 else 0
    plr = avg_win / avg_loss if avg_loss > 0 else float('inf')
    return {
        'count': len(valid),
        'mean': valid.mean(),
        'median': valid.median(),
        'std': valid.std(),
        'q25': valid.quantile(0.25),
        'q75': valid.quantile(0.75),
        'win_rate': len(wins) / len(valid) * 100,
        'profit_loss_ratio': plr,
    }


def generate_report(df_all: pd.DataFrame) -> str:
    """生成 Markdown 报告"""
    lines = [
        "# 震荡市背离专项回测报告",
        f"\n> 回测区间：{START_DATE} ~ {END_DATE}",
        f"> 股票池：{len(STOCKS)} 只",
        f"> 震荡市定义：ADX < 20 且 20日振幅 < 8%",
        f"> 入场价：信号日 T+1 开盘价",
        "",
    ]

    if df_all.empty:
        lines.append("**未检测到任何背离信号。**")
        return '\n'.join(lines)

    lines.append(f"## 总览\n")
    lines.append(f"- 总信号记录数：{len(df_all)}")
    lines.append(f"- 涉及股票数：{df_all['code'].nunique()}")
    lines.append(f"- 信号日期范围：{df_all['date'].min()} ~ {df_all['date'].max()}")
    lines.append("")

    indicators = [
        ('rsi', 'RSI'), ('macd', 'MACD'),
        ('obv', 'OBV'), ('kdj', 'KDJ(J)'),
    ]

    for sn in sorted(df_all['swing_n'].unique()):
        sub = df_all[df_all['swing_n'] == sn]
        lines.append(f"## Swing N={sn} 对比\n")

        for div_type, div_label in [('top', '顶背离'), ('bottom', '底背离')]:
            div_sub = sub[sub['div_type'] == div_type]
            if div_sub.empty:
                lines.append(f"### {div_label}\n\n无信号\n")
                continue

            lines.append(f"### {div_label}\n")

            for ind_key, ind_label in indicators:
                half_col = f'half_{ind_key}'
                swing_col = f'swing_{ind_key}'

                if half_col not in div_sub.columns or swing_col not in div_sub.columns:
                    continue

                half_hits = div_sub[div_sub[half_col] == True]
                swing_hits = div_sub[div_sub[swing_col] == True]

                if len(half_hits) == 0 and len(swing_hits) == 0:
                    continue

                both_hits = div_sub[(div_sub[half_col] == True) & (div_sub[swing_col] == True)]

                lines.append(f"#### {ind_label} {div_label}\n")
                lines.append(f"| 指标 | 半分法 | Swing Point (N={sn}) |")
                lines.append(f"|------|--------|---------------------|")
                lines.append(f"| 信号数 | {len(half_hits)} | {len(swing_hits)} |")

                if len(both_hits) > 0:
                    lines.append(f"| 重叠信号数 | {len(both_hits)} | {len(both_hits)} |")

                for ret_col, ret_label in [('ret_5d', '5日'), ('ret_10d', '10日')]:
                    h_stats = calc_stats(half_hits[ret_col])
                    s_stats = calc_stats(swing_hits[ret_col])

                    lines.append(f"\n**{ret_label}收益分布**\n")
                    lines.append(f"| 统计量 | 半分法 | Swing Point |")
                    lines.append(f"|--------|--------|-------------|")
                    lines.append(f"| 样本数 | {h_stats['count']:.0f} | {s_stats['count']:.0f} |")
                    lines.append(f"| 均值 | {h_stats['mean']:.2f}% | {s_stats['mean']:.2f}% |")
                    lines.append(f"| 中位数 | {h_stats['median']:.2f}% | {s_stats['median']:.2f}% |")
                    lines.append(f"| 标准差 | {h_stats['std']:.2f}% | {s_stats['std']:.2f}% |")
                    lines.append(f"| Q25 | {h_stats['q25']:.2f}% | {s_stats['q25']:.2f}% |")
                    lines.append(f"| Q75 | {h_stats['q75']:.2f}% | {s_stats['q75']:.2f}% |")
                    lines.append(f"| 胜率 | {h_stats['win_rate']:.1f}% | {s_stats['win_rate']:.1f}% |")
                    plr_h = f"{h_stats['profit_loss_ratio']:.2f}" if h_stats['profit_loss_ratio'] != float('inf') else "∞"
                    plr_s = f"{s_stats['profit_loss_ratio']:.2f}" if s_stats['profit_loss_ratio'] != float('inf') else "∞"
                    lines.append(f"| 盈亏比 | {plr_h} | {plr_s} |")

            lines.append("")

    lines.append("## 汇总\n")
    for sn in sorted(df_all['swing_n'].unique()):
        sub = df_all[df_all['swing_n'] == sn]
        lines.append(f"### N={sn} 信号统计\n")
        lines.append("| 类型 | 半RSI | 半MACD | 半OBV | 半KDJ | SwRSI | SwMACD | SwOBV | SwKDJ |")
        lines.append("|------|-------|--------|-------|-------|-------|--------|-------|-------|")
        for dt, dl in [('top', '顶背离'), ('bottom', '底背离')]:
            ds = sub[sub['div_type'] == dt]
            cols = []
            for k in ['half_rsi', 'half_macd', 'half_obv', 'half_kdj',
                       'swing_rsi', 'swing_macd', 'swing_obv', 'swing_kdj']:
                cols.append(f"{ds[k].sum():.0f}" if k in ds.columns else "0")
            lines.append(f"| {dl} | {' | '.join(cols)} |")
        lines.append("")

    return '\n'.join(lines)


# ─── 入口 ──────────────────────────────────────────────────

def main():
    logger.info("=" * 60)
    logger.info("震荡市背离专项回测开始")
    logger.info(f"股票池: {len(STOCKS)} 只, 区间: {START_DATE} ~ {END_DATE}")
    logger.info(f"对比: 半分法 vs Swing Point (N=3, N=5)")
    logger.info("=" * 60)

    df_all = run_backtest()

    if df_all.empty:
        logger.warning("回测未产生任何信号记录")
        report = "# 震荡市背离专项回测报告\n\n**未检测到任何背离信号。**\n"
    else:
        logger.info(f"回测完成，总信号记录: {len(df_all)}")
        report = generate_report(df_all)

    os.makedirs('reports', exist_ok=True)
    csv_path = 'reports/divergence_sideways_raw.csv'
    report_path = 'reports/divergence_sideways_report.md'

    df_all.to_csv(csv_path, index=False, encoding='utf-8-sig')
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write(report)

    logger.info(f"原始数据: {csv_path}")
    logger.info(f"报告: {report_path}")
    print(f"\n{'=' * 60}")
    print(f"报告已生成: {report_path}")
    print(f"原始数据: {csv_path}")
    print(f"{'=' * 60}")


if __name__ == '__main__':
    main()
