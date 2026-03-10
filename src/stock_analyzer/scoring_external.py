# -*- coding: utf-8 -*-
"""
评分系统 — ScoringExternal 模块
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


class ScoringExternal:
    """ScoringExternal Mixin"""


    @staticmethod
    def score_lhb_sentiment(result: TrendAnalysisResult, stock_code: str):
        """P5-C: 量化情绪指标 - 龙虎榜机构净买额分析

        通过龙虎榜近一月统计判断机构行为：
        - 机构净买额为正且上榜次数多：机构持续买入信号（+2~+3）
        - 机构净买额为负且上榜次数多：机构持续卖出信号（-2~-3）
        - 上榜但机构净买额接近零：博弈激烈，中性（0）
        - 未上榜：不处理
        """
        import threading
        import logging
        _logger = logging.getLogger(__name__)

        thread_results: Dict = {}

        def _fetch():
            try:
                import akshare as ak
                import time as _t
                import random

                try:
                    from data_provider.rate_limiter import get_global_limiter
                    limiter = get_global_limiter()
                    limiter.acquire('akshare', blocking=True, timeout=3.0)
                except Exception:
                    _t.sleep(random.uniform(0.3, 0.8))

                df_lhb = ak.stock_lhb_stock_statistic_em(symbol='近一月')
                if df_lhb is None or df_lhb.empty:
                    return

                row = df_lhb[df_lhb['代码'] == stock_code]
                if row.empty:
                    return

                row = row.iloc[0]
                lhb_net = float(row.get('龙虎榜净买额', 0) or 0)
                inst_net = float(row.get('机构买入净额', 0) or 0)
                times = int(row.get('上榜次数', 0) or 0)

                thread_results['lhb_net_buy'] = round(lhb_net, 2)
                thread_results['lhb_institution_net'] = round(inst_net, 2)
                thread_results['lhb_times'] = times

                p5c_adj = 0
                inst_net_wan = inst_net / 10000

                if inst_net_wan > 5000:
                    p5c_adj += 3
                    thread_results['lhb_signal'] = "机构持续买入"
                elif inst_net_wan > 1000:
                    p5c_adj += 2
                    thread_results['lhb_signal'] = "机构净买入"
                elif inst_net_wan < -5000:
                    p5c_adj -= 3
                    thread_results['lhb_signal'] = "机构持续卖出"
                elif inst_net_wan < -1000:
                    p5c_adj -= 2
                    thread_results['lhb_signal'] = "机构净卖出"
                elif times >= 3:
                    thread_results['lhb_signal'] = "龙虎榜活跃"

                p5c_adj = max(-3, min(3, p5c_adj))
                if p5c_adj != 0:
                    thread_results['p5c_lhb'] = p5c_adj
            except Exception as e:
                _logger.debug(f"[P5-C] {stock_code} 龙虎榜情绪分析失败: {e}")

        t = threading.Thread(target=_fetch, daemon=True)
        t.start()
        t.join(timeout=5)
        if t.is_alive():
            _logger.debug(f"[P5-C] {stock_code} 龙虎榜情绪分析超时，已跳过")
        else:
            for attr in ('lhb_net_buy', 'lhb_institution_net', 'lhb_times', 'lhb_signal'):
                if attr in thread_results:
                    setattr(result, attr, thread_results[attr])
            if 'p5c_lhb' in thread_results:
                result.score_breakdown['p5c_lhb'] = thread_results['p5c_lhb']


    @staticmethod
    def score_dzjy_and_holder(result: TrendAnalysisResult, stock_code: str):
        """P5-C补充: 大宗交易折溢价率 + 股东人数变化率（带超时保护）

        注意：akshare大宗交易接口为全市场拉取，耗时较长，使用线程超时5s保护。
        超时则跳过，不阻塞主流程。
        """
        import threading
        import logging
        logger = logging.getLogger(__name__)

        dzjy_results: Dict = {}
        holder_results: Dict = {}

        # ---- 大宗交易（线程+超时5秒）----
        def _fetch_dzjy():
            try:
                import akshare as ak
                from datetime import datetime, timedelta
                today = datetime.now().strftime('%Y%m%d')
                month_ago = (datetime.now() - timedelta(days=30)).strftime('%Y%m%d')
                df_dz = ak.stock_dzjy_mrmx(symbol='A股', start_date=month_ago, end_date=today)
                if df_dz is None or df_dz.empty or '证券代码' not in df_dz.columns:
                    return
                rows = df_dz[df_dz['证券代码'] == stock_code]
                if rows.empty:
                    return
                premiums = rows['折溢率'].astype(float).tolist()
                avg_prem = sum(premiums) / len(premiums)
                times = len(premiums)
                dzjy_results['dzjy_avg_premium'] = round(avg_prem, 4)
                dzjy_results['dzjy_times'] = times
                adj_dz = 0
                if avg_prem > 0.02:
                    adj_dz = 2
                    dzjy_results['dzjy_signal'] = "大宗溢价成交"
                elif avg_prem < -0.02 and times >= 3:
                    adj_dz = -3
                    dzjy_results['dzjy_signal'] = "大宗持续折价出货"
                elif avg_prem < -0.02:
                    adj_dz = -2
                    dzjy_results['dzjy_signal'] = "大宗折价出货"
                if adj_dz != 0:
                    dzjy_results['p5c_dzjy'] = adj_dz
            except Exception as e:
                logger.debug(f"[P5-C] {stock_code} 大宗交易查询失败: {e}")

        # ---- 股东人数变化率 ----
        def _fetch_holder():
            try:
                import akshare as ak
                df_holder = ak.stock_zh_a_gdhs(symbol=stock_code)
                if df_holder is None or df_holder.empty or len(df_holder) < 2:
                    return
                cols = df_holder.columns.tolist()
                holder_col = next((c for c in cols if '股东' in c or '持股人数' in c), None)
                if not holder_col:
                    return
                latest = float(df_holder.iloc[-1][holder_col])
                prev = float(df_holder.iloc[-2][holder_col])
                if prev <= 0:
                    return
                change_pct = (latest - prev) / prev * 100
                holder_results['holder_change_pct'] = round(change_pct, 2)
                adj_holder = 0
                if change_pct < -5:
                    holder_results['holder_signal'] = "筹码集中（缩股）"
                    adj_holder = 2
                elif change_pct < -2:
                    holder_results['holder_signal'] = "筹码小幅集中"
                    adj_holder = 1
                elif change_pct > 5:
                    holder_results['holder_signal'] = "筹码分散（增股）"
                    adj_holder = -1
                if adj_holder != 0:
                    holder_results['p5c_holder'] = adj_holder
            except Exception as e:
                logger.debug(f"[P5-C] {stock_code} 股东人数查询失败: {e}")

        import time as _time
        t_dz = threading.Thread(target=_fetch_dzjy, daemon=True)
        t_holder = threading.Thread(target=_fetch_holder, daemon=True)
        t_dz.start()
        t_holder.start()
        t_dz.join(timeout=5)
        t_holder.join(timeout=5)
        if t_dz.is_alive():
            logger.debug(f"[P5-C] {stock_code} 大宗交易查询超时，已跳过")
        else:
            for attr in ('dzjy_avg_premium', 'dzjy_times', 'dzjy_signal'):
                if attr in dzjy_results:
                    setattr(result, attr, dzjy_results[attr])
            if 'p5c_dzjy' in dzjy_results:
                result.score_breakdown['p5c_dzjy'] = dzjy_results['p5c_dzjy']
        if t_holder.is_alive():
            logger.debug(f"[P5-C] {stock_code} 股东人数查询超时，已跳过")
        else:
            for attr in ('holder_change_pct', 'holder_signal'):
                if attr in holder_results:
                    setattr(result, attr, holder_results[attr])
            if 'p5c_holder' in holder_results:
                result.score_breakdown['p5c_holder'] = holder_results['p5c_holder']


    @staticmethod
    def score_sector_strength(result: TrendAnalysisResult, sector_context: Union[SectorContext, dict, None] = None):
        """板块强弱评分"""
        if sector_context is None:
            return
        # 兼容 dict 和 SectorContext
        if isinstance(sector_context, dict):
            sector_context = SectorContext.from_dict(sector_context)
        
        sec_name = sector_context.sector_name
        sec_pct = sector_context.sector_pct
        rel = sector_context.relative
        
        if sec_name:
            result.sector_name = sec_name
        if isinstance(sec_pct, (int, float)):
            result.sector_pct = round(sec_pct, 2)
        if isinstance(rel, (int, float)):
            result.sector_relative = round(rel, 2)
        
        sec_score = 5
        signals = []
        
        if isinstance(sec_pct, (int, float)):
            if sec_pct > 2.0:
                sec_score += 2
                signals.append(f"{sec_name}板块强势(+{sec_pct:.1f}%)")
            elif sec_pct > 0:
                sec_score += 1
                signals.append(f"{sec_name}板块偏强(+{sec_pct:.1f}%)")
            elif sec_pct < -2.0:
                sec_score -= 2
                signals.append(f"⚠️{sec_name}板块弱势({sec_pct:.1f}%)")
            elif sec_pct < 0:
                sec_score -= 1
                signals.append(f"{sec_name}板块偏弱({sec_pct:.1f}%)")
        
        if isinstance(rel, (int, float)):
            if rel > 2.0:
                sec_score += 2
                signals.append(f"个股跑赢板块{rel:+.1f}pp,强势")
            elif rel > 0:
                sec_score += 1
                signals.append(f"个股略强于板块{rel:+.1f}pp")
            elif rel < -2.0:
                sec_score -= 2
                signals.append(f"⚠️个股跑输板块{rel:+.1f}pp,弱势")
            elif rel < 0:
                sec_score -= 1
                signals.append(f"个股略弱于板块{rel:+.1f}pp")
        
        sec_score = max(0, min(10, sec_score))
        result.sector_score = sec_score
        result.sector_signal = "；".join(signals) if signals else "板块表现中性"
        
        sector_adj = sec_score - 5
        if sector_adj != 0:
            result.score_breakdown['sector_adj'] = sector_adj
    

    @staticmethod
    def score_chip_distribution(result: TrendAnalysisResult, chip_data: Union[ChipDistribution, dict, None] = None):
        """筹码分布评分"""
        if chip_data is None:
            return
        # 兼容 dict
        if isinstance(chip_data, dict):
            profit_ratio = chip_data.get('profit_ratio')
            avg_cost = chip_data.get('avg_cost')
            concentration_90 = chip_data.get('concentration_90')
        else:
            profit_ratio = chip_data.profit_ratio
            avg_cost = chip_data.avg_cost
            concentration_90 = chip_data.concentration_90
        
        c_score = 5
        signals = []
        price = result.current_price
        
        if isinstance(profit_ratio, (int, float)):
            pr = profit_ratio * 100 if profit_ratio <= 1.0 else profit_ratio
            if pr > 90:
                c_score -= 2
                signals.append(f"获利盘{pr:.0f}%,抛压较大")
            elif pr > 70:
                c_score -= 1
                signals.append(f"获利盘{pr:.0f}%,偏高")
            elif pr < 10:
                c_score += 2
                signals.append(f"获利盘仅{pr:.0f}%,底部信号")
            elif pr < 30:
                c_score += 1
                signals.append(f"获利盘{pr:.0f}%,偏低有支撑")
        
        if isinstance(avg_cost, (int, float)) and avg_cost > 0 and price > 0:
            cost_ratio = price / avg_cost
            if cost_ratio > 1.15:
                c_score -= 1
                signals.append(f"现价高于均成本{avg_cost:.2f}元({(cost_ratio-1)*100:.0f}%),注意获利抛压")
            elif cost_ratio < 0.85:
                c_score += 1
                signals.append(f"现价低于均成本{avg_cost:.2f}元({(1-cost_ratio)*100:.0f}%),成本支撑")
        
        if isinstance(concentration_90, (int, float)) and concentration_90 > 0:
            if concentration_90 < 10:
                c_score += 1
                signals.append(f"筹码高度集中({concentration_90:.1f}%),主力控盘")
            elif concentration_90 > 50:
                c_score -= 1
                signals.append(f"筹码分散({concentration_90:.1f}%),缺乏主力")
        
        c_score = max(0, min(10, c_score))
        result.chip_score = c_score
        result.chip_signal = "；".join(signals) if signals else "筹码分布正常"
        
        chip_adj = c_score - 5
        if chip_adj != 0:
            result.score_breakdown['chip_adj'] = chip_adj
    

    @staticmethod
    def score_fundamental_quality(result: TrendAnalysisResult, fundamental_data: Union[FundamentalData, dict, None] = None):
        """基本面质量评分：ROE + 负债率 + 毛利率 + 净利增速 + 营收增速"""
        if fundamental_data is None:
            return
        # 兼容 dict（临时）和 FundamentalData
        if isinstance(fundamental_data, dict):
            fundamental_data = FundamentalData.from_dict(fundamental_data)
        
        fin = fundamental_data.financial
        if not fin.has_data:
            return
        
        f_score = 5
        signals = []
        
        # === ROE ===
        roe = fin.roe
        if roe is not None:
            if roe > 20:
                f_score += 2
                signals.append(f"ROE优秀({roe:.1f}%)")
            elif roe > 10:
                f_score += 1
                signals.append(f"ROE良好({roe:.1f}%)")
            elif roe < 0:
                f_score -= 2
                signals.append(f"⚠️ROE为负({roe:.1f}%),亏损")
            elif roe < 3:
                f_score -= 1
                signals.append(f"ROE偏低({roe:.1f}%)")
        
        # === 负债率 ===
        debt = fin.debt_ratio
        if debt is not None:
            if debt > 80:
                f_score -= 2
                signals.append(f"⚠️负债率过高({debt:.1f}%)")
            elif debt > 60:
                f_score -= 1
                signals.append(f"负债率偏高({debt:.1f}%)")
            elif debt < 30:
                f_score += 1
                signals.append(f"负债率健康({debt:.1f}%)")
        
        # === 毛利率（定价权指标）===
        gross = fin.gross_margin
        if gross is not None:
            if gross > 50:
                f_score += 1
                signals.append(f"毛利率优秀({gross:.1f}%)，定价权强")
            elif gross > 30:
                pass  # 正常，不加不减
            elif gross < 10:
                f_score -= 1
                signals.append(f"⚠️毛利率极低({gross:.1f}%)，竞争激烈")
        
        # === 净利润增速（成长性）===
        np_growth = fin.net_profit_growth
        if np_growth is not None:
            if np_growth > 50:
                f_score += 2
                signals.append(f"净利增速强劲({np_growth:.1f}%)")
            elif np_growth > 20:
                f_score += 1
                signals.append(f"净利增速良好({np_growth:.1f}%)")
            elif np_growth < -30:
                f_score -= 2
                signals.append(f"⚠️净利大幅下滑({np_growth:.1f}%)")
            elif np_growth < 0:
                f_score -= 1
                signals.append(f"⚠️净利负增长({np_growth:.1f}%)")
        
        # === 营收增速（业务扩张）===
        rev_growth = fin.revenue_growth
        if rev_growth is not None:
            if rev_growth > 30:
                f_score += 1
                signals.append(f"营收高增长({rev_growth:.1f}%)")
            elif rev_growth < -20:
                f_score -= 1
                signals.append(f"⚠️营收大幅萎缩({rev_growth:.1f}%)")
        
        f_score = max(0, min(10, f_score))
        result.fundamental_score = f_score
        result.fundamental_signal = "；".join(signals) if signals else "基本面数据正常"
        
        fund_adj = f_score - 5
        if fund_adj != 0:
            result.score_breakdown['fundamental_adj'] = fund_adj
    

    @staticmethod
    def score_forecast(result: TrendAnalysisResult, fundamental_data: Union[FundamentalData, dict, None] = None):
        """业绩预测评分：分析师评级 + 目标价 + 盈利预测"""
        if fundamental_data is None:
            return
        # 兼容 dict（临时）和 FundamentalData
        if isinstance(fundamental_data, dict):
            fundamental_data = FundamentalData.from_dict(fundamental_data)
        
        fc = fundamental_data.forecast
        if not fc.has_data:
            return
        
        adj = 0
        signals = []
        
        # === 分析师评级 ===
        rating = fc.rating
        if rating and rating not in ('无', '', 'N/A'):
            rating_lower = rating.strip()
            if any(k in rating_lower for k in ['买入', '增持', '强烈推荐', '推荐']):
                adj += 2
                signals.append(f"分析师评级「{rating_lower}」")
            elif any(k in rating_lower for k in ['中性', '持有', '审慎']):
                pass  # 中性不加不减
            elif any(k in rating_lower for k in ['减持', '卖出', '回避']):
                adj -= 2
                signals.append(f"⚠️分析师评级「{rating_lower}」")
        
        # === 目标价 vs 现价 ===
        if fc.target_price is not None and fc.target_price > 0 and result.current_price > 0:
            target = fc.target_price
            upside = (target - result.current_price) / result.current_price * 100
            if upside > 30:
                adj += 2
                signals.append(f"目标价{target:.2f}(上行空间{upside:.0f}%)")
            elif upside > 10:
                adj += 1
                signals.append(f"目标价{target:.2f}(上行空间{upside:.0f}%)")
            elif upside < -10:
                adj -= 1
                signals.append(f"⚠️目标价{target:.2f}(下行{upside:.0f}%)")
        
        # === 盈利预测变动 ===
        chg = fc.avg_profit_change
        if chg is not None:
            if chg > 20:
                adj += 1
                signals.append(f"盈利预测上调{chg:.1f}%")
            elif chg < -20:
                adj -= 1
                signals.append(f"⚠️盈利预测下调{chg:.1f}%")
        
        if adj != 0:
            result.score_breakdown['forecast_adj'] = adj
            if signals:
                for s in signals:
                    if '⚠️' in s:
                        result.risk_factors.append(s)
                    else:
                        result.signal_reasons.append(s)


    @staticmethod
    def detect_sentiment_extreme(result: TrendAnalysisResult, chip_data: Union[ChipDistribution, dict, None] = None,
                                  capital_flow: Union[CapitalFlowData, dict, None] = None, df: pd.DataFrame = None):
        """
        P3 情绪极端检测：综合获利盘/套牢盘比例 + 融资余额趋势

        - 获利盘>90% → 极度贪婪（短期回调概率高）
        - 套牢盘>80% → 极度恐慌（上方压力巨大）
        - 融资余额三档：轻度(3日±0.3)、中度(5日±0.6)、强烈(7日±1.0) + 幅度修正
        - 跨长假(日历间隔>5天)连续天数归零
        """
        details = []
        adj = 0
        
        # --- 1. 获利盘/套牢盘比例 ---
        if chip_data is not None:
            if isinstance(chip_data, dict):
                profit_ratio = chip_data.get('profit_ratio')
            else:
                profit_ratio = chip_data.profit_ratio
            if isinstance(profit_ratio, (int, float)):
                pr = profit_ratio * 100 if profit_ratio <= 1.0 else profit_ratio
                result.profit_ratio = pr
                result.trapped_ratio = 100 - pr
                
                if pr > 90:
                    details.append(f"🔴 获利盘{pr:.0f}%（极高），短期回调概率大，获利了结压力沉重")
                    adj -= 3
                    result.sentiment_extreme = "极度贪婪"
                elif pr > 80:
                    details.append(f"🟡 获利盘{pr:.0f}%（偏高），注意获利抛压")
                    adj -= 1
                elif pr < 10:
                    details.append(f"🟢 获利盘仅{pr:.0f}%（极低），套牢盘{100-pr:.0f}%，上方压力巨大但抛压已枯竭")
                    adj += 2
                    if not result.sentiment_extreme:
                        result.sentiment_extreme = "极度恐慌"
                elif pr < 20:
                    details.append(f"🟡 获利盘{pr:.0f}%（偏低），套牢盘{100-pr:.0f}%，上方有较大压力")
                    adj += 1
        
        # --- 2. 融资余额趋势（杠杆情绪指标，三档 + 幅度修正）---
        MARGIN_TREND_TIERS = [
            (7, 1.0, "强烈"),
            (5, 0.6, "中度"),
            (3, 0.3, "轻度"),
        ]
        if capital_flow is not None:
            if isinstance(capital_flow, dict):
                capital_flow = CapitalFlowData.from_dict(capital_flow)
            margin_history = capital_flow.margin_history
            margin_dates = getattr(capital_flow, 'margin_history_dates', None)

            if margin_history and isinstance(margin_history, (list, tuple)) and len(margin_history) >= 3:
                # 记录最新余额和变化百分比供 LLM 使用
                if isinstance(margin_history[-1], (int, float)) and margin_history[-1] > 0:
                    result.margin_balance_latest = margin_history[-1]
                margin_balance_change = capital_flow.margin_balance_change if capital_flow else None
                result.margin_change_pct = margin_balance_change

                def _date_gap_days(d1: str, d2: str) -> int:
                    """计算两个 YYYYMMDD 日期之间的自然日间隔"""
                    from datetime import datetime
                    try:
                        return abs((datetime.strptime(d2, '%Y%m%d') - datetime.strptime(d1, '%Y%m%d')).days)
                    except (ValueError, TypeError):
                        return 1

                consecutive_up = 0
                for i in range(len(margin_history) - 1, 0, -1):
                    if margin_dates and len(margin_dates) == len(margin_history):
                        if _date_gap_days(margin_dates[i - 1], margin_dates[i]) > 5:
                            break
                    curr, prev_val = margin_history[i], margin_history[i - 1]
                    if isinstance(curr, (int, float)) and isinstance(prev_val, (int, float)) and curr > prev_val:
                        consecutive_up += 1
                    else:
                        break

                consecutive_down = 0
                for i in range(len(margin_history) - 1, 0, -1):
                    if margin_dates and len(margin_dates) == len(margin_history):
                        if _date_gap_days(margin_dates[i - 1], margin_dates[i]) > 5:
                            break
                    curr, prev_val = margin_history[i], margin_history[i - 1]
                    if isinstance(curr, (int, float)) and isinstance(prev_val, (int, float)) and curr < prev_val:
                        consecutive_down += 1
                    else:
                        break

                # 三档判定：连续流入
                for threshold, score_adj, label in MARGIN_TREND_TIERS:
                    if consecutive_up >= threshold:
                        result.margin_trend = f"融资连续流入({label})"
                        result.margin_trend_days = consecutive_up
                        details.append(f"📈 融资余额连续{consecutive_up}日增加({label})，杠杆资金看多迹象")
                        adj += score_adj
                        break

                # 三档判定：连续流出
                for threshold, score_adj, label in MARGIN_TREND_TIERS:
                    if consecutive_down >= threshold:
                        result.margin_trend = f"融资连续流出({label})"
                        result.margin_trend_days = consecutive_down
                        details.append(f"📉 融资余额连续{consecutive_down}日减少({label})，杠杆资金撤退迹象")
                        adj -= score_adj
                        break

                # 幅度修正
                abs_chg = abs(margin_balance_change) if isinstance(margin_balance_change, (int, float)) else 0
                sign = 1 if consecutive_up > consecutive_down else -1
                if abs_chg > 5.0:
                    adj += 0.5 * sign
                elif abs_chg <= 2.0 and max(consecutive_up, consecutive_down) >= 3:
                    adj -= 0.3 * sign
        
        # --- 3. 价格位置 + 量能综合判断情绪 ---
        if df is not None and len(df) >= 60:
            # 近60日涨幅
            price_60d_ago = float(df.iloc[-60]['close'])
            if price_60d_ago > 0:
                gain_60d = (result.current_price - price_60d_ago) / price_60d_ago * 100
                if gain_60d > 50 and result.volume_extreme == "天量":
                    if not result.sentiment_extreme:
                        result.sentiment_extreme = "极度贪婪"
                    details.append(f"⚠️ 60日涨幅{gain_60d:.0f}%+天量，市场情绪过热")
                    adj -= 2
                elif gain_60d < -30 and result.volume_extreme == "地量":
                    if not result.sentiment_extreme:
                        result.sentiment_extreme = "极度恐慌"
                    details.append(f"💡 60日跌幅{abs(gain_60d):.0f}%+地量，恐慌情绪可能见底")
                    adj += 2
        
        # --- 汇总 ---
        if details:
            result.sentiment_extreme_detail = "；".join(details)
        
        if adj != 0:
            result.score_breakdown['sentiment_extreme'] = round(adj)


    @staticmethod
    def score_limit_and_enhanced(result: TrendAnalysisResult):
        """
        涨跌停 + 量价背离 + VWAP + 换手率分位数 + 缺口 综合评分修正
        
        涨跌停规则：
        - 涨停板：连板越多越强（但高位连板风险加大）
        - 跌停板：直接大幅扣分
        - 连续涨停 ≥3 板：追高风险警告
        
        量价背离：
        - 顶部量价背离：扣分（价格新高但量能萎缩 = 上涨乏力）
        - 底部量缩企稳：加分（可能筑底）
        
        VWAP：
        - 价格在 VWAP 上方 = 多头占优
        - 价格在 VWAP 下方 = 空头占优
        
        换手率分位数：
        - >90分位：异常活跃（可能见顶）
        - <10分位：极度冷清（可能见底）
        
        缺口：
        - 向上跳空 + 放量 = 突破信号
        - 向下跳空 = 风险信号
        """
        adj = 0

        # === 涨跌停评分 ===
        if result.is_limit_up:
            if result.consecutive_limits >= 4:
                # 4板以上：追高风险极大
                adj -= 3
                result.risk_factors.append(f"连续{result.consecutive_limits}板涨停，追高风险极大")
                result.score_breakdown['limit_risk'] = -3
            elif result.consecutive_limits >= 2:
                # 连板：强势但需警惕
                adj += 2
                result.signal_reasons.append(f"连续{result.consecutive_limits}板涨停，短期强势")
                result.score_breakdown['limit_adj'] = 2
            else:
                # 首板涨停
                adj += 3
                result.signal_reasons.append("涨停封板，多头强势")
                result.score_breakdown['limit_adj'] = 3
        elif result.is_limit_down:
            adj -= 5
            result.risk_factors.append("跌停板，风险极高")
            result.score_breakdown['limit_adj'] = -5

        # === 量价背离评分 ===
        vpd = result.volume_price_divergence
        if vpd == "顶部量价背离":
            adj -= 3
            result.risk_factors.append("量价背离：价格新高但成交量萎缩，上涨动能衰竭")
            result.score_breakdown['vp_divergence'] = -3
        elif vpd == "底部量缩企稳":
            adj += 2
            result.signal_reasons.append("底部量缩企稳，抛压减轻，可能筑底")
            result.score_breakdown['vp_divergence'] = 2

        # === VWAP 偏离评分 ===
        vwap_bias = result.vwap_bias
        if vwap_bias > 3.0:
            adj += 1
            result.signal_reasons.append(f"价格在VWAP上方{vwap_bias:.1f}%，多头占优")
            result.score_breakdown['vwap_adj'] = 1
        elif vwap_bias < -3.0:
            adj -= 1
            result.risk_factors.append(f"价格在VWAP下方{abs(vwap_bias):.1f}%，空头占优")
            result.score_breakdown['vwap_adj'] = -1

        # === 换手率分位数评分 ===
        tp = result.turnover_percentile
        if tp > 0.9:
            adj -= 2
            result.risk_factors.append(f"换手率处于历史{tp*100:.0f}%分位，异常活跃，警惕见顶")
            result.score_breakdown['turnover_adj'] = -2
        elif tp < 0.1 and tp > 0:
            adj += 1
            result.signal_reasons.append(f"换手率处于历史{tp*100:.0f}%分位，极度冷清，关注底部信号")
            result.score_breakdown['turnover_adj'] = 1

        # === 缺口评分 ===
        gap = result.gap_type
        if gap == "向上跳空":
            from .types import VolumeStatus
            if result.volume_status in (VolumeStatus.HEAVY_VOLUME_UP,):
                adj += 2
                result.signal_reasons.append("放量向上跳空，突破信号")
                result.score_breakdown['gap_adj'] = 2
            else:
                adj += 1
                result.signal_reasons.append("向上跳空缺口")
                result.score_breakdown['gap_adj'] = 1
        elif gap == "向下跳空":
            adj -= 2
            result.risk_factors.append("向下跳空缺口，短期风险")
            result.score_breakdown['gap_adj'] = -2

        # === 成交量异动评分（P1）===
        vol_ext = getattr(result, 'volume_extreme', '')
        vol_trend_3d = getattr(result, 'volume_trend_3d', '')
        if vol_ext == "天量":
            # 天量 = 变盘信号：上涨中天量可能见顶，下跌中天量可能见底
            price_up = result.bias_ma5 > 0
            if price_up:
                adj -= 2
                result.risk_factors.append("天量上涨：成交量创60日新高，警惕变盘见顶")
                result.score_breakdown['vol_extreme'] = -2
            else:
                adj += 2
                result.signal_reasons.append("天量下跌：放量杀跌可能是恐慌底，关注反弹")
                result.score_breakdown['vol_extreme'] = 2
        elif vol_ext == "地量":
            # 地量 = 底部信号（下跌中）或观望信号（上涨中）
            price_down = result.bias_ma5 < -2
            if price_down:
                adj += 2
                result.signal_reasons.append("地量下跌：成交量创60日新低，抛压枯竭，关注底部")
                result.score_breakdown['vol_extreme'] = 2
            else:
                adj -= 1
                result.risk_factors.append("地量：成交量极低，市场关注度不足")
                result.score_breakdown['vol_extreme'] = -1
        
        if vol_trend_3d == "连续放量":
            # 连续放量 + 上涨 = 趋势确认；连续放量 + 下跌 = 加速下跌
            if result.bias_ma5 > 0:
                adj += 1
                result.signal_reasons.append("连续3日放量上涨，趋势确认")
                result.score_breakdown['vol_trend_3d'] = 1
            else:
                adj -= 1
                result.risk_factors.append("连续3日放量下跌，加速下跌风险")
                result.score_breakdown['vol_trend_3d'] = -1
        elif vol_trend_3d == "连续缩量":
            if result.bias_ma5 < 0:
                adj += 1
                result.signal_reasons.append("连续3日缩量回调，洗盘特征")
                result.score_breakdown['vol_trend_3d'] = 1


    @staticmethod
    def score_concept_decay(result: TrendAnalysisResult, stock_code: str):
        """B-3: 概念退潮风险评分。个股所有概念今日跌幅均>2%时扣0.3分（映射到-3 breakdown）"""
        try:
            from src.storage import DatabaseManager
            from src.config import get_config
            import json as _json

            db = DatabaseManager.get_instance()
            config = get_config()

            my_concepts = db.get_stock_concepts(stock_code)
            if not my_concepts:
                return

            today_str = datetime.now().strftime('%Y-%m-%d')
            cached = db.get_data_cache('concept_daily', today_str,
                                        ttl_hours=config.cache_ttl_concept_hours)
            if not cached:
                return

            data = _json.loads(cached)
            concept_pcts: Dict[str, float] = {}
            for c in data.get('concepts', []):
                concept_pcts[c['name']] = c.get('pct_chg', 0)

            matched_pcts: List[float] = []
            for mc in my_concepts:
                if mc.concept_name in concept_pcts:
                    matched_pcts.append(concept_pcts[mc.concept_name])

            if not matched_pcts:
                return

            if all(p < -2.0 for p in matched_pcts):
                result.score_breakdown['concept_decay'] = -3
                result.risk_factors.append(
                    f"概念题材全面退潮(所属{len(matched_pcts)}个概念今日均跌超2%)"
                )
        except Exception:
            pass

