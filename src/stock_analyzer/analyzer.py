# -*- coding: utf-8 -*-
"""
主分析器模块
整合技术指标、评分系统、共振检测、风险管理、格式化输出等所有功能
"""

import logging
import pandas as pd
import numpy as np
from typing import Dict, Any

from .types import TrendAnalysisResult, TrendStatus, MarketRegime
from .types import VolumeStatus, MACDStatus, RSIStatus, KDJStatus
from .indicators import TechnicalIndicators
from .scoring import ScoringSystem
from .resonance import ResonanceDetector
from .risk_management import RiskManager
from .formatter import AnalysisFormatter

logger = logging.getLogger(__name__)


class StockTrendAnalyzer:
    """股票趋势分析器 - 模块化重构版"""
    
    VOLUME_SHRINK_RATIO = 0.7
    VOLUME_HEAVY_RATIO = 1.5
    
    def __init__(self):
        """初始化分析器"""
        pass
    
    def analyze(
        self,
        df: pd.DataFrame,
        code: str,
        market_regime: MarketRegime = MarketRegime.SIDEWAYS,
        index_returns: pd.Series = None,
        valuation: dict = None,
        capital_flow: dict = None,
        sector_context: dict = None,
        chip_data: dict = None,
        fundamental_data: dict = None,
        quote_extra: dict = None
    ) -> TrendAnalysisResult:
        """
        股票趋势分析主入口
        
        Args:
            df: K线数据（OHLCV）
            code: 股票代码
            market_regime: 市场环境（牛市/震荡/熊市）
            index_returns: 大盘收益率序列（计算Beta用）
            valuation: 估值数据
            capital_flow: 资金流数据
            sector_context: 板块数据
            chip_data: 筹码数据
            fundamental_data: 基本面数据
            quote_extra: 行情附加数据
            
        Returns:
            TrendAnalysisResult: 分析结果对象
        """
        result = TrendAnalysisResult(code=code)
        
        if df is None or df.empty or len(df) < 30:
            result.advice_for_empty = "数据不足，观望"
            result.advice_for_holding = "数据不足，谨慎"
            return result
        
        try:
            df = TechnicalIndicators.calculate_all(df)
            latest = df.iloc[-1]
            prev = df.iloc[-2]
            
            result.current_price = float(latest['close'])
            result.ma5 = float(latest['MA5'])
            result.ma10 = float(latest['MA10'])
            result.ma20 = float(latest['MA20'])
            result.ma60 = float(latest.get('MA60', 0) or 0)
            result.atr14 = float(latest.get('ATR14', 0) or 0)
            
            result.rsi_6 = float(latest.get(f'RSI_{TechnicalIndicators.RSI_SHORT}', 50) or 50)
            result.rsi_12 = float(latest.get(f'RSI_{TechnicalIndicators.RSI_MID}', 50) or 50)
            result.rsi_24 = float(latest.get(f'RSI_{TechnicalIndicators.RSI_LONG}', 50) or 50)
            result.rsi = result.rsi_12
            
            result.macd_dif = float(latest['MACD_DIF'])
            result.macd_dea = float(latest['MACD_DEA'])
            result.macd_bar = float(latest.get('MACD_BAR', 0) or 0)
            
            result.kdj_k = round(float(latest.get('K', 50) or 50), 2)
            result.kdj_d = round(float(latest.get('D', 50) or 50), 2)
            result.kdj_j = round(float(latest.get('J', 50) or 50), 2)
            
            result.bb_upper = round(float(latest.get('BB_UPPER', 0) or 0), 2)
            result.bb_lower = round(float(latest.get('BB_LOWER', 0) or 0), 2)
            result.bb_width = round(float(latest.get('BB_WIDTH', 0) or 0), 4)
            result.bb_pct_b = round(float(latest.get('BB_PCT_B', 0.5) or 0.5), 4)
            
            if len(df) >= 21:
                daily_ret = df['close'].pct_change().dropna().tail(20)
                result.volatility_20d = round(float(daily_ret.std() * np.sqrt(252) * 100), 2)
            
            if len(df) >= 60:
                high_60d = float(df['high'].tail(60).max())
                if high_60d > 0:
                    result.max_drawdown_60d = round((result.current_price - high_60d) / high_60d * 100, 2)
            
            if index_returns is not None and len(df) >= 60:
                try:
                    stock_ret = df['close'].pct_change().dropna().tail(60)
                    idx_ret = index_returns.tail(60)
                    if len(stock_ret) >= 30 and len(idx_ret) >= 30:
                        min_len = min(len(stock_ret), len(idx_ret))
                        s = stock_ret.values[-min_len:]
                        m = idx_ret.values[-min_len:]
                        cov = np.cov(s, m)[0][1]
                        var = np.var(m)
                        if var > 0:
                            result.beta_vs_index = round(cov / var, 2)
                except Exception:
                    pass
            
            self._analyze_volume(result, df, latest, prev)
            self._analyze_macd(result, prev)
            self._analyze_rsi(result, df, prev)
            self._analyze_kdj(result, prev)
            self._analyze_trend(result, df, prev)
            self._calculate_bias(result)
            
            result.support_levels, result.resistance_levels = RiskManager.compute_support_resistance_levels(df, result)
            
            score = ScoringSystem.calculate_base_score(result, market_regime)
            result.signal_score = score
            ScoringSystem.update_buy_signal(result)
            
            ResonanceDetector.detect_indicator_resonance(result, df, prev)
            ResonanceDetector.detect_market_behavior(result, df)
            ResonanceDetector.check_multi_timeframe_resonance(result, df)
            
            ScoringSystem.check_valuation(result, valuation)
            ScoringSystem.check_trading_halt(result)
            ScoringSystem.score_capital_flow(result, capital_flow)
            ScoringSystem.score_capital_flow_trend(result, df)
            ScoringSystem.score_sector_strength(result, sector_context)
            ScoringSystem.score_chip_distribution(result, chip_data)
            ScoringSystem.score_fundamental_quality(result, fundamental_data)
            ScoringSystem.score_quote_extra(result, quote_extra)
            ScoringSystem.cap_adjustments(result)
            ScoringSystem.detect_signal_conflict(result)
            
            RiskManager.calculate_stop_loss_and_take_profit(result, df)
            RiskManager.calculate_position(result, market_regime)
            ResonanceDetector.check_resonance(result)
            RiskManager.calculate_risk_reward(result, result.current_price)
            RiskManager.generate_detailed_advice(result)
            AnalysisFormatter.generate_beginner_summary(result)
            
            return result
            
        except Exception as e:
            logger.error(f"[{code}] 分析异常: {e}")
            return result
    
    def _analyze_volume(self, result: TrendAnalysisResult, df: pd.DataFrame, latest: pd.Series, prev: pd.Series):
        """量能分析"""
        vol_ma5 = df['volume'].iloc[-6:-1].mean()
        result.volume_ratio = float(latest['volume'] / vol_ma5) if vol_ma5 > 0 else 1.0
        if 'volume_ratio' in latest and latest['volume_ratio'] > 0:
            result.volume_ratio = float(latest['volume_ratio'])
        
        prev_close_price = float(prev['close'])
        price_change_pct = (result.current_price - prev_close_price) / prev_close_price * 100 if prev_close_price > 0 else 0
        vr = result.volume_ratio
        
        if vr >= self.VOLUME_HEAVY_RATIO:
            if price_change_pct > 0:
                result.volume_status = VolumeStatus.HEAVY_VOLUME_UP
                result.volume_trend = "放量上涨，多头力量强劲"
            else:
                result.volume_status = VolumeStatus.HEAVY_VOLUME_DOWN
                result.volume_trend = "放量下跌，注意风险"
        elif vr <= self.VOLUME_SHRINK_RATIO:
            if price_change_pct > 0:
                result.volume_status = VolumeStatus.SHRINK_VOLUME_UP
                result.volume_trend = "缩量上涨，上攻动能不足"
            else:
                result.volume_status = VolumeStatus.SHRINK_VOLUME_DOWN
                result.volume_trend = "缩量回调，洗盘特征明显"
        else:
            result.volume_status = VolumeStatus.NORMAL
            result.volume_trend = "量能正常"
    
    def _analyze_macd(self, result: TrendAnalysisResult, prev: pd.Series):
        """MACD分析"""
        dif, dea = result.macd_dif, result.macd_dea
        pdif, pdea = float(prev['MACD_DIF']), float(prev['MACD_DEA'])
        is_golden_cross = (pdif - pdea) <= 0 and (dif - dea) > 0
        is_death_cross = (pdif - pdea) >= 0 and (dif - dea) < 0
        is_crossing_up = pdif <= 0 and dif > 0
        is_crossing_down = pdif >= 0 and dif < 0
        
        if is_golden_cross and dif > 0:
            result.macd_status = MACDStatus.GOLDEN_CROSS_ZERO
            result.macd_signal = "零轴上金叉，强烈买入信号"
        elif is_crossing_up:
            result.macd_status = MACDStatus.CROSSING_UP
            result.macd_signal = "DIF上穿零轴，趋势转强"
        elif is_golden_cross:
            result.macd_status = MACDStatus.GOLDEN_CROSS
            result.macd_signal = "金叉，趋势向上"
        elif is_death_cross:
            result.macd_status = MACDStatus.DEATH_CROSS
            result.macd_signal = "死叉，趋势向下"
        elif is_crossing_down:
            result.macd_status = MACDStatus.CROSSING_DOWN
            result.macd_signal = "DIF下穿零轴，趋势转弱"
        elif dif > 0 and dea > 0:
            result.macd_status = MACDStatus.BULLISH
            result.macd_signal = "多头排列"
        elif dif < 0 and dea < 0:
            result.macd_status = MACDStatus.BEARISH
            result.macd_signal = "空头排列"
        else:
            result.macd_status = MACDStatus.NEUTRAL
            result.macd_signal = "MACD中性"
    
    def _analyze_rsi(self, result: TrendAnalysisResult, df: pd.DataFrame, prev: pd.Series):
        """RSI分析"""
        rsi_mid = result.rsi_12
        rsi_short = result.rsi_6
        prev_rsi6 = float(prev.get(f'RSI_{TechnicalIndicators.RSI_SHORT}', 50) or 50)
        prev_rsi12 = float(prev.get(f'RSI_{TechnicalIndicators.RSI_MID}', 50) or 50)
        is_rsi_golden = (prev_rsi6 <= prev_rsi12) and (rsi_short > rsi_mid)
        is_rsi_death = (prev_rsi6 >= prev_rsi12) and (rsi_short < rsi_mid)
        
        rsi_divergence = ""
        if len(df) >= 20:
            tail_20 = df.tail(20)
            tail_10 = df.tail(10)
            price_high_recent = float(tail_10['high'].max())
            price_high_prev = float(tail_20.head(10)['high'].max())
            rsi_high_recent = float(tail_10[f'RSI_{TechnicalIndicators.RSI_MID}'].max())
            rsi_high_prev = float(tail_20.head(10)[f'RSI_{TechnicalIndicators.RSI_MID}'].max())
            price_low_recent = float(tail_10['low'].min())
            price_low_prev = float(tail_20.head(10)['low'].min())
            rsi_low_recent = float(tail_10[f'RSI_{TechnicalIndicators.RSI_MID}'].min())
            rsi_low_prev = float(tail_20.head(10)[f'RSI_{TechnicalIndicators.RSI_MID}'].min())
            
            if price_high_recent > price_high_prev and rsi_high_recent < rsi_high_prev - 2:
                rsi_divergence = "顶背离"
            elif price_low_recent < price_low_prev and rsi_low_recent > rsi_low_prev + 2:
                rsi_divergence = "底背离"
        result.rsi_divergence = rsi_divergence
        
        if rsi_divergence == "底背离":
            result.rsi_status = RSIStatus.BULLISH_DIVERGENCE
            result.rsi_signal = f"RSI底背离(价格新低但RSI未新低)，反转买入信号"
        elif rsi_divergence == "顶背离":
            result.rsi_status = RSIStatus.BEARISH_DIVERGENCE
            result.rsi_signal = f"RSI顶背离(价格新高但RSI未新高)，回调风险"
        elif is_rsi_golden and rsi_mid < 30:
            result.rsi_status = RSIStatus.GOLDEN_CROSS_OVERSOLD
            result.rsi_signal = f"RSI超卖区金叉(RSI6={rsi_short:.1f}上穿RSI12={rsi_mid:.1f})，强买入"
        elif is_rsi_golden:
            result.rsi_status = RSIStatus.GOLDEN_CROSS
            result.rsi_signal = f"RSI金叉(RSI6={rsi_short:.1f}上穿RSI12={rsi_mid:.1f})，动能转强"
        elif is_rsi_death:
            result.rsi_status = RSIStatus.DEATH_CROSS
            result.rsi_signal = f"RSI死叉(RSI6={rsi_short:.1f}下穿RSI12={rsi_mid:.1f})，动能转弱"
        elif rsi_mid > 70:
            result.rsi_status = RSIStatus.OVERBOUGHT
            result.rsi_signal = f"RSI超买({rsi_mid:.1f}>70)，短期回调风险高"
        elif rsi_mid > 60:
            result.rsi_status = RSIStatus.STRONG_BUY
            result.rsi_signal = f"RSI强势({rsi_mid:.1f})，多头力量充足"
        elif rsi_mid >= 40:
            result.rsi_status = RSIStatus.NEUTRAL
            result.rsi_signal = f"RSI中性({rsi_mid:.1f})，震荡整理"
        elif rsi_mid >= 30:
            result.rsi_status = RSIStatus.WEAK
            result.rsi_signal = f"RSI弱势({rsi_mid:.1f})，关注反弹"
        else:
            result.rsi_status = RSIStatus.OVERSOLD
            result.rsi_signal = f"RSI超卖({rsi_mid:.1f}<30)，反弹机会大"
    
    def _analyze_kdj(self, result: TrendAnalysisResult, prev: pd.Series):
        """KDJ分析"""
        k_val, d_val, j_val = result.kdj_k, result.kdj_d, result.kdj_j
        pk_val, pd_val = float(prev.get('K', 50) or 50), float(prev.get('D', 50) or 50)
        is_kdj_golden = (pk_val <= pd_val) and (k_val > d_val)
        is_kdj_death = (pk_val >= pd_val) and (k_val < d_val)
        
        if is_kdj_golden and j_val < 20:
            result.kdj_status = KDJStatus.GOLDEN_CROSS_OVERSOLD
            result.kdj_signal = f"超卖区金叉(J={j_val:.1f}<20)，强买入信号"
        elif j_val > 100:
            result.kdj_status = KDJStatus.OVERBOUGHT
            result.kdj_signal = f"J值超买({j_val:.1f}>100)，短期回调风险"
        elif j_val < 0:
            result.kdj_status = KDJStatus.OVERSOLD
            result.kdj_signal = f"J值超卖({j_val:.1f}<0)，反弹机会"
        elif is_kdj_golden:
            result.kdj_status = KDJStatus.GOLDEN_CROSS
            result.kdj_signal = f"金叉(K={k_val:.1f}>D={d_val:.1f})，趋势向上"
        elif is_kdj_death:
            result.kdj_status = KDJStatus.DEATH_CROSS
            result.kdj_signal = f"死叉(K={k_val:.1f}<D={d_val:.1f})，趋势向下"
        elif k_val > d_val and j_val > 50:
            result.kdj_status = KDJStatus.BULLISH
            result.kdj_signal = f"多头排列(K={k_val:.1f}>D={d_val:.1f})，偏强"
        elif k_val < d_val and j_val < 50:
            result.kdj_status = KDJStatus.BEARISH
            result.kdj_signal = f"空头排列(K={k_val:.1f}<D={d_val:.1f})，偏弱"
        else:
            result.kdj_status = KDJStatus.NEUTRAL
            result.kdj_signal = f"KDJ中性(K={k_val:.1f} D={d_val:.1f} J={j_val:.1f})"
    
    def _analyze_trend(self, result: TrendAnalysisResult, df: pd.DataFrame, prev: pd.Series):
        """趋势分析"""
        ma5, ma10, ma20 = result.ma5, result.ma10, result.ma20
        
        if ma5 > ma10 > ma20:
            prev5 = df.iloc[-5] if len(df) >= 5 else prev
            prev_spread = (float(prev5['MA5']) - float(prev5['MA20'])) / float(prev5['MA20']) * 100 if float(prev5['MA20']) > 0 else 0
            curr_spread = (ma5 - ma20) / ma20 * 100 if ma20 > 0 else 0
            if curr_spread > prev_spread and curr_spread > 5:
                result.trend_status = TrendStatus.STRONG_BULL
                result.ma_alignment = "强势多头排列，均线发散上行"
                result.trend_strength = 90
            else:
                result.trend_status = TrendStatus.BULL
                result.ma_alignment = "多头排列 MA5>MA10>MA20"
                result.trend_strength = 75
        elif ma5 > ma10 and ma10 <= ma20:
            result.trend_status = TrendStatus.WEAK_BULL
            result.ma_alignment = "弱势多头，MA5>MA10 但 MA10<=MA20"
            result.trend_strength = 55
        elif ma5 < ma10 < ma20:
            prev5 = df.iloc[-5] if len(df) >= 5 else prev
            prev_spread = (float(prev5['MA20']) - float(prev5['MA5'])) / float(prev5['MA5']) * 100 if float(prev5['MA5']) > 0 else 0
            curr_spread = (ma20 - ma5) / ma5 * 100 if ma5 > 0 else 0
            if curr_spread > prev_spread and curr_spread > 5:
                result.trend_status = TrendStatus.STRONG_BEAR
                result.ma_alignment = "强势空头排列，均线发散下行"
                result.trend_strength = 10
            else:
                result.trend_status = TrendStatus.BEAR
                result.ma_alignment = "空头排列 MA5<MA10<MA20"
                result.trend_strength = 25
        elif ma5 < ma10 and ma10 >= ma20:
            result.trend_status = TrendStatus.WEAK_BEAR
            result.ma_alignment = "弱势空头，MA5<MA10 但 MA10>=MA20"
            result.trend_strength = 40
        else:
            result.trend_status = TrendStatus.CONSOLIDATION
            result.ma_alignment = "均线缠绕，趋势不明"
            result.trend_strength = 50
    
    def _calculate_bias(self, result: TrendAnalysisResult):
        """计算乖离率"""
        result.bias_ma5 = (result.current_price - result.ma5) / result.ma5 * 100 if result.ma5 > 0 else 0
        result.bias_ma10 = (result.current_price - result.ma10) / result.ma10 * 100 if result.ma10 > 0 else 0
        result.bias_ma20 = (result.current_price - result.ma20) / result.ma20 * 100 if result.ma20 > 0 else 0
    
    def format_analysis(self, result: TrendAnalysisResult) -> str:
        """格式化分析结果（完整版）"""
        return AnalysisFormatter.format_analysis(result)
    
    def format_for_llm(self, result: TrendAnalysisResult) -> str:
        """格式化分析结果（精简版，供LLM使用）"""
        return AnalysisFormatter.format_for_llm(result)
