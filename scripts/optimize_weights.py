"""
P3: 权重自动优化脚本
==============================
基于历史 K 线的滑动窗口回测，穷举搜索使胜率/夏普比率最优的 REGIME_WEIGHTS。

方法：
1. 从 DB 读取多只股票的历史 K 线（最近 500 日）
2. 对每个时间点计算7维原始分（trend/bias/volume/support/macd/rsi/kdj）
3. 用不同权重配置重算综合评分，买入信号阈值≥70分
4. 统计5日后实际收益，计算胜率/夏普比率
5. 输出 Top10 最优权重配置，并与当前权重对比

用法：
    cd /Users/chengxidai/daily_stock_analysis
    python scripts/optimize_weights.py [--days 5] [--stocks 10]
"""
import sys, os, argparse
import pandas as pd
import numpy as np
from itertools import product
from typing import Dict, List, Tuple, Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.stock_analyzer.scoring import ScoringSystem
from src.stock_analyzer.types import (
    TrendAnalysisResult, TrendStatus, MACDStatus, VolumeStatus,
    BuySignal, MarketRegime, RSIStatus, KDJStatus
)
from src.stock_analyzer.indicators import TechnicalIndicators
from src.storage import DatabaseManager


# ─── 当前权重（基准） ───────────────────────────────────────────────────
CURRENT_WEIGHTS = {
    'bull':     {'trend': 30, 'bias': 12, 'volume': 10, 'support': 5,  'macd': 20, 'rsi': 10, 'kdj': 13},
    'sideways': {'trend': 18, 'bias': 20, 'volume': 10, 'support': 12, 'macd': 15, 'rsi': 10, 'kdj': 15},
    'bear':     {'trend': 13, 'bias': 17, 'volume': 15, 'support': 13, 'macd': 14, 'rsi': 13, 'kdj': 15},
}

# 权重搜索的股票池（代表性+多样性）
DEFAULT_STOCKS = [
    '600519', '000858', '000333', '002594', '601318',
    '300750', '600036', '000001', '002415', '603288',
]


def calc_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    close = df['close'].astype(float)
    high = df['high'].astype(float)
    low = df['low'].astype(float)
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    df['MACD_DIF'] = ema12 - ema26
    df['MACD_DEA'] = df['MACD_DIF'].ewm(span=9, adjust=False).mean()
    df['MA5'] = close.rolling(5).mean()
    df['MA10'] = close.rolling(10).mean()
    df['MA20'] = close.rolling(20).mean()
    df['MA60'] = close.rolling(60).mean()
    prev_close = close.shift(1)
    tr = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    df['ATR14'] = tr.rolling(14).mean()
    df['BIAS_MA5'] = (close - df['MA5']) / df['MA5'] * 100
    bb_mid = close.rolling(20).mean()
    bb_std = close.rolling(20).std(ddof=0)
    df['BB_UPPER'] = bb_mid + 2 * bb_std
    df['BB_LOWER'] = bb_mid - 2 * bb_std
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(12).mean()
    loss = (-delta.clip(upper=0)).rolling(12).mean()
    df['RSI12'] = 100 - 100 / (1 + gain / (loss + 1e-9))
    low_min9 = low.rolling(9).min()
    high_max9 = high.rolling(9).max()
    rsv = (close - low_min9) / (high_max9 - low_min9 + 1e-9) * 100
    k = rsv.ewm(com=2, adjust=False).mean()
    df['KDJ_K'] = k
    df['KDJ_D'] = k.ewm(com=2, adjust=False).mean()
    df['KDJ_J'] = 3 * df['KDJ_K'] - 2 * df['KDJ_D']
    return df


