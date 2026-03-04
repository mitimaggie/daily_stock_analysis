# -*- coding: utf-8 -*-
"""
K线走势叙事生成器

将量化分析结果（TrendAnalysisResult）+ 原始K线DataFrame
转化为人类可读的"盘面叙事"，等效于AI看K线图后的文字描述。

设计原则：
- 只引用 TrendAnalysisResult 和 daily_df 的真实字段
- 生成的文字应类似"交易员旁白"，而非量化指标罗列
"""

import logging
from typing import Optional

import pandas as pd

from .types import TrendAnalysisResult, TrendStatus, MACDStatus, VolumeStatus

logger = logging.getLogger(__name__)


class KlineNarrator:
    """从量化分析结果生成K线走势叙事"""

    @staticmethod
    def describe(result: TrendAnalysisResult, daily_df: Optional[pd.DataFrame] = None) -> str:
        """
        生成走势叙事文本，供 LLM prompt 使用。

        Args:
            result: 量化分析结果
            daily_df: 原始日线数据（含 open/high/low/close/volume/date 列）

        Returns:
            多行叙事文本字符串
        """
        try:
            sections = [
                KlineNarrator._describe_trend_overview(result, daily_df),
                KlineNarrator._describe_ma_structure(result),
                KlineNarrator._describe_volume(result, daily_df),
                KlineNarrator._describe_momentum(result),
                KlineNarrator._describe_key_levels(result),
                KlineNarrator._describe_special(result),
            ]
            return "\n".join(s for s in sections if s)
        except Exception as e:
            logger.debug(f"KlineNarrator.describe 失败: {e}")
            return ""

    @staticmethod
    def _describe_trend_overview(result: TrendAnalysisResult, daily_df: Optional[pd.DataFrame]) -> str:
        price = result.current_price
        if price <= 0:
            return ""

        swing_desc = ""
        if daily_df is not None and not daily_df.empty and len(daily_df) >= 5:
            try:
                recent = daily_df.tail(30)
                period_high = float(recent['high'].max())
                period_low = float(recent['low'].min())

                if period_high > price:
                    drop_pct = (period_high - price) / period_high * 100
                    if drop_pct >= 5:
                        swing_desc = f"近30日从高点{period_high:.2f}回落{drop_pct:.1f}%至{price:.2f}"
                    elif drop_pct < 2:
                        swing_desc = f"近30日高点{period_high:.2f}，当前价{price:.2f}接近高位"
                    else:
                        swing_desc = f"近30日高点{period_high:.2f}，当前{price:.2f}较高点回落{drop_pct:.1f}%"
                else:
                    swing_desc = f"近30日维持强势，当前{price:.2f}运行于区间高位（30日低点{period_low:.2f}）"
            except Exception:
                pass

        bb_desc = ""
        if result.bb_upper > 0 and result.bb_lower > 0:
            pct_b = result.bb_pct_b
            if pct_b >= 0.85:
                bb_desc = "触及布林带上轨（超买区域）"
            elif pct_b >= 0.6:
                bb_desc = "处于布林带中上轨之间"
            elif pct_b >= 0.4:
                bb_desc = "在布林带中轨附近横盘"
            elif pct_b >= 0.15:
                bb_desc = "处于布林带中下轨之间"
            else:
                bb_desc = "跌至布林带下轨附近（超卖区域）"
            if result.bb_width > 0:
                if result.bb_width < 0.04:
                    bb_desc += "，布林带极度收窄（行情蓄势待发）"
                elif result.bb_width > 0.15:
                    bb_desc += "，布林带大幅扩张（波动率极高）"

        weekly_desc = ""
        if result.weekly_trend:
            weekly_map = {"多头": "，周线多头结构", "空头": "，周线空头结构", "震荡": "，周线宽幅震荡"}
            weekly_desc = weekly_map.get(result.weekly_trend, "")

        parts = [p for p in [swing_desc, bb_desc] if p]
        body = "，".join(parts) if parts else f"当前价{price:.2f}"
        return f"【走势概况】{body}{weekly_desc}。"

    @staticmethod
    def _describe_ma_structure(result: TrendAnalysisResult) -> str:
        ma5, ma10, ma20 = result.ma5, result.ma10, result.ma20
        if ma5 <= 0 or ma20 <= 0:
            return ""

        alignment_map = {
            TrendStatus.STRONG_BULL: "强势多头排列，均线向上发散",
            TrendStatus.BULL: "多头排列（MA5>MA10>MA20），多方占优",
            TrendStatus.WEAK_BULL: "弱多头排列，均线趋于收敛",
            TrendStatus.CONSOLIDATION: "均线粘合震荡，方向尚不明确",
            TrendStatus.WEAK_BEAR: "弱空头排列，均线趋于向下",
            TrendStatus.BEAR: "空头排列（MA5<MA10<MA20），空方占优",
            TrendStatus.STRONG_BEAR: "强势空头排列，均线向下发散",
        }
        align_desc = alignment_map.get(result.trend_status, result.ma_alignment or "")

        ma_vals = f"MA5={ma5:.2f} / MA10={ma10:.2f} / MA20={ma20:.2f}"
        if result.ma60 > 0:
            ma_vals += f" / MA60={result.ma60:.2f}"

        price_pos = ""
        price = result.current_price
        if price > 0 and ma20 > 0:
            if price > ma20:
                price_pos = f"，价格站上MA20（+{result.bias_ma20:.1f}%）"
            else:
                price_pos = f"，价格跌破MA20（{result.bias_ma20:.1f}%）"

        spread_desc = ""
        if result.ma_spread_signal:
            spread_desc = f"，均线{result.ma_spread_signal}"

        return f"【均线形态】{align_desc}（{ma_vals}）{price_pos}{spread_desc}。"

    @staticmethod
    def _describe_volume(result: TrendAnalysisResult, daily_df: Optional[pd.DataFrame]) -> str:
        parts = []

        vol_ratio = result.volume_ratio
        if vol_ratio > 0:
            if vol_ratio >= 2.5:
                parts.append(f"今日量比{vol_ratio:.1f}×（天量异动）")
            elif vol_ratio >= 1.5:
                parts.append(f"今日量比{vol_ratio:.1f}×（明显放量）")
            elif vol_ratio <= 0.5:
                parts.append(f"今日量比{vol_ratio:.1f}×（明显缩量）")
            else:
                parts.append(f"量比{vol_ratio:.1f}×")

        vol_status_map = {
            VolumeStatus.HEAVY_VOLUME_UP: "量价齐升，主力积极",
            VolumeStatus.HEAVY_VOLUME_DOWN: "放量杀跌，空方主导",
            VolumeStatus.SHRINK_VOLUME_UP: "缩量上涨，动能不足",
            VolumeStatus.SHRINK_VOLUME_DOWN: "缩量回调，属于健康整理",
        }
        if result.volume_status in vol_status_map:
            parts.append(vol_status_map[result.volume_status])

        if daily_df is not None and not daily_df.empty and len(daily_df) >= 20:
            try:
                avg_recent = float(daily_df['volume'].tail(10).mean())
                avg_prev = float(daily_df['volume'].tail(20).head(10).mean())
                if avg_prev > 0:
                    vol_chg_pct = (avg_recent - avg_prev) / avg_prev * 100
                    if vol_chg_pct <= -25:
                        parts.append(f"近10日成交量较前期萎缩{abs(vol_chg_pct):.0f}%（持续缩量）")
                    elif vol_chg_pct >= 40:
                        parts.append(f"近10日成交量较前期放大{vol_chg_pct:.0f}%（活跃度提升）")
            except Exception:
                pass

        if result.vol_anomaly:
            parts.append(result.vol_anomaly)
        if result.volume_price_divergence:
            parts.append(f"⚠️{result.volume_price_divergence}")
        if result.vol_price_structure:
            parts.append(result.vol_price_structure)

        if not parts:
            return ""
        return f"【量能特征】{'，'.join(parts)}。"

    @staticmethod
    def _describe_momentum(result: TrendAnalysisResult) -> str:
        parts = []

        macd_map = {
            MACDStatus.GOLDEN_CROSS_ZERO: "零轴上金叉（强势买入信号）",
            MACDStatus.GOLDEN_CROSS: "金叉形成，多方动能恢复",
            MACDStatus.CROSSING_UP: "上穿零轴，趋势由弱转强",
            MACDStatus.BULLISH: f"多头结构（DIF={result.macd_dif:.3f} > DEA={result.macd_dea:.3f}）",
            MACDStatus.NEUTRAL: f"中性（DIF={result.macd_dif:.3f} 接近零轴）",
            MACDStatus.BEARISH: f"空头结构（DIF={result.macd_dif:.3f} < DEA={result.macd_dea:.3f}）",
            MACDStatus.CROSSING_DOWN: "下穿零轴，趋势由强转弱",
            MACDStatus.DEATH_CROSS: "死叉，空方动能占优",
        }
        macd_desc = macd_map.get(result.macd_status, result.macd_status.value)
        if result.macd_momentum:
            macd_desc += f"，{result.macd_momentum}"
        if result.macd_bar_accel > 0 and result.macd_bar_slope != 0:
            direction = "延伸" if result.macd_bar_slope > 0 else "收缩"
            macd_desc += f"（柱状图连续{result.macd_bar_accel}日{direction}）"
        parts.append(f"MACD {macd_desc}")

        rsi12 = result.rsi_12
        if rsi12 > 0:
            if rsi12 >= 70:
                rsi_desc = f"RSI超买（RSI12={rsi12:.0f}）"
            elif rsi12 <= 30:
                rsi_desc = f"RSI超卖（RSI12={rsi12:.0f}）"
            elif rsi12 >= 55:
                rsi_desc = f"RSI强势区（RSI12={rsi12:.0f}）"
            elif rsi12 <= 45:
                rsi_desc = f"RSI弱势区（RSI12={rsi12:.0f}）"
            else:
                rsi_desc = f"RSI中性（RSI12={rsi12:.0f}）"
            if result.rsi_divergence:
                rsi_desc += f"，{result.rsi_divergence}"
            parts.append(rsi_desc)

        if result.adx > 0:
            if result.adx >= 25:
                parts.append(f"ADX={result.adx:.0f}（{result.adx_regime}，趋势方向明确）")
            elif result.adx <= 15:
                parts.append(f"ADX={result.adx:.0f}（震荡市，趋势不明）")

        return f"【动量指标】{'；'.join(parts)}。" if parts else ""

    @staticmethod
    def _describe_key_levels(result: TrendAnalysisResult) -> str:
        price = result.current_price
        if price <= 0:
            return ""

        parts = []

        supports = sorted([s for s in result.support_levels if 0 < s < price], reverse=True)[:2]
        if supports:
            parts.append(f"支撑: {' / '.join(f'{s:.2f}' for s in supports)}")
        elif result.bb_lower > 0 and result.bb_lower < price:
            parts.append(f"支撑: 布林下轨{result.bb_lower:.2f}")

        resistances = sorted([r for r in result.resistance_levels if r > price])[:2]
        if resistances:
            parts.append(f"压力: {' / '.join(f'{r:.2f}' for r in resistances)}")
        elif result.bb_upper > 0 and result.bb_upper > price:
            parts.append(f"压力: 布林上轨{result.bb_upper:.2f}")

        if result.stop_loss_short > 0:
            parts.append(f"短线止损参考: {result.stop_loss_short:.2f}")

        if result.fib_current_zone:
            fib_desc = result.fib_current_zone
            if result.fib_level_618 > 0:
                fib_desc += f"（0.618={result.fib_level_618:.2f}）"
            parts.append(f"Fib: {fib_desc}")

        if not parts:
            return ""
        return f"【关键价位】{'，'.join(parts)}。"

    @staticmethod
    def _describe_special(result: TrendAnalysisResult) -> str:
        parts = []

        if result.is_limit_up:
            limit_desc = f"🟢 当日涨停{'（连' + str(result.consecutive_limits) + '板）' if result.consecutive_limits >= 2 else ''}"
            parts.append(limit_desc)
        elif result.is_limit_down:
            parts.append("🔴 当日跌停")

        if result.chart_pattern:
            note = f"，{result.chart_pattern_note}" if result.chart_pattern_note else ""
            parts.append(f"形态: {result.chart_pattern}（{result.chart_pattern_signal}）{note}")

        if result.candle_pattern_summary:
            parts.append(f"K线形态: {result.candle_pattern_summary}")

        if result.forecast_scenario:
            prob = f"↑{result.forecast_prob_up}% / →{result.forecast_prob_sideways}% / ↓{result.forecast_prob_down}%"
            parts.append(f"1-5日预判: {result.forecast_scenario}（{prob}）")
            if result.forecast_trigger:
                parts.append(f"确认信号: {result.forecast_trigger}")

        if result.seq_behavior_note:
            parts.append(f"行为链: {result.seq_behavior_note}")

        if result.resonance_intent:
            parts.append(f"主力意图: {result.resonance_intent}")

        if not parts:
            return ""
        return f"【特殊信号】{'；'.join(parts)}。"
