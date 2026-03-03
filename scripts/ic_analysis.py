"""
IC 分析脚本 (P2)
================
对 analysis_history 中已回填的每条记录，
重新计算分析日当天的技术指标各维度得分，
然后与已知 5 日实际收益做 Spearman IC（信息系数）分析。

IC > 0.05 视为有预测能力，< 0 视为反向信号或噪声。

用法：
    cd /Users/chengxidai/daily_stock_analysis
    python scripts/ic_analysis.py
"""
import sys
import os
import json
import logging
import warnings
from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple

import pandas as pd
import numpy as np
from scipy import stats
from sqlalchemy import text

warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)


def get_analysis_records() -> List[dict]:
    """从 analysis_history 获取已回填记录"""
    from src.storage import DatabaseManager
    from datetime import datetime as _dt
    db = DatabaseManager()
    with db.get_session() as session:
        rows = session.execute(text("""
            SELECT code, created_at, sentiment_score, actual_pct_5d, operation_advice
            FROM analysis_history
            WHERE backtest_filled=1 AND actual_pct_5d IS NOT NULL
            ORDER BY created_at
        """)).fetchall()
        result = []
        for r in rows:
            raw_date = r[1]
            if raw_date is None:
                continue
            # 兼容 str / datetime / date
            if isinstance(raw_date, str):
                try:
                    adate = _dt.fromisoformat(raw_date[:19]).date()
                except Exception:
                    continue
            elif hasattr(raw_date, 'date'):
                adate = raw_date.date()
            else:
                adate = raw_date
            result.append({
                'code': r[0],
                'analysis_date': adate,
                'sentiment_score': r[2],
                'actual_pct_5d': float(r[3]),
                'operation_advice': r[4] or '',
            })
        return result


def get_stock_daily(code: str, end_date: date, lookback: int = 300) -> Optional[pd.DataFrame]:
    """从 stock_daily 获取截止 end_date 的所有K线数据（全量缓存用）"""
    from src.storage import DatabaseManager
    db = DatabaseManager()
    start_date = end_date - timedelta(days=int(lookback * 1.6))
    # 统一用字符串日期避免类型兼容问题
    end_str = end_date.strftime('%Y-%m-%d')
    start_str = start_date.strftime('%Y-%m-%d')
    try:
        with db._engine.connect() as conn:
            df = pd.read_sql(text("""
                SELECT date, open, high, low, close, volume
                FROM stock_daily
                WHERE code = :code AND date <= :end_date AND date >= :start_date
                ORDER BY date ASC
            """), conn, params={'code': code, 'end_date': end_str, 'start_date': start_str})
        if df.empty or len(df) < 20:
            return None
        df['date'] = pd.to_datetime(df['date'])
        df = df.sort_values('date').reset_index(drop=True)
        return df
    except Exception as e:
        logger.debug(f"获取 {code} 数据失败: {e}")
        return None


