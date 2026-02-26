"""
P0/P1b/P2a/P2b 改进效果回测验证
===================================
复用 backtest_p3_resonance.py 的数据获取框架，专门验证本次改动的实际效果：

P0  止损距离硬约束：触发率 + 触发后N日表现对比
P1b 均线死叉屏蔽MACD零轴上方金叉：屏蔽样本的后续亏损率
P2a 缺口分析：向上缺口/向下缺口信号后N日涨跌表现
P2b 突破量能确认：有量突破 vs 无量突破的后续表现对比

用法：
    cd /Users/chengxidai/daily_stock_analysis
    python scripts/backtest_improvements.py [--stocks 600519,000001] [--days 5] [--verbose]
"""
import sys
import os
import argparse
import pandas as pd
import numpy as np
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.stock_analyzer.scoring import ScoringSystem
from src.stock_analyzer.risk_management import RiskManager
from src.stock_analyzer.types import (
    TrendAnalysisResult, TrendStatus, MACDStatus, VolumeStatus, BuySignal, MarketRegime,
    RSIStatus, KDJStatus
)
from src.stock_analyzer.indicators import TechnicalIndicators
from src.storage import DatabaseManager


# ─────────────────────────────────────────────
# 指标计算工具
# ─────────────────────────────────────────────

def calc_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """为 df 计算 MACD / MA / ATR14"""
    df = df.copy()
    close = df['close'].astype(float)
    high = df['high'].astype(float)
    low = df['low'].astype(float)

    # EMA12 / EMA26
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    df['MACD_DIF'] = ema12 - ema26
    df['MACD_DEA'] = df['MACD_DIF'].ewm(span=9, adjust=False).mean()

    # MA5 / MA20
    df['MA5'] = close.rolling(5).mean()
    df['MA20'] = close.rolling(20).mean()

    # ATR14
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs()
    ], axis=1).max(axis=1)
    df['ATR14'] = tr.rolling(14).mean()

    # MA10 / MA60（trend_status 需要更多均线）
    df['MA10'] = close.rolling(10).mean()
    df['MA60'] = close.rolling(60).mean()

    # Bias MA5
    df['BIAS_MA5'] = (close - df['MA5']) / df['MA5'] * 100

    # Bollinger Bands (20, 2)
    bb_mid = close.rolling(20).mean()
    bb_std = close.rolling(20).std(ddof=0)
    df['BB_UPPER'] = bb_mid + 2 * bb_std
    df['BB_LOWER'] = bb_mid - 2 * bb_std
    df['BB_WIDTH'] = (df['BB_UPPER'] - df['BB_LOWER']) / bb_mid

    # RSI 12
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(12).mean()
    loss = (-delta.clip(upper=0)).rolling(12).mean()
    rs = gain / loss.replace(0, float('nan'))
    df['RSI_12'] = 100 - (100 / (1 + rs))
    df['RSI_12'] = df['RSI_12'].fillna(50)

    # KDJ (9,3,3)
    low9 = low.rolling(9).min()
    high9 = high.rolling(9).max()
    rsv = (close - low9) / (high9 - low9).replace(0, float('nan')) * 100
    rsv = rsv.fillna(50)
    k = rsv.ewm(com=2, adjust=False).mean()
    d = k.ewm(com=2, adjust=False).mean()
    df['KDJ_K'] = k
    df['KDJ_D'] = d
    df['KDJ_J'] = 3 * k - 2 * d

    # Volume ratio vs 20-day avg
    vol = df['volume'].astype(float)
    df['VOL_AVG20'] = vol.rolling(20).mean()

    # VWAP10 / VWAP20（机构成本线）
    tp = (high + low + close) / 3
    tp_vol = tp * vol
    for window in [10, 20]:
        vol_sum = vol.rolling(window).sum()
        tp_vol_sum = tp_vol.rolling(window).sum()
        vwap = tp_vol_sum / vol_sum.replace(0, float('nan'))
        df[f'VWAP{window}'] = vwap
        df[f'VWAP{window}_SLOPE'] = (vwap - vwap.shift(window)) / window

    # OBV（能量潮）
    prev_close = close.shift(1)
    obv = (vol * ((close > prev_close).astype(float) - (close < prev_close).astype(float))).cumsum()
    df['OBV'] = obv
    df['OBV_MA20'] = obv.rolling(20).mean()

    # ADX / +DI / -DI（14日）
    prev_high = high.shift(1)
    prev_low = low.shift(1)
    plus_dm = (high - prev_high).clip(lower=0).where(
        (high - prev_high) > (prev_low - low), 0)
    minus_dm = (prev_low - low).clip(lower=0).where(
        (prev_low - low) > (high - prev_high), 0)
    atr14 = df['ATR14']
    smoothed_plus = plus_dm.ewm(alpha=1/14, adjust=False).mean()
    smoothed_minus = minus_dm.ewm(alpha=1/14, adjust=False).mean()
    df['PLUS_DI'] = 100 * smoothed_plus / atr14.replace(0, float('nan'))
    df['MINUS_DI'] = 100 * smoothed_minus / atr14.replace(0, float('nan'))
    dx = 100 * ((df['PLUS_DI'] - df['MINUS_DI']).abs() /
                (df['PLUS_DI'] + df['MINUS_DI']).replace(0, float('nan')))
    df['ADX'] = dx.ewm(span=14, adjust=False).mean()

    return df


