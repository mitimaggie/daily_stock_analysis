# -*- coding: utf-8 -*-
"""
技术指标计算模块
包含所有技术指标的计算逻辑：MA、MACD、RSI、KDJ、ATR、布林带等
"""

from typing import List, Tuple, Optional

import numpy as np
import pandas as pd
import logging

logger = logging.getLogger(__name__)


class TechnicalIndicators:
    """技术指标计算器"""
    
    RSI_SHORT = 6
    RSI_MID = 12
    RSI_LONG = 24
    
    @staticmethod
    def calculate_all(df: pd.DataFrame) -> pd.DataFrame:
        """
        计算所有技术指标
        
        Args:
            df: 包含 OHLCV 数据的 DataFrame
            
        Returns:
            添加了技术指标列的 DataFrame
        """
        df = df.copy()
        
        df = TechnicalIndicators._calc_moving_averages(df)
        df = TechnicalIndicators._calc_macd(df)
        df = TechnicalIndicators._calc_kdj(df)
        df = TechnicalIndicators._calc_atr(df)
        df = TechnicalIndicators._calc_rsi(df)
        df = TechnicalIndicators._calc_bollinger_bands(df)
        df = TechnicalIndicators._calc_obv(df)
        df = TechnicalIndicators._calc_adx(df)
        df = TechnicalIndicators._calc_macd_momentum(df)
        df = TechnicalIndicators._calc_ma_spread_rate(df)
        df = TechnicalIndicators._calc_vwap(df)
        
        # 核心指标列：保留 NaN（预热期不应被零值污染）
        _CORE_INDICATOR_COLS = {
            'MA5', 'MA10', 'MA20', 'MA60',
            'MACD_DIF', 'MACD_DEA', 'MACD_BAR',
            'RSI_6', 'RSI_12', 'RSI_24',
            'ATR14',
            'BOLL_UPPER', 'BOLL_MID', 'BOLL_LOWER',
            'OBV',
            'VWAP10', 'VWAP20',
        }
        # 预热期标记：任一关键指标仍为 NaN 的行
        _warmup_cols = [c for c in ['MA60', 'MACD_DIF', 'RSI_12', 'ATR14'] if c in df.columns]
        df['_warmup'] = df[_warmup_cols].isna().any(axis=1) if _warmup_cols else False

        # 非核心衍生列填零（MACD_BAR_ACCEL、MA_SPREAD_RATE 等）
        _fill_cols = [c for c in df.columns if c not in _CORE_INDICATOR_COLS and c != '_warmup']
        df[_fill_cols] = df[_fill_cols].fillna(0)

        return df
    
    @staticmethod
    def _calc_moving_averages(df: pd.DataFrame) -> pd.DataFrame:
        """计算均线（复用 BaseFetcher 已计算的小写列，避免重复计算）"""
        df['MA5'] = df['ma5'] if 'ma5' in df.columns else df['close'].rolling(window=5).mean()
        df['MA10'] = df['ma10'] if 'ma10' in df.columns else df['close'].rolling(window=10).mean()
        df['MA20'] = df['ma20'] if 'ma20' in df.columns else df['close'].rolling(window=20).mean()
        df['MA60'] = df['close'].rolling(window=60).mean()
        return df
    
    @staticmethod
    def _calc_macd(df: pd.DataFrame) -> pd.DataFrame:
        """计算 MACD (12/26/9)"""
        ema12 = df['close'].ewm(span=12, adjust=False).mean()
        ema26 = df['close'].ewm(span=26, adjust=False).mean()
        df['MACD_DIF'] = ema12 - ema26
        df['MACD_DEA'] = df['MACD_DIF'].ewm(span=9, adjust=False).mean()
        df['MACD_BAR'] = (df['MACD_DIF'] - df['MACD_DEA']) * 2
        return df
    
    @staticmethod
    def _calc_kdj(df: pd.DataFrame) -> pd.DataFrame:
        """计算 KDJ（SMA递推，与通达信/同花顺一致）"""
        low_min = df['low'].rolling(window=9).min()
        high_max = df['high'].rolling(window=9).max()
        denom = (high_max - low_min).replace(0, np.nan)
        rsv = ((df['close'] - low_min) / denom * 100).fillna(50)

        rsv_values = rsv.values
        k_values = np.full(len(rsv_values), 50.0)
        d_values = np.full(len(rsv_values), 50.0)
        for i in range(1, len(rsv_values)):
            r = rsv_values[i]
            if np.isnan(r):
                k_values[i] = k_values[i - 1]
            else:
                k_values[i] = (2 / 3) * k_values[i - 1] + (1 / 3) * r
            d_values[i] = (2 / 3) * d_values[i - 1] + (1 / 3) * k_values[i]

        df['K'] = k_values
        df['D'] = d_values
        df['J'] = 3 * df['K'] - 2 * df['D']
        return df
    
    @staticmethod
    def _calc_atr(df: pd.DataFrame) -> pd.DataFrame:
        """计算 ATR(14)"""
        tr = np.maximum(
            df['high'] - df['low'],
            np.maximum(
                abs(df['high'] - df['close'].shift(1)),
                abs(df['low'] - df['close'].shift(1))
            )
        )
        df['ATR14'] = tr.rolling(window=14).mean()
        return df
    
    @staticmethod
    def _calc_rsi(df: pd.DataFrame) -> pd.DataFrame:
        """计算多周期 RSI (6/12/24) — Wilder's EMA"""
        delta = df['close'].diff()
        for period in [TechnicalIndicators.RSI_SHORT, 
                       TechnicalIndicators.RSI_MID, 
                       TechnicalIndicators.RSI_LONG]:
            gain = delta.where(delta > 0, 0.0)
            loss_s = (-delta).where(delta < 0, 0.0)
            avg_gain = gain.ewm(alpha=1.0/period, min_periods=period, adjust=False).mean()
            avg_loss = loss_s.ewm(alpha=1.0/period, min_periods=period, adjust=False).mean()
            rs = avg_gain / avg_loss.replace(0, np.nan)
            rsi = 100 - (100 / (1 + rs))
            rsi = rsi.where(avg_loss != 0, 100.0)
            df[f'RSI_{period}'] = rsi
        df['RSI'] = df[f'RSI_{TechnicalIndicators.RSI_MID}']
        return df
    
    @staticmethod
    def _calc_bollinger_bands(df: pd.DataFrame) -> pd.DataFrame:
        """计算布林带 (20, 2)"""
        bb_mid = df['MA20']
        bb_std = df['close'].rolling(window=20).std(ddof=0)
        df['BB_UPPER'] = bb_mid + 2 * bb_std
        df['BB_LOWER'] = bb_mid - 2 * bb_std
        df['BB_WIDTH'] = ((df['BB_UPPER'] - df['BB_LOWER']) / bb_mid).replace([np.inf, -np.inf], 0)
        band_range = (df['BB_UPPER'] - df['BB_LOWER']).replace(0, np.nan)
        df['BB_PCT_B'] = ((df['close'] - df['BB_LOWER']) / band_range).fillna(0.5)
        return df

    @staticmethod
    def _calc_obv(df: pd.DataFrame) -> pd.DataFrame:
        """
        计算 OBV (On-Balance Volume) 累积量能指标
        
        逻辑：收盘涨 → +volume，收盘跌 → -volume，平盘 → 0
        新增列：
        - OBV: 累积量能
        - OBV_MA20: OBV 的 20 日均线（用于判断 OBV 趋势）
        - OBV_divergence: OBV 与价格的背离方向
        """
        if 'volume' not in df.columns or len(df) < 5:
            df['OBV'] = 0
            df['OBV_MA20'] = 0
            return df
        
        direction = np.where(df['close'] > df['close'].shift(1), 1,
                    np.where(df['close'] < df['close'].shift(1), -1, 0))
        df['OBV'] = (df['volume'] * direction).cumsum()
        df['OBV_MA20'] = df['OBV'].rolling(window=20).mean()
        return df

    @staticmethod
    def _calc_adx(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
        """
        计算 ADX / DMI (Average Directional Index)
        
        ADX > 25 = 趋势市场，ADX < 20 = 震荡市场
        +DI > -DI = 多头趋势，-DI > +DI = 空头趋势
        
        新增列：
        - ADX: 趋势强度 (0-100)
        - PLUS_DI: +DI 多头方向指标
        - MINUS_DI: -DI 空头方向指标
        """
        if len(df) < period * 2:
            df['ADX'] = 0
            df['PLUS_DI'] = 0
            df['MINUS_DI'] = 0
            return df
        
        high = df['high']
        low = df['low']
        close = df['close']
        
        # True Range
        tr = np.maximum(high - low,
                np.maximum(abs(high - close.shift(1)),
                           abs(low - close.shift(1))))
        
        # Directional Movement
        up_move = high - high.shift(1)
        down_move = low.shift(1) - low
        
        plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
        minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
        
        plus_dm = pd.Series(plus_dm, index=df.index)
        minus_dm = pd.Series(minus_dm, index=df.index)
        
        # Smoothed averages (Wilder's smoothing)
        atr_smooth = tr.ewm(alpha=1.0/period, min_periods=period, adjust=False).mean()
        plus_di_smooth = plus_dm.ewm(alpha=1.0/period, min_periods=period, adjust=False).mean()
        minus_di_smooth = minus_dm.ewm(alpha=1.0/period, min_periods=period, adjust=False).mean()
        
        # +DI and -DI
        df['PLUS_DI'] = (plus_di_smooth / atr_smooth.replace(0, np.nan) * 100).fillna(0)
        df['MINUS_DI'] = (minus_di_smooth / atr_smooth.replace(0, np.nan) * 100).fillna(0)
        
        # DX and ADX
        di_sum = df['PLUS_DI'] + df['MINUS_DI']
        di_diff = abs(df['PLUS_DI'] - df['MINUS_DI'])
        dx = (di_diff / di_sum.replace(0, np.nan) * 100).fillna(0)
        df['ADX'] = dx.ewm(alpha=1.0/period, min_periods=period, adjust=False).mean()
        
        return df

    @staticmethod
    def _calc_macd_momentum(df: pd.DataFrame) -> pd.DataFrame:
        """
        计算 MACD 柱状图动量（加速度）
        
        - MACD_BAR_SLOPE: 柱状图斜率（今天 - 昨天），正=加速上涨，负=加速下跌
        - MACD_BAR_ACCEL: 连续 N 天柱状图同向变化的天数（正=连续放大，负=连续缩小）
        """
        if 'MACD_BAR' not in df.columns or len(df) < 3:
            df['MACD_BAR_SLOPE'] = 0
            df['MACD_BAR_ACCEL'] = 0
            return df
        
        df['MACD_BAR_SLOPE'] = df['MACD_BAR'] - df['MACD_BAR'].shift(1)
        
        # 计算连续同向变化天数
        slope = df['MACD_BAR_SLOPE'].values
        accel = np.zeros(len(slope))
        for i in range(1, len(slope)):
            if slope[i] > 0 and slope[i-1] > 0:
                accel[i] = accel[i-1] + 1
            elif slope[i] < 0 and slope[i-1] < 0:
                accel[i] = accel[i-1] - 1
            else:
                accel[i] = 1 if slope[i] > 0 else (-1 if slope[i] < 0 else 0)
        df['MACD_BAR_ACCEL'] = accel
        
        return df

    @staticmethod
    def _calc_ma_spread_rate(df: pd.DataFrame) -> pd.DataFrame:
        """
        计算均线发散速率：MA5-MA20 差值的变化率
        
        - MA_SPREAD: (MA5 - MA20) / MA20 * 100，当前均线距离百分比
        - MA_SPREAD_RATE: MA_SPREAD 的 5 日变化量，正=加速发散，负=收敛
        """
        if 'MA5' not in df.columns or 'MA20' not in df.columns or len(df) < 25:
            df['MA_SPREAD'] = 0
            df['MA_SPREAD_RATE'] = 0
            return df
        
        ma20_safe = df['MA20'].replace(0, np.nan)
        df['MA_SPREAD'] = ((df['MA5'] - df['MA20']) / ma20_safe * 100).fillna(0)
        df['MA_SPREAD_RATE'] = df['MA_SPREAD'] - df['MA_SPREAD'].shift(5)
        
        return df

    @staticmethod
    def detect_obv_divergence(df: pd.DataFrame, lookback: int = 20) -> str:
        """OBV 背离检测：价格新高但 OBV 动能减弱 / 价格新低但 OBV 动能增强"""
        if df is None or len(df) < lookback or 'OBV' not in df.columns:
            return ""
        try:
            recent = df.tail(lookback)
            half = lookback // 2
            first_half = recent.head(half)
            second_half = recent.tail(half)

            price_high_1 = first_half['high'].max()
            price_high_2 = second_half['high'].max()
            price_low_1 = first_half['low'].min()
            price_low_2 = second_half['low'].min()

            def _obv_slope(series: pd.Series) -> float:
                x = np.arange(len(series), dtype=float)
                y = series.values.astype(float)
                mask = ~np.isnan(y)
                if mask.sum() < 3:
                    return 0.0
                x, y = x[mask], y[mask]
                slope = (np.mean(x * y) - np.mean(x) * np.mean(y)) / max(np.var(x), 1e-10)
                return slope

            obv_slope_1 = _obv_slope(first_half['OBV'])
            obv_slope_2 = _obv_slope(second_half['OBV'])

            if price_high_2 > price_high_1 * 1.01 and obv_slope_2 < obv_slope_1 * 0.5:
                return "OBV顶背离"
            if price_low_2 < price_low_1 * 0.99 and obv_slope_2 > obv_slope_1 * 0.5 and obv_slope_2 > 0:
                return "OBV底背离"
            return ""
        except Exception:
            return ""

    @staticmethod
    def detect_limit(df: pd.DataFrame, code: str = "") -> pd.DataFrame:
        """
        检测涨跌停状态（A股特有）
        
        规则：
        - 创业板(300xxx): ±20%
        - 科创板(688xxx): ±20%
        - 北交所(8xxxxx/4xxxxx): ±30%
        - 主板/中小板: ±10%
        
        新增列:
        - limit_up: bool, 当日涨停
        - limit_down: bool, 当日跌停
        - limit_pct: float, 该股涨跌停幅度
        """
        df['limit_up'] = False
        df['limit_down'] = False

        # 根据股票代码前缀精确判断涨跌停幅度
        code_str = str(code).strip()
        # 去掉可能的市场前缀（如 sh600000 -> 600000）
        for prefix in ('sh', 'sz', 'bj', 'SH', 'SZ', 'BJ'):
            if code_str.startswith(prefix):
                code_str = code_str[len(prefix):]
                break
        # 去掉可能的后缀（如 600000.SH -> 600000）
        if '.' in code_str:
            code_str = code_str.split('.')[0]

        if code_str.startswith('300') or code_str.startswith('301') or code_str.startswith('688') or code_str.startswith('689'):
            limit_pct = 20.0
        elif code_str.startswith('8') or code_str.startswith('4'):
            limit_pct = 30.0
        else:
            limit_pct = 10.0

        df['limit_pct'] = limit_pct

        if len(df) < 2:
            return df

        if 'pct_chg' in df.columns and df['pct_chg'].notna().sum() > len(df) * 0.5:
            pct = df['pct_chg']
        else:
            pct = df['close'].pct_change() * 100

        suspected_ex_right = pct.abs() > limit_pct * 1.5

        tolerance = limit_pct * 0.02
        df['limit_up'] = (pct >= (limit_pct - tolerance)) & ~suspected_ex_right
        df['limit_down'] = (pct <= -(limit_pct - tolerance)) & ~suspected_ex_right
        return df

    @staticmethod
    def calc_vwap(df: pd.DataFrame) -> pd.DataFrame:
        """[Deprecated] 请使用 calculate_all() 中自动调用的 _calc_vwap()。

        保留此方法仅为兼容性，内部委托到 _calc_vwap()。
        """
        import warnings
        warnings.warn("calc_vwap() 已废弃，VWAP/VWAP_bias 由 _calc_vwap() 在 calculate_all() 中统一计算",
                       DeprecationWarning, stacklevel=2)
        return TechnicalIndicators._calc_vwap(df)

    @staticmethod
    def detect_volume_price_divergence(df: pd.DataFrame, lookback: int = 20) -> str:
        """
        量价背离检测：价格新高但成交量萎缩 / 价格新低但成交量萎缩
        
        Returns:
            "顶部量价背离" / "底部量缩企稳" / ""
        """
        if df is None or len(df) < lookback:
            return ""
        try:
            recent = df.tail(lookback)
            half = lookback // 2
            first_half = recent.head(half)
            second_half = recent.tail(half)

            price_high_1 = first_half['high'].max()
            price_high_2 = second_half['high'].max()
            vol_avg_1 = first_half['volume'].mean()
            vol_avg_2 = second_half['volume'].mean()

            price_low_1 = first_half['low'].min()
            price_low_2 = second_half['low'].min()

            # 价格创新高但量能萎缩 > 20%
            if price_high_2 > price_high_1 and vol_avg_2 < vol_avg_1 * 0.8:
                return "顶部量价背离"
            # 价格创新低但量能萎缩（缩量探底，可能企稳）
            if price_low_2 < price_low_1 and vol_avg_2 < vol_avg_1 * 0.7:
                return "底部量缩企稳"
            return ""
        except Exception:
            return ""

    @staticmethod
    def calc_turnover_percentile(df: pd.DataFrame, turnover_rate: float, lookback: int = 60) -> float:
        """
        计算当前换手率在历史中的分位数
        
        Args:
            df: K线数据（需包含 volume 列）
            turnover_rate: 当前换手率
            lookback: 回看天数
            
        Returns:
            分位数 (0.0-1.0)，0.9 表示当前换手率高于历史90%的交易日
        """
        if turnover_rate <= 0 or df is None or len(df) < lookback // 2:
            return 0.5
        try:
            # 盘中折算：换手率是当日累计值，需用经验分布推算全天等价值再与历史比较
            # A股成交分布不均匀（开盘和收盘前集中），不能用线性时间折算
            # 与 market_monitor.py 保持同一套经验权重曲线
            _INTRADAY_CUM_WEIGHTS = [
                ((9, 30),  0.000),
                ((10, 0),  0.220),
                ((10, 30), 0.330),
                ((11, 0),  0.415),
                ((11, 30), 0.480),
                ((13, 0),  0.480),
                ((13, 30), 0.545),
                ((14, 0),  0.620),
                ((14, 30), 0.710),
                ((15, 0),  1.000),
            ]
            from datetime import datetime as _dt
            _now = _dt.now()
            _h, _m = _now.hour, _now.minute

            def _get_cum_ratio_tr(h, m):
                t = h * 60 + m
                for i in range(len(_INTRADAY_CUM_WEIGHTS) - 1):
                    (h0, m0), r0 = _INTRADAY_CUM_WEIGHTS[i]
                    (h1, m1), r1 = _INTRADAY_CUM_WEIGHTS[i + 1]
                    t0, t1 = h0 * 60 + m0, h1 * 60 + m1
                    if t0 <= t <= t1:
                        return r0 + (r1 - r0) * (t - t0) / (t1 - t0) if t1 != t0 else r0
                return 1.0 if t >= 15 * 60 else 0.0

            cum_ratio = _get_cum_ratio_tr(_h, _m)
            adjusted_rate = turnover_rate
            if 0 < cum_ratio < 1.0:
                adjusted_rate = turnover_rate / cum_ratio
            
            # 优先用 df 中的历史换手率序列（如果存在且有足够数据）
            if 'turnover_rate' in df.columns:
                tr_series = df['turnover_rate'].dropna().tail(lookback)
                if len(tr_series) >= lookback // 2:
                    return float((tr_series < adjusted_rate).sum() / len(tr_series))

            # 回退：用成交量序列计算相对分位（成交量越大≈换手率越高）
            vol_series = df['volume'].dropna().tail(lookback)
            if len(vol_series) < lookback // 2:
                return 0.5
            avg = vol_series.mean()
            if avg <= 0:
                return 0.5
            # 用当前换手率与历史成交量分位对应（当前成交量 = 最后一行）
            current_vol = float(vol_series.iloc[-1])
            return float((vol_series < current_vol).sum() / len(vol_series))
        except Exception:
            return 0.5

    @staticmethod
    def detect_gap(df: pd.DataFrame) -> str:
        """
        检测最近一个交易日的跳空缺口
        
        Returns:
            "向上跳空" / "向下跳空" / ""
        """
        if df is None or len(df) < 2:
            return ""
        try:
            today = df.iloc[-1]
            yesterday = df.iloc[-2]
            # 向上跳空：今日最低价 > 昨日最高价
            if float(today['low']) > float(yesterday['high']):
                return "向上跳空"
            # 向下跳空：今日最高价 < 昨日最低价
            if float(today['high']) < float(yesterday['low']):
                return "向下跳空"
            return ""
        except Exception:
            return ""

    @staticmethod
    def detect_kdj_divergence(df: pd.DataFrame, lookback: int = 30) -> str:
        """
        KDJ 背离检测：价格新高/新低但 J 值未同步
        双窗口检测：30日（短期）+ 60日（中期，捕捉更大级别顶底）
        
        Args:
            df: 包含 J 列的 DataFrame
            lookback: 基础回看天数（兼容旧调用）
            
        Returns:
            "KDJ底背离" / "KDJ顶背离" / "KDJ底背离(中期)" / "KDJ顶背离(中期)" / ""
        """
        if df is None or 'J' not in df.columns:
            return ""
        try:
            # 双窗口：短期30日 + 中期60日
            for window, label_suffix in [(lookback, ""), (60, "(中期)")]:
                if len(df) < window:
                    continue
                recent = df.tail(window)
                half = window // 2
                first_half = recent.head(half)
                second_half = recent.tail(half)

                price_high_1 = first_half['high'].max()
                price_high_2 = second_half['high'].max()
                j_high_1 = first_half['J'].max()
                j_high_2 = second_half['J'].max()

                price_low_1 = first_half['low'].min()
                price_low_2 = second_half['low'].min()
                j_low_1 = first_half['J'].min()
                j_low_2 = second_half['J'].min()

                # 中期窗口用更宽松的阈值
                price_thr = 1.02 if window >= 60 else 1.01
                j_thr = 8 if window >= 60 else 5

                if (price_high_2 > price_high_1 * price_thr and 
                    j_high_2 < j_high_1 - j_thr):
                    return f"KDJ顶背离{label_suffix}"
                if (price_low_2 < price_low_1 * (2 - price_thr) and 
                    j_low_2 > j_low_1 + j_thr):
                    return f"KDJ底背离{label_suffix}"
            return ""
        except Exception:
            return ""

    @staticmethod
    def detect_kdj_consecutive_extreme(df: pd.DataFrame, days: int = 3) -> str:
        """
        J 值连续极端检测：连续多日 J>100 或 J<0
        
        Args:
            df: 包含 J 列的 DataFrame
            days: 连续天数阈值
            
        Returns:
            "J值连续超买N天" / "J值连续超卖N天" / ""
        """
        if df is None or len(df) < days or 'J' not in df.columns:
            return ""
        try:
            recent_j = df['J'].tail(days).values
            if all(j > 100 for j in recent_j):
                return f"J值连续超买{days}天"
            if all(j < 0 for j in recent_j):
                return f"J值连续超卖{days}天"
            return ""
        except Exception:
            return ""

    @staticmethod
    def detect_kdj_passivation(df: pd.DataFrame, trend_strength: float, lookback: int = 10) -> bool:
        """
        KDJ 钝化识别：强趋势中 KDJ 长期处于超买/超卖区域
        
        在强趋势行情中，KDJ 会持续处于极端区域（"钝化"），
        此时超买/超卖信号不可靠，应降低其权重。
        
        Args:
            df: 包含 K, D 列的 DataFrame
            trend_strength: 趋势强度 (0-100)
            lookback: 回看天数
            
        Returns:
            True = KDJ 处于钝化状态，超买/超卖信号不可靠
        """
        if df is None or len(df) < lookback or 'K' not in df.columns:
            return False
        try:
            # 只在强趋势中检测钝化（趋势强度 >= 70 或 <= 30）
            if 30 < trend_strength < 70:
                return False
            
            recent_k = df['K'].tail(lookback).values
            # 多头钝化：近N日中 >= 70% 的天数 K > 80
            overbought_days = sum(1 for k in recent_k if k > 80)
            if overbought_days >= lookback * 0.7 and trend_strength >= 70:
                return True
            # 空头钝化：近N日中 >= 70% 的天数 K < 20
            oversold_days = sum(1 for k in recent_k if k < 20)
            if oversold_days >= lookback * 0.7 and trend_strength <= 30:
                return True
            return False
        except Exception:
            return False

    @staticmethod
    def calc_atr_percentile(df: pd.DataFrame, lookback: int = 60) -> float:
        """
        计算当前ATR在历史中的分位数（用于自适应止损倍数）
        
        Args:
            df: 包含 ATR14 列的 DataFrame
            lookback: 回看期数
            
        Returns:
            ATR 分位数 (0.0-1.0)
        """
        try:
            if 'ATR14' not in df.columns or len(df) < lookback:
                return 0.5
            
            atr_series = df['ATR14'].dropna().tail(lookback)
            if len(atr_series) < lookback // 2:
                return 0.5
            
            current_atr = atr_series.iloc[-1]
            if current_atr <= 0:
                return 0.5
            
            percentile = (atr_series < current_atr).sum() / len(atr_series)
            return percentile
        except Exception:
            return 0.5
    
    @staticmethod
    def _calc_vwap(df: pd.DataFrame) -> pd.DataFrame:
        """计算多日累积VWAP（10日/20日）及斜率、偏离率

        输出列：
        - VWAP10, VWAP20: 10/20日成交量加权均价
        - VWAP10_SLOPE, VWAP20_SLOPE: VWAP斜率（正=机构成本上移）
        - VWAP: VWAP20的别名，兼容旧接口
        - VWAP_bias: 现价相对VWAP20的偏离率(%)
        """
        try:
            tp = (df['high'] + df['low'] + df['close']) / 3
            tp_vol = tp * df['volume']
            for window in [10, 20]:
                vol_sum = df['volume'].rolling(window=window, min_periods=window).sum()
                tp_vol_sum = tp_vol.rolling(window=window, min_periods=window).sum()
                vwap = tp_vol_sum / vol_sum.replace(0, np.nan)
                df[f'VWAP{window}'] = vwap
                df[f'VWAP{window}_SLOPE'] = (vwap - vwap.shift(window)) / window
            df['VWAP'] = df['VWAP20'].fillna(df['close'])
            df['VWAP_bias'] = ((df['close'] - df['VWAP']) / df['VWAP'] * 100).fillna(0).round(2)
        except Exception as e:
            logger.debug(f"VWAP计算失败: {e}")
        return df

    # ── swing point 极值检测与背离分析 ──────────────────────────

    @staticmethod
    def find_swing_highs(highs: np.ndarray, n: int = 3, lookback: int = 60) -> List[Tuple[int, float]]:
        """在最近 lookback 根 K 线中，用 N-bar high 算法检测局部最高点。

        Args:
            highs: 全部 K 线的 high 数组
            n: 左右各需 n 根 K 线作为比较窗口
            lookback: 只扫描最近 lookback 根 K 线

        Returns:
            [(绝对索引, 价格值), ...] 按索引升序
        """
        if len(highs) < 2 * n + 1:
            return []

        start_idx = max(0, len(highs) - lookback)
        result: List[Tuple[int, float]] = []

        for i in range(start_idx + n, len(highs) - n):
            window = highs[i - n: i + n + 1]
            val = highs[i]
            if val >= window.max() - 1e-9 and (val > highs[i - n] or val > highs[i + n]):
                result.append((i, float(val)))

        return result

    @staticmethod
    def find_swing_lows(lows: np.ndarray, n: int = 3, lookback: int = 60) -> List[Tuple[int, float]]:
        """在最近 lookback 根 K 线中，用 N-bar low 算法检测局部最低点。

        Args:
            lows: 全部 K 线的 low 数组
            n: 左右各需 n 根 K 线作为比较窗口
            lookback: 只扫描最近 lookback 根 K 线

        Returns:
            [(绝对索引, 价格值), ...] 按索引升序
        """
        if len(lows) < 2 * n + 1:
            return []

        start_idx = max(0, len(lows) - lookback)
        result: List[Tuple[int, float]] = []

        for i in range(start_idx + n, len(lows) - n):
            window = lows[i - n: i + n + 1]
            val = lows[i]
            if val <= window.min() + 1e-9 and (val < lows[i - n] or val < lows[i + n]):
                result.append((i, float(val)))

        return result

    @staticmethod
    def detect_divergence_swing(
        df: pd.DataFrame,
        indicator_col: str = 'RSI_12',
        swing_n: int = 3,
        lookback: int = 60,
        price_min_pct: float = 1.0,
        indicator_min_diff: float = 3.0,
    ) -> dict:
        """基于 swing point 的价格-指标背离检测。

        对比最近两个价格极值点与对应位置的指标值，
        判断是否出现顶背离（价格新高但指标走弱）或底背离（价格新低但指标走强）。

        Args:
            df: 含 high/low 及指标列的 DataFrame
            indicator_col: 用于比较的指标列名
            swing_n: swing point 窗口半径
            lookback: 回溯 K 线数
            price_min_pct: 价格差异最小百分比阈值
            indicator_min_diff: 指标差异最小绝对值阈值

        Returns:
            包含 top_divergence / bottom_divergence 布尔值及详情的字典
        """
        empty: dict = {
            'top_divergence': False,
            'bottom_divergence': False,
            'top_detail': '',
            'bottom_detail': '',
            'swing_highs': [],
            'swing_lows': [],
        }

        if df is None or len(df) < 2 * swing_n + 1:
            return empty
        if indicator_col not in df.columns:
            logger.debug(f"detect_divergence_swing: 指标列 {indicator_col} 不存在")
            return empty

        indicator = df[indicator_col].values
        swing_highs = TechnicalIndicators.find_swing_highs(df['high'].values, swing_n, lookback)
        swing_lows = TechnicalIndicators.find_swing_lows(df['low'].values, swing_n, lookback)

        result: dict = {
            'top_divergence': False,
            'bottom_divergence': False,
            'top_detail': '',
            'bottom_detail': '',
            'swing_highs': swing_highs,
            'swing_lows': swing_lows,
        }

        # ── 顶背离：价格创新高、指标走弱 ──
        valid_highs = [(idx, val) for idx, val in swing_highs
                       if idx < len(indicator) and not np.isnan(indicator[idx])]
        if len(valid_highs) >= 2:
            p1_idx, p1_val = valid_highs[-2]
            p2_idx, p2_val = valid_highs[-1]
            ind1, ind2 = indicator[p1_idx], indicator[p2_idx]
            if (p2_val > p1_val * (1 + price_min_pct / 100)
                    and ind2 < ind1 - indicator_min_diff):
                result['top_divergence'] = True
                result['top_detail'] = (
                    f"价格高点{p2_val:.1f}>{p1_val:.1f}，"
                    f"{indicator_col} {ind2:.1f}<{ind1:.1f}"
                )

        # ── 底背离：价格创新低、指标走强 ──
        valid_lows = [(idx, val) for idx, val in swing_lows
                      if idx < len(indicator) and not np.isnan(indicator[idx])]
        if len(valid_lows) >= 2:
            t1_idx, t1_val = valid_lows[-2]
            t2_idx, t2_val = valid_lows[-1]
            ind1, ind2 = indicator[t1_idx], indicator[t2_idx]
            if (t2_val < t1_val * (1 - price_min_pct / 100)
                    and ind2 > ind1 + indicator_min_diff):
                result['bottom_divergence'] = True
                result['bottom_detail'] = (
                    f"价格低点{t2_val:.1f}<{t1_val:.1f}，"
                    f"{indicator_col} {ind2:.1f}>{ind1:.1f}"
                )

        return result

    @staticmethod
    def resample_to_weekly(df: pd.DataFrame) -> pd.DataFrame:
        """
        将日线K线 resample 为周线K线
        
        Args:
            df: 日线数据
            
        Returns:
            周线数据
        """
        try:
            if df is None or len(df) < 5:
                return None
            
            df_weekly = df.copy()
            if not isinstance(df_weekly.index, pd.DatetimeIndex):
                if 'date' in df_weekly.columns:
                    df_weekly['date'] = pd.to_datetime(df_weekly['date'])
                    df_weekly = df_weekly.set_index('date')
                else:
                    return None
            
            weekly = df_weekly.resample('W').agg({
                'open': 'first',
                'high': 'max',
                'low': 'min',
                'close': 'last',
                'volume': 'sum'
            }).dropna()
            
            if len(weekly) < 3:
                return None
            
            weekly = TechnicalIndicators.calculate_all(weekly)
            return weekly
            
        except Exception as e:
            logger.debug(f"Resample到周线失败: {e}")
            return None