def calc_dimension_scores(df: pd.DataFrame) -> Optional[Dict[str, float]]:
    """用最后一个交易日的技术指标数值直接计算各维度原始因子值（连续变量）
    
    不调用枚举状态判断，直接用连续数值做 Spearman IC，
    避免枚举离散化造成的信息损失，同时规避 StockTrendAnalyzer 初始化依赖。
    """
    try:
        from src.stock_analyzer.indicators import TechnicalIndicators
        import numpy as np

        if len(df) < 30:
            return None

        # 确保df有数值列
        for col in ['open', 'high', 'low', 'close', 'volume']:
            df[col] = pd.to_numeric(df[col], errors='coerce')
        df = df.dropna(subset=['close', 'high', 'low', 'volume'])
        if len(df) < 30:
            return None

        # 用 calculate_all 计算全部指标列
        df_ind = TechnicalIndicators.calculate_all(df.copy())
        last = df_ind.iloc[-1]
        prev = df_ind.iloc[-2] if len(df_ind) >= 2 else last
        close = float(last['close'])

        # === 1. 趋势因子：MA5>MA10>MA20 程度（多头排列度）===
        ma5  = float(last.get('MA5',  last.get('ma5',  0)) or 0)
        ma10 = float(last.get('MA10', last.get('ma10', 0)) or 0)
        ma20 = float(last.get('MA20', last.get('ma20', 0)) or 0)
        if close > 0 and ma20 > 0:
            # 趋势因子：(MA5-MA20)/MA20，正值=多头，负值=空头
            trend_factor = (ma5 - ma20) / ma20 * 100
        else:
            trend_factor = 0.0

        # === 2. 乖离率因子：(close-MA20)/MA20 ===
        bias_factor = ((close - ma20) / ma20 * 100) if ma20 > 0 else 0.0

        # === 3. 量能因子：成交量/20日均量 ===
        vol = float(last.get('volume', 0) or 0)
        vol_ma20 = float(df_ind['volume'].rolling(20).mean().iloc[-1] or 0)
        volume_factor = (vol / vol_ma20) if vol_ma20 > 0 else 1.0

        # === 4. 支撑因子：现价距MA20的距离（下方=正支撑） ===
        support_factor = ((close - ma20) / ma20 * 100) if ma20 > 0 else 0.0

        # === 5. MACD因子：MACD柱状图值 (MACD_BAR) ===
        macd_bar = float(last.get('MACD_BAR', last.get('MACD_hist', 0)) or 0)
        macd_factor = macd_bar  # 柱状图正负直接体现多空

        # === 6. RSI因子：RSI12值（连续值）===
        rsi12 = float(last.get('RSI_12', last.get('RSI', 50)) or 50)
        rsi_factor = rsi12

        # === 7. KDJ因子：J值（连续值）===
        j_val = float(last.get('J', last.get('KDJ_J', 50)) or 50)
        kdj_factor = j_val

        return {
            'trend':   trend_factor,
            'bias':    bias_factor,
            'volume':  volume_factor,
            'support': support_factor,
            'macd':    macd_factor,
            'rsi':     rsi_factor,
            'kdj':     kdj_factor,
        }
    except Exception as e:
        logger.debug(f"计算维度评分失败: {e}", exc_info=True)
        return None