def get_macd_status(row: pd.Series, prev_row: pd.Series) -> MACDStatus:
    """根据当前和前一行判断 MACD 状态"""
    dif = row['MACD_DIF']
    dea = row['MACD_DEA']
    prev_dif = prev_row['MACD_DIF']
    prev_dea = prev_row['MACD_DEA']

    if pd.isna(dif) or pd.isna(dea):
        return MACDStatus.NEUTRAL

    # 金叉判断
    if prev_dif <= prev_dea and dif > dea:
        if dif > 0:
            return MACDStatus.GOLDEN_CROSS_ZERO
        else:
            return MACDStatus.GOLDEN_CROSS

    # 死叉判断
    if prev_dif >= prev_dea and dif < dea:
        return MACDStatus.DEATH_CROSS

    # 持续状态
    if dif > dea:
        if dif > 0:
            return MACDStatus.BULLISH
        return MACDStatus.NEUTRAL
    else:
        if dif < 0:
            return MACDStatus.BEARISH
        return MACDStatus.NEUTRAL


def get_trend_status(row: pd.Series) -> TrendStatus:
    ma5 = row.get('MA5', float('nan'))
    ma10 = row.get('MA10', float('nan'))
    ma20 = row.get('MA20', float('nan'))
    ma60 = row.get('MA60', float('nan'))
    if pd.isna(ma5) or pd.isna(ma20) or ma20 == 0:
        return TrendStatus.CONSOLIDATION
    # 多均线排列判断（与生产逻辑对齐）
    bull_count = 0
    bear_count = 0
    if not pd.isna(ma10) and ma5 > ma10:
        bull_count += 1
    elif not pd.isna(ma10):
        bear_count += 1
    if not pd.isna(ma10) and not pd.isna(ma20) and ma10 > ma20:
        bull_count += 1
    elif not pd.isna(ma10) and not pd.isna(ma20):
        bear_count += 1
    if not pd.isna(ma20) and not pd.isna(ma60) and ma20 > ma60:
        bull_count += 1
    elif not pd.isna(ma20) and not pd.isna(ma60):
        bear_count += 1
    if bull_count >= 3:
        return TrendStatus.STRONG_BULL
    elif bull_count == 2:
        return TrendStatus.BULL
    elif bull_count == 1:
        return TrendStatus.WEAK_BULL
    elif bear_count == 1:
        return TrendStatus.WEAK_BEAR
    elif bear_count == 2:
        return TrendStatus.BEAR
    elif bear_count >= 3:
        return TrendStatus.STRONG_BEAR
    return TrendStatus.CONSOLIDATION


def get_market_regime(row: pd.Series) -> MarketRegime:
    """根据当前均线排列估算市场环境"""
    ts = get_trend_status(row)
    if ts in (TrendStatus.STRONG_BULL, TrendStatus.BULL):
        return MarketRegime.BULL
    elif ts in (TrendStatus.STRONG_BEAR, TrendStatus.BEAR):
        return MarketRegime.BEAR
    return MarketRegime.SIDEWAYS


