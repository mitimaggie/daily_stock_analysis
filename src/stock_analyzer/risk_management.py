# -*- coding: utf-8 -*-
"""
风险管理模块
包含止损止盈、仓位管理、风险收益比计算等逻辑
"""

import logging
import numpy as np
import pandas as pd
from typing import List, Tuple, Dict, Any, Optional
from .types import TrendAnalysisResult, TrendStatus, MarketRegime, RSIStatus, VolumeStatus, MACDStatus

logger = logging.getLogger(__name__)


class RiskManager:
    """风险管理器：止损止盈、仓位管理"""
    
    @staticmethod
    def calculate_stop_loss_and_take_profit(result: TrendAnalysisResult, df: pd.DataFrame):
        """
        计算动态止损止盈锚点
        
        Args:
            result: 分析结果对象
            df: K线数据
        """
        atr = result.atr14
        price = result.current_price
        
        if atr <= 0 or price <= 0:
            return
        
        from .indicators import TechnicalIndicators
        atr_percentile = TechnicalIndicators.calc_atr_percentile(df)
        
        # 回测验证：4-6%止损距离胜率88%，<2%止损距离触发率69%（大量误触）
        # 目标止损距离法：根据ATR%动态调整目标，高波动股止损更紧
        # ATR%<2%（低波动蓝筹）→目标3.5%；ATR%2-4%→目标3.0%；ATR%>4%（高波动成长）→目标2.5%
        atr_ratio = atr / price if price > 0 else 0.02
        if atr_ratio < 0.02:      # ATR < 2%，低波动蓝筹
            TARGET_SHORT_PCT = 0.035
            TARGET_MID_PCT   = 0.055
        elif atr_ratio < 0.04:    # ATR 2-4%，中等波动
            TARGET_SHORT_PCT = 0.030
            TARGET_MID_PCT   = 0.050
        elif atr_ratio < 0.05:    # ATR 4-5%，高波动
            TARGET_SHORT_PCT = 0.025
            TARGET_MID_PCT   = 0.040
        else:                      # ATR > 5%，超高波动（如涨停板概念股）
            TARGET_SHORT_PCT = 0.020
            TARGET_MID_PCT   = 0.035
        if atr_ratio > 0:
            raw_mult_short = TARGET_SHORT_PCT / atr_ratio
            raw_mult_mid   = TARGET_MID_PCT   / atr_ratio
        else:
            raw_mult_short = 2.0
            raw_mult_mid   = 3.0
        # 限制倍数范围：短线[1.0, 4.0]，中线[1.2, 6.0]
        atr_multiplier_short = max(1.0, min(4.0, raw_mult_short))
        atr_multiplier_mid   = max(1.2, min(6.0, raw_mult_mid))

        # P5-A: Beta 叠加修正 — 高 Beta 股波动更大，止损空间需相应放宽
        beta = getattr(result, 'beta_vs_index', 1.0) or 1.0
        if beta > 1.5:
            atr_multiplier_short *= 1.2
            atr_multiplier_mid *= 1.2
        elif beta < 0.6:
            atr_multiplier_short *= 0.9
            atr_multiplier_mid *= 0.9

        # P5-A: VWAP 位置修正 — 价格在机构成本下方时，止损空间收紧（已跌破成本，止损更严格）
        vwap_pos = getattr(result, 'vwap_position', '')
        vwap_trend = getattr(result, 'vwap_trend', '')
        if vwap_pos == "价格在VWAP下方" and vwap_trend == "机构成本下移":
            # 跌破下行VWAP，空头格局明确，收紧止损避免越扛越深
            atr_multiplier_short *= 0.85
            atr_multiplier_mid *= 0.85
        
        # A股涨跌停限制：止损价不应低于跌停价（无法执行）
        limit_pct = getattr(result, 'limit_pct', 10.0) or 10.0
        limit_floor = round(price * (1 - limit_pct / 100), 2)
        
        result.stop_loss_intraday = round(max(price - 0.7 * atr_multiplier_short * atr, limit_floor), 2)
        result.stop_loss_short = round(max(price - atr_multiplier_short * atr, limit_floor), 2)
        
        if len(df) >= 20:
            recent_high_20d = float(df['high'].tail(20).max())
            chandelier_sl = recent_high_20d - atr_multiplier_mid * atr
            sl_ma20 = result.ma20 * 0.98 if result.ma20 > 0 else chandelier_sl
            result.stop_loss_mid = round(max(min(chandelier_sl, sl_ma20), limit_floor), 2)
        else:
            sl_atr_mid = price - atr_multiplier_mid * atr
            sl_ma20 = result.ma20 * 0.98 if result.ma20 > 0 else sl_atr_mid
            raw_mid = min(sl_atr_mid, sl_ma20) if sl_ma20 > 0 else sl_atr_mid
            result.stop_loss_mid = round(max(raw_mid, limit_floor), 2)
        
        # 理想买点：优先用 MA5/MA10 回踩，但不能高于现价
        ma_anchor = result.ma5 if result.ma5 > 0 else result.ma10
        if ma_anchor > 0 and ma_anchor <= price:
            result.ideal_buy_anchor = round(ma_anchor, 2)
        else:
            # MA 在现价之上（下跌趋势）→ 取最近支撑位或 ATR 回踩价
            support_below = [s for s in (result.support_levels or []) if s < price]
            if support_below:
                result.ideal_buy_anchor = round(max(support_below), 2)
            else:
                result.ideal_buy_anchor = round(price - 0.3 * atr, 2)
        
        if result.trend_status in [TrendStatus.STRONG_BULL, TrendStatus.BULL]:
            tp_multiplier_short = 2.0
            tp_multiplier_mid = 3.5
        elif result.trend_status == TrendStatus.CONSOLIDATION:
            tp_multiplier_short = 1.2
            tp_multiplier_mid = 2.0
        else:
            tp_multiplier_short = 1.5
            tp_multiplier_mid = 2.5
        
        atr_tp_short = round(price + tp_multiplier_short * atr, 2)
        # 止盈取 min(ATR止盈, 最近阻力位-0.5%)：阻力位是现实的压力墙，避免止盈设在墙外
        # 修复：阻力位距现价必须至少1.5x ATR，否则太近无参考价值（会导致止盈<止损距离）
        if result.resistance_levels:
            nearest_resistance = result.resistance_levels[0]
            resistance_tp = round(nearest_resistance * 0.995, 2)  # 阻力位下方 0.5%
            # 阻力位有效条件：①高于现价 ②低于ATR止盈 ③距现价至少1.5x ATR（约等于止损距离）
            resistance_meaningful = (nearest_resistance - price) >= 1.5 * atr
            if price < resistance_tp < atr_tp_short and resistance_meaningful:
                result.take_profit_short = resistance_tp
                result.score_breakdown['tp_capped_by_resistance'] = 1  # 仅作日志标记
            else:
                result.take_profit_short = atr_tp_short
        else:
            result.take_profit_short = atr_tp_short
        
        if result.resistance_levels:
            # take_profit_mid 取第二阻力位（若存在），否则 ATR 止盈
            # 同样要求阻力位距现价至少 2x ATR
            mid_resistance = result.resistance_levels[1] if len(result.resistance_levels) > 1 else result.resistance_levels[0]
            mid_resistance_tp = round(mid_resistance * 0.995, 2)
            if (mid_resistance - price) >= 2.0 * atr:
                result.take_profit_mid = mid_resistance_tp
            else:
                result.take_profit_mid = round(price + tp_multiplier_mid * atr, 2)
        else:
            result.take_profit_mid = round(price + tp_multiplier_mid * atr, 2)
        
        # RR兜底：止盈距离必须 >= 止损距离（保证风险回报比≥1.0）
        sl_dist_abs = price - result.stop_loss_short
        tp_dist_abs = result.take_profit_short - price
        if sl_dist_abs > 0 and tp_dist_abs < sl_dist_abs:
            result.take_profit_short = round(price + sl_dist_abs, 2)

        if len(df) >= 20:
            recent_high = float(df['high'].tail(20).max())
            trailing_atr_mult = 1.5 if result.trend_strength >= 75 else 1.2
            result.take_profit_trailing = round(recent_high - trailing_atr_mult * atr, 2)
        
        tp1 = result.take_profit_short
        tp2 = result.take_profit_mid
        result.take_profit_plan = (
            f"第1批(1/3仓位): 到{tp1:.2f}止盈 | "
            f"第2批(1/3仓位): 到{tp2:.2f}止盈 | "
            f"第3批(底仓): 移动止盈线{result.take_profit_trailing:.2f}跟踪（Parabolic SAR）"
        )
    
    @staticmethod
    def calculate_position(result: TrendAnalysisResult, market_regime: MarketRegime, regime_strength: int = 50):
        """
        增强版仓位管理系统：动态仓位 + 凯利公式 + 风险分散
        
        仓位决策因子：
        1. 信号评分 (signal_score)
        2. 风险收益比 (risk_reward_ratio)
        3. 趋势强度 (trend_strength)
        4. 市场环境 (market_regime)
        5. 波动率 (volatility_20d)
        """
        base_position = 0
        
        score = result.signal_score
        if score >= 85:
            base_position = 50
        elif score >= 70:
            base_position = 40
        elif score >= 60:
            base_position = 30
        elif score >= 50:
            base_position = 20
        elif score >= 40:
            base_position = 10
        else:
            base_position = 0
        
        multipliers = []
        
        if result.risk_reward_ratio >= 3.0:
            multipliers.append(1.3)
        elif result.risk_reward_ratio >= 2.0:
            multipliers.append(1.1)
        elif result.risk_reward_ratio < 1.0:
            multipliers.append(0.7)
        
        if result.trend_strength >= 80:
            multipliers.append(1.2)
        elif result.trend_strength < 50:
            multipliers.append(0.8)
        
        regime_mult = {
            MarketRegime.BULL: 1.2,
            MarketRegime.SIDEWAYS: 1.0,
            MarketRegime.BEAR: 0.6,
        }
        multipliers.append(regime_mult.get(market_regime, 1.0))
        
        if result.volatility_20d > 0:
            if result.volatility_20d > 60:
                multipliers.append(0.7)
            elif result.volatility_20d < 25:
                multipliers.append(1.1)
        
        position = base_position
        for mult in multipliers:
            position = position * mult
        
        position = max(0, min(80, int(position)))
        result.recommended_position = position
        
        # 动态仓位上限（替代硬编码30%）
        # 根据信号确定性分级：普通→15%，中强→20%，强→25%，极强→30%
        has_resonance = bool(getattr(result, 'timeframe_resonance', ''))
        has_multi_resonance = getattr(result, 'resonance_count', 0) >= 3
        rr_good = result.risk_reward_ratio >= 2.0
        
        if score >= 90 and has_resonance and rr_good:
            # 极强信号：评分>90 + 多周期共振 + R:R>2
            cap = 30
        elif score >= 80 and (has_resonance or has_multi_resonance) and rr_good:
            # 强信号：评分>80 + (共振或多指标共振) + R:R>2
            cap = 25
        elif score >= 70 and rr_good:
            # 中强信号：评分>70 + R:R>2
            cap = 20
        else:
            # 普通信号
            cap = 15
        
        # 熊市环境额外压缩
        if market_regime == MarketRegime.BEAR:
            cap = min(cap, 15)
        
        result.suggested_position_pct = min(cap, max(0, position // 2))
        
        result.position_breakdown = {
            'base': base_position,
            'multipliers': multipliers,
            'final': position,
            'cap': cap,
            'cap_reason': f"{'极强' if cap >= 30 else '强' if cap >= 25 else '中强' if cap >= 20 else '普通'}信号",
        }
    
    @staticmethod
    def calculate_risk_reward(result: TrendAnalysisResult, price: float):
        """风险收益比计算"""
        if result.stop_loss_short > 0 and result.take_profit_short > 0 and price > 0:
            risk = price - result.stop_loss_short
            reward = result.take_profit_short - price
            if risk > 0:
                result.risk_reward_ratio = round(reward / risk, 2)
                if result.risk_reward_ratio >= 2.0:
                    result.risk_reward_verdict = "值得"
                elif result.risk_reward_ratio >= 1.5:
                    result.risk_reward_verdict = "中性"
                else:
                    result.risk_reward_verdict = "不值得"
    
    @staticmethod
    def _calc_volume_profile(df: pd.DataFrame, window: int = 60, bins: int = 50) -> Dict[str, float]:
        """计算成交量密集区（Volume Profile）

        Returns:
            {'poc': float, 'val_low': float, 'val_high': float} 或 {}
        """
        tail = df.tail(window)
        if len(tail) < 10:
            return {}

        try:
            price_low = float(tail['low'].min())
            price_high = float(tail['high'].max())
            if price_high <= price_low:
                return {}

            bin_edges = np.linspace(price_low, price_high, bins + 1)
            vol_profile = np.zeros(bins)

            for _, row in tail.iterrows():
                low_idx = int(np.searchsorted(bin_edges, float(row['low']))) - 1
                high_idx = int(np.searchsorted(bin_edges, float(row['high']))) - 1
                low_idx = max(0, min(low_idx, bins - 1))
                high_idx = max(0, min(high_idx, bins - 1))
                vol = float(row['volume'])
                if high_idx > low_idx:
                    vol_per_bin = vol / (high_idx - low_idx + 1)
                    vol_profile[low_idx:high_idx + 1] += vol_per_bin
                else:
                    vol_profile[low_idx] += vol

            poc_idx = int(np.argmax(vol_profile))
            poc = (bin_edges[poc_idx] + bin_edges[poc_idx + 1]) / 2

            total_vol = vol_profile.sum()
            if total_vol <= 0:
                return {'poc': round(poc, 2), 'val_low': round(price_low, 2), 'val_high': round(price_high, 2)}

            target = total_vol * 0.70
            cum_vol = vol_profile[poc_idx]
            low_bound = poc_idx
            high_bound = poc_idx
            while cum_vol < target and (low_bound > 0 or high_bound < bins - 1):
                expand_low = vol_profile[low_bound - 1] if low_bound > 0 else 0
                expand_high = vol_profile[high_bound + 1] if high_bound < bins - 1 else 0
                if expand_low >= expand_high and low_bound > 0:
                    low_bound -= 1
                    cum_vol += expand_low
                elif high_bound < bins - 1:
                    high_bound += 1
                    cum_vol += expand_high
                else:
                    low_bound -= 1
                    cum_vol += expand_low

            val_low = bin_edges[low_bound]
            val_high = bin_edges[min(high_bound + 1, bins)]

            return {
                'poc': round(float(poc), 2),
                'val_low': round(float(val_low), 2),
                'val_high': round(float(val_high), 2),
            }
        except Exception:
            return {}

    @staticmethod
    def compute_support_resistance_levels(df: pd.DataFrame, result: TrendAnalysisResult) -> Tuple[List[float], List[float]]:
        """
        计算支撑位和阻力位（优先级排序版）

        数据源及权重优先级：均线(1.0) > Volume Profile(0.8) > Swing(0.6) > 整数关口(0.4)

        Returns:
            (支撑位列表, 阻力位列表)  — 按权重降序排列
        """
        levels: List[Dict[str, Any]] = []
        price = result.current_price
        if price <= 0:
            return [], []

        # === 1. 多窗口 Swing 高低点 ===
        swing_weights = {30: 0.6, 60: 0.55, 120: 0.5}
        for window, weight in swing_weights.items():
            if len(df) < window:
                continue
            label = {30: '短期', 60: '中期', 120: '长期'}[window]
            tail = df.tail(window)
            if len(tail) < 5:
                continue
            tail_records = tail[['high', 'low']].to_dict('records')
            for i in range(2, len(tail_records) - 2):
                h = float(tail_records[i]['high'])
                l = float(tail_records[i]['low'])
                prev_h = float(tail_records[i - 1]['high'])
                prev_l = float(tail_records[i - 1]['low'])
                next_h = float(tail_records[i + 1]['high'])
                next_l = float(tail_records[i + 1]['low'])
                if h > prev_h and h > next_h:
                    levels.append({'price': h, 'type': 'resistance', 'source': f'{label}高点', 'weight': weight})
                if l < prev_l and l < next_l:
                    levels.append({'price': l, 'type': 'support', 'source': f'{label}低点', 'weight': weight})

        # === 2. 均线（最高权重 1.0）===
        ma_map = {'MA5': result.ma5, 'MA10': result.ma10, 'MA20': result.ma20, 'MA60': result.ma60}
        for ma_name, ma_val in ma_map.items():
            if ma_val and ma_val > 0 and abs(ma_val - price) / price < 0.15:
                ltype = 'support' if ma_val < price else 'resistance'
                levels.append({'price': ma_val, 'type': ltype, 'source': ma_name, 'weight': 1.0})

        # === 3. Volume Profile（权重 0.8）===
        vp = RiskManager._calc_volume_profile(df)
        if vp:
            result.volume_profile = vp
            levels.append({'price': vp['poc'], 'type': 'support_resistance', 'source': '成交量密集区(POC)', 'weight': 0.8})
            levels.append({'price': vp['val_low'], 'type': 'support', 'source': '成交量密集区下沿', 'weight': 0.7})
            levels.append({'price': vp['val_high'], 'type': 'resistance', 'source': '成交量密集区上沿', 'weight': 0.7})

        # === 4. 整数关口（A 股特有，权重 0.4）===
        if price >= 100:
            step = 10
        elif price >= 50:
            step = 5
        elif price >= 10:
            step = 2
        else:
            step = 1
        base_level = int(price / step) * step
        for offset in range(-2, 3):
            level = base_level + offset * step
            if level > 0 and abs(level - price) > 0.01:
                ltype = 'support' if level < price else 'resistance'
                levels.append({'price': float(level), 'type': ltype, 'source': '整数关口', 'weight': 0.4})

        # === 去重合并（价格相近的取高权重）===
        merged: List[Dict[str, Any]] = []
        for lv in sorted(levels, key=lambda x: -x['weight']):
            too_close = False
            for m in merged:
                if abs(m['price'] - lv['price']) / price < 0.005:
                    if lv['weight'] > m['weight']:
                        m.update(lv)
                    too_close = True
                    break
            if not too_close:
                merged.append(lv)

        # === 分离支撑/阻力并按权重排序 ===
        supports_raw = [lv for lv in merged if lv['type'] in ('support', 'support_resistance') and lv['price'] < price]
        resistances_raw = [lv for lv in merged if lv['type'] in ('resistance', 'support_resistance') and lv['price'] > price]

        supports_raw.sort(key=lambda x: -x['weight'])
        resistances_raw.sort(key=lambda x: -x['weight'])

        result.support_levels_detail = supports_raw[:7]
        result.resistance_levels_detail = resistances_raw[:7]

        supports = [round(lv['price'], 2) for lv in supports_raw[:5]]
        resistances = [round(lv['price'], 2) for lv in resistances_raw[:5]]

        return supports, resistances
    
    # ================================================================
    # P0 级风控：不交易过滤器 + 止损触发回溯 + 成交量异动
    # ================================================================

    @staticmethod
    def check_no_trade_filter(result: TrendAnalysisResult, df: pd.DataFrame,
                              market_snapshot: dict = None):
        """
        P0 不交易过滤器：在给出买卖建议之前，先判断是否应该"不交易"。
        
        检测维度：
        1. 个股流动性不足（日均成交额 < 5000万）
        2. 缩量横盘（ATR百分位极低 + 布林带极窄）
        3. 大盘系统性风险（连续下跌、成交额萎缩）→ 仓位上限
        
        Args:
            result: 分析结果对象（已完成技术指标计算）
            df: K线数据
            market_snapshot: 大盘快照 {'indices': [...], 'total_volume': ...}
        """
        reasons = []
        severity = "soft"  # 默认建议级别

        # --- 1. 流动性检测 ---
        if len(df) >= 10 and 'volume' in df.columns and 'close' in df.columns:
            # 计算近10日日均成交额（万元）
            recent = df.tail(10)
            # 优先使用 amount 列（单位：元），避免 volume 单位歧义
            if 'amount' in df.columns:
                avg_amount_raw = recent['amount'].mean()
                avg_amount_wan = avg_amount_raw / 10000  # 元 → 万元
            else:
                # 回退：用 volume * close 估算，需判断 volume 单位
                # 判断依据：A股单日成交额通常在百万~千亿量级
                # volume*close > 1e10 且 close < 1000 → volume 单位是股
                avg_close = float(recent['close'].mean())
                avg_vol = float(recent['volume'].mean())
                raw_product = avg_vol * avg_close
                if avg_close > 0 and raw_product / avg_close > 1e6:
                    # volume 单位是股（直接用）
                    avg_amount_wan = raw_product / 10000
                else:
                    # volume 单位是手（×100 转股）
                    avg_amount_wan = raw_product * 100 / 10000
            
            if avg_amount_wan < 1000:  # < 1000万
                reasons.append(f"🚫 流动性极差：日均成交额约{avg_amount_wan:.0f}万，低于1000万，买卖困难")
                severity = "hard"
                result.liquidity_warning = f"日均成交额{avg_amount_wan:.0f}万，流动性极差"
            elif avg_amount_wan < 5000:  # < 5000万
                reasons.append(f"⚠️ 流动性不足：日均成交额约{avg_amount_wan:.0f}万，低于5000万，大单冲击成本高")
                result.liquidity_warning = f"日均成交额{avg_amount_wan:.0f}万，流动性偏低"

        # --- 2. 缩量横盘检测 ---
        if len(df) >= 60:
            from .indicators import TechnicalIndicators
            atr_pct = TechnicalIndicators.calc_atr_percentile(df)
            
            # ATR百分位 < 10% 且布林带宽极窄 → 死水行情
            bb_width = result.bb_width
            if atr_pct < 0.10 and bb_width > 0 and bb_width < 0.03:
                reasons.append(f"⏸️ 缩量横盘：ATR百分位{atr_pct:.0%}（极低），布林带宽{bb_width:.4f}（极窄），等待突破方向")
                result.sideways_warning = f"ATR百分位{atr_pct:.0%}，布林带宽{bb_width:.4f}，死水行情"
            elif atr_pct < 0.15:
                # 近10日成交量也在萎缩
                if len(df) >= 20:
                    vol_10 = df['volume'].tail(10).mean()
                    vol_20 = df['volume'].tail(20).mean()
                    if vol_20 > 0 and vol_10 / vol_20 < 0.6:
                        reasons.append(f"⏸️ 量能萎缩+波动收窄：ATR百分位{atr_pct:.0%}，近10日量能仅为20日均量的{vol_10/vol_20:.0%}，等待放量突破")
                        result.sideways_warning = f"ATR低位+量能萎缩，等待突破"

        # --- 3. 大盘系统性风险检测 ---
        if market_snapshot and isinstance(market_snapshot, dict):
            indices = market_snapshot.get('indices', [])
            total_vol = market_snapshot.get('total_volume', 0)
            
            # 检测主要指数连续下跌
            sh_idx = next((i for i in indices if '上证' in i.get('name', '')), None)
            if sh_idx:
                change_pct = float(sh_idx.get('change_pct', 0))
                # 当日大盘暴跌 > 2%
                if change_pct < -2.0:
                    cap = 10
                    reasons.append(f"🔴 大盘暴跌{change_pct:.1f}%，系统性风险，仓位上限{cap}%")
                    result.market_risk_cap = min(result.market_risk_cap, cap)
                    severity = "hard"
                elif change_pct < -1.0:
                    cap = 30
                    reasons.append(f"🟡 大盘下跌{change_pct:.1f}%，控制仓位，上限{cap}%")
                    result.market_risk_cap = min(result.market_risk_cap, cap)
            
            # 成交额萎缩（两市成交额 < 6000亿 → 市场冷清）
            # 仅 14:00 后才判断（已过 ~62% 成交量，全天总额估算可靠）
            # 盘中开盘初期实时累计额远低于全天，会导致误报"市场冷清"
            from datetime import datetime as _dt_mkt
            _now_h = _dt_mkt.now().hour
            if isinstance(total_vol, (int, float)) and 0 < total_vol < 6000 and _now_h >= 14:
                reasons.append(f"🟡 两市成交额{total_vol:.0f}亿，市场冷清，不宜重仓")
                result.market_risk_cap = min(result.market_risk_cap, 30)

        # --- 汇总 ---
        if reasons:
            result.no_trade = True
            result.no_trade_reasons = reasons
            result.no_trade_severity = severity
        
        # 仓位上限约束（独立于 no_trade_reasons，确保小盘股/大盘风险 cap 始终生效）
        if result.market_risk_cap < 100:
            capped = min(result.suggested_position_pct, result.market_risk_cap)
            if capped != result.suggested_position_pct:
                result.suggested_position_pct = capped

    @staticmethod
    def check_stop_loss_breach(result: TrendAnalysisResult, df: pd.DataFrame):
        """
        P0 止损触发回溯：检测当日盘中最低价是否已跌破止损位。
        
        如果今天最低价跌破了止损位但收盘拉回，说明止损位被测试过，
        持仓者应高度警惕——这是一个非常重要的风控信号。
        """
        if df is None or df.empty:
            return
        
        latest = df.iloc[-1]
        intraday_low = float(latest.get('low', 0))
        if intraday_low <= 0:
            return
        
        result.intraday_low = intraday_low
        
        # 检测各级别止损是否被触发
        breaches = []
        
        if result.stop_loss_intraday > 0 and intraday_low <= result.stop_loss_intraday:
            breaches.append(("intraday", result.stop_loss_intraday, "日内止损"))
        
        if result.stop_loss_short > 0 and intraday_low <= result.stop_loss_short:
            breaches.append(("short", result.stop_loss_short, "短线止损"))
        
        if result.stop_loss_mid > 0 and intraday_low <= result.stop_loss_mid:
            breaches.append(("mid", result.stop_loss_mid, "中线止损"))
        
        if breaches:
            result.stop_loss_breached = True
            # 取最严重的级别
            worst = breaches[-1]  # mid > short > intraday
            result.stop_loss_breach_level = worst[0]
            
            details = []
            for level_key, level_price, level_name in breaches:
                gap_pct = (intraday_low - level_price) / level_price * 100
                recovered = result.current_price > level_price
                status = "已收回" if recovered else "未收回"
                details.append(
                    f"🚨 {level_name}({level_price:.2f})已被击穿"
                    f"（最低{intraday_low:.2f}，{gap_pct:+.1f}%，{status}）"
                )
            
            result.stop_loss_breach_detail = " | ".join(details)
            
            # 如果收盘价仍在止损位下方，更新建议
            if result.current_price <= result.stop_loss_short:
                result.advice_for_holding = f"🚨 已跌破短线止损{result.stop_loss_short:.2f}，建议止损离场"
            elif result.current_price <= result.stop_loss_intraday and result.stop_loss_intraday > 0:
                result.advice_for_holding = f"🚨 已跌破日内止损{result.stop_loss_intraday:.2f}，短线应止损"

    @staticmethod
    def detect_volume_extreme(result: TrendAnalysisResult, df: pd.DataFrame):
        """
        成交量异动检测：天量/地量 + 连续放量/缩量趋势
        
        - 天量：成交量创近60日新高，通常是变盘信号
        - 地量：成交量创近60日新低，通常是底部信号
        - 连续3天放量/缩量：趋势确认
        """
        if df is None or len(df) < 20:
            return
        
        latest_vol = float(df.iloc[-1]['volume'])
        if latest_vol <= 0:
            return
        
        # --- 天量/地量检测 ---
        lookback = min(60, len(df))
        vol_window = df['volume'].tail(lookback)
        # 排除今日（最后一行），只用历史数据作为基准
        hist_window = vol_window.iloc[:-1] if len(vol_window) > 1 else vol_window
        vol_max = float(hist_window.max())
        vol_min = float(hist_window.min())
        
        if latest_vol >= vol_max and lookback >= 30:
            result.volume_extreme = "天量"
        elif latest_vol <= vol_min * 1.05 and lookback >= 30:
            result.volume_extreme = "地量"
        
        # --- 连续放量/缩量趋势 ---
        if len(df) >= 5:
            vols = df['volume'].values
            # 分别检测连续放量和连续缩量
            consecutive_up = 0
            for i in range(len(vols) - 1, len(vols) - 4, -1):
                v = float(vols[i])
                v_prev = float(vols[i-1])
                if v > v_prev * 1.1:
                    consecutive_up += 1
                else:
                    break
            
            consecutive_down = 0
            for i in range(len(vols) - 1, len(vols) - 4, -1):
                v = float(vols[i])
                v_prev = float(vols[i-1])
                if v < v_prev * 0.9:
                    consecutive_down += 1
                else:
                    break
            
            if consecutive_up >= 3:
                result.volume_trend_3d = "连续放量"
            elif consecutive_down >= 3:
                result.volume_trend_3d = "连续缩量"

    @staticmethod
    def generate_intraday_watchlist(result: TrendAnalysisResult, df: pd.DataFrame, cost_price: float = 0.0):
        """
        P1 盘中关键价位提醒：生成今日盘中应关注的价位清单
        
        交易员需要知道今天盘中应该关注哪些价位：
        - 突破XX价位 → 加仓信号
        - 跌破XX价位 → 止损信号  
        - 回踩XX价位 → 买入机会
        
        Args:
            cost_price: 用户持仓成本价，>0 时启用持仓模式（加仓/减仓描述）
        """
        watchlist = []
        price = result.current_price
        has_position = cost_price > 0 and price > 0
        if price <= 0:
            result.intraday_watchlist = watchlist
            return

        pnl_pct: Optional[float] = None
        if has_position:
            pnl_pct = (price - cost_price) / cost_price * 100
        
        # 1. 止损价位（最重要）
        if result.stop_loss_intraday > 0:
            if has_position:
                sl_pnl = (result.stop_loss_intraday - cost_price) / cost_price * 100
                sl_desc = f'跌破{result.stop_loss_intraday:.2f}→日内止损，届时盈亏{sl_pnl:+.1f}%'
            else:
                sl_desc = f'跌破{result.stop_loss_intraday:.2f}→短线止损离场'
            watchlist.append({
                'price': result.stop_loss_intraday,
                'type': 'stop_loss',
                'action': '日内止损',
                'desc': sl_desc,
                'priority': 1,
            })
        if result.stop_loss_short > 0 and result.stop_loss_short != result.stop_loss_intraday:
            if has_position:
                sl_pnl = (result.stop_loss_short - cost_price) / cost_price * 100
                sl_desc = f'跌破{result.stop_loss_short:.2f}→短线止损，届时盈亏{sl_pnl:+.1f}%'
            else:
                sl_desc = f'跌破{result.stop_loss_short:.2f}→短线止损'
            watchlist.append({
                'price': result.stop_loss_short,
                'type': 'stop_loss',
                'action': '短线止损',
                'desc': sl_desc,
                'priority': 1,
            })
        
        # 1b. 成本线（持仓时插入，作为重要心理位）
        if has_position:
            cp_dist_pct = (price - cost_price) / price * 100
            if abs(cp_dist_pct) < 15:  # 距离成本不超过15%才有盘中监控意义
                pnl_str = f'+{pnl_pct:.1f}%' if pnl_pct >= 0 else f'{pnl_pct:.1f}%'
                watchlist.append({
                    'price': cost_price,
                    'type': 'cost_line',
                    'action': '持仓成本',
                    'desc': f'成本线{cost_price:.2f}（当前浮盈{pnl_str}），跌破后止损出场',
                    'priority': 1,
                })
        
        # 2. 买入/加仓价位
        if result.ideal_buy_anchor > 0 and result.ideal_buy_anchor < price:
            if has_position:
                buy_desc = f'回踩{result.ideal_buy_anchor:.2f}(MA5/MA10)→加仓机会'
            else:
                buy_desc = f'回踩{result.ideal_buy_anchor:.2f}(MA5/MA10)→建仓买入机会'
            watchlist.append({
                'price': result.ideal_buy_anchor,
                'type': 'buy',
                'action': '加仓点' if has_position else '建仓点',
                'desc': buy_desc,
                'priority': 2,
            })
        
        # 3. 突破价位（阻力位）
        if result.resistance_levels:
            first_res = result.resistance_levels[0]
            if has_position:
                _brk_action = '突破加仓'
                _brk_desc = f'突破{first_res:.2f}(第一阻力)→确认上攻，可加仓'
            else:
                _brk_action = '追入信号'
                _brk_desc = f'突破{first_res:.2f}(第一阻力)→确认上攻，可考虑入场'
            watchlist.append({
                'price': first_res,
                'type': 'breakout',
                'action': _brk_action,
                'desc': _brk_desc,
                'priority': 2,
            })
        
        # 4. 止盈/目标价位
        if result.take_profit_short > 0:
            if has_position:
                _tp_action = '短线止盈'
                _tp_desc = f'到达{result.take_profit_short:.2f}→第一批止盈(1/3仓位)'
            else:
                _tp_action = '目标价位'
                _tp_desc = f'到达{result.take_profit_short:.2f}→短线目标价位，可分批止盈'
            watchlist.append({
                'price': result.take_profit_short,
                'type': 'take_profit',
                'action': _tp_action,
                'desc': _tp_desc,
                'priority': 3,
            })
        
        # 5. 均线支撑（MA20是中线生命线）
        if result.ma20 > 0 and result.ma20 < price:
            dist_pct = (price - result.ma20) / price * 100
            if dist_pct < 5:  # 距离MA20较近才有意义
                watchlist.append({
                    'price': result.ma20,
                    'type': 'support',
                    'action': 'MA20支撑',
                    'desc': f'跌破{result.ma20:.2f}(MA20)→中线趋势转弱',
                    'priority': 2,
                })
        
        # 6. 布林带上下轨
        if result.bb_upper > 0 and result.bb_upper > price:
            watchlist.append({
                'price': result.bb_upper,
                'type': 'resistance',
                'action': '布林上轨',
                'desc': f'触及{result.bb_upper:.2f}(布林上轨)→短期压力，注意回落',
                'priority': 3,
            })
        if result.bb_lower > 0 and result.bb_lower < price:
            dist_pct = (price - result.bb_lower) / price * 100
            if dist_pct < 5:
                watchlist.append({
                    'price': result.bb_lower,
                    'type': 'support',
                    'action': '布林下轨',
                    'desc': f'触及{result.bb_lower:.2f}(布林下轨)→超卖区域，关注反弹',
                    'priority': 2,
                })
        
        # 按价格排序（从高到低）
        watchlist.sort(key=lambda x: x['price'], reverse=True)
        result.intraday_watchlist = watchlist

    @staticmethod
    def generate_detailed_advice(result: TrendAnalysisResult, signal_confirm_days: int = 0):
        """生成持仓/空仓的分离建议
        
        Args:
            result: 分析结果
            signal_confirm_days: 信号确认期（天），>0时首次出现买入信号会标注"待确认"
        """
        bias = result.bias_ma5
        trend = result.trend_status
        score = result.signal_score
        
        if score >= 85:
            result.advice_for_empty = f"技术面强势({score}分)，乖离{bias:.1f}%，可适当追高，止损{result.stop_loss_short:.2f}"
            if -3 <= bias <= 5:
                result.advice_for_holding = f"可加仓({score}分)，回踩MA5加仓，目标{result.take_profit_mid:.2f}，移动止盈{result.take_profit_trailing:.2f}"
            else:
                result.advice_for_holding = f"持有+移动止盈({score}分)，乖离{bias:.1f}%偏大不宜加仓，目标{result.take_profit_mid:.2f}"
        elif score >= 70:
            if -3 <= bias <= 3:
                result.advice_for_empty = f"回踩买点，可分批建仓({score}分)，止损{result.stop_loss_short:.2f}"
                result.advice_for_holding = f"可小幅加仓({score}分)，回踩MA5附近加仓，目标{result.take_profit_mid:.2f}"
            else:
                result.advice_for_empty = f"技术面偏强({score}分)但乖离{bias:.1f}%偏大，等回调至MA5附近"
                result.advice_for_holding = f"持有为主({score}分)，乖离偏大不加仓，分批止盈{result.take_profit_short:.2f}"
        elif score >= 60:
            result.advice_for_empty = f"谨慎乐观({score}分)，轻仓试探，止损{result.stop_loss_short:.2f}"
            result.advice_for_holding = f"持有观察({score}分)，不加仓，短线目标{result.take_profit_short:.2f}"
        elif score >= 50:
            result.advice_for_empty = f"观望为主({score}分)，等待更明确信号"
            result.advice_for_holding = f"持股待涨({score}分)，不加仓，止损{result.stop_loss_mid:.2f}"
        elif score >= 35:
            result.advice_for_empty = f"不建议入场({score}分)，信号偏弱"
            result.advice_for_holding = f"减仓观望({score}分)，止损{result.stop_loss_mid:.2f}，不加仓"
        else:
            result.advice_for_empty = f"空仓观望({score}分)，技术面偏空"
            result.advice_for_holding = f"建议清仓({score}分)，止损{result.stop_loss_mid:.2f}"
        
        if hasattr(result, '_conflict_warnings') and result._conflict_warnings:
            conflict_text = " | ".join(result._conflict_warnings)
            result.advice_for_empty = f"{result.advice_for_empty} [{conflict_text}]"
            result.advice_for_holding = f"{result.advice_for_holding} [{conflict_text}]"

    @staticmethod
    def generate_holding_horizon(result: TrendAnalysisResult) -> Dict[str, Any]:
        """
        生成持仓时间维度建议（短线/中线/长线三档评级）

        基于现有技术指标和基本面数据，为不同时间周期的持仓策略给出星级评分（0-3星）和依据。
        注意：此方法只做纯规则计算，不修改 result 字段。
        """
        score = result.signal_score or 0
        trend = result.trend_status
        macd = result.macd_status
        rsi_status = result.rsi_status
        bb_width = getattr(result, 'bb_width', 0) or 0
        vr = result.volume_ratio or 1.0
        weekly = getattr(result, 'weekly_trend', '') or ''
        valuation_verdict = getattr(result, 'valuation_verdict', '') or ''
        fundamental_score = getattr(result, 'fundamental_score', 5) or 5
        fundamental_signal = getattr(result, 'fundamental_signal', '') or ''
        pb_ratio = getattr(result, 'pb_ratio', 0) or 0
        _is_strong_bear = trend == TrendStatus.STRONG_BEAR
        _is_bear = trend in [TrendStatus.BEAR, TrendStatus.STRONG_BEAR]

        weekly_strong_bull = '多头' in weekly and '弱' not in weekly
        weekly_bull = '多头' in weekly or '弱多头' in weekly

        # ── 短线评分 (博弈1-10天) ────────────────────────────────────
        s_score = 0
        s_reasons: list = []

        # 修复1: RSI超卖在强空头趋势下是飞刀，不加分
        rsi_oversold = rsi_status in [RSIStatus.OVERSOLD, RSIStatus.GOLDEN_CROSS_OVERSOLD]
        if rsi_oversold and not _is_strong_bear:
            s_score += 2
            s_reasons.append("RSI超卖")

        # 修复2: 布林带收口需方向确认，空头趋势收口是下杀蓄力，不是做多信号
        if bb_width > 0 and bb_width < 0.06 and not _is_bear:
            s_score += 2
            s_reasons.append("布林带收口（蓄势待发）")

        if vr >= 2.0:
            s_score += 1
            s_reasons.append(f"量比{vr:.1f}x异动")

        if macd in [MACDStatus.GOLDEN_CROSS, MACDStatus.GOLDEN_CROSS_ZERO]:
            s_score += 1
            s_reasons.append("MACD金叉")

        if trend in [TrendStatus.STRONG_BULL, TrendStatus.BULL]:
            s_score += 1
            s_reasons.append("日线趋势支撑")
        elif _is_strong_bear:
            s_score -= 1

        s_score = max(0, min(5, s_score))
        s_stars = 0 if s_score <= 1 else (1 if s_score <= 2 else (2 if s_score <= 3 else 3))

        # ── 中线评分 (趋势10-30天) ───────────────────────────────────
        m_score = 0
        m_reasons: list = []

        if weekly_strong_bull:
            m_score += 2
            m_reasons.append("周线强多头")
        elif weekly_bull:
            m_score += 1
            m_reasons.append("周线多头")

        if trend == TrendStatus.STRONG_BULL:
            m_score += 2
            m_reasons.append("日线强多头")
        elif trend in [TrendStatus.BULL, TrendStatus.WEAK_BULL]:
            m_score += 1
            m_reasons.append("日线偏多")
        elif _is_bear:
            m_score -= 1

        if score >= 70:
            m_score += 1
            m_reasons.append(f"技术面{score}分")
        elif score < 35:
            m_score -= 1

        m_score = max(0, min(5, m_score))
        m_stars = 0 if m_score <= 1 else (1 if m_score <= 2 else (2 if m_score <= 3 else 3))

        # ── 长线评分 (价值30天+) ─────────────────────────────────────
        # 修复3: 去掉板块强势（短中期因素），加入基本面质量检验，规避价值陷阱
        l_score = 0
        l_reasons: list = []
        l_warnings: list = []

        # 基本面数据可用性判断（efinance/akshare 被封时 fundamental_score 停留在默认值 5）
        # 判据：pb_ratio>0 或 fundamental_signal 不为空 → 有真实数据
        _fundamental_available = pb_ratio > 0 or bool(fundamental_signal) or fundamental_score != 5

        if not _fundamental_available:
            l_warnings.append("基本面数据暂不可用（可能因数据源封禁）")

        # 价值陷阱检测：低PB但基本面差 = 钢铁/煤炭等周期陷阱（仅在数据可用时检测）
        _is_value_trap = _fundamental_available and (
            (0 < pb_ratio < 1.2 and fundamental_score < 4)
            or any(k in fundamental_signal for k in ('亏损', '利润下滑', 'ST', '连续亏'))
        )

        if '低估' in valuation_verdict:
            if _is_value_trap:
                l_warnings.append("低估但基本面弱（疑似价值陷阱）")
            else:
                l_score += 2
                l_reasons.append("估值低估")
        elif '合理' in valuation_verdict:
            l_score += 1
            l_reasons.append("估值合理")
        elif any(k in valuation_verdict for k in ('高估', '泡沫', '偏高')):
            l_score -= 1

        # 基本面质量 — ROE/成长性综合评分（用fundamental_score代理）
        # 数据不可用时跳过，避免用默认值5给出虚假评分
        if _fundamental_available:
            if fundamental_score >= 7:
                l_score += 2
                l_reasons.append(f"基本面优质(评分{fundamental_score}/10)")
            elif fundamental_score >= 5:
                l_score += 1
                l_reasons.append("基本面稳健")
            elif fundamental_score < 3:
                l_score -= 1
                l_warnings.append("基本面偏弱")

        if weekly_strong_bull:
            l_score += 1
            l_reasons.append("周线趋势强劲")

        if score >= 78:
            l_score += 1
            l_reasons.append("技术面良好")
        elif score < 35:
            l_score -= 2

        l_score = max(0, min(5, l_score))
        l_stars = 0 if l_score <= 1 else (1 if l_score <= 2 else (2 if l_score <= 3 else 3))
        # 有价值陷阱警告时，长线最多1星
        if l_warnings and l_stars > 1:
            l_stars = 1

        # ── 推荐结论 ─────────────────────────────────────────────────
        stars_map = {'short': s_stars, 'mid': m_stars, 'long': l_stars}
        max_stars = max(stars_map.values())

        if max_stars == 0:
            recommended = 'none'
            summary = "当前三个时间维度信号均偏弱，建议观望等待更明确信号"
        else:
            best = max(stars_map, key=stars_map.get)
            recommended = best
            if best == 'short':
                r = '、'.join(s_reasons[:3]) if s_reasons else '短线技术信号'
                summary = f"短线机会突出：{r}，适合博弈短期波动（1-10天）"
            elif best == 'mid':
                r = '、'.join(m_reasons[:3]) if m_reasons else '中线趋势信号'
                summary = f"中线持有价值较高：{r}，建议中线参与（10-30天）"
            else:
                r = '、'.join(l_reasons[:3]) if l_reasons else '基本面支撑'
                summary = f"长线布局价值突出：{r}，适合长线持有（30天+）"
                if l_warnings:
                    summary += f"；⚠️ {l_warnings[0]}"

        return {
            'short': {'stars': s_stars, 'score': s_score, 'reasons': s_reasons[:4], 'horizon': '1-10天'},
            'mid':   {'stars': m_stars, 'score': m_score, 'reasons': m_reasons[:4], 'horizon': '10-30天'},
            'long':  {'stars': l_stars, 'score': l_score, 'reasons': l_reasons[:4], 'horizon': '30天+', 'warnings': l_warnings},
            'recommended': recommended,
            'summary': summary,
        }

    @staticmethod
    def generate_holding_strategy(
        result: TrendAnalysisResult,
        cost_price: float = 0.0,
        current_price: Optional[float] = None,
    ) -> Dict[str, Any]:
        """生成统一的持仓者策略（供 PushPlus / Web / API 共用）

        根据 评分 × 盈亏状态 × 趋势 三维度推荐止损止盈，
        同时暴露所有量化锚点让用户自主决策。

        Args:
            result: 量化分析结果
            cost_price: 用户持仓成本（0=未知）
            current_price: 当前价格（默认取 result.current_price）

        Returns:
            结构化 dict，字段见代码注释
        """
        price = current_price if current_price and current_price > 0 else result.current_price
        score = result.signal_score
        sl_short = result.stop_loss_short
        sl_mid = result.stop_loss_mid
        trailing = result.take_profit_trailing
        tp_short = result.take_profit_short
        tp_mid = result.take_profit_mid

        # ---------- 盈亏状态 ----------
        pnl_pct: Optional[float] = None
        if cost_price > 0 and price > 0:
            pnl_pct = (price - cost_price) / cost_price * 100

        # ---------- 推荐止损 ----------
        rec_stop: float
        rec_stop_type: str
        rec_stop_reason: str

        if pnl_pct is not None:
            # 有成本信息：评分 × 盈亏 综合判断
            if score >= 70 and pnl_pct >= 5:
                # 强势盈利：移动止盈线保护利润
                rec_stop = trailing
                rec_stop_type = "trailing"
                rec_stop_reason = f"强势盈利({score}分, +{pnl_pct:.1f}%)，移动止盈线锁定利润"
            elif score >= 50 and pnl_pct > 0:
                # 盈利但不强势
                if trailing > cost_price:
                    rec_stop = trailing
                    rec_stop_type = "trailing"
                    rec_stop_reason = f"移动止盈线({trailing:.2f})高于成本({cost_price:.2f})，可锁定部分利润"
                else:
                    rec_stop = sl_short
                    rec_stop_type = "short"
                    rec_stop_reason = f"盈利但从高点回落较多，紧守短线止损"
            elif score >= 50 and pnl_pct <= 0:
                # 浮亏但技术面中性偏好
                rec_stop = sl_mid
                rec_stop_type = "mid"
                rec_stop_reason = f"暂时浮亏({pnl_pct:.1f}%)但技术面尚可({score}分)，中线止损给反弹空间"
            elif score >= 35:
                # 弱势
                rec_stop = sl_short
                rec_stop_type = "short"
                rec_stop_reason = f"技术面偏弱({score}分)，紧守短线止损准备离场"
            else:
                # 极弱
                rec_stop = sl_short
                rec_stop_type = "short"
                rec_stop_reason = f"技术面极弱({score}分)，建议尽快止损离场"
        else:
            # 无成本信息：纯技术面推荐
            if score >= 70:
                rec_stop = trailing
                rec_stop_type = "trailing"
                rec_stop_reason = f"强势({score}分)，移动止盈线跟踪"
            elif score >= 50:
                rec_stop = sl_mid
                rec_stop_type = "mid"
                rec_stop_reason = f"中性({score}分)，中线止损防守"
            elif score >= 35:
                rec_stop = sl_short
                rec_stop_type = "short"
                rec_stop_reason = f"偏弱({score}分)，短线止损防守"
            else:
                rec_stop = sl_short
                rec_stop_type = "short"
                rec_stop_reason = f"极弱({score}分)，建议止损离场"

        # ---------- 防护：推荐值为0时降级 ----------
        if rec_stop <= 0:
            # 按优先级降级：trailing → short → mid
            for fallback, fb_type in [(trailing, "trailing"), (sl_short, "short"), (sl_mid, "mid")]:
                if fallback > 0:
                    rec_stop = fallback
                    rec_stop_type = fb_type
                    _labels = {"trailing": "移动止盈线", "short": "短线止损", "mid": "中线止损"}
                    rec_stop_reason = f"({_labels.get(fb_type, fb_type)}降级)"
                    break

        # ---------- 推荐止盈目标 ----------
        if score >= 70:
            rec_target = tp_mid
            rec_target_type = "mid"
        else:
            rec_target = tp_short
            rec_target_type = "short"

        # ---------- 综合建议文本 ----------
        advice = RiskManager._build_holding_advice_text(
            score, pnl_pct, rec_stop, rec_stop_type, rec_target, rec_target_type,
            trailing, sl_short, sl_mid, tp_short, tp_mid, cost_price,
        )

        return {
            # 推荐止损
            "recommended_stop": round(rec_stop, 2),
            "recommended_stop_type": rec_stop_type,
            "recommended_stop_reason": rec_stop_reason,
            # 推荐止盈
            "recommended_target": round(rec_target, 2),
            "recommended_target_type": rec_target_type,
            # 所有锚点
            "stop_loss_short": round(sl_short, 2),
            "stop_loss_mid": round(sl_mid, 2),
            "trailing_stop": round(trailing, 2),
            "target_short": round(tp_short, 2),
            "target_mid": round(tp_mid, 2),
            # 综合建议
            "advice": advice,
            # 空仓入场参考
            "entry_stop_loss": round(sl_short, 2),
            "entry_position_pct": result.suggested_position_pct,
            "entry_advice": result.advice_for_empty,
        }

    @staticmethod
    def _build_holding_advice_text(
        score: int,
        pnl_pct: Optional[float],
        rec_stop: float,
        rec_stop_type: str,
        rec_target: float,
        rec_target_type: str,
        trailing: float,
        sl_short: float,
        sl_mid: float,
        tp_short: float,
        tp_mid: float,
        cost_price: float,
    ) -> str:
        """生成持仓者综合建议文本"""
        parts: List[str] = []

        if score >= 85:
            parts.append(f"强势持有({score}分)")
            parts.append(f"移动止盈{trailing:.2f}跟踪")
            parts.append(f"目标看{tp_mid:.2f}")
        elif score >= 70:
            parts.append(f"持有为主({score}分)")
            parts.append(f"止盈参考{tp_mid:.2f}")
            parts.append(f"跌破{rec_stop:.2f}减仓")
        elif score >= 60:
            parts.append(f"持有观察({score}分)")
            parts.append(f"短线目标{tp_short:.2f}")
            if rec_stop_type == "trailing":
                parts.append(f"移动止盈线{rec_stop:.2f}")
            else:
                parts.append(f"止损守{rec_stop:.2f}")
        elif score >= 50:
            if pnl_pct is not None and pnl_pct > 0:
                parts.append(f"持股待涨({score}分)")
                parts.append(f"止盈线{rec_stop:.2f}")
                parts.append(f"不加仓")
            else:
                parts.append(f"耐心持有({score}分)")
                parts.append(f"止损{rec_stop:.2f}不可破")
                parts.append(f"反弹至{tp_short:.2f}可减仓")
        elif score >= 35:
            parts.append(f"考虑减仓({score}分)")
            parts.append(f"跌破{rec_stop:.2f}果断离场")
        else:
            parts.append(f"建议清仓({score}分)")
            parts.append(f"止损{rec_stop:.2f}")

        return "，".join(parts)

    @staticmethod
    def generate_trade_advice(result: TrendAnalysisResult, position_info: Optional[Dict[str, Any]] = None):
        """
        基于回测场景识别生成操作建议（L1→L4层级递进框架）

        场景识别优先级（按强度从高到低）：
        A: STRONG_BEAR + very_high换手 → 超跌反弹场景（20d预期+4-6%，胜率61%+）
        B: WEAK_BULL + very_high换手 → 弱势多头资金异动（20d预期+2-3%，胜率53%+）
        C: STRONG_BULL + very_high换手 → 强势趋势共振（20d预期+3-4%，胜率57%+）
        D: 任意趋势 + RSI超卖 + very_high换手 → 超卖反弹共振（20d预期+4-6%）
        E: 警示场景（低换手+缩量上涨 / WEAK_BULL+缩量回调）
        F: 无明显场景信号
        """
        price = result.current_price
        trend = result.trend_status
        tp = getattr(result, 'turnover_percentile', 0.0) or 0.0
        vol = result.volume_status
        macd = result.macd_status
        rsi = result.rsi_status
        sl_short = result.stop_loss_short or 0.0
        sl_mid = result.stop_loss_mid or 0.0
        tp_short = result.take_profit_short or 0.0
        tp_mid = result.take_profit_mid or 0.0
        score = result.signal_score

        # 持仓信息
        cost_price = float(position_info.get('cost_price', 0) or 0) if position_info else 0.0
        has_position = cost_price > 0
        pnl_pct: Optional[float] = None
        if has_position and price > 0:
            pnl_pct = (price - cost_price) / cost_price * 100

        # ── 场景识别 ────────────────────────────────────────────────
        scenario_id = "none"
        scenario_label = ""
        scenario_confidence = "低"
        expected_20d = ""
        win_rate = ""
        base_position = 0

        # 盘中状态判断
        from datetime import datetime as _dt_gta
        _is_intraday = _dt_gta.now().hour < 15
        vr = getattr(result, 'volume_ratio', 1.0) or 1.0

        # 换手率分级
        tp_confidence = getattr(result, 'turnover_percentile_confidence', '') or ''
        _tp_is_intraday_est = tp_confidence == "盘中折算估算"   # 已用折算值（方案2）
        _tp_is_default = abs(tp - 0.5) < 0.01 and not _tp_is_intraday_est  # 真正未计算（无turnover_rate）
        _intraday_vol_proxy = _is_intraday and _tp_is_default  # 无折算值时才用量比代理（方案3）

        # 量比>=2.5 代理 "极高换手"，量比>=1.8 代理 "偏高换手"（仅量比代理时用）
        _vr_very_high = vr >= 2.5
        _vr_high = vr >= 1.8

        turn_very_high = tp >= 0.9 or (_intraday_vol_proxy and _vr_very_high)
        turn_high = tp >= 0.7 or (_intraday_vol_proxy and _vr_high)
        # 盘中（折算估算或量比代理）不判低换手，数据不足以确认
        turn_low = tp <= 0.1 and not _is_intraday
        turn_very_low = tp <= 0.1 and not _is_intraday

        # 盘中（折算估算 or 量比代理）触发时，置信度降档
        _confidence_downgrade = _is_intraday and (turn_very_high or turn_high)

        # RSI超卖判断
        rsi_oversold = rsi in [RSIStatus.OVERSOLD, RSIStatus.GOLDEN_CROSS_OVERSOLD]

        # 量能状态
        vol_shrink_up = vol == VolumeStatus.SHRINK_VOLUME_UP
        vol_shrink_down = vol == VolumeStatus.SHRINK_VOLUME_DOWN
        vol_heavy_up = vol == VolumeStatus.HEAVY_VOLUME_UP

        # 场景D（最高优先级）：RSI超卖 + very_high换手（无论趋势）
        if rsi_oversold and turn_very_high:
            scenario_id = "D"
            if trend == TrendStatus.STRONG_BEAR:
                scenario_label = "超卖反弹共振（空头区RSI超卖+极高换手）"
                expected_20d = "+4-6%"
                win_rate = "~60%"
                scenario_confidence = "高"
                base_position = 25
            else:
                scenario_label = "RSI超卖+资金异动共振"
                expected_20d = "+3-5%"
                win_rate = "~58%"
                scenario_confidence = "高"
                base_position = 25

        # 场景A：STRONG_BEAR + very_high换手
        elif trend == TrendStatus.STRONG_BEAR and turn_very_high:
            scenario_id = "A"
            if vol_heavy_up:
                scenario_label = "超跌反弹-极强场景（空头区放量+极高换手）"
                expected_20d = "+6%"
                win_rate = "61%"
                scenario_confidence = "高"
                base_position = 30
            else:
                scenario_label = "超跌反弹场景（强势空头+极高换手）"
                expected_20d = "+4-6%"
                win_rate = "61%"
                scenario_confidence = "高"
                base_position = 25

        # 场景B：WEAK_BULL + very_high换手
        elif trend == TrendStatus.WEAK_BULL and turn_very_high:
            scenario_id = "B"
            if vol_heavy_up:
                scenario_label = "弱势多头量能突破（极高换手+放量上涨）"
                expected_20d = "+3-4%"
                win_rate = "53%"
                scenario_confidence = "高"
                base_position = 35
            else:
                scenario_label = "弱势多头资金异动（极高换手）"
                expected_20d = "+2-3%"
                win_rate = "54%"
                scenario_confidence = "高"
                base_position = 30

        # 场景C：STRONG_BULL + very_high换手
        elif trend == TrendStatus.STRONG_BULL and turn_very_high:
            scenario_id = "C"
            scenario_label = "强势趋势+资金共振（强多头+极高换手）"
            expected_20d = "+3-4%"
            win_rate = "57%"
            scenario_confidence = "高"
            base_position = 45

        # BULL + very_high换手（中强）
        elif trend == TrendStatus.BULL and turn_very_high:
            scenario_id = "C2"
            scenario_label = "多头趋势+资金激活（多头+极高换手）"
            expected_20d = "+2%"
            win_rate = "55%"
            scenario_confidence = "中"
            base_position = 35

        # STRONG_BEAR + high换手（次强反弹）
        elif trend == TrendStatus.STRONG_BEAR and turn_high:
            scenario_id = "A2"
            scenario_label = "超跌反弹潜力（强势空头+偏高换手）"
            expected_20d = "+2%"
            win_rate = "54%"
            scenario_confidence = "中"
            base_position = 15

        # 场景E：警示场景
        elif vol_shrink_up and turn_low:
            scenario_id = "E1"
            scenario_label = "假突破警示（低换手+缩量上涨）"
            expected_20d = "-1.5%~-4%"
            win_rate = "~44%"
            scenario_confidence = "高"
            base_position = 0
        elif trend == TrendStatus.WEAK_BULL and vol_shrink_down and not turn_high:
            scenario_id = "E2"
            scenario_label = "弱势多头缩量回调（阴跌风险）"
            expected_20d = "-0.5%~-2%"
            win_rate = "~40%"
            scenario_confidence = "中"
            base_position = 0
        elif trend == TrendStatus.BEAR:
            scenario_id = "E3"
            scenario_label = "空头排列回避区"
            expected_20d = "<-1%"
            win_rate = "<45%"
            scenario_confidence = "高"
            base_position = 0
        else:
            scenario_id = "none"
            scenario_label = "无明显场景信号"
            expected_20d = "基准±1%"
            win_rate = "~50%"
            scenario_confidence = "低"
            base_position = 0

        # 盘中触发时，置信度降档并在标签中标注数据来源
        if _confidence_downgrade and scenario_id not in ("none", "E1", "E2", "E3"):
            _confidence_map = {"高": "中", "中": "低", "低": "低"}
            scenario_confidence = _confidence_map.get(scenario_confidence, "低")
            if "盘中" not in scenario_label:
                if _tp_is_intraday_est:
                    scenario_label = f"{scenario_label}（盘中换手率折算估算，待收盘确认）"
                else:
                    scenario_label = f"{scenario_label}（盘中量比代理估算，待收盘确认）"

        # ── 生成操作建议文本 ──────────────────────────────────────────
        sl_ref = sl_short if sl_short > 0 else sl_mid
        tp_ref = tp_short if tp_short > 0 else 0.0

        # 空仓者建议
        if scenario_id.startswith("E") or scenario_id == "none":
            if scenario_id == "E1":
                advice_empty = f"⚠️ 不建议入场：低换手缩量上涨为假突破信号（回测20d均-1.5%～-4%），等待量能放大再看"
            elif scenario_id == "E2":
                advice_empty = f"⚠️ 暂不入场：弱势多头缩量回调，有阴跌风险，等待换手率回升或趋势企稳"
            elif scenario_id == "E3":
                advice_empty = f"❌ 回避：空头排列趋势，历史回测20d均-0.96%，等待趋势扭转再考虑"
            else:
                advice_empty = f"观望为主：当前无强信号场景，等待换手率异动（>70th分位）或趋势明确后介入"
        else:
            pos_pct = min(base_position, result.suggested_position_pct or 50) if result.suggested_position_pct else base_position
            sl_str = f"止损{sl_ref:.2f}" if sl_ref > 0 else "止损参考MA20"
            tp_str = f"目标{tp_ref:.2f}" if tp_ref > 0 else ""
            advice_empty = (
                f"✅ 【场景{scenario_id}：{scenario_label}】"
                f"可考虑建仓（仓位≤{pos_pct}%），"
                f"预期20日收益{expected_20d}，胜率{win_rate}。"
                f"{sl_str}，持有15-20日。"
                + (f" {tp_str}" if tp_str else "")
            )

        # 持仓者建议
        if has_position and pnl_pct is not None:
            pnl_str = f"+{pnl_pct:.1f}%" if pnl_pct >= 0 else f"{pnl_pct:.1f}%"
            if scenario_id.startswith("E") or scenario_id == "E3":
                advice_holding = (
                    f"⚠️ 持仓风险：当前场景（{scenario_label}）对持仓不利，浮盈{pnl_str}。"
                    f"建议{('止盈减仓' if pnl_pct > 0 else '止损离场')}，"
                    f"跌破{sl_ref:.2f}必须执行止损。"
                ) if sl_ref > 0 else (
                    f"⚠️ 持仓风险：{scenario_label}，浮盈{pnl_str}，考虑减仓。"
                )
            elif scenario_id in ("C", "C2", "A", "D") and pnl_pct >= 0:
                advice_holding = (
                    f"✅ 持股续涨：{scenario_label}，当前浮盈{pnl_str}，场景预期{expected_20d}。"
                    f"建议持有，移动止盈跟踪（当前止损{sl_ref:.2f}）。"
                ) if sl_ref > 0 else (
                    f"✅ 持股续涨：{scenario_label}，浮盈{pnl_str}，建议持有。"
                )
            elif scenario_id in ("B",) and pnl_pct >= 0:
                advice_holding = (
                    f"持有观察：{scenario_label}，浮盈{pnl_str}，预期{expected_20d}。"
                    f"止损守{sl_ref:.2f}，反弹至{tp_ref:.2f}可部分止盈。"
                ) if sl_ref > 0 and tp_ref > 0 else (
                    f"持有观察：{scenario_label}，浮盈{pnl_str}，持有15日。"
                )
            elif pnl_pct < -5 and score < 50:
                advice_holding = (
                    f"⚠️ 浮亏{pnl_str}且技术面偏弱（评分{score}），"
                    f"建议止损，跌破{sl_ref:.2f}果断离场。"
                ) if sl_ref > 0 else (
                    f"⚠️ 浮亏{pnl_str}且技术面偏弱，考虑止损。"
                )
            else:
                advice_holding = (
                    f"持有等待：{scenario_label or '无强信号'}，当前{pnl_str}。"
                    f"止损守{sl_ref:.2f}"
                    + (f"，目标{tp_ref:.2f}" if tp_ref > 0 else "")
                    + "。"
                ) if sl_ref > 0 else (
                    f"持有等待：当前{pnl_str}，等待信号明确。"
                )
        else:
            # 无持仓信息时的通用持仓建议
            if score >= 70 and not scenario_id.startswith("E"):
                advice_holding = (
                    f"强势持仓：{scenario_label or '技术面良好'}（评分{score}），"
                    f"移动止盈跟踪，跌破{sl_ref:.2f}减仓。"
                ) if sl_ref > 0 else f"强势持仓（评分{score}），持有为主。"
            elif score >= 50:
                advice_holding = (
                    f"持股观察（评分{score}），止损守{sl_ref:.2f}，"
                    f"无明显卖点前继续持有。"
                ) if sl_ref > 0 else f"持股观察（评分{score}）。"
            else:
                advice_holding = (
                    f"考虑减仓（评分{score}偏弱），跌破{sl_ref:.2f}果断离场。"
                ) if sl_ref > 0 else f"考虑减仓（评分{score}偏弱）。"

        # 写入result字段
        result.scenario_id = scenario_id
        result.scenario_label = scenario_label
        result.scenario_confidence = scenario_confidence
        result.scenario_expected_20d = expected_20d
        result.scenario_win_rate = win_rate
        result.trade_advice_empty = advice_empty
        result.trade_advice_holding = advice_holding
        result.trade_advice_position_pct = base_position

    @staticmethod
    def check_stop_loss_distance(result: TrendAnalysisResult, atr_multiplier: float = 2.0):
        """
        P0 止损硬约束：当前价距短线止损位超过 atr_multiplier × ATR14 时，警告空仓者不宜追入。

        使用 ATR 倍数而非固定百分比，因为不同股票波动幅度差异巨大：
        - 小盘妖股 ATR 可达 5-10%，固定阈值会失真
        - 蓝筹白马 ATR 仅 1-2%，固定阈值过宽
        - 2×ATR = 追入后若止损，实际亏损已超该股两个正常波动单位
        - 仅影响空仓建议（advice_for_empty）和评分，不干预持仓逻辑
        """
        price = result.current_price
        sl = result.stop_loss_short
        atr = result.atr14
        if price <= 0 or sl <= 0 or atr <= 0:
            return

        dist = price - sl
        threshold = atr_multiplier * atr
        if dist > threshold:
            dist_pct = dist / price * 100
            warning = (
                f"⚠️ 当前价距止损位{dist_pct:.1f}%（>{atr_multiplier:.0f}×ATR={threshold:.2f}元），"
                f"追入风险过大，等待回踩再入场"
            )
            result.risk_factors.append(warning)
            result.score_breakdown['stop_dist_risk'] = -5
            if result.advice_for_empty:
                result.advice_for_empty = warning + "\n" + result.advice_for_empty
            else:
                result.advice_for_empty = warning

    @staticmethod
    def calc_atr_trailing_stop(
        df: pd.DataFrame,
        cost_price: float,
        current_price: float,
        prev_atr_stop: Optional[float] = None,
        prev_highest: Optional[float] = None,
        atr_multiplier: float = 2.0,
        atr_period: int = 14,
    ) -> Dict[str, Any]:
        """
        计算 ATR 动态追踪止损线（只上移不下移）

        逻辑：
        1. 计算 ATR(14)
        2. 新止损候选 = 当前最高价 - atr_multiplier × ATR
        3. 取 max(prev_atr_stop, 新止损候选)：只上移
        4. 若 current_price <= atr_stop → 触发止损信号

        Args:
            df: 历史日线K线（需要至少 atr_period+1 行）
            cost_price: 买入成本价
            current_price: 当前价
            prev_atr_stop: 上次记录的ATR止损价（None表示首次计算）
            prev_highest: 上次记录的最高价（None表示首次计算）
            atr_multiplier: ATR倍数，默认2.0
            atr_period: ATR计算周期，默认14

        Returns:
            {
                'atr': float,                 # 当前ATR值
                'atr_stop': float,            # 新的ATR追踪止损价
                'highest_price': float,       # 更新后的最高价
                'stop_triggered': bool,       # 是否触发止损
                'pnl_pct': float,             # 当前浮盈%
                'stop_pnl_pct': float,        # 止损位对应浮盈%（可能为负）
            }
        """
        result: Dict[str, Any] = {
            'atr': 0.0,
            'atr_stop': 0.0,
            'highest_price': current_price,
            'stop_triggered': False,
            'pnl_pct': 0.0,
            'stop_pnl_pct': 0.0,
        }

        if df is None or len(df) < atr_period + 1 or current_price <= 0:
            return result

        # 计算 ATR
        try:
            high = df['high'].values
            low = df['low'].values
            close = df['close'].values
            tr_list = []
            for i in range(1, len(high)):
                tr = max(high[i] - low[i], abs(high[i] - close[i-1]), abs(low[i] - close[i-1]))
                tr_list.append(tr)
            if len(tr_list) < atr_period:
                return result
            # Wilder平滑（与indicators.py _calc_atr保持一致）
            atr = tr_list[0]
            for tr_val in tr_list[1:]:
                atr = (atr * (atr_period - 1) + tr_val) / atr_period
            atr = float(atr)
        except Exception:
            return result

        result['atr'] = round(atr, 4)

        # 更新最高价
        new_highest = max(current_price, prev_highest or cost_price)
        result['highest_price'] = round(new_highest, 2)

        # 计算新止损候选（基于最高价）
        candidate_stop = new_highest - atr_multiplier * atr

        # 只上移：取 max(上次止损, 新候选)
        if prev_atr_stop and prev_atr_stop > 0:
            atr_stop = max(prev_atr_stop, candidate_stop)
        else:
            # 首次计算：从成本价下方开始（不高于当前候选）
            initial_stop = cost_price - atr_multiplier * atr
            atr_stop = max(initial_stop, candidate_stop)

        result['atr_stop'] = round(atr_stop, 2)

        # 触发判断
        result['stop_triggered'] = current_price <= atr_stop

        # 浮盈计算
        if cost_price > 0:
            result['pnl_pct'] = round((current_price - cost_price) / cost_price * 100, 2)
            result['stop_pnl_pct'] = round((atr_stop - cost_price) / cost_price * 100, 2)

        return result
