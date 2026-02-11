# -*- coding: utf-8 -*-
"""
技术指标计算模块
包含所有技术指标的计算逻辑：MA、MACD、RSI、KDJ、ATR、布林带等
"""

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
        
        return df.fillna(0)
    
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
        """计算 KDJ"""
        low_min = df['low'].rolling(window=9).min()
        high_max = df['high'].rolling(window=9).max()
        rsv = (df['close'] - low_min) / (high_max - low_min) * 100
        df['K'] = rsv.ewm(com=2, adjust=False).mean()
        df['D'] = df['K'].ewm(com=2, adjust=False).mean()
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
            df[f'RSI_{period}'] = rsi.fillna(50)
        df['RSI'] = df[f'RSI_{TechnicalIndicators.RSI_MID}']
        return df
    
    @staticmethod
    def _calc_bollinger_bands(df: pd.DataFrame) -> pd.DataFrame:
        """计算布林带 (20, 2)"""
        bb_mid = df['MA20']
        bb_std = df['close'].rolling(window=20).std()
        df['BB_UPPER'] = bb_mid + 2 * bb_std
        df['BB_LOWER'] = bb_mid - 2 * bb_std
        df['BB_WIDTH'] = ((df['BB_UPPER'] - df['BB_LOWER']) / bb_mid).replace([np.inf, -np.inf], 0)
        band_range = (df['BB_UPPER'] - df['BB_LOWER']).replace(0, np.nan)
        df['BB_PCT_B'] = ((df['close'] - df['BB_LOWER']) / band_range).fillna(0.5)
        return df

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

        if code_str.startswith('300') or code_str.startswith('688'):
            limit_pct = 20.0
        elif code_str.startswith('8') or code_str.startswith('4'):
            limit_pct = 30.0
        else:
            limit_pct = 10.0

        df['limit_pct'] = limit_pct

        if len(df) < 2:
            return df

        pct_chg = df['close'].pct_change() * 100
        tolerance = limit_pct * 0.02  # 2% 容差（如10%板用9.8%判定）
        df['limit_up'] = pct_chg >= (limit_pct - tolerance)
        df['limit_down'] = pct_chg <= -(limit_pct - tolerance)
        return df

    @staticmethod
    def calc_vwap(df: pd.DataFrame) -> pd.DataFrame:
        """
        计算 VWAP（成交量加权平均价）
        
        VWAP = Σ(典型价格 × 成交量) / Σ(成交量)
        典型价格 = (High + Low + Close) / 3
        
        新增列:
        - VWAP: 当日 VWAP（使用滚动20日窗口近似）
        - VWAP_bias: 现价相对 VWAP 的偏离率(%)
        """
        typical_price = (df['high'] + df['low'] + df['close']) / 3
        tp_vol = typical_price * df['volume']
        # 使用20日滚动窗口
        df['VWAP'] = tp_vol.rolling(20).sum() / df['volume'].rolling(20).sum()
        df['VWAP'] = df['VWAP'].fillna(df['close'])
        vwap = df['VWAP']
        df['VWAP_bias'] = ((df['close'] - vwap) / vwap * 100).fillna(0).round(2)
        return df

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
            # 用量比作为换手率的代理（如果没有直接的换手率序列）
            if 'volume_ratio' in df.columns:
                series = df['volume_ratio'].dropna().tail(lookback)
                current = df['volume_ratio'].iloc[-1]
            else:
                vol_series = df['volume'].dropna().tail(lookback)
                avg = vol_series.mean()
                if avg <= 0:
                    return 0.5
                series = vol_series / avg
                current = vol_series.iloc[-1] / avg
            
            if len(series) < lookback // 2:
                return 0.5
            return float((series < current).sum() / len(series))
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
        
        Args:
            df: 包含 J 列的 DataFrame
            lookback: 回看天数
            
        Returns:
            "KDJ底背离" / "KDJ顶背离" / ""
        """
        if df is None or len(df) < lookback or 'J' not in df.columns:
            return ""
        try:
            recent = df.tail(lookback)
            half = lookback // 2
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

            # 价格创新高但 J 值未新高（阈值：价格高1%以上，J值低5以上）
            if (price_high_2 > price_high_1 * 1.01 and 
                j_high_2 < j_high_1 - 5):
                return "KDJ顶背离"
            # 价格创新低但 J 值未新低
            if (price_low_2 < price_low_1 * 0.99 and 
                j_low_2 > j_low_1 + 5):
                return "KDJ底背离"
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