def build_result(df_slice: pd.DataFrame, code: str) -> TrendAnalysisResult:
    """从切片末尾行构建 TrendAnalysisResult，填充关键字段"""
    result = TrendAnalysisResult(code=code)
    result.signal_reasons = []
    result.risk_factors = []
    result.score_breakdown = {}

    n = len(df_slice)
    if n < 2:
        return result

    row = df_slice.iloc[-1]
    prev_row = df_slice.iloc[-2]

    result.current_price = float(row.get('close', 0))
    result.macd_dif = float(row.get('MACD_DIF', 0) or 0)
    result.macd_dea = float(row.get('MACD_DEA', 0) or 0)
    result.macd_status = get_macd_status(row, prev_row)
    result.trend_status = get_trend_status(row)
    result.atr14 = float(row.get('ATR14', 0) or 0)

    # 均线死叉判断：MA5 < MA20 且前一日 MA5 >= MA20
    ma5_cur = float(row.get('MA5', float('nan')) or float('nan'))
    ma20_cur = float(row.get('MA20', float('nan')) or float('nan'))
    ma5_prev = float(prev_row.get('MA5', float('nan')) or float('nan'))
    ma20_prev = float(prev_row.get('MA20', float('nan')) or float('nan'))
    result.ma_death_cross = (
        not pd.isna(ma5_cur) and not pd.isna(ma20_cur) and
        not pd.isna(ma5_prev) and not pd.isna(ma20_prev) and
        ma5_cur < ma20_cur and ma5_prev >= ma20_prev
    )

    # 止损位（简单用 ATR 估算）
    if result.atr14 > 0:
        result.stop_loss_short = result.current_price - 1.5 * result.atr14
    else:
        result.stop_loss_short = result.current_price * 0.93

    # 乖离率
    result.bias_ma5 = float(row.get('BIAS_MA5', 0) or 0)

    # 布林带
    result.bb_upper = float(row.get('BB_UPPER', 0) or 0)
    result.bb_lower = float(row.get('BB_LOWER', 0) or 0)
    result.bb_width = float(row.get('BB_WIDTH', 0) or 0)
    # bb_pct_b = (close - lower) / (upper - lower)
    _bb_range = result.bb_upper - result.bb_lower
    result.bb_pct_b = (result.current_price - result.bb_lower) / _bb_range if _bb_range > 0 else 0.5

    # RSI
    result.rsi = float(row.get('RSI_12', 50) or 50)
    result.rsi_6 = result.rsi
    result.rsi_12 = result.rsi
    result.rsi_24 = result.rsi
    # RSI 状态（从数值推断，忽略金叉/背离需要多行历史）
    _rsi = result.rsi
    if _rsi > 70:
        result.rsi_status = RSIStatus.OVERBOUGHT
    elif _rsi > 60:
        result.rsi_status = RSIStatus.STRONG_BUY
    elif _rsi >= 40:
        result.rsi_status = RSIStatus.NEUTRAL
    elif _rsi >= 30:
        result.rsi_status = RSIStatus.WEAK
    else:
        result.rsi_status = RSIStatus.OVERSOLD

    # KDJ
    result.kdj_k = float(row.get('KDJ_K', 50) or 50)
    result.kdj_d = float(row.get('KDJ_D', 50) or 50)
    result.kdj_j = float(row.get('KDJ_J', 50) or 50)
    # KDJ 状态（从 K/D/J 值推断，忽略金叉/死叉需要多行）
    _k, _d, _j = result.kdj_k, result.kdj_d, result.kdj_j
    if _j > 100:
        result.kdj_status = KDJStatus.OVERBOUGHT
    elif _j < 0:
        result.kdj_status = KDJStatus.OVERSOLD
    elif _k > _d and _j > 50:
        result.kdj_status = KDJStatus.BULLISH
    elif _k < _d and _j < 50:
        result.kdj_status = KDJStatus.BEARISH
    else:
        result.kdj_status = KDJStatus.NEUTRAL

    # 检测 K/D 金叉/死叉（需要前一行）
    if n >= 2:
        prev_row2 = df_slice.iloc[-2]
        _k_prev = float(prev_row2.get('KDJ_K', 50) or 50)
        _d_prev = float(prev_row2.get('KDJ_D', 50) or 50)
        if _k > _d and _k_prev <= _d_prev:
            result.kdj_status = KDJStatus.GOLDEN_CROSS_OVERSOLD if _j < 20 else KDJStatus.GOLDEN_CROSS
        elif _k < _d and _k_prev >= _d_prev:
            result.kdj_status = KDJStatus.DEATH_CROSS
        _rsi_prev = float(prev_row2.get('RSI_12', 50) or 50)
        if result.rsi > _rsi_prev and _rsi <= 30:
            result.rsi_status = RSIStatus.GOLDEN_CROSS_OVERSOLD
        elif result.rsi > _rsi_prev and _rsi < result.rsi:
            result.rsi_status = RSIStatus.GOLDEN_CROSS if _rsi_prev < result.rsi else result.rsi_status

    # MA 附加字段
    result.ma5 = float(row.get('MA5', 0) or 0)
    result.ma10 = float(row.get('MA10', 0) or 0)
    result.ma20 = float(row.get('MA20', 0) or 0)
    result.ma60 = float(row.get('MA60', 0) or 0)

    # VWAP 机构成本线
    _vwap10 = float(row.get('VWAP10', 0) or 0)
    _vwap20 = float(row.get('VWAP20', 0) or 0)
    _vwap10_slope = float(row.get('VWAP10_SLOPE', 0) or 0)
    _vwap20_slope = float(row.get('VWAP20_SLOPE', 0) or 0)
    if _vwap10 > 0:
        result.vwap10 = round(_vwap10, 2)
        result.vwap10_slope = round(_vwap10_slope, 4)
    if _vwap20 > 0:
        result.vwap20 = round(_vwap20, 2)
        result.vwap20_slope = round(_vwap20_slope, 4)
    _vwap_ref = _vwap10 if _vwap10 > 0 else _vwap20
    _slope_ref = _vwap10_slope if _vwap10 > 0 else _vwap20_slope
    if _vwap_ref > 0:
        _slope_pct = _slope_ref / _vwap_ref * 100
        if _slope_pct > 0.05:
            result.vwap_trend = "机构成本上移"
        elif _slope_pct < -0.05:
            result.vwap_trend = "机构成本下移"
        else:
            result.vwap_trend = "机构成本横盘"
        result.vwap_position = "价格在VWAP上方" if result.current_price > _vwap_ref else "价格在VWAP下方"

    # OBV 背离 / 趋势
    _n = len(df_slice)
    if _n >= 20:
        _close_arr = df_slice['close'].values.astype(float)
        _obv_arr = df_slice['OBV'].values if 'OBV' in df_slice.columns else None
        _obv_ma20_arr = df_slice['OBV_MA20'].values if 'OBV_MA20' in df_slice.columns else None
        if _obv_arr is not None and not pd.isna(_obv_arr[-1]):
            _obv_cur = float(_obv_arr[-1])
            _obv_5_ago = float(_obv_arr[-5]) if _n >= 5 else _obv_cur
            _close_5_ago = float(_close_arr[-5]) if _n >= 5 else float(_close_arr[-1])
            _close_cur = float(_close_arr[-1])
            _obv_20_ago = float(_obv_arr[-20]) if _n >= 20 else _obv_cur
            _close_20_ago = float(_close_arr[-20]) if _n >= 20 else _close_cur
            _close_rising = _close_cur > _close_20_ago
            _obv_rising = _obv_cur > _obv_20_ago
            if _close_rising and not _obv_rising:
                result.obv_divergence = "OBV顶背离"
            elif not _close_rising and _obv_rising:
                result.obv_divergence = "OBV底背离"
            if _obv_ma20_arr is not None and not pd.isna(_obv_ma20_arr[-1]):
                result.obv_trend = "OBV多头" if _obv_cur > float(_obv_ma20_arr[-1]) else "OBV空头"

    # ADX 趋势强度
    _adx = float(row.get('ADX', 0) or 0)
    _plus_di = float(row.get('PLUS_DI', 0) or 0)
    _minus_di = float(row.get('MINUS_DI', 0) or 0)
    if _adx > 0:
        result.adx = round(_adx, 1)
        result.plus_di = round(_plus_di, 1)
        result.minus_di = round(_minus_di, 1)

    # 成交量状态
    vol = float(row.get('volume', 0) or 0)
    vol_avg20 = float(row.get('VOL_AVG20', 0) or 0)
    close_cur = float(row.get('close', 0) or 0)
    open_cur = float(row.get('open', 0) or 0)
    if vol_avg20 > 0:
        ratio = vol / vol_avg20
        up_day = close_cur >= open_cur
        if ratio >= 1.5 and up_day:
            result.volume_status = VolumeStatus.HEAVY_VOLUME_UP
        elif ratio >= 1.5 and not up_day:
            result.volume_status = VolumeStatus.HEAVY_VOLUME_DOWN
        elif ratio <= 0.7 and up_day:
            result.volume_status = VolumeStatus.SHRINK_VOLUME_UP
        elif ratio <= 0.7 and not up_day:
            result.volume_status = VolumeStatus.SHRINK_VOLUME_DOWN
        else:
            result.volume_status = VolumeStatus.NORMAL
    else:
        result.volume_status = VolumeStatus.NORMAL

    return result


