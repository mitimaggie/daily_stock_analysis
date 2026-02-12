# -*- coding: utf-8 -*-
"""
风险管理模块
包含止损止盈、仓位管理、风险收益比计算等逻辑
"""

import logging
import pandas as pd
from typing import List, Tuple
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
        
        result.stop_loss_anchor = result.stop_loss_short
        result.ideal_buy_anchor = round(result.ma5 if result.ma5 > 0 else result.ma10, 2)
        
        if result.trend_status in [TrendStatus.STRONG_BULL, TrendStatus.BULL]:
            tp_multiplier_short = 2.0
            tp_multiplier_mid = 3.5
        elif result.trend_status == TrendStatus.CONSOLIDATION:
            tp_multiplier_short = 1.2
            tp_multiplier_mid = 2.0
        else:
            tp_multiplier_short = 1.5
            tp_multiplier_mid = 2.5
        
        result.take_profit_short = round(price + tp_multiplier_short * atr, 2)
        
        if result.resistance_levels:
            result.take_profit_mid = round(result.resistance_levels[0], 2)
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
        
        if result.ma5 > 0:
            support_set.add(result.ma5)
        if result.ma10 > 0:
            support_set.add(result.ma10)
        if result.ma20 > 0:
            support_set.add(result.ma20)
        if result.ma60 > 0:
            support_set.add(result.ma60)
        
        price = result.current_price

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
            avg_amount = (recent['volume'] * recent['close']).mean()
            # 部分数据源 volume 单位是手(100股)，需要适配
            # 如果 avg_amount 明显偏大（>1e12），说明 volume 单位是股
            if avg_amount > 1e12:
                avg_amount_wan = avg_amount / 10000
            else:
                avg_amount_wan = avg_amount * 100 / 10000  # volume是手 → 股 → 万元
            
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
            if isinstance(total_vol, (int, float)) and 0 < total_vol < 6000:
                reasons.append(f"🟡 两市成交额{total_vol:.0f}亿，市场冷清，不宜重仓")
                result.market_risk_cap = min(result.market_risk_cap, 30)

        # --- 汇总 ---
        if reasons:
            result.no_trade = True
            result.no_trade_reasons = reasons
            result.no_trade_severity = severity
            # 仓位上限约束
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
        vol_max = float(vol_window.max())
        vol_min = float(vol_window[:-1].min()) if len(vol_window) > 1 else latest_vol  # 排除当日
        
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
