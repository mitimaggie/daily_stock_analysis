"""
P3 共振算法回测验证脚本
=============================
滑动窗口模拟：对每个历史时间点，用截至当日的数据运行
detect_sequential_behavior / score_multi_signal_resonance / forecast_next_days，
然后统计 N 日后的实际涨跌，验证预判方向准确率。

用法：
    cd /Users/chengxidai/daily_stock_analysis
    python scripts/backtest_p3_resonance.py [--stocks 600519,000001] [--days 5] [--verbose]
"""
import sys
import os
import argparse
import pandas as pd
import numpy as np
from collections import defaultdict
from typing import Optional

# 确保能 import 项目模块
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.stock_analyzer.scoring import ScoringSystem
from src.stock_analyzer.types import TrendAnalysisResult, TrendStatus
from src.storage import DatabaseManager


# ─────────────────────────────────────────────
# 工具：模拟一个时间点的信号
# ─────────────────────────────────────────────
def run_signals_at(df_slice: pd.DataFrame, code: str) -> TrendAnalysisResult:
    """对给定的历史切片运行 P3 信号，返回结果对象"""
    result = TrendAnalysisResult(code=code)
    result.signal_reasons = []
    result.risk_factors = []
    result.score_breakdown = {}

    # 简单判断日线趋势（MA5/MA20）
    close = df_slice['close'].values.astype(float)
    n = len(close)
    if n >= 20:
        ma5 = close[-5:].mean()
        ma20 = close[-20:].mean()
        if ma5 > ma20 * 1.01:
            result.trend_status = TrendStatus.BULL
        elif ma5 < ma20 * 0.99:
            result.trend_status = TrendStatus.BEAR
        else:
            result.trend_status = TrendStatus.SIDEWAYS

    # 简单模拟周线趋势（用60日均线判断）
    if n >= 60:
        ma60 = close[-60:].mean()
        if close[-1] > ma60 * 1.02:
            result.weekly_trend = "多头"
        elif close[-1] < ma60 * 0.98:
            result.weekly_trend = "空头"
        else:
            result.weekly_trend = "震荡"

    # 运行 P2/P3 信号
    ScoringSystem.score_vol_anomaly(result, df_slice)
    ScoringSystem.score_fibonacci_levels(result, df_slice)
    ScoringSystem.score_vol_price_structure(result, df_slice)
    ScoringSystem.detect_sequential_behavior(result, df_slice)
    ScoringSystem.score_multi_signal_resonance(result, df_slice)
    ScoringSystem.forecast_next_days(result, df_slice)

    return result


# ─────────────────────────────────────────────
# 主回测逻辑
# ─────────────────────────────────────────────
def backtest_stock(code: str, full_df: pd.DataFrame, forward_days: int = 5,
                   min_history: int = 60, verbose: bool = False):
    """
    对单只股票做滑动窗口回测。
    
    Returns:
        list of dict: 每个时间点的信号和结果
    """
    records = []
    n = len(full_df)

    for i in range(min_history, n - forward_days):
        df_slice = full_df.iloc[:i].copy()
        df_future = full_df.iloc[i:i + forward_days]

        try:
            result = run_signals_at(df_slice, code)
        except Exception as e:
            continue

        if not result.forecast_scenario:
            continue

        # 计算 N 日后实际涨跌
        entry_price = float(full_df.iloc[i]['close'])
        future_close = float(df_future['close'].iloc[-1])
        actual_return = (future_close - entry_price) / entry_price

        # 定义实际方向（±1.5% 为有效方向，中间算横盘）
        if actual_return > 0.015:
            actual_dir = "up"
        elif actual_return < -0.015:
            actual_dir = "down"
        else:
            actual_dir = "sideways"

        # 预判方向：取最大概率方向
        prob_up = result.forecast_prob_up
        prob_down = result.forecast_prob_down
        prob_sw = result.forecast_prob_sideways

        max_p = max(prob_up, prob_down, prob_sw)
        if max_p == prob_up:
            pred_dir = "up"
        elif max_p == prob_down:
            pred_dir = "down"
        else:
            pred_dir = "sideways"

        is_correct = (pred_dir == actual_dir)
        # 只统计预测涨/跌的强方向，横盘预测排除（准确率意义较小）
        is_directional = pred_dir in ("up", "down")

        date_str = str(full_df.index[i]) if isinstance(full_df.index, pd.DatetimeIndex) else \
                   str(full_df.iloc[i].get('date', i))

        record = {
            'code': code,
            'date': date_str,
            'resonance_level': result.resonance_level,
            'resonance_intent': result.resonance_intent,
            'forecast_scenario': result.forecast_scenario,
            'seq_behaviors': ','.join(result.seq_behaviors),
            'prob_up': prob_up,
            'prob_down': prob_down,
            'prob_sw': prob_sw,
            'pred_dir': pred_dir,
            'actual_return': round(actual_return * 100, 2),
            'actual_dir': actual_dir,
            'is_correct': is_correct,
            'is_directional': is_directional,
        }
        records.append(record)

        if verbose and is_directional:
            mark = "✓" if is_correct else "✗"
            print(f"  {mark} {date_str} | {result.resonance_level}/{result.resonance_intent} "
                  f"| 预测{pred_dir}({prob_up}/{prob_down}) | 实际{actual_dir}({actual_return*100:.1f}%)")

    return records