# ─────────────────────────────────────────────
# 各改进的信号检测函数
# ─────────────────────────────────────────────

def check_p0_signal(result: TrendAnalysisResult) -> dict:
    """P0：检测止损距离是否触发硬约束"""
    before_adj = dict(result.score_breakdown)
    RiskManager.check_stop_loss_distance(result)
    triggered = 'stop_dist_risk' in result.score_breakdown
    return {'triggered': triggered, 'adj': result.score_breakdown.get('stop_dist_risk', 0)}


def check_p1b_signal(result: TrendAnalysisResult) -> dict:
    """P1b：检测是否存在「均线死叉 + MACD零轴上方金叉」被屏蔽的情形"""
    is_death_cross_ma = result.ma_death_cross
    is_macd_golden_above_zero = result.macd_status == MACDStatus.GOLDEN_CROSS_ZERO
    is_macd_golden_below_zero = result.macd_status == MACDStatus.GOLDEN_CROSS

    blocked = is_death_cross_ma and is_macd_golden_above_zero
    preserved = is_death_cross_ma and is_macd_golden_below_zero
    return {
        'ma_death': is_death_cross_ma,
        'macd_golden_above': is_macd_golden_above_zero,
        'macd_golden_below': is_macd_golden_below_zero,
        'blocked': blocked,     # 被屏蔽（零轴上方金叉被死叉否决）
        'preserved': preserved, # 保留（水下金叉超卖反弹）
    }


