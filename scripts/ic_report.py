# -*- coding: utf-8 -*-
"""离线 IC (Information Coefficient) 报告脚本

分析各评分维度与未来收益率的相关性，为信号权重校准提供数据支持。
基于 raw_result.score_breakdown 中已存储的各维度得分，无需重新计算指标。
用法：python scripts/ic_report.py
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import json
import logging
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from scipy import stats
from sqlalchemy import text

from src.storage import DatabaseManager

logger = logging.getLogger(__name__)

SCORE_DIMENSIONS = ['trend', 'bias', 'volume', 'support', 'macd', 'rsi', 'kdj']
ADJ_KEYS = ['valuation_adj', 'capital_flow_adj', 'sector_adj', 'chip_adj', 'fundamental_adj']
RETURN_HORIZONS = ['actual_pct_1d', 'actual_pct_3d', 'actual_pct_5d', 'actual_pct_10d', 'actual_pct_20d']


def load_records(db: DatabaseManager, min_records: int = 50) -> pd.DataFrame:
    """从 analysis_history 加载有回测结果且含 score_breakdown 的记录"""
    with db.get_session() as session:
        raw_rows = session.execute(text("""
            SELECT code, created_at, sentiment_score, raw_result,
                   actual_pct_1d, actual_pct_3d, actual_pct_5d,
                   actual_pct_10d, actual_pct_20d
            FROM analysis_history
            WHERE backtest_filled = 1 AND actual_pct_5d IS NOT NULL
            ORDER BY created_at DESC
            LIMIT 5000
        """)).fetchall()

    rows = []
    for r in raw_rows:
        if r[6] is None:
            continue
        breakdown = {}
        if r[3]:
            try:
                raw = json.loads(r[3])
                breakdown = raw.get('score_breakdown', {})
            except Exception:
                continue
        if not breakdown:
            continue
        row = {
            'code': r[0],
            'created_at': r[1],
            'sentiment_score': r[2],
            'actual_pct_1d': r[4],
            'actual_pct_3d': r[5],
            'actual_pct_5d': r[6],
            'actual_pct_10d': r[7],
            'actual_pct_20d': r[8],
        }
        for dim in SCORE_DIMENSIONS:
            row[dim] = breakdown.get(dim, 0)
        for key in ADJ_KEYS:
            row[key] = breakdown.get(key, 0)
        row['signal_score'] = sum(breakdown.get(d, 0) for d in SCORE_DIMENSIONS)
        rows.append(row)

    df = pd.DataFrame(rows)
    if len(df) < min_records:
        logger.warning(f"有效记录仅 {len(df)} 条，不足 {min_records}，IC 报告可能不可靠")
    return df


def calc_ic(df: pd.DataFrame, factor_col: str, return_col: str) -> Tuple[float, float]:
    """计算 Rank IC（Spearman 相关系数）"""
    valid = df[[factor_col, return_col]].dropna()
    if len(valid) < 10:
        return 0.0, 1.0
    corr, pval = stats.spearmanr(valid[factor_col], valid[return_col])
    return round(float(corr), 4), round(float(pval), 4)


def generate_report(df: pd.DataFrame) -> str:
    """生成 IC 报告"""
    lines = [
        "# 评分维度 IC 报告",
        f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"样本数量: {len(df)}",
        "",
        "## 基础维度 Rank IC（vs 未来收益率）",
        "",
        "| 维度 | 1日IC | 3日IC | 5日IC | 10日IC | 20日IC |",
        "|------|-------|-------|-------|--------|--------|",
    ]

    all_factors = SCORE_DIMENSIONS + ADJ_KEYS + ['signal_score', 'sentiment_score']
    for factor in all_factors:
        if factor not in df.columns:
            continue
        ic_vals = []
        for horizon in RETURN_HORIZONS:
            if horizon in df.columns:
                ic, pval = calc_ic(df, factor, horizon)
                sig = '*' if pval < 0.05 else ''
                ic_vals.append(f"{ic:.3f}{sig}")
            else:
                ic_vals.append("N/A")
        lines.append(f"| {factor} | {' | '.join(ic_vals)} |")

    lines.extend([
        "",
        "（* 表示 p<0.05 统计显著）",
        "",
        "## 解读建议",
        "- IC > 0.03 且显著：该维度对未来收益有正向预测力，可考虑维持或加大权重",
        "- IC < -0.03 且显著：该维度与未来收益负相关，可能需要反转信号或降低权重",
        "- |IC| < 0.03：该维度预测力弱，可降低权重",
    ])
    return "\n".join(lines)


def main():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
    db = DatabaseManager()
    logger.info("加载回测记录...")
    df = load_records(db)
    if df.empty:
        logger.error("无有效回测记录，无法生成 IC 报告")
        return
    logger.info(f"加载 {len(df)} 条有效记录")

    report = generate_report(df)
    output_path = os.path.join(os.path.dirname(__file__), '..', 'docs', 'IC_REPORT.md')
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(report)
    logger.info(f"IC 报告已写入 {output_path}")
    print(report)


if __name__ == '__main__':
    main()