def print_stats(all_records: list, forward_days: int):
    df = pd.DataFrame(all_records)
    if df.empty:
        print("无回测数据")
        return

    total = len(df)
    directional = df[df['is_directional']]
    d_total = len(directional)
    d_correct = directional['is_correct'].sum()

    print(f"\n{'='*60}")
    print(f"回测汇总 (前向{forward_days}日，总样本={total})")
    print(f"{'='*60}")
    print(f"强方向预测（涨/跌）: {d_total}次，准确率: {d_correct/d_total*100:.1f}%" if d_total > 0 else "无强方向预测")

    # 预测分布 vs 实际分布
    pred_dist = df['pred_dir'].value_counts()
    actual_dist = df['actual_dir'].value_counts()
    print(f"\n── 预测分布 vs 实际分布（全样本 {total} 个）──")
    for d in ['up', 'sideways', 'down']:
        p_cnt = pred_dist.get(d, 0)
        a_cnt = actual_dist.get(d, 0)
        print(f"  {d:<10} 预测={p_cnt:>4}({p_cnt/total*100:>4.1f}%)  实际={a_cnt:>4}({a_cnt/total*100:>4.1f}%)")

    print(f"\n── 按共振级别分组 ──")
    if 'resonance_level' in df.columns:
        for level, grp in directional.groupby('resonance_level'):
            acc = grp['is_correct'].mean() * 100
            avg_ret = grp['actual_return'].mean()
            print(f"  {level:<20} 样本={len(grp):>4}  准确率={acc:>5.1f}%  平均收益={avg_ret:>+6.2f}%")

    print(f"\n── 按意图分组 ──")
    if 'resonance_intent' in df.columns:
        for intent, grp in directional.groupby('resonance_intent'):
            if not intent:
                continue
            acc = grp['is_correct'].mean() * 100
            avg_ret = grp['actual_return'].mean()
            print(f"  {intent:<20} 样本={len(grp):>4}  准确率={acc:>5.1f}%  平均收益={avg_ret:>+6.2f}%")

    print(f"\n── 按情景分组 ──")
    if 'forecast_scenario' in df.columns:
        for scenario, grp in directional.groupby('forecast_scenario'):
            acc = grp['is_correct'].mean() * 100
            avg_ret = grp['actual_return'].mean()
            print(f"  {scenario:<20} 样本={len(grp):>4}  准确率={acc:>5.1f}%  平均收益={avg_ret:>+6.2f}%")

    # 整体收益分析（仅看预测方向正确的情况下的收益）
    if d_total > 0:
        correct_ret = directional[directional['is_correct']]['actual_return'].mean()
        wrong_ret = directional[~directional['is_correct']]['actual_return'].mean()
        print(f"\n── 方向判断收益分析 ──")
        print(f"  预测正确时平均收益: {correct_ret:+.2f}%")
        print(f"  预测错误时平均收益: {wrong_ret:+.2f}%")

    # 意图×共振级别交叉分析（全样本，含横盘预测）
    print(f"\n── 意图×共振级别：实际方向分布 ──")
    cross = df.groupby(['resonance_intent', 'resonance_level'])
    for (intent, level), grp in cross:
        if not intent:
            continue
        n = len(grp)
        if n < 5:
            continue
        a_up = (grp['actual_dir'] == 'up').sum()
        a_sw = (grp['actual_dir'] == 'sideways').sum()
        a_dn = (grp['actual_dir'] == 'down').sum()
        avg_ret = grp['actual_return'].mean()
        print(f"  {intent}/{level:<18} n={n:>3}  实际up={a_up/n*100:.0f}% sw={a_sw/n*100:.0f}% dn={a_dn/n*100:.0f}%  avg={avg_ret:+.2f}%")

    # 行为链统计
    print(f"\n── 行为链出现频次 ──")
    behavior_counts = defaultdict(int)
    behavior_acc = defaultdict(list)
    for _, row in directional.iterrows():
        for b in str(row.get('seq_behaviors', '')).split(','):
            b = b.strip()
            if b:
                behavior_counts[b] += 1
                behavior_acc[b].append(row['is_correct'])
    for b, cnt in sorted(behavior_counts.items(), key=lambda x: -x[1]):
        acc = sum(behavior_acc[b]) / len(behavior_acc[b]) * 100 if behavior_acc[b] else 0
        print(f"  {b:<25} 出现={cnt:>4}次  准确率={acc:>5.1f}%")


