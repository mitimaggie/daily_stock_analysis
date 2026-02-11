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
    
    @staticmethod
    def detect_market_regime(df: pd.DataFrame, index_change_pct: float = 0.0, 
                            volume_data: pd.Series = None) -> tuple:
        """
        增强版市场环境检测：多维度判断 + 强度量化
        
        判断维度：
        1. MA趋势：MA5/MA10/MA20/MA60排列 + MA20斜率
        2. 大盘环境：近20日涨跌幅 + 当日方向
        3. 量能特征：放量/缩量趋势
        4. 波动率：近20日波动率（高波动=震荡/熊市）
        5. 平滑机制：连续3天方向一致才切换
        
        Returns:
            (MarketRegime, 环境强度 0-100)
        """
        SMOOTH_DAYS = 3
        SLOPE_THRESHOLD = 1.0
        
        if df is None or df.empty or len(df) < 30:
            return MarketRegime.SIDEWAYS, 50
        
        try:
            ma5 = df['close'].rolling(5).mean()
            ma10 = df['close'].rolling(10).mean()
            ma20 = df['close'].rolling(20).mean()
            ma60 = df['close'].rolling(60).mean()
            
            if len(ma20) < 15:
                return MarketRegime.SIDEWAYS, 50
            
            latest_ma5 = ma5.iloc[-1]
            latest_ma10 = ma10.iloc[-1]
            latest_ma20 = ma20.iloc[-1]
            latest_ma60 = ma60.iloc[-1] if len(ma60) >= 60 else latest_ma20
            
            ma_bull_score = 0
            if latest_ma5 > latest_ma10 > latest_ma20:
                ma_bull_score += 3
            elif latest_ma5 < latest_ma10 < latest_ma20:
                ma_bull_score -= 3
            if latest_ma10 > latest_ma20 > latest_ma60:
                ma_bull_score += 2
            elif latest_ma10 < latest_ma20 < latest_ma60:
                ma_bull_score -= 2
            
            bull_count = 0
            bear_count = 0
            for offset in range(SMOOTH_DAYS):
                idx = -(1 + offset)
                idx_10 = -(11 + offset)
                if abs(idx_10) > len(ma20):
                    break
                now_val = ma20.iloc[idx]
                ago_val = ma20.iloc[idx_10]
                if now_val <= 0 or ago_val <= 0:
                    break
                slope = (now_val - ago_val) / ago_val * 100
                if slope > SLOPE_THRESHOLD:
                    bull_count += 1
                elif slope < -SLOPE_THRESHOLD:
                    bear_count += 1
            
            ma_slope_score = 0
            if bull_count >= SMOOTH_DAYS:
                ma_slope_score = 3
            elif bear_count >= SMOOTH_DAYS:
                ma_slope_score = -3
            
            index_score = 0
            if index_change_pct > 1.0:
                index_score = 2
            elif index_change_pct > 0:
                index_score = 1
            elif index_change_pct < -1.0:
                index_score = -2
            elif index_change_pct < 0:
                index_score = -1
            
            volume_score = 0
            if volume_data is not None and len(volume_data) >= 20:
                recent_vol = volume_data.tail(5).mean()
                avg_vol = volume_data.tail(20).mean()
                if avg_vol > 0:
                    vol_ratio = recent_vol / avg_vol
                    if vol_ratio > 1.3:
                        volume_score = 1
                    elif vol_ratio < 0.7:
                        volume_score = -1
            
            volatility_score = 0
            if len(df) >= 20:
                recent_20 = df.tail(20)
                high_20 = recent_20['high'].max()
                low_20 = recent_20['low'].min()
                volatility = (high_20 - low_20) / low_20 * 100 if low_20 > 0 else 0
                if volatility > 30:
                    volatility_score = -2
                elif volatility < 15:
                    volatility_score = 1
            
            total_score = ma_bull_score + ma_slope_score + index_score + volume_score + volatility_score
            
            if total_score >= 5:
                regime = MarketRegime.BULL
                strength = min(100, 50 + total_score * 5)
            elif total_score <= -5:
                regime = MarketRegime.BEAR
                strength = max(0, 50 + total_score * 5)
            else:
                regime = MarketRegime.SIDEWAYS
                strength = 50 + total_score * 3
            
            return regime, int(strength)
            
        except Exception:
            return MarketRegime.SIDEWAYS, 50
    
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
                    # 优先使用120日窗口（学术标准），不足时降级到60日
                    lookback = 120 if len(df) >= 120 else 60
                    stock_ret = df['close'].pct_change().dropna().tail(lookback)
                    idx_ret = index_returns.tail(lookback)
                    min_len = min(len(stock_ret), len(idx_ret))
                    if min_len >= 30:
                        s = stock_ret.values[-min_len:]
                        m = idx_ret.values[-min_len:]
                        cov = np.cov(s, m)[0][1]
                        var = np.var(m)
                        if var > 0:
                            result.beta_vs_index = round(cov / var, 2)
                except Exception:
                    pass
            
            # === 新增指标计算 ===
            # 涨跌停检测（A股特有）
            df = TechnicalIndicators.detect_limit(df, code=code)
            result.is_limit_up = bool(df.iloc[-1].get('limit_up', False))
            result.is_limit_down = bool(df.iloc[-1].get('limit_down', False))
            result.limit_pct = float(df.iloc[-1].get('limit_pct', 10.0))
            # 连板检测
            if result.is_limit_up or result.is_limit_down:
                col = 'limit_up' if result.is_limit_up else 'limit_down'
                count = 0
                for i in range(len(df) - 1, -1, -1):
                    if df.iloc[i][col]:
                        count += 1
                    else:
                        break
                result.consecutive_limits = count

            # VWAP
            df = TechnicalIndicators.calc_vwap(df)
            result.vwap = round(float(df.iloc[-1].get('VWAP', 0) or 0), 2)
            result.vwap_bias = round(float(df.iloc[-1].get('VWAP_bias', 0) or 0), 2)

            # 量价背离
            result.volume_price_divergence = TechnicalIndicators.detect_volume_price_divergence(df)

            # 缺口检测
            result.gap_type = TechnicalIndicators.detect_gap(df)

            # 换手率分位数（需要 quote_extra 中的 turnover_rate）
            turnover = (quote_extra or {}).get('turnover_rate', 0) or 0
            if turnover > 0:
                result.turnover_percentile = TechnicalIndicators.calc_turnover_percentile(df, turnover)

            self._analyze_volume(result, df, latest, prev)
            self._analyze_macd(result, prev)
            self._analyze_rsi(result, df, prev)
            self._analyze_kdj(result, df, prev)
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
            ScoringSystem.score_limit_and_enhanced(result)
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
        """量能分析（含涨跌停特殊处理 + z-score自适应阈值）"""
        if 'volume_ratio' in latest and not pd.isna(latest['volume_ratio']) and latest['volume_ratio'] > 0:
            result.volume_ratio = float(latest['volume_ratio'])
        else:
            vol_ma5 = df['volume'].iloc[-6:-1].mean()
            result.volume_ratio = float(latest['volume'] / vol_ma5) if vol_ma5 > 0 else 1.0
        
        # z-score 自适应阈值：根据统计显著性动态调整放量/缩量判定
        heavy_ratio = self.VOLUME_HEAVY_RATIO
        shrink_ratio = self.VOLUME_SHRINK_RATIO
        if len(df) >= 20:
            vol_20 = df['volume'].tail(20)
            vol_mean = vol_20.mean()
            vol_std = vol_20.std()
            if vol_std > 0 and vol_mean > 0:
                vol_zscore = (float(latest['volume']) - vol_mean) / vol_std
                # z > 2.0 → 统计显著放量，降低放量阈值使其更容易触发
                if vol_zscore > 2.0:
                    heavy_ratio = min(heavy_ratio, result.volume_ratio * 0.95)
                # z < -1.5 → 统计显著缩量，提高缩量阈值使其更容易触发
                elif vol_zscore < -1.5:
                    shrink_ratio = max(shrink_ratio, result.volume_ratio * 1.05)
        
        prev_close_price = float(prev['close'])
        price_change_pct = (result.current_price - prev_close_price) / prev_close_price * 100 if prev_close_price > 0 else 0
        vr = result.volume_ratio

        # === 涨跌停特殊处理（A股特有）===
        # 涨停板：缩量封板是正常的（买盘无法成交），不应判为"缩量上涨动能不足"
        # 跌停板：缩量跌停说明恐慌抛售无人接盘，放量跌停说明有资金抄底
        if result.is_limit_up:
            if vr <= shrink_ratio:
                result.volume_status = VolumeStatus.SHRINK_VOLUME_UP
                result.volume_trend = "缩量涨停封板，筹码锁定良好"
            else:
                result.volume_status = VolumeStatus.HEAVY_VOLUME_UP
                result.volume_trend = "放量涨停，多空分歧较大"
                if result.consecutive_limits >= 2:
                    result.volume_trend += f"（连续{result.consecutive_limits}板）"
            return
        
        if result.is_limit_down:
            if vr >= heavy_ratio:
                result.volume_status = VolumeStatus.HEAVY_VOLUME_DOWN
                result.volume_trend = "放量跌停，有资金承接但抛压沉重"
            else:
                result.volume_status = VolumeStatus.SHRINK_VOLUME_DOWN
                result.volume_trend = "缩量跌停，恐慌情绪蔓延，无人接盘"
            return

        # === 常规量能分析（使用z-score自适应阈值）===
        if vr >= heavy_ratio:
            if price_change_pct > 0:
                result.volume_status = VolumeStatus.HEAVY_VOLUME_UP
                result.volume_trend = "放量上涨，多头力量强劲"
            else:
                result.volume_status = VolumeStatus.HEAVY_VOLUME_DOWN
                result.volume_trend = "放量下跌，注意风险"
        elif vr <= shrink_ratio:
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
        if len(df) >= 30:
            tail_30 = df.tail(30)
            half = 15
            first_half = tail_30.head(half)
            second_half = tail_30.tail(half)
            rsi_col = f'RSI_{TechnicalIndicators.RSI_MID}'
            
            price_high_prev = float(first_half['high'].max())
            price_high_recent = float(second_half['high'].max())
            rsi_high_prev = float(first_half[rsi_col].max())
            rsi_high_recent = float(second_half[rsi_col].max())
            
            price_low_prev = float(first_half['low'].min())
            price_low_recent = float(second_half['low'].min())
            rsi_low_prev = float(first_half[rsi_col].min())
            rsi_low_recent = float(second_half[rsi_col].min())
            
            # 顶背离：价格新高(>1%) + RSI未新高(差>3)
            if (price_high_recent > price_high_prev * 1.01 and 
                rsi_high_recent < rsi_high_prev - 3):
                rsi_divergence = "顶背离"
            # 底背离：价格新低(>1%) + RSI未新低(差>3)
            elif (price_low_recent < price_low_prev * 0.99 and 
                  rsi_low_recent > rsi_low_prev + 3):
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
    
    def _analyze_kdj(self, result: TrendAnalysisResult, df: pd.DataFrame, prev: pd.Series):
        """KDJ分析（含背离检测、连续极端、钝化识别）"""
        k_val, d_val, j_val = result.kdj_k, result.kdj_d, result.kdj_j
        pk_val, pd_val = float(prev.get('K', 50) or 50), float(prev.get('D', 50) or 50)
        is_kdj_golden = (pk_val <= pd_val) and (k_val > d_val)
        is_kdj_death = (pk_val >= pd_val) and (k_val < d_val)
        
        # === KDJ 背离检测 ===
        result.kdj_divergence = TechnicalIndicators.detect_kdj_divergence(df)
        
        # === J 值连续极端检测 ===
        result.kdj_consecutive_extreme = TechnicalIndicators.detect_kdj_consecutive_extreme(df)
        
        # === KDJ 钝化识别（需要趋势强度，先用临时值，_analyze_trend 后会更新）===
        result.kdj_passivation = TechnicalIndicators.detect_kdj_passivation(df, result.trend_strength)
        
        # === KDJ 背离优先级最高 ===
        if result.kdj_divergence == "KDJ底背离":
            result.kdj_status = KDJStatus.GOLDEN_CROSS_OVERSOLD
            result.kdj_signal = f"KDJ底背离(价格新低但J值未新低)，反转买入信号"
        elif result.kdj_divergence == "KDJ顶背离":
            result.kdj_status = KDJStatus.OVERBOUGHT
            result.kdj_signal = f"KDJ顶背离(价格新高但J值未新高)，见顶风险"
        # === 连续极端信号 ===
        elif result.kdj_consecutive_extreme:
            if "超买" in result.kdj_consecutive_extreme:
                result.kdj_status = KDJStatus.OVERBOUGHT
                result.kdj_signal = f"{result.kdj_consecutive_extreme}，短期严重超买，回调概率极高"
            else:
                result.kdj_status = KDJStatus.OVERSOLD
                result.kdj_signal = f"{result.kdj_consecutive_extreme}，短期严重超卖，反弹概率极高"
        # === 钝化状态：降低超买/超卖信号权重 ===
        elif result.kdj_passivation:
            if j_val > 100 or k_val > 80:
                result.kdj_status = KDJStatus.BULLISH
                result.kdj_signal = f"KDJ钝化(强趋势中持续超买K={k_val:.1f})，超买信号不可靠，趋势可能延续"
            elif j_val < 0 or k_val < 20:
                result.kdj_status = KDJStatus.BEARISH
                result.kdj_signal = f"KDJ钝化(弱趋势中持续超卖K={k_val:.1f})，超卖信号不可靠，下跌可能延续"
            elif is_kdj_golden:
                result.kdj_status = KDJStatus.GOLDEN_CROSS
                result.kdj_signal = f"金叉(K={k_val:.1f}>D={d_val:.1f})，但KDJ钝化中，信号需确认"
            elif is_kdj_death:
                result.kdj_status = KDJStatus.DEATH_CROSS
                result.kdj_signal = f"死叉(K={k_val:.1f}<D={d_val:.1f})，但KDJ钝化中，信号需确认"
            else:
                result.kdj_status = KDJStatus.NEUTRAL
                result.kdj_signal = f"KDJ钝化中(K={k_val:.1f} D={d_val:.1f} J={j_val:.1f})，信号可靠性降低"
        # === 常规 KDJ 分析 ===
        elif is_kdj_golden and j_val < 20:
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
    
    def format_enhanced(self, result: TrendAnalysisResult) -> str:
        """格式化分析结果（增强版：更易读、更便于决策）"""
        return AnalysisFormatter.format_enhanced(result)
    
    def format_for_llm(self, result: TrendAnalysisResult) -> str:
        """格式化分析结果（精简版，供LLM使用）"""
        return AnalysisFormatter.format_for_llm(result)
