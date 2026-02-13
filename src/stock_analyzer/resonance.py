# -*- coding: utf-8 -*-
"""
共振检测模块
包含指标组合共振、市场行为识别、多时间周期共振等检测逻辑
"""

import logging
import pandas as pd
from typing import List
from .types import TrendAnalysisResult, TrendStatus
from .types import MACDStatus, KDJStatus, RSIStatus, VolumeStatus
logger = logging.getLogger(__name__)


class ResonanceDetector:
    """共振检测器：多指标共振、市场行为识别、多周期共振"""
    
    # Q4: 不同指标的信号有效期（天数）和衰减曲线
    # KDJ金叉有效期短（2-3天），MACD金叉有效期长（5-7天）
    SIGNAL_EFFECTIVE_DAYS = {
        'KDJ': 3,    # KDJ信号有效期短
        'MACD': 5,   # MACD信号有效期较长
        'RSI': 4,    # RSI信号中等
    }

    @staticmethod
    def _calc_signal_decay(df: pd.DataFrame, col1: str, col2: str, cross_type: str = 'golden',
                           indicator: str = 'MACD') -> float:
        """
        计算交叉信号的时间衰减权重（Q4增强：指标自适应+波动率调整）
        
        Args:
            df: K线数据
            col1, col2: 交叉的两个指标列名
            cross_type: 'golden'(上穿) 或 'death'(下穿)
            indicator: 指标类型 ('MACD'/'KDJ'/'RSI')，决定有效期
            
        Returns:
            衰减权重 (1.0=今天发生, 递减至0.0)
        """
        if df is None or len(df) < 3:
            return 1.0
        
        # Q4: 根据指标类型确定搜索窗口和衰减曲线
        effective_days = ResonanceDetector.SIGNAL_EFFECTIVE_DAYS.get(indicator, 5)
        
        # Q4: 波动率自适应 - 高波动环境下信号衰减更快
        vol_factor = 1.0
        if len(df) >= 20:
            try:
                daily_ret = df['close'].pct_change().dropna().tail(20)
                vol_20d = float(daily_ret.std() * (252 ** 0.5) * 100)
                if vol_20d > 60:
                    vol_factor = 0.7  # 高波动：有效期缩短30%
                elif vol_20d < 20:
                    vol_factor = 1.3  # 低波动：有效期延长30%
            except Exception:
                pass
        
        adjusted_days = max(2, int(effective_days * vol_factor))
        search_range = min(adjusted_days, len(df) - 1)
        
        try:
            for offset in range(search_range):
                idx = -(1 + offset)
                prev_idx = -(2 + offset)
                if abs(prev_idx) > len(df):
                    break
                c1_now = float(df[col1].iloc[idx])
                c2_now = float(df[col2].iloc[idx])
                c1_prev = float(df[col1].iloc[prev_idx])
                c2_prev = float(df[col2].iloc[prev_idx])
                
                is_cross = False
                if cross_type == 'golden':
                    is_cross = c1_prev <= c2_prev and c1_now > c2_now
                else:
                    is_cross = c1_prev >= c2_prev and c1_now < c2_now
                
                if is_cross:
                    # 线性衰减：第0天=1.0，第N天=0.0
                    decay = max(0.0, 1.0 - offset / adjusted_days)
                    return round(decay, 2)
            return 0.2  # 搜索窗口内未找到交叉，信号已过时，给予最低权重
        except Exception:
            return 0.5

    @staticmethod
    def detect_indicator_resonance(result: TrendAnalysisResult, df: pd.DataFrame, prev: pd.Series):
        """
        指标组合共振判断：识别关键买卖信号（含信号时间衰减）
        
        组合逻辑：
        1. MACD水下金叉 + KDJ金叉 + 缩量：底部吸筹信号 ★★★★★
        2. MACD零轴上金叉 + KDJ金叉 + 放量上涨：主升浪启动 ★★★★★
        3. MACD金叉 + RSI底背离：反转信号 ★★★★
        4. MACD死叉 + KDJ死叉 + 放量下跌：恐慌抛售 ☆☆☆☆☆
        5. MACD死叉 + RSI顶背离：顶部信号 ☆☆☆☆
        6. 放量上涨 + KDJ超买 + MACD高位：诱多嫌疑 ☆☆☆
        7. 缩量下跌 + KDJ超卖 + MACD低位：洗盘特征 ★★★
        
        信号衰减：金叉/死叉发生在今天权重1.0，昨天0.7，前天0.4
        """
        resonance_signals = []
        resonance_score_adj = 0
        
        macd_status = result.macd_status
        kdj_status = result.kdj_status
        rsi_status = result.rsi_status
        vol_status = result.volume_status
        
        dif, dea = result.macd_dif, result.macd_dea
        j_val = result.kdj_j
        
        # 计算 MACD 和 KDJ 交叉信号的衰减权重
        macd_golden_decay = ResonanceDetector._calc_signal_decay(df, 'MACD_DIF', 'MACD_DEA', 'golden', indicator='MACD')
        macd_death_decay = ResonanceDetector._calc_signal_decay(df, 'MACD_DIF', 'MACD_DEA', 'death', indicator='MACD')
        kdj_golden_decay = ResonanceDetector._calc_signal_decay(df, 'K', 'D', 'golden', indicator='KDJ')
        
        if (macd_status == MACDStatus.GOLDEN_CROSS and dif < 0 and dea < 0 and 
            kdj_status in [KDJStatus.GOLDEN_CROSS, KDJStatus.GOLDEN_CROSS_OVERSOLD] and
            vol_status in [VolumeStatus.SHRINK_VOLUME_UP, VolumeStatus.NORMAL]):
            decay = min(macd_golden_decay, kdj_golden_decay)
            adj = int(10 * decay)
            resonance_signals.append(f"★★★★★ 底部吸筹信号：MACD水下金叉+KDJ金叉+缩量，主力建仓阶段{f'(衰减{decay:.1f})' if decay < 1.0 else ''}")
            resonance_score_adj += adj
        
        elif (macd_status == MACDStatus.GOLDEN_CROSS_ZERO and 
              kdj_status in [KDJStatus.GOLDEN_CROSS, KDJStatus.BULLISH] and
              vol_status == VolumeStatus.HEAVY_VOLUME_UP):
            decay = macd_golden_decay
            adj = int(12 * decay)
            resonance_signals.append(f"★★★★★ 主升浪启动：MACD零轴上金叉+KDJ金叉+放量突破，趋势行情{f'(衰减{decay:.1f})' if decay < 1.0 else ''}")
            resonance_score_adj += adj
        
        elif (macd_status in [MACDStatus.GOLDEN_CROSS, MACDStatus.GOLDEN_CROSS_ZERO] and
              rsi_status == RSIStatus.BULLISH_DIVERGENCE):
            decay = macd_golden_decay
            adj = int(8 * decay)
            resonance_signals.append(f"★★★★ 反转信号：MACD金叉+RSI底背离，跌不动了{f'(衰减{decay:.1f})' if decay < 1.0 else ''}")
            resonance_score_adj += adj
        
        if (macd_status == MACDStatus.DEATH_CROSS and
            kdj_status == KDJStatus.DEATH_CROSS and
            vol_status == VolumeStatus.HEAVY_VOLUME_DOWN):
            decay = macd_death_decay
            adj = int(-15 * decay)
            resonance_signals.append(f"☆☆☆☆☆ 恐慌抛售：MACD+KDJ双死叉+放量下跌，赶紧离场{f'(衰减{decay:.1f})' if decay < 1.0 else ''}")
            resonance_score_adj += adj
        
        elif (macd_status == MACDStatus.DEATH_CROSS and
              rsi_status == RSIStatus.BEARISH_DIVERGENCE):
            decay = macd_death_decay
            adj = int(-10 * decay)
            resonance_signals.append(f"☆☆☆☆ 顶部信号：MACD死叉+RSI顶背离，涨不上去了{f'(衰减{decay:.1f})' if decay < 1.0 else ''}")
            resonance_score_adj += adj
        
        if (vol_status == VolumeStatus.HEAVY_VOLUME_UP and
            kdj_status == KDJStatus.OVERBOUGHT and
            dif > 0 and dif > dea and result.trend_strength < 70):
            resonance_signals.append("☆☆☆ 诱多嫌疑：高位放量+KDJ超买，小心接盘")
            resonance_score_adj -= 5
        
        if (vol_status == VolumeStatus.SHRINK_VOLUME_DOWN and
            kdj_status in [KDJStatus.OVERSOLD, KDJStatus.GOLDEN_CROSS_OVERSOLD] and
            dif < 0 and result.trend_strength > 60):
            resonance_signals.append("★★★ 洗盘特征：缩量回调+KDJ超卖，不破MA20可接")
            resonance_score_adj += 5
        
        if resonance_signals:
            result.indicator_resonance = "\n".join(resonance_signals)
            result.score_breakdown['resonance_adj'] = resonance_score_adj
        else:
            result.indicator_resonance = ""
    
    @staticmethod
    def detect_market_behavior(result: TrendAnalysisResult, df: pd.DataFrame):
        """
        市场行为识别：诱多/诱空/吸筹/洗盘/拉升/出货
        
        识别逻辑：
        1. 诱多：高位大阳线+巨量+次日低开低走
        2. 诱空：低位大阴线+巨量+次日高开高走
        3. 吸筹：低位缩量震荡+MACD水下+慢慢探底
        4. 洗盘：中位缩量回调+不破关键均线+KDJ超卖后反弹
        5. 拉升：持续放量上涨+重心上移+均线多头发散
        6. 出货：高位震荡+量价背离+MACD顶背离
        """
        if df is None or len(df) < 10:
            result.market_behavior = ""
            return
        
        behavior_signals = []
        
        latest = df.iloc[-1]
        prev = df.iloc[-2] if len(df) >= 2 else latest
        recent_5 = df.tail(5)
        recent_10 = df.tail(10)
        
        close = float(latest['close'])
        open_price = float(latest['open'])
        high = float(latest['high'])
        low = float(latest['low'])
        volume = float(latest['volume'])
        
        body_size = abs(close - open_price) / open_price * 100 if open_price > 0 else 0
        is_big_candle = body_size > 5
        is_yang = close > open_price
        
        vol_ratio = result.volume_ratio
        
        if len(df) >= 60:
            high_60 = float(df['high'].tail(60).max())
            low_60 = float(df['low'].tail(60).min())
            price_position = (close - low_60) / (high_60 - low_60) * 100 if high_60 > low_60 else 50
        else:
            price_position = 50
        
        if (price_position > 70 and is_big_candle and is_yang and vol_ratio > 2.5 and
            result.kdj_status == KDJStatus.OVERBOUGHT and
            result.rsi_status in [RSIStatus.OVERBOUGHT, RSIStatus.BEARISH_DIVERGENCE]):
            behavior_signals.append("🚨 诱多嫌疑：高位巨量长阳+KDJ/RSI超买，谨防接盘")
        
        elif (price_position < 30 and is_big_candle and not is_yang and vol_ratio > 2.5 and
              result.kdj_status == KDJStatus.OVERSOLD and
              result.rsi_status in [RSIStatus.OVERSOLD, RSIStatus.BULLISH_DIVERGENCE]):
            behavior_signals.append("🔥 诱空嫌疑：低位巨量长阴+KDJ/RSI超卖，反弹在即")
        
        if (price_position < 40 and 
            result.macd_status in [MACDStatus.BEARISH, MACDStatus.NEUTRAL] and
            result.macd_dif < 0 and
            vol_ratio < 1.2 and
            len(recent_10) >= 10):
            recent_volatility = (recent_10['high'].max() - recent_10['low'].min()) / recent_10['low'].min() * 100
            if recent_volatility < 15:
                behavior_signals.append("🧠 疑似吸筹：低位缩量震荡+MACD水下，主力慢慢建仓")
        
        if (40 <= price_position <= 70 and
            result.volume_status in [VolumeStatus.SHRINK_VOLUME_DOWN, VolumeStatus.SHRINK_VOLUME_UP] and
            result.kdj_status in [KDJStatus.OVERSOLD, KDJStatus.GOLDEN_CROSS_OVERSOLD] and
            result.current_price > result.ma20 and
            result.trend_strength >= 65):
            behavior_signals.append("🌀 洗盘特征：缩量回调+不破MA20+KDJ超卖，上车机会")
        
        if (result.trend_status in [TrendStatus.STRONG_BULL, TrendStatus.BULL] and
            len(recent_5) >= 5):
            up_days = sum(1 for i in range(len(recent_5)) if recent_5.iloc[i]['close'] > recent_5.iloc[i]['open'])
            avg_vol_ratio = recent_5['volume'].mean() / df['volume'].tail(20).mean() if len(df) >= 20 else 1.0
            if up_days >= 4 and avg_vol_ratio > 1.3:
                behavior_signals.append("🚀 拉升阶段：持续放量上涨+均线多头，跟着主力吃肉")
        
        if (price_position > 75 and
            result.rsi_status in [RSIStatus.BEARISH_DIVERGENCE, RSIStatus.OVERBOUGHT] and
            result.macd_status in [MACDStatus.DEATH_CROSS, MACDStatus.CROSSING_DOWN] and
            len(recent_5) >= 5):
            price_high_recent = recent_5['high'].max()
            price_high_prev = df.tail(10).head(5)['high'].max() if len(df) >= 10 else 0
            vol_recent = recent_5['volume'].mean()
            vol_prev = df.tail(10).head(5)['volume'].mean() if len(df) >= 10 else vol_recent
            if price_high_recent > price_high_prev and vol_recent < vol_prev * 0.8:
                behavior_signals.append("⚠️ 出货嫌疑：高位震荡+量价背离+指标顶背离，先走为妙")
        
        result.market_behavior = "\n".join(behavior_signals) if behavior_signals else ""
    
    @staticmethod
    def check_multi_timeframe_resonance(result: TrendAnalysisResult, df: pd.DataFrame):
        """
        多时间周期共振验证：日线 + 周线共振
        
        逻辑：
        1. 将日线数据 resample 为周线
        2. 计算周线的 MACD、KDJ、MA趋势
        3. 判断日线和周线是否同向
        4. 共振加分，背离减分
        
        共振级别：
        - 强共振：日线+周线同时金叉/死叉 +5分
        - 中共振：日线+周线趋势一致 +3分
        - 背离：日线多头但周线空头 -5分
        """
        if df is None or len(df) < 60:
            result.timeframe_resonance = ""
            return
        
        try:
            from .indicators import TechnicalIndicators
            weekly_df = TechnicalIndicators.resample_to_weekly(df)
            if weekly_df is None or len(weekly_df) < 5:
                result.timeframe_resonance = ""
                return
            
            w_latest = weekly_df.iloc[-1]
            w_prev = weekly_df.iloc[-2]
            
            w_macd_dif = float(w_latest.get('MACD_DIF', 0))
            w_macd_dea = float(w_latest.get('MACD_DEA', 0))
            w_prev_dif = float(w_prev.get('MACD_DIF', 0))
            w_prev_dea = float(w_prev.get('MACD_DEA', 0))
            
            w_is_golden = (w_prev_dif <= w_prev_dea) and (w_macd_dif > w_macd_dea)
            w_is_death = (w_prev_dif >= w_prev_dea) and (w_macd_dif < w_macd_dea)
            
            w_ma5 = float(w_latest.get('MA5', 0))
            w_ma10 = float(w_latest.get('MA10', 0))
            w_ma20 = float(w_latest.get('MA20', 0))
            w_trend_bullish = w_ma5 > w_ma10 > w_ma20
            w_trend_bearish = w_ma5 < w_ma10 < w_ma20
            
            d_is_golden = result.macd_status in [MACDStatus.GOLDEN_CROSS, MACDStatus.GOLDEN_CROSS_ZERO]
            d_is_death = result.macd_status == MACDStatus.DEATH_CROSS
            d_trend_bullish = result.trend_status in [TrendStatus.STRONG_BULL, TrendStatus.BULL]
            d_trend_bearish = result.trend_status in [TrendStatus.STRONG_BEAR, TrendStatus.BEAR]
            
            resonance_adj = 0
            resonance_msg = []
            
            if d_is_golden and w_is_golden:
                resonance_adj = 5
                resonance_msg.append("✅ 强共振：日线+周线同时金叉，趋势强劲")
            elif d_is_death and w_is_death:
                resonance_adj = -5
                resonance_msg.append("❌ 强背离：日线+周线同时死叉，趋势转弱")
            elif d_trend_bullish and w_trend_bullish:
                resonance_adj = 3
                resonance_msg.append("✅ 中共振：日线+周线趋势一致向上")
            elif d_trend_bearish and w_trend_bearish:
                resonance_adj = -3
                resonance_msg.append("❌ 中背离：日线+周线趋势一致向下")
            elif d_trend_bullish and w_trend_bearish:
                resonance_adj = -5
                resonance_msg.append("⚠️ 周期背离：日线多头但周线空头，警惕反转")
            elif d_trend_bearish and w_trend_bullish:
                resonance_adj = 2
                resonance_msg.append("✅ 回调机会：日线回调但周线多头，逢低买入")
            
            if resonance_msg:
                result.timeframe_resonance = "\n".join(resonance_msg)
                if resonance_adj != 0:
                    result.score_breakdown['timeframe_resonance'] = resonance_adj
            else:
                result.timeframe_resonance = ""
        
        except Exception as e:
            logger.debug(f"多周期共振计算失败: {e}")
            result.timeframe_resonance = ""
    
    @staticmethod
    def check_resonance(result: TrendAnalysisResult):
        """多指标共振检测：MACD/KDJ/RSI/量价/趋势同向信号
        
        注意：此方法只做信号统计和标记，不重复加分。
        加分已在 detect_indicator_resonance() 中完成，此处仅补充
        detect_indicator_resonance 未覆盖的「弱共振」场景（>=3个同向但非经典组合）。
        """
        bullish_resonance = []
        bearish_resonance = []
        
        if result.trend_status in [TrendStatus.STRONG_BULL, TrendStatus.BULL]:
            bullish_resonance.append("趋势多头")
        elif result.trend_status in [TrendStatus.STRONG_BEAR, TrendStatus.BEAR]:
            bearish_resonance.append("趋势空头")
        
        if result.macd_status in [MACDStatus.GOLDEN_CROSS_ZERO, MACDStatus.GOLDEN_CROSS, MACDStatus.BULLISH]:
            bullish_resonance.append("MACD多头")
        elif result.macd_status in [MACDStatus.DEATH_CROSS, MACDStatus.BEARISH]:
            bearish_resonance.append("MACD空头")
        
        if result.kdj_status in [KDJStatus.GOLDEN_CROSS_OVERSOLD, KDJStatus.GOLDEN_CROSS, KDJStatus.BULLISH]:
            bullish_resonance.append("KDJ多头")
        elif result.kdj_status in [KDJStatus.DEATH_CROSS, KDJStatus.BEARISH]:
            bearish_resonance.append("KDJ空头")
        
        if result.rsi_status in [RSIStatus.GOLDEN_CROSS_OVERSOLD, RSIStatus.GOLDEN_CROSS, 
                                 RSIStatus.STRONG_BUY, RSIStatus.BULLISH_DIVERGENCE]:
            bullish_resonance.append("RSI强势")
        elif result.rsi_status in [RSIStatus.DEATH_CROSS, RSIStatus.WEAK, RSIStatus.BEARISH_DIVERGENCE]:
            bearish_resonance.append("RSI弱势")
        
        if result.volume_status in [VolumeStatus.HEAVY_VOLUME_UP, VolumeStatus.SHRINK_VOLUME_DOWN]:
            bullish_resonance.append("量价配合")
        elif result.volume_status == VolumeStatus.HEAVY_VOLUME_DOWN:
            bearish_resonance.append("放量下跌")
        
        result.resonance_count = len(bullish_resonance) if len(bullish_resonance) >= 3 else -len(bearish_resonance) if len(bearish_resonance) >= 3 else 0
        
        # 只在 detect_indicator_resonance 未产生加分时，才由此方法补充加分
        already_scored = result.score_breakdown.get('resonance_adj', 0) != 0
        
        if len(bullish_resonance) >= 3:
            result.resonance_signals = bullish_resonance
            if not already_scored:
                bonus = min(8, len(bullish_resonance) * 2)
                result.resonance_bonus = bonus
                result.score_breakdown['cross_resonance'] = bonus
            else:
                result.resonance_bonus = 0
        elif len(bearish_resonance) >= 3:
            result.resonance_signals = bearish_resonance
            if not already_scored:
                penalty = -min(8, len(bearish_resonance) * 2)
                result.resonance_bonus = penalty
                result.score_breakdown['cross_resonance'] = penalty
            else:
                result.resonance_bonus = 0
        else:
            result.resonance_signals = []
            result.resonance_bonus = 0