def fetch_history_with_supplement(code: str, days: int, db) -> pd.DataFrame:
    """
    获取历史数据，规则：
    1. 先读 DB 缓存
    2. 若 DB 行数 < days，计算缺口，用 efinance 补充拉取缺失部分
       - 随机延时 2-5 秒限速，避免封禁
    3. 拼合后返回；任何拉取失败都 raise 异常（不静默）
    """
    import time, random
    import efinance as ef

    db_df = None
    try:
        db_df = db.get_stock_history_df(code, days=days)
        if db_df is not None and 'date' in db_df.columns:
            db_df['date'] = pd.to_datetime(db_df['date'])
            db_df = db_df.set_index('date').sort_index()
    except Exception as e:
        raise RuntimeError(f"DB 读取失败 [{code}]: {e}")

    db_rows = len(db_df) if db_df is not None else 0
    print(f"  DB 缓存: {db_rows} 行（需要 {days} 行）")

    if db_rows >= days:
        return db_df.iloc[-days:]

    # DB 数据与需求差距 ≤10行（节假日误差），直接使用 DB 数据，不触发网络请求
    if db_rows > 0 and (days - db_rows) <= 10:
        print(f"  DB 缺口仅 {days - db_rows} 行（≤10行容差），直接使用 DB 数据")
        return db_df

    # DB 不足超过容差，补充拉取
    if db_rows > 0:
        missing_days = days - db_rows + 10  # 多拉10天作为缓冲
        print(f"  DB 数据不足（缺 {days - db_rows} 行），需补充拉取，等待限速...")
    else:
        missing_days = days
        print(f"  DB 无数据，需拉取全部 {missing_days} 天，等待限速...")

    # 通过项目内全局限流器控制请求速率（与正式代码共享限流逻辑）
    try:
        from data_provider.rate_limiter import get_global_limiter
        limiter = get_global_limiter()
        limiter.acquire('efinance', blocking=True, timeout=15.0)
    except Exception:
        # 限流器不可用时手动等待
        wait = random.uniform(2.0, 5.0)
        print(f"  限流器不可用，手动等待 {wait:.1f}s...")
        time.sleep(wait)

    from datetime import date, timedelta
    end_dt = date.today()
    beg_dt = end_dt - timedelta(days=int(days * 1.6))  # 多拉 60%，避免节假日缺口
    beg_str = beg_dt.strftime('%Y%m%d')
    end_str = end_dt.strftime('%Y%m%d')

    print(f"  请求 efinance 日线数据 {beg_str}~{end_str}...")
    raw = ef.stock.get_quote_history(code, beg=beg_str, end=end_str, klt=101, fqt=1)
    if raw is None or len(raw) == 0:
        raise RuntimeError(f"efinance 返回空数据 [{code}]")
    if len(raw) < 80:
        raise RuntimeError(f"efinance 返回数据不足 [{code}]: 仅 {len(raw)} 行，需要至少 80 行")

    col_map = {
        '日期': 'date', '开盘': 'open', '收盘': 'close',
        '最高': 'high', '最低': 'low', '成交量': 'volume',
        '成交额': 'amount'
    }
    raw = raw.rename(columns=col_map)
    if 'date' not in raw.columns:
        raise RuntimeError(f"efinance 返回数据缺少日期列 [{code}]，列名: {raw.columns.tolist()}")

    raw['date'] = pd.to_datetime(raw['date'])
    raw = raw.set_index('date').sort_index()

    # 拼合 DB + efinance（去重，以 efinance 为准）
    if db_df is not None and len(db_df) > 0:
        combined = pd.concat([raw, db_df])
        combined = combined[~combined.index.duplicated(keep='first')].sort_index()
    else:
        combined = raw

    # 取最近 days 行
    result_df = combined.iloc[-days:] if len(combined) > days else combined

    print(f"  最终数据: {len(result_df)} 行（DB {db_rows} + efinance {len(raw)}，去重后 {len(combined)}）")
    return result_df


def main():
    parser = argparse.ArgumentParser(description="P3 共振算法回测验证")
    parser.add_argument('--stocks', default='600519,000858,000333',
                        help='逗号分隔的股票代码（每次最多3只，避免封禁）')
    parser.add_argument('--days', type=int, default=5, help='前向验证天数（默认5日）')
    parser.add_argument('--history', type=int, default=500, help='拉取历史天数（默认500日）')
    parser.add_argument('--verbose', action='store_true', help='打印每个时间点详情')
    args = parser.parse_args()

    codes = [c.strip() for c in args.stocks.split(',')]

    # 每次最多 3 只，超出直接报错提示
    if len(codes) > 3:
        raise SystemExit(
            f"❌ 每次回测最多3只股票（当前 {len(codes)} 只），请减少 --stocks 数量以避免封禁。"
        )

    db = DatabaseManager.get_instance()

    all_records = []
    for idx, code in enumerate(codes):
        print(f"\n[{idx+1}/{len(codes)}] {code} 获取 {args.history} 日历史数据...")
        # 数据拉取失败 raise 异常，不继续
        df = fetch_history_with_supplement(code, args.history, db)

        if len(df) < 80:
            raise RuntimeError(f"[{code}] 最终数据行数不足（{len(df)} < 80），终止回测")

        print(f"  开始回测...")
        records = backtest_stock(code, df, forward_days=args.days, verbose=args.verbose)
        print(f"  生成 {len(records)} 个样本点")
        all_records.extend(records)

    if all_records:
        print_stats(all_records, args.days)
    else:
        print("无有效回测记录")


if __name__ == '__main__':
    main()