def run_ic_analysis():
    print("=" * 60)
    print("IC 分析 (P2) — 各评分维度预测能力检验")
    print("=" * 60)
    print()

    records = get_analysis_records()
    print(f"读取 {len(records)} 条已回填记录...")

    # 去重：同股同日只取一条（保持与回测一致）
    dedup: Dict[tuple, dict] = {}
    for r in records:
        key = (r['code'], r['analysis_date'])
        if key not in dedup or r['sentiment_score'] > dedup[key]['sentiment_score']:
            dedup[key] = r
    records = list(dedup.values())
    print(f"去重后: {len(records)} 条")
    print()

    # 重算各维度评分
    rows = []
    skip_count = 0
    cache: Dict[str, pd.DataFrame] = {}

    for i, rec in enumerate(records):
        code = rec['code']
        adate = rec['analysis_date']

        # 缓存该stock的全量df（取到今天，截取时按分析日过滤），避免重复IO
        if code not in cache:
            df_full = get_stock_daily(code, date.today())
            cache[code] = df_full

        df_full = cache[code]
        if df_full is None:
            skip_count += 1
            continue

        # 截取到分析日当天（统一转为 pd.Timestamp 后比较）
        adate_ts = pd.Timestamp(adate)
        df_cut = df_full[pd.to_datetime(df_full['date']) <= adate_ts].copy()
        if len(df_cut) < 30:
            skip_count += 1
            continue

        scores = calc_dimension_scores(df_cut)
        if scores is None:
            skip_count += 1
            continue

        rows.append({
            'code':           code,
            'analysis_date':  adate,
            'actual_pct_5d':  rec['actual_pct_5d'],
            'sentiment_score': rec['sentiment_score'],
            **scores,
        })

        if (i + 1) % 50 == 0:
            print(f"  进度: {i+1}/{len(records)}，跳过 {skip_count} 条...")

    print(f"\n有效样本: {len(rows)}，跳过: {skip_count}")

    if len(rows) < 10:
        print("⚠️  有效样本不足10条，无法进行IC分析")
        return

    df_ic = pd.DataFrame(rows)
    returns = df_ic['actual_pct_5d'].values

    dims = ['trend', 'bias', 'volume', 'support', 'macd', 'rsi', 'kdj', 'sentiment_score']
    dim_labels = {
        'trend':          '趋势状态',
        'bias':           '乖离率',
        'volume':         '量能',
        'support':        '支撑位',
        'macd':           'MACD',
        'rsi':            'RSI',
        'kdj':            'KDJ',
        'sentiment_score': '总评分',
    }

    print()
    print("=" * 60)
    print("IC（Spearman 秩相关）vs 5日实际收益")
    print("说明：IC>0.05 有正向预测能力，<-0.05 反向信号，|IC|>0.1 显著")
    print("=" * 60)
    print(f"{'维度':<12} {'IC':>8} {'p值':>8} {'显著性':>6} {'判断'}")
    print("-" * 60)

    results_ic = {}
    for dim in dims:
        if dim not in df_ic.columns:
            continue
        factor = df_ic[dim].values
        valid_mask = ~np.isnan(factor) & ~np.isnan(returns)
        if valid_mask.sum() < 10:
            continue
        ic, pval = stats.spearmanr(factor[valid_mask], returns[valid_mask])
        sig = '***' if pval < 0.01 else '**' if pval < 0.05 else '*' if pval < 0.1 else ''
        
        if abs(ic) >= 0.1 and pval < 0.05:
            judge = '✅ 显著有效'
        elif ic >= 0.05:
            judge = '🟡 弱正向'
        elif ic <= -0.05:
            judge = '🔴 反向（噪声或逆信号）'
        else:
            judge = '⚪ 无预测能力'
        
        label = dim_labels.get(dim, dim)
        print(f"{label:<12} {ic:>8.4f} {pval:>8.4f} {sig:>6} {judge}")
        results_ic[dim] = {'ic': ic, 'pval': pval}

    print()

    # 分位数分析：按总评分分档，看各档平均收益
    print("=" * 60)
    print("总评分分档 vs 平均5日收益（Monotonicity 单调性检验）")
    print("=" * 60)
    score_col = 'sentiment_score'
    bins = [0, 50, 60, 70, 75, 80, 85, 90, 101]
    labels_bins = ['<50', '50-59', '60-69', '70-74', '75-79', '80-84', '85-89', '90+']
    df_ic['score_bucket'] = pd.cut(df_ic[score_col], bins=bins, labels=labels_bins, right=False)
    
    print(f"{'分档':<10} {'样本数':>6} {'平均收益':>10} {'胜率':>8} {'夏普':>8}")
    print("-" * 50)
    for label in labels_bins:
        sub = df_ic[df_ic['score_bucket'] == label]['actual_pct_5d']
        if len(sub) == 0:
            continue
        avg = sub.mean()
        win = (sub > 0).mean() * 100
        sharpe = (sub.mean() / sub.std() * np.sqrt(50)) if sub.std() > 0 else 0
        print(f"{label:<10} {len(sub):>6} {avg:>+10.2f}% {win:>7.0f}% {sharpe:>8.2f}")
    
    print()
    print("=" * 60)
    print("改进建议（基于IC分析）")
    print("=" * 60)
    # 自动生成建议
    for dim, res in results_ic.items():
        ic = res['ic']
        pval = res['pval']
        label = dim_labels.get(dim, dim)
        if ic < -0.05 and pval < 0.1:
            print(f"⚠️  {label}（IC={ic:.4f}）：当前该维度为反向信号，建议降低或反转其权重")
        elif abs(ic) < 0.02:
            print(f"📉 {label}（IC={ic:.4f}）：无预测能力，建议减少权重占比")
        elif ic >= 0.1 and pval < 0.05:
            print(f"💡 {label}（IC={ic:.4f}，p={pval:.3f}）：显著正向，建议适当提高权重")


if __name__ == '__main__':
    run_ic_analysis()
