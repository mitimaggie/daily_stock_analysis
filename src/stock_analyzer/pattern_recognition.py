# -*- coding: utf-8 -*-
"""
K线形态识别模块
检测经典 K 线形态：锤子线、吞没、十字星、启明星、黄昏星、三只乌鸦、红三兵、跳空缺口等
"""

import logging
import pandas as pd
import numpy as np
from typing import List, Dict, Any
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class CandlePattern:
    """单个 K 线形态"""
    name: str           # 形态名称
    direction: str      # "bullish" / "bearish" / "neutral"
    strength: int       # 信号强度 1-5
    description: str    # 中文描述
    bar_index: int = -1 # 出现在第几根K线（-1=最新）


class PatternRecognition:
    """K 线形态识别器"""

    # === 实体/影线阈值 ===
    DOJI_BODY_RATIO = 0.1       # 十字星：实体 < 振幅的 10%
    LONG_SHADOW_RATIO = 2.0     # 长影线：影线 >= 实体的 2 倍
    ENGULF_MIN_BODY = 0.005     # 吞没最小实体比例（避免噪音）

    @classmethod
    def detect_all(cls, df: pd.DataFrame) -> List[CandlePattern]:
        """
        检测所有 K 线形态，返回按强度降序排列的形态列表。
        需要至少 5 根 K 线。
        """
        if df is None or len(df) < 5:
            return []

        patterns: List[CandlePattern] = []

        try:
            patterns.extend(cls._detect_doji(df))
            patterns.extend(cls._detect_hammer(df))
            patterns.extend(cls._detect_engulfing(df))
            patterns.extend(cls._detect_morning_evening_star(df))
            patterns.extend(cls._detect_three_soldiers_crows(df))
            patterns.extend(cls._detect_gaps(df))
            patterns.extend(cls._detect_harami(df))
            patterns.extend(cls._detect_tweezer(df))
        except Exception as e:
            logger.debug(f"K线形态检测异常: {e}")

        # 按强度降序
        patterns.sort(key=lambda p: p.strength, reverse=True)
        return patterns

    @classmethod
    def detect_and_summarize(cls, df: pd.DataFrame) -> Dict[str, Any]:
        """
        检测形态并返回结构化摘要，供 TrendAnalysisResult 使用。

        Returns:
            {
                'patterns': [{'name', 'direction', 'strength', 'description'}, ...],
                'bullish_count': int,
                'bearish_count': int,
                'net_signal': str,           # "看多" / "看空" / "中性"
                'top_pattern': str,          # 最强形态名称
                'pattern_score_adj': int,    # 评分调整 (-5 ~ +5)
                'summary': str,              # 一句话摘要
            }
        """
        patterns = cls.detect_all(df)

        bullish = [p for p in patterns if p.direction == "bullish"]
        bearish = [p for p in patterns if p.direction == "bearish"]

        bull_strength = sum(p.strength for p in bullish)
        bear_strength = sum(p.strength for p in bearish)

        if bull_strength > bear_strength + 2:
            net = "看多"
        elif bear_strength > bull_strength + 2:
            net = "看空"
        else:
            net = "中性"

        # 评分调整：最强形态贡献 ±3，次强 ±1，上限 ±5
        adj = 0
        if patterns:
            top = patterns[0]
            adj = top.strength if top.direction == "bullish" else -top.strength
            adj = max(-5, min(5, adj))

        top_name = patterns[0].name if patterns else ""

        # 摘要
        if not patterns:
            summary = "近期无明显K线形态"
        else:
            names = [p.name for p in patterns[:3]]
            summary = f"检测到{'、'.join(names)}，整体{net}"

        return {
            'patterns': [
                {'name': p.name, 'direction': p.direction,
                 'strength': p.strength, 'description': p.description}
                for p in patterns
            ],
            'bullish_count': len(bullish),
            'bearish_count': len(bearish),
            'net_signal': net,
            'top_pattern': top_name,
            'pattern_score_adj': adj,
            'summary': summary,
        }

    # ========== 具体形态检测 ==========

    @classmethod
    def _bar(cls, row) -> Dict[str, float]:
        """提取单根 K 线关键数值"""
        o = float(row['open'])
        h = float(row['high'])
        l = float(row['low'])
        c = float(row['close'])
        body = abs(c - o)
        rng = h - l if h > l else 0.001  # 避免除零
        upper_shadow = h - max(o, c)
        lower_shadow = min(o, c) - l
        return {
            'o': o, 'h': h, 'l': l, 'c': c,
            'body': body, 'range': rng,
            'upper': upper_shadow, 'lower': lower_shadow,
            'is_bull': c >= o,
            'body_ratio': body / rng,
        }

    # ---------- 十字星 ----------
    @classmethod
    def _detect_doji(cls, df: pd.DataFrame) -> List[CandlePattern]:
        """十字星：实体极小，上下影线较长，表示多空平衡"""
        results = []
        bar = cls._bar(df.iloc[-1])

        if bar['body_ratio'] < cls.DOJI_BODY_RATIO and bar['range'] > 0:
            # 判断类型
            if bar['lower'] > bar['upper'] * 2:
                # 蜻蜓十字（下影线长）= 底部反转
                results.append(CandlePattern(
                    name="蜻蜓十字星", direction="bullish", strength=3,
                    description="实体极小+长下影线，底部反转信号，多方尝试抄底"
                ))
            elif bar['upper'] > bar['lower'] * 2:
                # 墓碑十字 = 顶部反转
                results.append(CandlePattern(
                    name="墓碑十字星", direction="bearish", strength=3,
                    description="实体极小+长上影线，顶部反转信号，上方抛压沉重"
                ))
            else:
                # 普通十字星
                results.append(CandlePattern(
                    name="十字星", direction="neutral", strength=2,
                    description="多空胶着，变盘前兆，需结合趋势判断方向"
                ))
        return results

    # ---------- 锤子线 / 上吊线 ----------
    @classmethod
    def _detect_hammer(cls, df: pd.DataFrame) -> List[CandlePattern]:
        """
        锤子线：实体较小在上方，长下影线 >= 实体2倍。
        下跌趋势中 = 锤子线（看涨），上涨趋势中 = 上吊线（看跌）。
        倒锤子：实体在下方，长上影线。
        """
        results = []
        bar = cls._bar(df.iloc[-1])

        if bar['body'] < 0.001:
            return results

        # 锤子线 / 上吊线
        if (bar['lower'] >= bar['body'] * cls.LONG_SHADOW_RATIO and
                bar['upper'] < bar['body'] * 0.5):
            # 判断趋势方向（用近5日均价 vs 近20日均价）
            if len(df) >= 20:
                ma5 = df['close'].tail(5).mean()
                ma20 = df['close'].tail(20).mean()
                if ma5 < ma20:
                    results.append(CandlePattern(
                        name="锤子线", direction="bullish", strength=4,
                        description="下跌趋势中出现长下影线，空方无力继续杀跌，底部反转信号"
                    ))
                else:
                    results.append(CandlePattern(
                        name="上吊线", direction="bearish", strength=3,
                        description="上涨趋势中出现长下影线，获利盘回吐，顶部警告"
                    ))

        # 倒锤子 / 流星线
        if (bar['upper'] >= bar['body'] * cls.LONG_SHADOW_RATIO and
                bar['lower'] < bar['body'] * 0.5):
            if len(df) >= 20:
                ma5 = df['close'].tail(5).mean()
                ma20 = df['close'].tail(20).mean()
                if ma5 < ma20:
                    results.append(CandlePattern(
                        name="倒锤子", direction="bullish", strength=3,
                        description="下跌趋势中出现长上影线，多方试探性上攻，潜在反转"
                    ))
                else:
                    results.append(CandlePattern(
                        name="流星线", direction="bearish", strength=4,
                        description="上涨趋势中冲高回落，上方抛压沉重，见顶信号"
                    ))
        return results

    # ---------- 吞没形态 ----------
    @classmethod
    def _detect_engulfing(cls, df: pd.DataFrame) -> List[CandlePattern]:
        """
        看涨吞没：前阴+后阳，后阳实体完全包住前阴实体
        看跌吞没：前阳+后阴，后阴实体完全包住前阳实体
        """
        results = []
        if len(df) < 2:
            return results

        prev = cls._bar(df.iloc[-2])
        curr = cls._bar(df.iloc[-1])

        # 最小实体过滤
        if prev['body_ratio'] < cls.ENGULF_MIN_BODY or curr['body_ratio'] < cls.ENGULF_MIN_BODY:
            return results

        # 看涨吞没
        if (not prev['is_bull'] and curr['is_bull'] and
                curr['body'] > prev['body'] * 1.1 and
                curr['c'] > prev['o'] and curr['o'] <= prev['c']):
            results.append(CandlePattern(
                name="看涨吞没", direction="bullish", strength=4,
                description="阳线实体完全吞没前一根阴线，多方强势反攻"
            ))

        # 看跌吞没
        if (prev['is_bull'] and not curr['is_bull'] and
                curr['body'] > prev['body'] * 1.1 and
                curr['o'] > prev['c'] and curr['c'] <= prev['o']):
            results.append(CandlePattern(
                name="看跌吞没", direction="bearish", strength=4,
                description="阴线实体完全吞没前一根阳线，空方强势压制"
            ))

        return results

    # ---------- 启明星 / 黄昏星 ----------
    @classmethod
    def _detect_morning_evening_star(cls, df: pd.DataFrame) -> List[CandlePattern]:
        """
        启明星（底部反转）：大阴 + 小实体(跳空低开) + 大阳(收复大半)
        黄昏星（顶部反转）：大阳 + 小实体(跳空高开) + 大阴(吞回大半)
        """
        results = []
        if len(df) < 3:
            return results

        b1 = cls._bar(df.iloc[-3])
        b2 = cls._bar(df.iloc[-2])
        b3 = cls._bar(df.iloc[-1])

        avg_body = (b1['body'] + b2['body'] + b3['body']) / 3
        if avg_body < 0.001:
            return results

        # 启明星
        if (not b1['is_bull'] and b1['body_ratio'] > 0.4 and
                b2['body_ratio'] < 0.3 and
                b3['is_bull'] and b3['body_ratio'] > 0.4 and
                b3['c'] > (b1['o'] + b1['c']) / 2):
            results.append(CandlePattern(
                name="启明星", direction="bullish", strength=5,
                description="经典三K线底部反转：大阴→小实体→大阳收复，强烈看涨"
            ))

        # 黄昏星
        if (b1['is_bull'] and b1['body_ratio'] > 0.4 and
                b2['body_ratio'] < 0.3 and
                not b3['is_bull'] and b3['body_ratio'] > 0.4 and
                b3['c'] < (b1['o'] + b1['c']) / 2):
            results.append(CandlePattern(
                name="黄昏星", direction="bearish", strength=5,
                description="经典三K线顶部反转：大阳→小实体→大阴吞回，强烈看跌"
            ))

        return results

    # ---------- 红三兵 / 三只乌鸦 ----------
    @classmethod
    def _detect_three_soldiers_crows(cls, df: pd.DataFrame) -> List[CandlePattern]:
        """
        红三兵：连续3根阳线，收盘价依次走高
        三只乌鸦：连续3根阴线，收盘价依次走低
        """
        results = []
        if len(df) < 3:
            return results

        bars = [cls._bar(df.iloc[i]) for i in range(-3, 0)]

        # 红三兵
        if (all(b['is_bull'] for b in bars) and
                bars[1]['c'] > bars[0]['c'] and bars[2]['c'] > bars[1]['c'] and
                all(b['body_ratio'] > 0.3 for b in bars)):
            # 检查是否"前进受阻"（实体逐渐缩小+上影线变长）
            if bars[2]['body'] < bars[0]['body'] * 0.6:
                results.append(CandlePattern(
                    name="前进受阻红三兵", direction="bullish", strength=2,
                    description="连续3阳但实体递减，上攻动能减弱，涨势可能放缓"
                ))
            else:
                results.append(CandlePattern(
                    name="红三兵", direction="bullish", strength=4,
                    description="连续3根实体阳线依次走高，多方持续推升，强势看涨"
                ))

        # 三只乌鸦
        if (all(not b['is_bull'] for b in bars) and
                bars[1]['c'] < bars[0]['c'] and bars[2]['c'] < bars[1]['c'] and
                all(b['body_ratio'] > 0.3 for b in bars)):
            results.append(CandlePattern(
                name="三只乌鸦", direction="bearish", strength=4,
                description="连续3根实体阴线依次走低，空方持续打压，强势看跌"
            ))

        return results

    # ---------- 跳空缺口 ----------
    @classmethod
    def _detect_gaps(cls, df: pd.DataFrame) -> List[CandlePattern]:
        """
        向上跳空：当日最低 > 前日最高
        向下跳空：当日最高 < 前日最低
        连续缺口增强信号强度
        """
        results = []
        if len(df) < 2:
            return results

        prev = cls._bar(df.iloc[-2])
        curr = cls._bar(df.iloc[-1])

        if curr['l'] > prev['h']:
            # 计算缺口大小
            gap_pct = (curr['l'] - prev['h']) / prev['h'] * 100
            strength = 3 if gap_pct < 2 else 4
            results.append(CandlePattern(
                name="向上跳空缺口", direction="bullish", strength=strength,
                description=f"跳空高开{gap_pct:.1f}%未回补，多方强势突破"
            ))

        if curr['h'] < prev['l']:
            gap_pct = (prev['l'] - curr['h']) / prev['l'] * 100
            strength = 3 if gap_pct < 2 else 4
            results.append(CandlePattern(
                name="向下跳空缺口", direction="bearish", strength=strength,
                description=f"跳空低开{gap_pct:.1f}%未回补，空方强势打压"
            ))

        return results

    # ---------- 孕线（Harami）----------
    @classmethod
    def _detect_harami(cls, df: pd.DataFrame) -> List[CandlePattern]:
        """
        看涨孕线：大阴 + 小阳（小阳实体在大阴实体内）
        看跌孕线：大阳 + 小阴（小阴实体在大阳实体内）
        """
        results = []
        if len(df) < 2:
            return results

        prev = cls._bar(df.iloc[-2])
        curr = cls._bar(df.iloc[-1])

        if prev['body_ratio'] < 0.3 or curr['body_ratio'] < 0.05:
            return results

        # 看涨孕线
        if (not prev['is_bull'] and curr['is_bull'] and
                curr['body'] < prev['body'] * 0.6 and
                curr['c'] < prev['o'] and curr['o'] > prev['c']):
            results.append(CandlePattern(
                name="看涨孕线", direction="bullish", strength=3,
                description="大阴后小阳被包含其中，下跌动能耗尽，可能反转"
            ))

        # 看跌孕线
        if (prev['is_bull'] and not curr['is_bull'] and
                curr['body'] < prev['body'] * 0.6 and
                curr['o'] < prev['c'] and curr['c'] > prev['o']):
            results.append(CandlePattern(
                name="看跌孕线", direction="bearish", strength=3,
                description="大阳后小阴被包含其中，上涨动能耗尽，可能回调"
            ))

        return results

    # ---------- 镊子顶/底（Tweezer）----------
    @classmethod
    def _detect_tweezer(cls, df: pd.DataFrame) -> List[CandlePattern]:
        """
        镊子底：连续两根K线最低价几乎相同（差距<0.3%），前阴后阳
        镊子顶：连续两根K线最高价几乎相同，前阳后阴
        """
        results = []
        if len(df) < 2:
            return results

        prev = cls._bar(df.iloc[-2])
        curr = cls._bar(df.iloc[-1])
        tol = prev['c'] * 0.003  # 0.3% 容差

        # 镊子底
        if (abs(curr['l'] - prev['l']) < tol and
                not prev['is_bull'] and curr['is_bull']):
            results.append(CandlePattern(
                name="镊子底", direction="bullish", strength=3,
                description="两根K线低点几乎相同+前阴后阳，强支撑位确认"
            ))

        # 镊子顶
        if (abs(curr['h'] - prev['h']) < tol and
                prev['is_bull'] and not curr['is_bull']):
            results.append(CandlePattern(
                name="镊子顶", direction="bearish", strength=3,
                description="两根K线高点几乎相同+前阳后阴，强阻力位确认"
            ))

        return results
