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