def build_result(df_slice: pd.DataFrame, code: str) -> TrendAnalysisResult:
    """从历史切片构建 TrendAnalysisResult，计算7维原始分所需的字段"""
    result = TrendAnalysisResult(code=code)
    result.signal_reasons = []
    result.risk_factors = []
    result.score_breakdown = {}
    result.is_limit_up = False
    result.is_limit_down = False

    row = df_slice.iloc[-1]
    prev = df_slice.iloc[-2] if len(df_slice) >= 2 else row
    result.current_price = float(row.get('close', 0))
    result.bias_ma5 = float(row.get('BIAS_MA5', 0) or 0)
    result.atr = float(row.get('ATR14', 0) or 0)

    # --- 趋势状态 ---
    ma5 = float(row.get('MA5') or 0)
    ma10 = float(row.get('MA10') or 0)
    ma20 = float(row.get('MA20') or 0)
    ma60 = float(row.get('MA60') or 0)
    close = float(row.get('close', 0))
    if all(v > 0 for v in [ma5, ma10, ma20, ma60]):
        if ma5 > ma10 > ma20 > ma60 and close > ma5:
            result.trend_status = TrendStatus.STRONG_BULL
        elif ma5 > ma20 and close > ma20:
            result.trend_status = TrendStatus.BULL
        elif ma5 > ma20:
            result.trend_status = TrendStatus.WEAK_BULL
        elif ma5 < ma10 < ma20 < ma60 and close < ma5:
            result.trend_status = TrendStatus.STRONG_BEAR
        elif ma5 < ma20 and close < ma20:
            result.trend_status = TrendStatus.BEAR
        elif ma5 < ma20:
            result.trend_status = TrendStatus.WEAK_BEAR
        else:
            result.trend_status = TrendStatus.CONSOLIDATION
    else:
        result.trend_status = TrendStatus.CONSOLIDATION

    # --- MACD ---
    dif = float(row.get('MACD_DIF') or 0)
    dea = float(row.get('MACD_DEA') or 0)
    prev_dif = float(prev.get('MACD_DIF') or 0)
    prev_dea = float(prev.get('MACD_DEA') or 0)
    if dif > 0 and dea > 0:
        if dif > dea and prev_dif <= prev_dea:
            result.macd_status = MACDStatus.GOLDEN_CROSS_ZERO
        elif dif > dea:
            result.macd_status = MACDStatus.BULLISH
        else:
            result.macd_status = MACDStatus.BULLISH
    elif dif < 0 and dea < 0:
        if dif < dea and prev_dif >= prev_dea:
            result.macd_status = MACDStatus.DEATH_CROSS
        elif dif < dea:
            result.macd_status = MACDStatus.BEARISH
        else:
            result.macd_status = MACDStatus.BEARISH
    elif dif > dea:
        result.macd_status = MACDStatus.GOLDEN_CROSS
    else:
        result.macd_status = MACDStatus.BEARISH

    # --- RSI ---
    rsi = float(row.get('RSI12') or 50)
    result.rsi = rsi
    if rsi >= 80:
        result.rsi_status = RSIStatus.OVERBOUGHT
    elif rsi >= 60:
        result.rsi_status = RSIStatus.BULLISH
    elif rsi >= 40:
        result.rsi_status = RSIStatus.NEUTRAL
    elif rsi >= 20:
        result.rsi_status = RSIStatus.WEAK
    else:
        result.rsi_status = RSIStatus.OVERSOLD

    # --- KDJ ---
    k_val = float(row.get('KDJ_K') or 50)
    d_val = float(row.get('KDJ_D') or 50)
    j_val = float(row.get('KDJ_J') or 50)
    result.kdj_k = k_val
    result.kdj_d = d_val
    result.kdj_j = j_val
    if k_val > d_val and k_val < 80:
        result.kdj_status = KDJStatus.GOLDEN_CROSS
    elif k_val < d_val and k_val > 20:
        result.kdj_status = KDJStatus.DEATH_CROSS
    elif k_val >= 80:
        result.kdj_status = KDJStatus.OVERBOUGHT
    elif k_val <= 20:
        result.kdj_status = KDJStatus.OVERSOLD
    else:
        result.kdj_status = KDJStatus.NEUTRAL

    # --- Volume ---
    vols = df_slice['volume'].values.astype(float)
    if len(vols) >= 5:
        avg5 = vols[-5:].mean()
        avg20 = vols[-20:].mean() if len(vols) >= 20 else avg5
        cur_vol = vols[-1]
        if cur_vol > avg20 * 2 and close > float(prev.get('close', close)):
            result.volume_status = VolumeStatus.HEAVY_VOLUME_UP
        elif cur_vol > avg20 * 2 and close < float(prev.get('close', close)):
            result.volume_status = VolumeStatus.HEAVY_VOLUME_DOWN
        elif cur_vol > avg20 * 1.3:
            result.volume_status = VolumeStatus.VOLUME_UP
        elif cur_vol < avg20 * 0.5:
            result.volume_status = VolumeStatus.LOW_VOLUME
        else:
            result.volume_status = VolumeStatus.NORMAL

    # --- Support ---
    if len(df_slice) >= 20:
        lows20 = df_slice['low'].values[-20:].astype(float)
        support = float(np.percentile(lows20, 15))
        result.support_distance = abs(close - support) / support * 100 if support > 0 else 999

    return result


