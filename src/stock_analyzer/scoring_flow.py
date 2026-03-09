# -*- coding: utf-8 -*-
"""
评分系统 — ScoringFlow 模块
从 scoring.py 拆分，由 ScoringSystem 通过多继承聚合。
"""

import logging
from datetime import datetime
from typing import Dict, List, Union, Optional

import numpy as np
import pandas as pd
from collections import defaultdict
from .types import TrendAnalysisResult, BuySignal, MarketRegime, TrendStatus
from .types import VolumeStatus, MACDStatus, RSIStatus, KDJStatus
from data_provider.fundamental_types import FundamentalData, ValuationSnapshot, FinancialSummary, ForecastData
from data_provider.analysis_types import CapitalFlowData, SectorContext, QuoteExtra
from data_provider.realtime_types import ChipDistribution

logger = logging.getLogger(__name__)

_P4_GLOBAL_FAIL_TS: float = 0.0

class ScoringFlow:
    """ScoringFlow Mixin"""


    @staticmethod
    def score_capital_flow(result: TrendAnalysisResult, capital_flow: Union[CapitalFlowData, dict, None] = None):
        """资金面评分：主力资金（超大单+大单）+ 主力净占比 + 融资余额"""
        if capital_flow is None:
            return
        # 兼容 dict 和 CapitalFlowData
        if isinstance(capital_flow, dict):
            capital_flow = CapitalFlowData.from_dict(capital_flow)
        
        cf_score = 5
        cf_signals = []
        
        # === 主力资金（含超大单+大单拆分）===
        main_net = capital_flow.main_net_flow  # 万元
        daily_avg = capital_flow.daily_avg_amount  # 万元
        if isinstance(main_net, (int, float)):
            if isinstance(daily_avg, (int, float)) and daily_avg > 0:
                main_threshold = daily_avg * 0.05
                main_large_threshold = daily_avg * 0.15
            else:
                main_threshold = 5000
                main_large_threshold = 15000
            
            if main_net > main_large_threshold:
                cf_score += 3
                cf_signals.append(f"主力大幅净流入{main_net/10000:.1f}亿")
            elif main_net > main_threshold:
                cf_score += 2
                cf_signals.append(f"主力净流入{main_net/10000:.1f}亿")
            elif main_net < -main_large_threshold:
                cf_score -= 3
                cf_signals.append(f"⚠️主力大幅净流出{abs(main_net)/10000:.1f}亿")
            elif main_net < -main_threshold:
                cf_score -= 2
                cf_signals.append(f"⚠️主力净流出{abs(main_net)/10000:.1f}亿")
        
        # === 超大单独立评估（机构行为信号）===
        super_large = capital_flow.super_large_net  # 万元
        if isinstance(super_large, (int, float)):
            sl_threshold = (daily_avg * 0.08) if isinstance(daily_avg, (int, float)) and daily_avg > 0 else 8000
            if super_large > sl_threshold:
                cf_score += 1
                cf_signals.append(f"超大单净流入{super_large/10000:.1f}亿（机构买入信号）")
            elif super_large < -sl_threshold:
                cf_score -= 1
                cf_signals.append(f"⚠️超大单净流出{abs(super_large)/10000:.1f}亿（机构离场）")
        
        # === 主力净占比（比绝对值更有意义）===
        main_pct = capital_flow.main_net_flow_pct
        if isinstance(main_pct, (int, float)):
            if main_pct > 15:
                cf_score += 1
                cf_signals.append(f"主力净占比{main_pct:.1f}%（资金高度集中买入）")
            elif main_pct < -15:
                cf_score -= 1
                cf_signals.append(f"⚠️主力净占比{main_pct:.1f}%（资金集中流出）")
        
        # === 融资余额趋势（百分比阈值 ±3.5%）===
        margin_pct = capital_flow.margin_balance_change
        if isinstance(margin_pct, (int, float)):
            if margin_pct > 3.5:
                cf_score += 1
                cf_signals.append(f"融资余额增加{margin_pct:.1f}%")
            elif margin_pct < -3.5:
                cf_score -= 1
                cf_signals.append(f"融资余额减少{abs(margin_pct):.1f}%")
        
        result.capital_flow_score = max(0, min(10, cf_score))
        result.capital_flow_signal = "；".join(cf_signals) if cf_signals else "资金面数据正常"
        
        cf_adj = cf_score - 5
        if cf_adj != 0:
            result.score_breakdown['capital_flow_adj'] = cf_adj
    

    @staticmethod
    def score_capital_flow_history(result: TrendAnalysisResult, stock_code: str):
        """P4: 主力资金追踪 - 大单净流入连续性检测

        通过 akshare 历史资金流数据（最近120日）分析：
        1. 连续净流入/流出天数
        2. 近5日主力净流入累计
        3. 资金流入趋势：持续流入 / 持续流出 / 间歇流入 / 资金离场
        4. 流入强度：大幅 / 温和 / 轻微
        5. 加速/减速信号
        6. 聪明钱（超大单）持续行为
        """
        global _P4_GLOBAL_FAIL_TS
        try:
            import akshare as ak
            import time
            import random

            if (time.time() - _P4_GLOBAL_FAIL_TS) < 1800:
                return

            market = "sh" if stock_code.startswith(('6', '5', '9')) else "sz"

            from concurrent.futures import ThreadPoolExecutor, TimeoutError as _FuturesTimeout
            _p4_ex = ThreadPoolExecutor(max_workers=1)
            try:
                df_flow = _p4_ex.submit(
                    ak.stock_individual_fund_flow, stock=stock_code, market=market
                ).result(timeout=10)
            except _FuturesTimeout:
                logging.getLogger(__name__).debug(f"[P4] {stock_code} 主力资金超时(10s)，全局熔断30min")
                _P4_GLOBAL_FAIL_TS = time.time()
                return
            finally:
                _p4_ex.shutdown(wait=False)
            if df_flow is None or len(df_flow) < 5:
                return

            # 标准化列名
            col_map = {
                '日期': 'date',
                '主力净流入-净额': 'main_net',
                '超大单净流入-净额': 'super_large_net',
                '大单净流入-净额': 'large_net',
                '主力净流入-净占比': 'main_pct',
            }
            df_flow = df_flow.rename(columns={k: v for k, v in col_map.items() if k in df_flow.columns})

            for col in ['main_net', 'super_large_net', 'large_net', 'main_pct']:
                if col in df_flow.columns:
                    df_flow[col] = pd.to_numeric(df_flow[col], errors='coerce').fillna(0)

            # 取最近 20 天用于分析
            recent = df_flow.tail(20).reset_index(drop=True)
            if len(recent) < 5:
                return

            main_net_series = recent['main_net'].values  # 单位：元
            sl_net_series = recent.get('super_large_net', pd.Series([0]*len(recent))).values if 'super_large_net' in recent.columns else [0]*len(recent)

            # === 1. 连续净流入/流出天数 ===
            last_net = main_net_series[-1]
            consecutive = 0
            if last_net >= 0:
                for v in reversed(main_net_series):
                    if v >= 0:
                        consecutive += 1
                    else:
                        break
            else:
                for v in reversed(main_net_series):
                    if v < 0:
                        consecutive -= 1
                    else:
                        break
            result.capital_flow_days = consecutive

            # === 2. 近5日主力净流入累计（万元）===
            last5 = main_net_series[-5:]
            total_5d = float(sum(last5)) / 10000
            result.capital_flow_5d_total = round(total_5d, 2)

            # === 3. 趋势分类 ===
            positive_count = sum(1 for v in last5 if v > 0)
            if positive_count >= 4:
                trend = "持续流入"
            elif positive_count >= 3:
                trend = "间歇流入"
            elif positive_count <= 1:
                trend = "持续流出"
            else:
                trend = "资金离场"
            result.capital_flow_trend = trend

            # === 4. 流入强度（基于近5日日均额 vs 主力净流入比例）===
            # 用 abs(主力净流入/日均成交额) 衡量强度
            avg_daily_amount = getattr(result, 'daily_avg_amount', None) or 0
            if avg_daily_amount <= 0:
                # 估算：用近5日高低中值
                try:
                    avg_daily_amount = abs(total_5d) / 5 * 20  # 粗估：净流入占5%成交额
                except Exception:
                    avg_daily_amount = 10000
            abs_5d = abs(total_5d)
            if avg_daily_amount > 0:
                intensity_ratio = abs_5d / (avg_daily_amount * 5) * 100
            else:
                intensity_ratio = 0

            if abs_5d > 50000:  # 超过5亿
                intensity = "大幅"
            elif abs_5d > 10000:  # 超过1亿
                intensity = "温和"
            elif abs_5d > 1000:
                intensity = "轻微"
            else:
                intensity = ""
            result.capital_flow_intensity = intensity

            # === 5. 加速/减速检测 ===
            if len(main_net_series) >= 10:
                prev5 = main_net_series[-10:-5]
                curr5 = main_net_series[-5:]
                prev_avg = sum(prev5) / 5
                curr_avg = sum(curr5) / 5
                if curr_avg > 0 and prev_avg > 0:
                    if curr_avg > prev_avg * 1.5:
                        result.capital_flow_acceleration = "加速流入"
                    elif curr_avg < prev_avg * 0.5:
                        result.capital_flow_acceleration = "趋缓"
                    else:
                        result.capital_flow_acceleration = ""
                elif curr_avg < 0 and prev_avg < 0:
                    if curr_avg < prev_avg * 1.5:
                        result.capital_flow_acceleration = "加速流出"
                    elif curr_avg > prev_avg * 0.5:
                        result.capital_flow_acceleration = "趋缓"
                    else:
                        result.capital_flow_acceleration = ""

            # === 6. 聪明钱（超大单）信号 ===
            sl_last5 = [float(v) for v in sl_net_series[-5:]]
            sl_positive = sum(1 for v in sl_last5 if v > 0)
            sl_total = sum(sl_last5) / 10000
            if sl_positive >= 4 and sl_total > 5000:
                result.capital_smart_money = "超大单持续买入"
            elif sl_positive <= 1 and sl_total < -5000:
                result.capital_smart_money = "超大单持续卖出"
            else:
                result.capital_smart_money = ""

            # === 7. 对 score_breakdown 做调整 ===
            p4_adj = 0
            if trend == "持续流入" and consecutive >= 3:
                p4_adj += 3
            elif trend == "持续流入":
                p4_adj += 2
            elif trend == "间歇流入":
                p4_adj += 1
            elif trend == "持续流出" and consecutive <= -3:
                p4_adj -= 3
            elif trend == "持续流出":
                p4_adj -= 2
            elif trend == "资金离场":
                p4_adj -= 1

            if result.capital_smart_money == "超大单持续买入":
                p4_adj += 2
            elif result.capital_smart_money == "超大单持续卖出":
                p4_adj -= 2

            if intensity == "大幅":
                p4_adj = int(p4_adj * 1.3)

            p4_adj = max(-5, min(5, p4_adj))
            if p4_adj != 0:
                result.score_breakdown['p4_capital_flow'] = p4_adj

        except Exception as e:
            import logging
            import time as _t_p4
            _P4_GLOBAL_FAIL_TS = _t_p4.time()
            logging.getLogger(__name__).debug(f"[P4] {stock_code} 主力资金追踪失败，全局熔断30min: {e}")


    @staticmethod
    def score_capital_flow_trend(result: TrendAnalysisResult, df: pd.DataFrame):
        """资金面连续性检测：近3日量价关系判断持续性资金流向"""
        if df is None or len(df) < 5:
            return
        
        recent = df.tail(3)
        if len(recent) < 3:
            return
        
        volumes = recent['volume'].values
        
        # 使用 pct_chg（涨跌幅）判断多空方向，比 close>open 更准确
        # close>open 忽略缺口，如低开高走 close>open 但实际偏空
        if 'pct_chg' in recent.columns:
            pct_chgs = recent['pct_chg'].values
            up_days = sum(1 for p in pct_chgs if isinstance(p, (int, float)) and p > 0)
            down_days = sum(1 for p in pct_chgs if isinstance(p, (int, float)) and p < 0)
        else:
            closes = recent['close'].values
            opens = recent['open'].values
            up_days = sum(1 for c, o in zip(closes, opens) if c > o)
            down_days = sum(1 for c, o in zip(closes, opens) if c < o)
        
        vol_increasing = volumes[-1] > volumes[-2] > volumes[-3] if all(v > 0 for v in volumes) else False
        vol_decreasing = volumes[-1] < volumes[-2] < volumes[-3] if all(v > 0 for v in volumes) else False
        
        adj = 0
        if up_days == 3 and vol_increasing:
            adj = 2
            result.score_breakdown['cf_trend'] = 2
        elif down_days == 3 and vol_increasing:
            adj = -3
            result.score_breakdown['cf_trend'] = -3
        elif down_days == 3 and vol_decreasing:
            adj = -2
            result.score_breakdown['cf_trend'] = -2
        

    @staticmethod
    def score_vwap_trend(result: TrendAnalysisResult):
        """P5-B: VWAP 机构成本线评分

        逻辑：
        - 机构成本上移 + 价格在VWAP上方 → 机构持续增持，+2
        - 机构成本下移 + 价格在VWAP下方 → 机构持续离场，-2
        - 机构成本上移 + 价格在VWAP下方 → 短期回调（未跌破成本），+1（支撑）
        - 机构成本下移 + 价格在VWAP上方 → 反弹但成本仍在下移，-1（阻力）
        """
        vwap_trend = result.vwap_trend
        vwap_pos = result.vwap_position
        if not vwap_trend or not vwap_pos:
            return

        adj = 0
        if vwap_trend == "机构成本上移" and vwap_pos == "价格在VWAP上方":
            adj = 2
        elif vwap_trend == "机构成本下移" and vwap_pos == "价格在VWAP下方":
            adj = -2
        elif vwap_trend == "机构成本上移" and vwap_pos == "价格在VWAP下方":
            adj = 1
        elif vwap_trend == "机构成本下移" and vwap_pos == "价格在VWAP上方":
            adj = -1

        if adj != 0:
            result.score_breakdown['vwap_adj'] = adj


    @staticmethod
    def score_intraday_volume_signal(result: TrendAnalysisResult):
        """盘中量比×价格联动主力行为检测
        
        换手率盘中是累计残缺值，不可靠。
        量比（当前每分钟成交速率 vs 过去5日同时段均值）是已归一化的盘中指标，
        结合价格方向可判断主力行为：
        - 量比>2 + 价格上涨  → 放量拉升（主力买入信号）+2
        - 量比>3 + 价格上涨  → 强势放量拉升 +3
        - 量比>2 + 价格下跌  → 放量出货（主力离场信号）-2
        - 量比>3 + 价格下跌  → 强势出货 -3
        - 量比<0.5           → 缩量（流动性差，中性偏负）-1
        
        仅盘中（15:00前）触发，收盘后由换手率历史百分位接管。
        """
        from datetime import datetime as _dt_iv
        if _dt_iv.now().hour >= 15:
            return  # 收盘后由换手率历史百分位接管，不重复计

        vr = result.volume_ratio
        if not isinstance(vr, (int, float)) or vr <= 0:
            return

        from .types import TrendStatus, VolumeStatus
        # 用 trend_status + volume_status 联合判断价格方向
        is_rising = result.trend_status in (TrendStatus.STRONG_BULL, TrendStatus.BULL) or \
                    result.volume_status in (VolumeStatus.HEAVY_VOLUME_UP,)
        is_falling = result.trend_status in (TrendStatus.STRONG_BEAR, TrendStatus.BEAR) or \
                     result.volume_status in (VolumeStatus.HEAVY_VOLUME_DOWN,)

        adj = 0
        if vr >= 3.0:
            if is_rising:
                adj = 3
                result.signal_reasons.append(f"量比{vr:.1f}强势放量拉升，主力积极买入")
            elif is_falling:
                adj = -3
                result.risk_factors.append(f"量比{vr:.1f}强势放量下跌，主力出货信号")
        elif vr >= 2.0:
            if is_rising:
                adj = 2
                result.signal_reasons.append(f"量比{vr:.1f}放量上涨，资金活跃")
            elif is_falling:
                adj = -2
                result.risk_factors.append(f"量比{vr:.1f}放量下跌，警惕主力出货")
        elif vr < 0.5:
            adj = -1
            result.risk_factors.append(f"量比{vr:.1f}极度缩量，流动性不足")

        if adj != 0:
            result.score_breakdown['intraday_vol_signal'] = adj


    @staticmethod
    def score_quote_extra(result: TrendAnalysisResult, quote_extra: Union[QuoteExtra, dict, None] = None):
        """行情附加数据评分：换手率异常检测 + 52周高低位 + 市值风控"""
        if quote_extra is None:
            return
        # 兼容 dict 和 QuoteExtra
        if isinstance(quote_extra, dict):
            quote_extra = QuoteExtra.from_dict(quote_extra)
        
        adj = 0
        price = result.current_price
        
        turnover = quote_extra.turnover_rate
        if isinstance(turnover, (int, float)) and turnover > 0:
            if turnover > 15:
                if not result.trading_halt:
                    result.trading_halt = True
                    result.trading_halt_reason = (result.trading_halt_reason + "；" if result.trading_halt_reason else "") + f"换手率异常({turnover:.1f}%>15%)，疑似游资炒作"
            elif turnover < 0.3:
                adj -= 1
                result.score_breakdown['liquidity_risk'] = -1
        
        high_52w = quote_extra.high_52w
        low_52w = quote_extra.low_52w
        if isinstance(high_52w, (int, float)) and isinstance(low_52w, (int, float)) and high_52w > low_52w > 0 and price > 0:
            week52_range = high_52w - low_52w
            if week52_range > 0:
                position = (price - low_52w) / week52_range * 100
                result.week52_position = round(position, 1)
                if position > 95:
                    adj -= 2
                    result.score_breakdown['week52_risk'] = -2
                elif position > 80:
                    adj -= 1
                    result.score_breakdown['week52_risk'] = -1
                elif position < 5:
                    adj += 2
                    result.score_breakdown['week52_opp'] = 2
                elif position < 20:
                    adj += 1
                    result.score_breakdown['week52_opp'] = 1
        
        # === 市值风控：小盘股流动性差/波动大，压缩仓位上限 ===
        circ_mv = quote_extra.circ_mv  # 流通市值（元）
        total_mv = quote_extra.total_mv  # 总市值（元）
        mv = circ_mv or total_mv  # 优先使用流通市值
        if isinstance(mv, (int, float)) and mv > 0:
            mv_yi = mv / 1e8  # 转为亿元
            if mv_yi < 20:
                # 微盘股（<20亿）：仓位上限压缩，风险提示
                result.market_risk_cap = min(result.market_risk_cap, 15)
                result.risk_factors.append(f"微盘股(流通市值{mv_yi:.0f}亿)，流动性风险高，仓位上限15%")
                result.score_breakdown['mcap_risk'] = -1
                adj -= 1
            elif mv_yi < 50:
                # 小盘股（20-50亿）：轻微压缩
                result.market_risk_cap = min(result.market_risk_cap, 25)
                result.risk_factors.append(f"小盘股(流通市值{mv_yi:.0f}亿)，注意流动性")
        

    @staticmethod
    def score_market_sentiment_adj(result: TrendAnalysisResult):
        """P0: 市场情绪温度修正（三级 fallback + DB 持久化 + 结构化评分）

        逻辑（逆向情绪投资）：
        - 极度恐惧（temperature<25）→ +5
        - 恐惧（25~40）→ +2
        - 中性（40~65）→ 不修正
        - 贪婪（65~80）→ -3
        - 极度贪婪（>80）→ -6

        结构化维度（B-2 新增）：
        - 涨跌停比修正：涨停占比>70% → +1，跌停占比>35% → -1
        - 炸板率修正：>50% → -1，>30% → -0.5，<10% → +0.5
        - 偏离度标注：偏离 ±1.5σ 时标注信息（不加减分）

        注意：该修正仅调整 score_breakdown，不直接修改 signal_score，
        由 cap_adjustments 统一应用。
        """
        try:
            from src.market_sentiment import get_market_sentiment_cached
            sentiment = get_market_sentiment_cached()
        except Exception:
            sentiment = None

        if sentiment is None:
            return

        temp = sentiment.temperature
        adj = 0

        # ---- 温度区间修正（逆向情绪投资）----
        if temp < 25:
            adj = 5
            result.signal_reasons.append(
                f"🌡️ 市场极度恐惧(温度{temp})，历史上往往是底部区域，逆向机会"
            )
        elif temp < 40:
            adj = 2
            result.signal_reasons.append(f"🌡️ 市场偏冷(温度{temp})，情绪修复行情可期")
        elif temp > 80:
            adj = -6
            result.risk_factors.append(
                f"🌡️ 市场极度贪婪(温度{temp}，涨停{sentiment.limit_up_count}家)，"
                f"过热行情追涨风险极高，建议减仓"
            )
        elif temp > 65:
            adj = -3
            result.risk_factors.append(
                f"🌡️ 市场偏热(温度{temp})，情绪高涨时需警惕回调"
            )

        # ---- 涨跌停比修正 ----
        total_limits = sentiment.limit_up_count + sentiment.limit_down_count
        if total_limits > 0:
            up_ratio = sentiment.limit_up_count / total_limits
            down_ratio = sentiment.limit_down_count / total_limits
            if up_ratio > 0.70:
                adj += 1
            elif down_ratio > 0.35:
                adj -= 1

        # ---- 炸板率修正（两档）----
        if sentiment.broken_limit_rate > 50:
            adj -= 1.0
        elif sentiment.broken_limit_rate > 30:
            adj -= 0.5
        elif sentiment.broken_limit_rate < 10:
            adj += 0.5

        # ---- 偏离度标注（仅信息展示，不额外加减分）----
        try:
            from src.market_sentiment import calc_temperature_deviation
            deviation = calc_temperature_deviation(temp)
            if deviation is not None:
                if deviation > 1.5:
                    result.signal_reasons.append(
                        f"🌡️ 情绪显著升温(偏离+{deviation}σ)，注意过热风险"
                    )
                elif deviation < -1.5:
                    result.risk_factors.append(
                        f"🌡️ 情绪骤冷(偏离{deviation}σ)，市场恐慌情绪蔓延"
                    )
        except Exception:
            pass

        if adj != 0:
            result.score_breakdown['market_sentiment_adj'] = adj