def check_p2a_signal(result: TrendAnalysisResult, df_slice: pd.DataFrame) -> dict:
    """P2a：运行缺口分析，返回缺口类型"""
    ScoringSystem.score_gap_analysis(result, df_slice)
    return {
        'gap_type': result.gap_type,
        'gap_signal': result.gap_signal,
        'gap_upper': result.gap_upper,
        'gap_lower': result.gap_lower,
        'gap_adj': result.score_breakdown.get('gap_adj', 0),
    }


def check_p2b_signal(result: TrendAnalysisResult, df_slice: pd.DataFrame) -> dict:
    """P2b：在识别到看多形态（双底/头肩底）时检测突破量能
    
    第一步调用 score_chart_patterns，若识别到看多形态，再计算量能分级。
    这才是 P2b 在生产代码中的真实运行场景。
    """
    if len(df_slice) < 21:
        return {'vol_ratio': 1.0, 'category': 'no_pattern'}
    # 运行形态识别
    ScoringSystem.score_chart_patterns(result, df_slice)
    pattern_signal = getattr(result, 'chart_pattern_signal', '')
    if pattern_signal != '看多':
        return {'vol_ratio': 1.0, 'category': 'no_pattern'}
    # 识别到看多形态，取当日量能比
    last_vol = float(df_slice.iloc[-1].get('volume', 0) or 0)
    avg_vol20 = float(df_slice['volume'].tail(21).iloc[:-1].mean())
    ratio = last_vol / avg_vol20 if avg_vol20 > 0 else 1.0
    if ratio >= 1.5:
        category = 'strong'
    elif ratio >= 1.3:
        category = 'confirm'
    else:
        category = 'weak'
    return {
        'vol_ratio': round(ratio, 2),
        'category': category,
        'pattern': getattr(result, 'chart_pattern', ''),
    }


# ─────────────────────────────────────────────
# 回测主循环
# ─────────────────────────────────────────────

def backtest_stock(code: str, full_df: pd.DataFrame, forward_days: int = 5,
                   min_history: int = 60, verbose: bool = False):
    """滑动窗口回测，每个时间点检测4个改进信号并记录N日后实际表现"""
    full_df = calc_indicators(full_df)
    records = []
    n = len(full_df)

    for i in range(min_history, n - forward_days):
        df_slice = full_df.iloc[:i].copy()
        df_future = full_df.iloc[i:i + forward_days]

        try:
            result = build_result(df_slice, code)
        except Exception:
            continue

        if result.current_price <= 0:
            continue

        entry_price = result.current_price
        future_close = float(df_future['close'].iloc[-1])
        actual_return = (future_close - entry_price) / entry_price * 100

        date_str = str(full_df.index[i]) if isinstance(full_df.index, pd.DatetimeIndex) else \
                   str(full_df.iloc[i].get('date', i))

        # 完整评分链（不重算指标）
        market_regime = get_market_regime(df_slice.iloc[-1])
        try:
            score = ScoringSystem.calculate_base_score(result, market_regime)
            result.signal_score = score
            ScoringSystem.update_buy_signal(result)
        except Exception:
            result.signal_score = 0

        buy_signal_name = result.buy_signal.value if result.buy_signal else 'HOLD'

        # 评分分档
        s = result.signal_score or 0
        if s >= 75:
            score_band = '75+'
        elif s >= 65:
            score_band = '65-75'
        elif s >= 55:
            score_band = '55-65'
        elif s >= 40:
            score_band = '40-55'
        else:
            score_band = '<40'

        # 各改进信号
        p0 = check_p0_signal(result)
        p1b = check_p1b_signal(result)
        p2a = check_p2a_signal(result, df_slice)
        p2b = check_p2b_signal(result, df_slice)

        record = {
            'code': code,
            'date': date_str,
            'actual_return': round(actual_return, 2),
            # 完整评分
            'signal_score': round(s, 1),
            'score_band': score_band,
            'buy_signal': buy_signal_name,
            'market_regime': market_regime.value,
            # P0
            'p0_triggered': p0['triggered'],
            'p0_adj': p0['adj'],
            # P1b
            'p1b_ma_death': p1b['ma_death'],
            'p1b_blocked': p1b['blocked'],
            'p1b_preserved': p1b['preserved'],
            # P2a
            'p2a_gap_type': p2a['gap_type'],
            'p2a_gap_signal': p2a['gap_signal'],  # 细分状态
            'p2a_gap_adj': p2a['gap_adj'],
            # P2b
            'p2b_vol_ratio': p2b['vol_ratio'],
            'p2b_category': p2b['category'],
        }
        records.append(record)

        if verbose:
            flags = []
            if p0['triggered']:
                flags.append(f"P0触发({p0['adj']})")
            if p1b['blocked']:
                flags.append("P1b屏蔽金叉")
            if p1b['preserved']:
                flags.append("P1b保留水下金叉")
            if p2a['gap_signal']:
                flags.append(f"P2a:{p2a['gap_signal']}")
            if p2b['category'] != 'weak':
                flags.append(f"P2b:{p2b['category']}({p2b['vol_ratio']}x)")
            if flags:
                print(f"  {date_str} | {', '.join(flags)} | 后{forward_days}日: {actual_return:+.2f}%")

    return records