def get_market_regime(row) -> MarketRegime:
    ma5 = float(row.get('MA5') or 0)
    ma20 = float(row.get('MA20') or 0)
    ma60 = float(row.get('MA60') or 0)
    if ma5 > ma20 and ma20 > ma60 * 0.98:
        return MarketRegime.BULL
    elif ma5 < ma20 and ma20 < ma60 * 1.02:
        return MarketRegime.BEAR
    return MarketRegime.SIDEWAYS


def collect_samples(stocks: List[str], forward_days: int = 5) -> List[Dict]:
    """收集所有股票的历史样本（时间点 + 7维原始分 + 市场环境 + 实际收益）"""
    db = DatabaseManager()
    all_samples = []

    for code in stocks:
        try:
            df = db.get_stock_history_df(code, days=500)
            if df is None or len(df) < 80:
                print(f"  {code}: 数据不足，跳过")
                continue
            df = calc_indicators(df)
            n = len(df)
            count = 0
            for i in range(60, n - forward_days):
                df_slice = df.iloc[:i]
                df_future = df.iloc[i: i + forward_days]
                try:
                    result = build_result(df_slice, code)
                    if result.current_price <= 0:
                        continue
                    entry_price = result.current_price
                    future_close = float(df_future['close'].iloc[-1])
                    actual_return = (future_close - entry_price) / entry_price * 100
                    regime = get_market_regime(df_slice.iloc[-1])

                    # 获取7维原始分率
                    raw_scores = ScoringSystem._get_raw_dimension_scores(result)

                    all_samples.append({
                        'code': code,
                        'regime': regime.value,
                        'actual_return': actual_return,
                        'raw_scores': raw_scores,
                    })
                    count += 1
                except Exception:
                    continue
            print(f"  {code}: {count} 样本")
        except Exception as e:
            print(f"  {code}: 跳过 ({e})")

    return all_samples


def calc_score_with_weights(raw_scores: Dict[str, float], regime: str, weights: Dict) -> int:
    """用指定权重重算综合评分"""
    regime_key = regime.lower() if regime else 'sideways'
    if regime_key not in ('bull', 'sideways', 'bear'):
        regime_key = 'sideways'
    w = weights.get(regime_key, weights.get('sideways', {}))
    score = sum(
        min(w.get(dim, 0), round(raw_scores.get(dim, 0) * w.get(dim, 0)))
        for dim in raw_scores
        if dim in w
    )
    return min(100, max(0, score))


def evaluate_weights(samples: List[Dict], weights: Dict, threshold: int = 70) -> Dict:
    """用给定权重评估所有样本，返回胜率/夏普等指标"""
    buy_returns = []
    for s in samples:
        score = calc_score_with_weights(s['raw_scores'], s['regime'], weights)
        if score >= threshold:
            buy_returns.append(s['actual_return'])

    if len(buy_returns) < 5:
        return {'buy_count': 0, 'win_rate': 0.0, 'avg_return': -999.0, 'sharpe': -999.0}

    win_rate = sum(1 for r in buy_returns if r > 0) / len(buy_returns) * 100
    avg_r = np.mean(buy_returns)
    std_r = np.std(buy_returns) + 1e-9
    sharpe = avg_r / std_r * np.sqrt(252 / 5)

    return {
        'buy_count': len(buy_returns),
        'win_rate': round(win_rate, 1),
        'avg_return': round(avg_r, 3),
        'sharpe': round(sharpe, 3),
    }


