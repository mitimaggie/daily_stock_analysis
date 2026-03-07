#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Flash+Pro vs 纯Pro A/B 胜率对比
运行：python scripts/ab_winrate_compare.py

说明：
- ab_variant='flash_pro'  → Flash+Pro双阶段（2026-03-07起）
- ab_variant='standard'   → 旧版单阶段纯Pro
- 只对 actual_pct_5d 已回填的记录统计（backtest_filled=1 且 actual_pct_5d IS NOT NULL）
- 需要至少5个交易日后才有足够的回填数据
"""

import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'stock_analysis.db')


def query_winrate(conn, variant: str, min_records: int = 10):
    cur = conn.execute("""
        SELECT
            COUNT(*)                                               AS n,
            ROUND(AVG(CASE WHEN actual_pct_5d > 0 THEN 1.0 ELSE 0.0 END) * 100, 1) AS win_rate_pct,
            ROUND(AVG(actual_pct_5d), 3)                           AS avg_5d_return,
            ROUND(AVG(CASE WHEN actual_pct_5d > 0 THEN actual_pct_5d ELSE 0 END), 3) AS avg_win,
            ROUND(AVG(CASE WHEN actual_pct_5d <= 0 THEN actual_pct_5d ELSE 0 END), 3) AS avg_loss,
            ROUND(COUNT(CASE WHEN operation_advice IN ('买入','加仓') THEN 1 END) * 100.0 / COUNT(*), 1) AS buy_rate_pct
        FROM analysis_history
        WHERE ab_variant = ?
          AND actual_pct_5d IS NOT NULL
          AND backtest_filled = 1
    """, (variant,))
    row = cur.fetchone()
    if not row or row[0] < min_records:
        return None, row[0] if row else 0
    return row, row[0]


def query_advice_breakdown(conn, variant: str):
    cur = conn.execute("""
        SELECT operation_advice,
               COUNT(*)                                               AS n,
               ROUND(AVG(CASE WHEN actual_pct_5d > 0 THEN 1.0 ELSE 0.0 END) * 100, 1) AS win_rate_pct,
               ROUND(AVG(actual_pct_5d), 3)                           AS avg_5d
        FROM analysis_history
        WHERE ab_variant = ?
          AND actual_pct_5d IS NOT NULL
          AND backtest_filled = 1
        GROUP BY operation_advice
        ORDER BY n DESC
    """, (variant,))
    return cur.fetchall()


def main():
    if not os.path.exists(DB_PATH):
        print(f"DB not found: {DB_PATH}")
        return

    conn = sqlite3.connect(DB_PATH)

    print("=" * 60)
    print("  Flash+Pro vs 纯Pro  A/B 胜率对比")
    print("=" * 60)

    variants = [
        ("flash_pro", "Flash+Pro 双阶段（新）"),
        ("standard",  "纯Pro 单阶段（旧）"),
    ]

    results = {}
    for variant, label in variants:
        row, n = query_winrate(conn, variant)
        print(f"\n▶ {label}  [ab_variant={variant}]")
        if row is None:
            print(f"  样本不足（已回填: {n} 条，至少需要10条）")
            print("  请等待更多交易日积累数据（约5个交易日后再跑）")
        else:
            n, wr, avg, avg_w, avg_l, buy_rate = row
            profit_factor = abs(avg_w / avg_l) if avg_l and avg_l != 0 else float('inf')
            print(f"  已回填样本:  {n} 条")
            print(f"  5日胜率:     {wr}%")
            print(f"  平均收益:    {avg:+.3f}%")
            print(f"  平均盈利:    {avg_w:+.3f}%  / 平均亏损: {avg_l:+.3f}%")
            print(f"  盈亏比:      {profit_factor:.2f}")
            print(f"  买入信号占比: {buy_rate}%")

            breakdown = query_advice_breakdown(conn, variant)
            if breakdown:
                print("  按操作建议细分:")
                for advice, cnt, wr2, avg2 in breakdown:
                    print(f"    {advice:<6} n={cnt:>4}  胜率={wr2}%  avg={avg2:+.3f}%")

            results[variant] = {"n": n, "win_rate": wr, "avg": avg, "profit_factor": profit_factor}

    if len(results) == 2:
        print("\n" + "=" * 60)
        print("  对比结论")
        print("=" * 60)
        fp = results["flash_pro"]
        sp = results["standard"]
        wr_diff = fp["win_rate"] - sp["win_rate"]
        avg_diff = fp["avg"] - sp["avg"]
        print(f"  胜率差: Flash+Pro {wr_diff:+.1f}%pts")
        print(f"  收益差: Flash+Pro {avg_diff:+.3f}%pts")
        if wr_diff > 2 and avg_diff > 0:
            print("  ✅ Flash+Pro 显著优于纯Pro，建议保留")
        elif wr_diff < -2:
            print("  ⚠️  Flash+Pro 劣于纯Pro，建议检查Flash prompt设计")
        else:
            print("  ➡  差异在统计误差范围内，继续积累数据")

    conn.close()


if __name__ == "__main__":
    main()