# ─────────────────────────────────────────────
# 统计输出
# ─────────────────────────────────────────────

def avg_ret(series):
    return f"{series.mean():+.2f}%" if len(series) > 0 else "N/A"


def win_rate(series, threshold=0):
    if len(series) == 0:
        return "N/A"
    return f"{(series > threshold).mean() * 100:.1f}%"


def print_stats(all_records: list, forward_days: int):
    df = pd.DataFrame(all_records)
    if df.empty:
        print("无回测数据")
        return

    total = len(df)
    overall_ret = df['actual_return'].mean()
    overall_win = (df['actual_return'] > 0).mean() * 100
    print(f"\n{'='*65}")
    print(f"改进效果回测 (前向{forward_days}日，总样本={total})")
    print(f"{'='*65}")
    print(f"整体基准均收益: {overall_ret:+.2f}%  胜率: {overall_win:.1f}%")

    # ── 综合评分分档 ──
    print(f"\n── 综合评分分档 vs 后续{forward_days}日收益 ──")
    band_order = ['<40', '40-55', '55-65', '65-75', '75+']
    for band in band_order:
        grp = df[df['score_band'] == band]
        if len(grp) == 0:
            continue
        avg = grp['actual_return'].mean()
        win = (grp['actual_return'] > 0).mean() * 100
        vs = avg - overall_ret
        mark = '✅' if (band in ['65-75', '75+'] and vs > 0) or (band == '<40' and vs < 0) else '  '
        print(f"  {mark} 评分{band:<8} {len(grp):>4}次  均收益: {avg:+.2f}%  胜率: {win:.1f}%  vs基准: {vs:+.2f}%")

    # 高分 vs 低分区分度
    high = df[df['signal_score'] >= 65]
    low = df[df['signal_score'] < 55]
    if len(high) > 0 and len(low) > 0:
        diff = high['actual_return'].mean() - low['actual_return'].mean()
        print(f"  核心结论: {'✅ 高分(≥65)明显优于低分(<55)，评分区分度有效' if diff > 0 else '⚠️ 高低分收益差=' + f'{diff:+.2f}% ，区分度不足'} (差值 {diff:+.2f}%)")

    # ── BuySignal 方向准确率 ──
    print(f"\n── BuySignal 方向准确率 ──")
    for bs, grp in df.groupby('buy_signal'):
        if len(grp) < 3:
            continue
        avg = grp['actual_return'].mean()
        win = (grp['actual_return'] > 0).mean() * 100
        vs = avg - overall_ret
        is_bull = any(x in str(bs) for x in ['买入', 'BUY', 'buy'])
        is_bear = any(x in str(bs) for x in ['卖出', 'SELL', 'sell'])
        mark = ''
        if is_bull and vs > 0:
            mark = '✅'
        elif is_bear and vs < 0:
            mark = '✅'
        elif is_bull or is_bear:
            mark = '⚠️'
        print(f"  {mark} {str(bs):<16} {len(grp):>4}次  均收益: {avg:+.2f}%  胜率: {win:.1f}%  vs基准: {vs:+.2f}%")

    # ── P0：止损距离硬约束 ──
    print(f"\n── P0 止损距离硬约束 ──")
    p0_triggered = df[df['p0_triggered']]
    p0_normal = df[~df['p0_triggered']]
    print(f"  触发次数: {len(p0_triggered)} / {total} ({len(p0_triggered)/total*100:.1f}%)")
    if len(p0_triggered) > 0:
        print(f"  触发后平均收益: {avg_ret(p0_triggered['actual_return'])}  胜率: {win_rate(p0_triggered['actual_return'])}")
        print(f"  未触发平均收益: {avg_ret(p0_normal['actual_return'])}  胜率: {win_rate(p0_normal['actual_return'])}")
        print(f"  结论: {'✅ 触发后表现确实更差，约束有效' if p0_triggered['actual_return'].mean() < p0_normal['actual_return'].mean() else '⚠️ 触发后表现未必更差，需审查阈值'}")

    # ── P1b：均线死叉屏蔽MACD零轴上方金叉 ──
    print(f"\n── P1b 均线死叉屏蔽MACD零轴上方金叉 ──")
    p1b_blocked = df[df['p1b_blocked']]
    p1b_preserved = df[df['p1b_preserved']]
    p1b_normal_golden = df[
        (~df['p1b_ma_death']) &
        (df['p1b_blocked'] == False) &
        (df['p1b_preserved'] == False)
    ]
    print(f"  被屏蔽（零轴上方金叉+死叉）: {len(p1b_blocked)}次")
    print(f"  被保留（水下金叉+死叉）: {len(p1b_preserved)}次")
    if len(p1b_blocked) > 0:
        print(f"  被屏蔽后均收益: {avg_ret(p1b_blocked['actual_return'])}  胜率: {win_rate(p1b_blocked['actual_return'])}")
    if len(p1b_preserved) > 0:
        print(f"  保留水下金叉均收益: {avg_ret(p1b_preserved['actual_return'])}  胜率: {win_rate(p1b_preserved['actual_return'])}")
    if len(p1b_blocked) > 0:
        blocked_ret = p1b_blocked['actual_return'].mean()
        print(f"  结论: {'✅ 屏蔽的信号均收益为负，屏蔽正确' if blocked_ret < 0 else '⚠️ 屏蔽样本均收益非负，需审查逻辑'}")

    # ── P2a：缺口分析（按细分信号分组）──
    print(f"\n── P2a 缺口分析（按细分信号）──")
    no_gap = df[df['p2a_gap_type'] == '']
    if len(no_gap) > 0:
        print(f"  无缺口基准: {len(no_gap)}次  均收益: {avg_ret(no_gap['actual_return'])}  胜率: {win_rate(no_gap['actual_return'])}")
    signals_order = [
        ('未回补支撑缺口',                '看多 +2'),
        ('未回补支撑缺口(空头趋势降级)',    '看多 +1'),
        ('未回补支撑缺口(时效衰减)',      '看多 +1'),
        ('未回补支撑缺口(高位/时效衰减)',  '看多 +1'),
        ('缺口回补完成',                '中性  0'),
        ('向上缺口已破位',            '看空 -2'),
        ('未回补压力缺口',            '看空 -2'),
        ('向下缺口已回补（阻力位）',      '看空 -1'),
    ]
    bull_signals = ['未回补支撑缺口', '未回补支撑缺口(空头趋势降级)', '未回补支撑缺口(时效衰减)', '未回补支撑缺口(高位/时效衰减)']
    bear_signals = ['向上缺口已破位', '未回补压力缺口', '向下缺口已回补（阻力位）']
    bull_ok, bear_ok = True, True
    for sig, label in signals_order:
        grp = df[df['p2a_gap_signal'] == sig]
        if len(grp) == 0:
            continue
        base_ret = no_gap['actual_return'].mean() if len(no_gap) > 0 else 0
        diff = grp['actual_return'].mean() - base_ret
        mark = '✅' if (sig in bull_signals and diff > 0) or (sig in bear_signals and diff < 0) else '⚠️'
        if sig in bull_signals and diff <= 0:
            bull_ok = False
        if sig in bear_signals and diff >= 0:
            bear_ok = False
        print(f"  {mark} {sig}({label}): {len(grp)}次  均收益: {avg_ret(grp['actual_return'])}  胜率: {win_rate(grp['actual_return'])}  vs基准: {diff:+.2f}%")
    overall_ok = bull_ok and bear_ok
    print(f"  总结论: {'✅ 缺口位置过滤有效，看多/看空方向均符合预期' if overall_ok else '⚠️ 部分信号方向仍不符预期，需继续审查'}")

    # ── P2b：突破量能确认 ──
    print(f"\n── P2b 突破量能确认 ──")
    p2b_strong = df[df['p2b_category'] == 'strong']
    p2b_confirm = df[df['p2b_category'] == 'confirm']
    p2b_weak = df[df['p2b_category'] == 'weak']
    print(f"  放量突破(≥1.5x): {len(p2b_strong)}次  量能确认(1.3-1.5x): {len(p2b_confirm)}次  量能不足(<1.3x): {len(p2b_weak)}次")
    for label, grp in [('放量突破(≥1.5x)', p2b_strong), ('量能确认(1.3x)', p2b_confirm), ('量能不足(<1.3x)', p2b_weak)]:
        if len(grp) > 0:
            print(f"  {label} 均收益: {avg_ret(grp['actual_return'])}  胜率: {win_rate(grp['actual_return'])}")
    if len(p2b_strong) > 0 and len(p2b_weak) > 0:
        s_ret = p2b_strong['actual_return'].mean()
        w_ret = p2b_weak['actual_return'].mean()
        print(f"  结论: {'✅ 放量突破>量能不足，量能确认有效' if s_ret > w_ret else '⚠️ 量能分级效果不明显，需审查'}")

    # ── 综合：按触发信号组合看整体表现 ──
    print(f"\n── 综合：多信号触发时表现 ──")
    df['signal_count'] = (
        df['p0_triggered'].astype(int) +
        df['p1b_blocked'].astype(int) +
        (df['p2a_gap_type'] != '').astype(int) +
        (df['p2b_category'] == 'strong').astype(int)
    )
    for cnt, grp in df.groupby('signal_count'):
        print(f"  触发{cnt}个信号: {len(grp):>4}次  均收益: {avg_ret(grp['actual_return'])}  胜率: {win_rate(grp['actual_return'])}")