def generate_weight_candidates() -> List[Dict]:
    """生成候选权重配置（基于当前权重附近的合理变体）"""
    candidates = []

    # 当前权重作为基准
    candidates.append({'name': '当前权重(基准)', 'weights': CURRENT_WEIGHTS})

    # 策略1：趋势优先型（牛市更看重趋势，熊市看重支撑）
    candidates.append({'name': '趋势优先', 'weights': {
        'bull':     {'trend': 35, 'bias': 10, 'volume': 8,  'support': 5,  'macd': 18, 'rsi': 12, 'kdj': 12},
        'sideways': {'trend': 22, 'bias': 18, 'volume': 8,  'support': 12, 'macd': 18, 'rsi': 10, 'kdj': 12},
        'bear':     {'trend': 15, 'bias': 15, 'volume': 12, 'support': 15, 'macd': 15, 'rsi': 14, 'kdj': 14},
    }})

    # 策略2：量价优先型（重视量能确认）
    candidates.append({'name': '量价优先', 'weights': {
        'bull':     {'trend': 28, 'bias': 10, 'volume': 18, 'support': 5,  'macd': 16, 'rsi': 10, 'kdj': 13},
        'sideways': {'trend': 16, 'bias': 18, 'volume': 18, 'support': 12, 'macd': 12, 'rsi': 10, 'kdj': 14},
        'bear':     {'trend': 12, 'bias': 15, 'volume': 20, 'support': 14, 'macd': 12, 'rsi': 13, 'kdj': 14},
    }})

    # 策略3：振荡市优化（熊市/震荡加强RSI/KDJ捕捉超跌反弹）
    candidates.append({'name': 'RSI/KDJ增强', 'weights': {
        'bull':     {'trend': 30, 'bias': 12, 'volume': 10, 'support': 5,  'macd': 18, 'rsi': 12, 'kdj': 13},
        'sideways': {'trend': 15, 'bias': 18, 'volume': 8,  'support': 12, 'macd': 12, 'rsi': 18, 'kdj': 17},
        'bear':     {'trend': 10, 'bias': 15, 'volume': 12, 'support': 14, 'macd': 12, 'rsi': 18, 'kdj': 19},
    }})

    # 策略4：均衡型（各维度更均匀）
    candidates.append({'name': '均衡型', 'weights': {
        'bull':     {'trend': 25, 'bias': 14, 'volume': 13, 'support': 7,  'macd': 16, 'rsi': 12, 'kdj': 13},
        'sideways': {'trend': 18, 'bias': 17, 'volume': 13, 'support': 12, 'macd': 14, 'rsi': 13, 'kdj': 13},
        'bear':     {'trend': 14, 'bias': 16, 'volume': 15, 'support': 13, 'macd': 13, 'rsi': 14, 'kdj': 15},
    }})

    # 策略5：MACD+趋势共振优化（强趋势时更依赖 MACD 确认）
    candidates.append({'name': 'MACD趋势共振', 'weights': {
        'bull':     {'trend': 32, 'bias': 10, 'volume': 8,  'support': 5,  'macd': 25, 'rsi': 10, 'kdj': 10},
        'sideways': {'trend': 18, 'bias': 18, 'volume': 10, 'support': 12, 'macd': 18, 'rsi': 12, 'kdj': 12},
        'bear':     {'trend': 12, 'bias': 16, 'volume': 14, 'support': 14, 'macd': 16, 'rsi': 14, 'kdj': 14},
    }})

    # 策略6：支撑强调型（加大技术支撑权重）
    candidates.append({'name': '支撑强调型', 'weights': {
        'bull':     {'trend': 28, 'bias': 12, 'volume': 10, 'support': 10, 'macd': 18, 'rsi': 10, 'kdj': 12},
        'sideways': {'trend': 16, 'bias': 18, 'volume': 10, 'support': 18, 'macd': 14, 'rsi': 10, 'kdj': 14},
        'bear':     {'trend': 12, 'bias': 15, 'volume': 13, 'support': 20, 'macd': 13, 'rsi': 13, 'kdj': 14},
    }})

    # 策略7：Bias优先（乖离率信号更重要）
    candidates.append({'name': 'Bias优先', 'weights': {
        'bull':     {'trend': 28, 'bias': 16, 'volume': 10, 'support': 5,  'macd': 18, 'rsi': 10, 'kdj': 13},
        'sideways': {'trend': 15, 'bias': 25, 'volume': 10, 'support': 12, 'macd': 12, 'rsi': 12, 'kdj': 14},
        'bear':     {'trend': 12, 'bias': 22, 'volume': 13, 'support': 13, 'macd': 12, 'rsi': 14, 'kdj': 14},
    }})

    return candidates


