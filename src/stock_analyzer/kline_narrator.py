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
                KlineNarrator._describe_ma_interaction(result, daily_df),
                KlineNarrator._describe_candle_sequence(result, daily_df),
                KlineNarrator._describe_volume(result, daily_df),
                KlineNarrator._describe_momentum(result),
                KlineNarrator._describe_key_levels(result),
                KlineNarrator._describe_gap_status(result),
                KlineNarrator._describe_52week_range(result, daily_df),
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
    def _describe_ma_interaction(result: TrendAnalysisResult, daily_df: Optional[pd.DataFrame]) -> str:
        """描述价格与均线的交互动作：回踩/触碰/突破，有助于判断支撑确认或压力测试"""
        if daily_df is None or daily_df.empty or len(daily_df) < 6:
            return ""
        price = result.current_price
        if price <= 0:
            return ""
        parts = []
        try:
            closes = daily_df['close'].values
            n = len(closes)
            # 计算过去10日的MA20值（若可用）
            if n >= 20 and result.ma20 > 0:
                ma20 = result.ma20
                # 判断最近5日是否有回踩MA20的行为
                recent_lows = daily_df['low'].values[-6:-1]  # 前5日最低价
                recent_closes = closes[-6:-1]
                today_close = closes[-1]
                # 寻找回踩：前5日内有某天low触碰MA20（偏差±1.5%）
                for i, (low, cls) in enumerate(zip(recent_lows, recent_closes)):
                    touch_pct = abs(low - ma20) / ma20 * 100
                    if touch_pct <= 1.5:
                        days_ago = 5 - i
                        if cls > ma20 and today_close > ma20:
                            parts.append(f"{days_ago}日前回踩MA20={ma20:.2f}后站稳，支撑有效")
                        elif cls < ma20:
                            parts.append(f"{days_ago}日前跌破MA20={ma20:.2f}，当前{'已收复' if today_close > ma20 else '仍在下方'}")
                        break
                # 如果没有触碰事件，描述价格与MA20的相对位置和持续天数
                if not parts:
                    above_count = sum(1 for c in closes[-10:] if c > ma20)
                    if above_count >= 8:
                        parts.append(f"近10日持续站上MA20={ma20:.2f}，多方占据主动")
                    elif above_count <= 2:
                        parts.append(f"近10日持续运行于MA20={ma20:.2f}下方，多方未能收复")
            # MA5回踩MA10
            if result.ma5 > 0 and result.ma10 > 0 and not parts:
                if abs(result.ma5 - result.ma10) / result.ma10 * 100 < 0.5:
                    parts.append(f"MA5({result.ma5:.2f})与MA10({result.ma10:.2f})高度粘合，方向待定")
        except Exception:
            pass
        if not parts:
            return ""
        return f"【均线交互】{'，'.join(parts)}。"

    @staticmethod
    def _describe_candle_sequence(result: TrendAnalysisResult, daily_df: Optional[pd.DataFrame]) -> str:
        """描述近期连续阴阳线节奏，判断趋势动能是否持续"""
        if daily_df is None or daily_df.empty or len(daily_df) < 5:
            return ""
        parts = []
        try:
            opens = daily_df['open'].values[-10:]
            closes = daily_df['close'].values[-10:]
            n = len(closes)
            # 统计最近的连续阳线/阴线
            is_up = closes[-1] >= opens[-1]
            streak = 1
            for i in range(n - 2, -1, -1):
                if (closes[i] >= opens[i]) == is_up:
                    streak += 1
                else:
                    break
            if streak >= 3:
                direction = "阳线" if is_up else "阴线"
                if streak >= 6:
                    warn = "，需警惕动能衰竭" if is_up else "，需关注超卖反弹机会"
                    parts.append(f"连续{streak}根{direction}{warn}")
                else:
                    parts.append(f"连续{streak}根{direction}，{'多方持续做多' if is_up else '空方持续施压'}")
            # 今日是否为阳包阴/阴包阳（吞没形态）
            if n >= 2:
                prev_body = abs(closes[-2] - opens[-2])
                curr_body = abs(closes[-1] - opens[-1])
                if prev_body > 0 and curr_body > prev_body * 1.2:
                    if closes[-1] > opens[-1] and closes[-2] < opens[-2]:
                        parts.append("今日阳包阴（多方吞没），短线止跌信号")
                    elif closes[-1] < opens[-1] and closes[-2] > opens[-2]:
                        parts.append("今日阴包阳（空方吞没），短线见顶信号")
        except Exception:
            pass
        if not parts:
            return ""
        return f"【K线节奏】{'，'.join(parts)}。"

    @staticmethod
    def _describe_gap_status(result: TrendAnalysisResult) -> str:
        """描述缺口状态（未回补的缺口是重要支撑/压力位）"""
        if not result.gap_type:
            return ""
        parts = []
        try:
            gap_upper = result.gap_upper
            gap_lower = result.gap_lower
            price = result.current_price
            if result.gap_filled:
                parts.append(f"{result.gap_type}缺口（{gap_lower:.2f}-{gap_upper:.2f}）已回补")
            else:
                if result.gap_type == "向上跳空":
                    if price > gap_upper:
                        parts.append(f"向上跳空缺口（{gap_lower:.2f}-{gap_upper:.2f}）未回补，为下方有效支撑")
                    else:
                        parts.append(f"向上跳空缺口（{gap_lower:.2f}-{gap_upper:.2f}）未回补，价格已回落至缺口区域")
                elif result.gap_type == "向下跳空":
                    if price < gap_lower:
                        parts.append(f"向下跳空缺口（{gap_lower:.2f}-{gap_upper:.2f}）未回补，为上方压力位")
                    else:
                        parts.append(f"向下跳空缺口（{gap_lower:.2f}-{gap_upper:.2f}）未回补，价格已反弹至缺口区域")
        except Exception:
            pass
        if not parts:
            return ""
        return f"【缺口状态】{'；'.join(parts)}。"

    @staticmethod
    def _describe_52week_range(result: TrendAnalysisResult, daily_df: Optional[pd.DataFrame]) -> str:
        """描述52周（约250交易日）高低点区间对比，量化价格所处历史位置"""
        if daily_df is None or daily_df.empty or len(daily_df) < 20:
            return ""
        price = result.current_price
        if price <= 0:
            return ""
        try:
            n_days = min(250, len(daily_df))
            period_df = daily_df.tail(n_days)
            period_high = float(period_df['high'].max())
            period_low = float(period_df['low'].min())
            label = "52周" if n_days >= 200 else f"{n_days}交易日"

            if period_high <= period_low or period_high <= 0:
                return ""

            pct_from_high = (price - period_high) / period_high * 100   # 负数
            pct_from_low = (price - period_low) / period_low * 100       # 正数
            position_pct = (price - period_low) / (period_high - period_low) * 100  # 0-100%

            parts = []
            # 绝对位置描述
            if price >= period_high:
                # 当前价突破52周高点（盘中新高）
                if pct_from_high < 1:
                    parts.append(f"当前价{price:.2f}触及{label}新高（高点{period_high:.2f}），突破确认需收盘站稳")
                else:
                    parts.append(f"当前价{price:.2f}突破{label}高点{period_high:.2f}（超出+{pct_from_high:.1f}%），强势突破")
            elif price <= period_low:
                parts.append(f"当前价{price:.2f}跌破{label}低点{period_low:.2f}（跌幅{pct_from_low:.1f}%），需警惕继续下探")
            elif pct_from_high >= -5:
                parts.append(f"当前价{price:.2f}接近{label}高点（高点{period_high:.2f}，距高点{abs(pct_from_high):.1f}%），关注突破可能")
            elif pct_from_high <= -30:
                parts.append(f"距{label}高点{period_high:.2f}已回落{abs(pct_from_high):.0f}%，处于深度调整区")
            elif pct_from_low <= 10:
                parts.append(f"当前价{price:.2f}接近{label}低点区（低点{period_low:.2f}，距低点+{pct_from_low:.1f}%），关注止跌信号")
            else:
                # 区间百分位
                if position_pct >= 75:
                    zone = "区间上方3/4位置"
                elif position_pct >= 50:
                    zone = "区间中上部"
                elif position_pct >= 25:
                    zone = "区间中下部"
                else:
                    zone = "区间下方1/4位置"
                parts.append(
                    f"{label}区间{period_low:.2f}-{period_high:.2f}，"
                    f"当前价位于{zone}（分位{position_pct:.0f}%，"
                    f"距高点{abs(pct_from_high):.1f}% / 距低点+{pct_from_low:.1f}%）"
                )

            if not parts:
                return ""
            return f"【{label}区间】{'；'.join(parts)}。"
        except Exception:
            return ""

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
