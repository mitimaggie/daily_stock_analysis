# -*- coding: utf-8 -*-
"""
风险管理模块
包含止损止盈、仓位管理、风险收益比计算等逻辑
"""

import logging
import pandas as pd
from typing import List, Tuple, Dict, Any, Optional
from .types import TrendAnalysisResult, TrendStatus, MarketRegime

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
        
        if atr_percentile > 0.8:
            atr_multiplier_short = 1.5
            atr_multiplier_mid = 2.0
        elif atr_percentile < 0.2:
            atr_multiplier_short = 0.8
            atr_multiplier_mid = 1.2
        else:
            atr_multiplier_short = 1.0
            atr_multiplier_mid = 1.5

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
        if result.resistance_levels:
            nearest_resistance = result.resistance_levels[0]
            resistance_tp = round(nearest_resistance * 0.995, 2)  # 阻力位下方 0.5%
            # 只在阻力位高于现价且低于 ATR 止盈时才采纳（否则阻力位太低没参考价值）
            if price < resistance_tp < atr_tp_short:
                result.take_profit_short = resistance_tp
                result.score_breakdown['tp_capped_by_resistance'] = 1  # 仅作日志标记
            else:
                result.take_profit_short = atr_tp_short
        else:
            result.take_profit_short = atr_tp_short
        
        if result.resistance_levels:
            # take_profit_mid 取第二阻力位（若存在），否则 ATR 止盈
            mid_resistance = result.resistance_levels[1] if len(result.resistance_levels) > 1 else result.resistance_levels[0]
            result.take_profit_mid = round(mid_resistance * 0.995, 2)
        else:
            result.take_profit_mid = round(price + tp_multiplier_mid * atr, 2)
        
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
        # 根据信号确定性分级：普通→20%，强信号→40%，极强→50%
        has_resonance = bool(getattr(result, 'timeframe_resonance', ''))
        has_multi_resonance = getattr(result, 'resonance_count', 0) >= 3
        rr_good = result.risk_reward_ratio >= 2.0
        
        if score >= 90 and has_resonance and rr_good:
            # 极强信号：评分>90 + 多周期共振 + R:R>2
            cap = 50
        elif score >= 80 and (has_resonance or has_multi_resonance) and rr_good:
            # 强信号：评分>80 + (共振或多指标共振) + R:R>2
            cap = 40
        elif score >= 70 and rr_good:
            # 中强信号：评分>70 + R:R>2
            cap = 30
        else:
            # 普通信号
            cap = 20
        
        # 熊市环境额外压缩
        if market_regime == MarketRegime.BEAR:
            cap = min(cap, 20)
        
        result.suggested_position_pct = min(cap, max(0, position // 2))
        
        result.position_breakdown = {
            'base': base_position,
            'multipliers': multipliers,
            'final': position,
            'cap': cap,
            'cap_reason': f"{'极强' if cap >= 50 else '强' if cap >= 40 else '中强' if cap >= 30 else '普通'}信号",
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
    def compute_support_resistance_levels(df: pd.DataFrame, result: TrendAnalysisResult) -> Tuple[List[float], List[float]]:
        """
        计算支撑位和阻力位：Swing高低点 + 均线 + 整数关口 + 筹码峰值 (Q2增强)
        
        Args:
            df: K线数据
            result: 分析结果对象
            
        Returns:
            (支撑位列表, 阻力位列表)
        """
        support_set, resistance_set = set(), set()
        tail = df.tail(30)
        
        if len(tail) >= 5:
            for i in range(2, len(tail) - 2):
                h = float(tail.iloc[i]['high'])
                l = float(tail.iloc[i]['low'])
                prev_h = float(tail.iloc[i-1]['high'])
                prev_l = float(tail.iloc[i-1]['low'])
                next_h = float(tail.iloc[i+1]['high'])
                next_l = float(tail.iloc[i+1]['low'])
                
                if h > prev_h and h > next_h:
                    resistance_set.add(h)
                if l < prev_l and l < next_l:
                    support_set.add(l)
        
        price = result.current_price

        for ma_val in [result.ma5, result.ma10, result.ma20, result.ma60]:
            if ma_val > 0:
                if ma_val < price:
                    support_set.add(ma_val)
                elif ma_val > price:
                    resistance_set.add(ma_val)

        # Q2: 整数关口效应（A股特有：10/20/50/100等整数位有天然支撑/阻力）
        if price > 0:
            # 根据价格量级确定整数关口间距
            if price >= 100:
                step = 10
            elif price >= 50:
                step = 5
            elif price >= 10:
                step = 2
            else:
                step = 1
            # 找到价格附近的整数关口（上下各2个）
            base = int(price / step) * step
            for offset in range(-2, 3):
                level = base + offset * step
                if level > 0 and level != price:
                    if level < price:
                        support_set.add(float(level))
                    else:
                        resistance_set.add(float(level))

        supports = sorted([s for s in support_set if 0 < s < price], reverse=True)[:5]
        resistances = sorted([r for r in resistance_set if r > price])[:5]
        
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
            # 分别检测连续放量和连续缩量
            consecutive_up = 0
            for i in range(-1, -4, -1):
                v = float(df.iloc[i]['volume'])
                v_prev = float(df.iloc[i-1]['volume'])
                if v > v_prev * 1.1:
                    consecutive_up += 1
                else:
                    break
            
            consecutive_down = 0
            for i in range(-1, -4, -1):
                v = float(df.iloc[i]['volume'])
                v_prev = float(df.iloc[i-1]['volume'])
                if v < v_prev * 0.9:
                    consecutive_down += 1
                else:
                    break
            
            if consecutive_up >= 3:
                result.volume_trend_3d = "连续放量"
            elif consecutive_down >= 3:
                result.volume_trend_3d = "连续缩量"

    @staticmethod
    def generate_intraday_watchlist(result: TrendAnalysisResult, df: pd.DataFrame):
        """
        P1 盘中关键价位提醒：生成今日盘中应关注的价位清单
        
        交易员需要知道今天盘中应该关注哪些价位：
        - 突破XX价位 → 加仓信号
        - 跌破XX价位 → 止损信号  
        - 回踩XX价位 → 买入机会
        """
        watchlist = []
        price = result.current_price
        if price <= 0:
            result.intraday_watchlist = watchlist
            return
        
        # 1. 止损价位（最重要）
        if result.stop_loss_intraday > 0:
            watchlist.append({
                'price': result.stop_loss_intraday,
                'type': 'stop_loss',
                'action': '日内止损',
                'desc': f'跌破{result.stop_loss_intraday:.2f}→短线止损离场',
                'priority': 1,
            })
        if result.stop_loss_short > 0 and result.stop_loss_short != result.stop_loss_intraday:
            watchlist.append({
                'price': result.stop_loss_short,
                'type': 'stop_loss',
                'action': '短线止损',
                'desc': f'跌破{result.stop_loss_short:.2f}→短线止损',
                'priority': 1,
            })
        
        # 2. 买入/加仓价位
        if result.ideal_buy_anchor > 0 and result.ideal_buy_anchor < price:
            watchlist.append({
                'price': result.ideal_buy_anchor,
                'type': 'buy',
                'action': '理想买点',
                'desc': f'回踩{result.ideal_buy_anchor:.2f}(MA5/MA10)→买入/加仓机会',
                'priority': 2,
            })
        
        # 3. 突破价位（阻力位）
        if result.resistance_levels:
            first_res = result.resistance_levels[0]
            watchlist.append({
                'price': first_res,
                'type': 'breakout',
                'action': '突破加仓',
                'desc': f'突破{first_res:.2f}(第一阻力)→确认上攻，可加仓',
                'priority': 2,
            })
        
        # 4. 止盈价位
        if result.take_profit_short > 0:
            watchlist.append({
                'price': result.take_profit_short,
                'type': 'take_profit',
                'action': '短线止盈',
                'desc': f'到达{result.take_profit_short:.2f}→第一批止盈(1/3仓位)',
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