def main():
    parser = argparse.ArgumentParser(description='P3: 权重自动优化')
    parser.add_argument('--days', type=int, default=5, help='前向天数')
    parser.add_argument('--threshold', type=int, default=70, help='买入信号阈值')
    parser.add_argument('--stocks', type=int, default=10, help='股票池大小')
    parser.add_argument('--verbose', action='store_true')
    args = parser.parse_args()

    stocks = DEFAULT_STOCKS[:args.stocks]
    print(f"\n=== P3 权重优化回测 ===")
    print(f"股票池: {len(stocks)} 只 | 前向: {args.days}日 | 买入阈值: {args.threshold}分")
    print(f"股票: {', '.join(stocks)}\n")

    print("正在收集历史样本...")
    samples = collect_samples(stocks, forward_days=args.days)
    print(f"\n共收集 {len(samples)} 个样本\n")

    if len(samples) < 100:
        print("⚠️ 样本数不足100，回测结果可靠性低")
        return

    candidates = generate_weight_candidates()
    results = []

    print(f"评估 {len(candidates)} 套权重配置...\n")
    for cfg in candidates:
        metrics = evaluate_weights(samples, cfg['weights'], threshold=args.threshold)
        results.append({**cfg, **metrics})
        if args.verbose:
            print(f"  [{cfg['name']}] 买入{metrics['buy_count']}次 胜率{metrics['win_rate']}% 平均{metrics['avg_return']:+.3f}% 夏普{metrics['sharpe']:.3f}")

    # 按夏普比率排序
    results.sort(key=lambda x: x['sharpe'], reverse=True)

    print("=" * 70)
    print("📊 权重配置回测结果（按夏普比率排序）")
    print("=" * 70)
    print(f"{'排名':<4} {'配置名称':<20} {'买入次数':<8} {'胜率':<8} {'平均收益':<10} {'夏普比率':<10}")
    print("-" * 70)
    for rank, r in enumerate(results, 1):
        marker = " ★" if rank == 1 else ""
        print(f"{rank:<4} {r['name']:<20} {r['buy_count']:<8} {r['win_rate']:<7.1f}% {r['avg_return']:+.3f}%{' ':4} {r['sharpe']:.3f}{marker}")

    best = results[0]
    current = next((r for r in results if r['name'] == '当前权重(基准)'), None)

    print("\n" + "=" * 70)
    print(f"🏆 最优配置: {best['name']}")
    print(f"   买入次数: {best['buy_count']} | 胜率: {best['win_rate']}% | 平均收益: {best['avg_return']:+.3f}% | 夏普: {best['sharpe']:.3f}")

    if current and best['name'] != '当前权重(基准)':
        sharpe_improve = best['sharpe'] - current['sharpe']
        wr_improve = best['win_rate'] - current['win_rate']
        print(f"\n   vs 当前权重：夏普 {sharpe_improve:+.3f}，胜率 {wr_improve:+.1f}%")
        print(f"\n{'最优权重配置详情':}")
        for regime in ('bull', 'sideways', 'bear'):
            w = best['weights'][regime]
            print(f"  {regime:8}: trend={w['trend']:2} bias={w['bias']:2} volume={w['volume']:2} "
                  f"support={w['support']:2} macd={w['macd']:2} rsi={w['rsi']:2} kdj={w['kdj']:2} "
                  f"(sum={sum(w.values())})")

        # 判断是否建议更新
        MIN_IMPROVE_SHARPE = 0.05
        MIN_IMPROVE_WR = 1.0
        if sharpe_improve > MIN_IMPROVE_SHARPE and wr_improve > 0:
            print(f"\n✅ 建议更新权重（夏普提升>{MIN_IMPROVE_SHARPE}，胜率提升>0%）")
            print("   可手动将以上权重更新到 src/stock_analyzer/scoring.py 的 REGIME_WEIGHTS")
        else:
            print(f"\n⚠️ 最优配置改善不显著（夏普提升{sharpe_improve:.3f}），建议维持当前权重")
    else:
        print("\n当前权重已是最优配置，无需调整")

    print(f"\n回测样本统计：{len(samples)} 个时间点")
    regime_counts = {}
    for s in samples:
        regime_counts[s['regime']] = regime_counts.get(s['regime'], 0) + 1
    for r, c in sorted(regime_counts.items()):
        print(f"  {r}: {c} ({c/len(samples)*100:.0f}%)")


if __name__ == '__main__':
    main()