# ─────────────────────────────────────────────
# 数据获取（复用 backtest_p3_resonance 的逻辑）
# ─────────────────────────────────────────────

def fetch_history(code: str, days: int, db) -> pd.DataFrame:
    import time, random

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

    if db_rows > 0 and (days - db_rows) <= 10:
        print(f"  DB 缺口仅 {days - db_rows} 行（≤10行容差），直接使用")
        return db_df

    if db_rows > 0:
        print(f"  DB 数据不足（缺 {days - db_rows} 行），补充拉取...")
    else:
        print(f"  DB 无数据，拉取全部 {days} 天...")

    from datetime import date, timedelta
    end_dt = date.today()
    beg_dt = end_dt - timedelta(days=int(days * 1.6))
    raw = None

    # 优先尝试 baostock（稳定，无封禁风险）
    try:
        import baostock as bs
        # code 格式转换：600519 -> sh.600519，000858 -> sz.000858
        prefix = 'sh' if code.startswith('6') else 'sz'
        bs_code = f'{prefix}.{code}'
        lg = bs.login()
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
        bs.logout()
        if data:
            raw = pd.DataFrame(data, columns=rs.fields)
            raw['date'] = pd.to_datetime(raw['date'])
            for col in ['open', 'high', 'low', 'close', 'volume', 'amount', 'turn']:
                if col in raw.columns:
                    raw[col] = pd.to_numeric(raw[col], errors='coerce')
            raw = raw.set_index('date').sort_index()
            print(f"  baostock 拉取: {len(raw)} 行")
    except Exception as e:
        print(f"  baostock 失败: {e}，尝试 efinance...")

    # 回退到 efinance
    if raw is None or len(raw) == 0:
        try:
            from data_provider.rate_limiter import get_global_limiter
            get_global_limiter().acquire('efinance', blocking=True, timeout=15.0)
        except Exception:
            time.sleep(random.uniform(2.0, 5.0))

        import efinance as ef
        raw = ef.stock.get_quote_history(
            code, beg=beg_dt.strftime('%Y%m%d'), end=end_dt.strftime('%Y%m%d'), klt=101, fqt=1
        )
        if raw is None or len(raw) == 0:
            raise RuntimeError(f"efinance 返回空数据 [{code}]")
        col_map = {'日期': 'date', '开盘': 'open', '收盘': 'close',
                   '最高': 'high', '最低': 'low', '成交量': 'volume', '成交额': 'amount'}
        raw = raw.rename(columns=col_map)
        raw['date'] = pd.to_datetime(raw['date'])
        raw = raw.set_index('date').sort_index()

    if db_df is not None and len(db_df) > 0:
        combined = pd.concat([raw, db_df])
        combined = combined[~combined.index.duplicated(keep='first')].sort_index()
    else:
        combined = raw

    result_df = combined.iloc[-days:] if len(combined) > days else combined
    print(f"  最终数据: {len(result_df)} 行")
    return result_df


# ─────────────────────────────────────────────
# 入口
# ─────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="P0/P1b/P2a/P2b 改进效果回测")
    parser.add_argument('--stocks', default='600519,000858,000333',
                        help='逗号分隔的股票代码（每次最多3只，避免封禁）')
    parser.add_argument('--days', type=int, default=5, help='前向验证天数（默认5日）')
    parser.add_argument('--history', type=int, default=500, help='拉取历史天数（默认500日）')
    parser.add_argument('--verbose', action='store_true', help='打印每个时间点详情')
    args = parser.parse_args()

    codes = [c.strip() for c in args.stocks.split(',')]
    if len(codes) > 3:
        raise SystemExit(
            f"❌ 每次回测最多3只股票（当前 {len(codes)} 只），请减少 --stocks 数量以避免封禁。"
        )

    db = DatabaseManager.get_instance()
    all_records = []

    for idx, code in enumerate(codes):
        print(f"\n[{idx+1}/{len(codes)}] {code} 获取 {args.history} 日历史数据...")
        df = fetch_history(code, args.history, db)
        if len(df) < 80:
            raise RuntimeError(f"[{code}] 数据不足（{len(df)} < 80），终止")

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
