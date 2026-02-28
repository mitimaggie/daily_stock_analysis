# -*- coding: utf-8 -*-
"""
===================================
回测模块 - 验证分析系统的实际胜率
===================================

功能：
1. 回填 analysis_history 中 5 个交易日后的实际收益率
2. 检查止损/止盈是否被触发
3. 输出按评分段位的胜率/平均收益/止损命中率统计

使用：python main.py --backtest
"""

import logging
from datetime import datetime, timedelta, date
from typing import List, Dict, Any, Optional, Tuple

import pandas as pd
import numpy as np
from sqlalchemy import select, and_, text

from src.storage import DatabaseManager, AnalysisHistory

logger = logging.getLogger(__name__)


class BacktestRunner:
    """分析回测器：回填实际收益并统计胜率"""

    def __init__(self):
        self.db = DatabaseManager()

    def run(self, lookback_days: int = 60) -> str:
        """执行回测，返回统计报告文本"""
        logger.info("===== 开始回测分析 =====")
        
        # 1. 找到需要回填的记录（created_at > 5 交易日前 且 backtest_filled=0）
        unfilled = self._get_unfilled_records(lookback_days)
        if unfilled:
            logger.info(f"发现 {len(unfilled)} 条待回填记录")
            filled_count = self._backfill_records(unfilled)
            logger.info(f"成功回填 {filled_count} 条")
        else:
            logger.info("无新的待回填记录")

        # 2. 生成统计报告
        report = self._generate_stats_report(lookback_days)
        logger.info("===== 回测分析完成 =====")
        return report

    def _get_unfilled_records(self, lookback_days: int) -> List[AnalysisHistory]:
        """获取需要回填的历史记录（5个交易日前的 + 未回填）"""
        cutoff = datetime.now() - timedelta(days=lookback_days)
        # 至少 7 天前的记录才能回填（5 个交易日 ≈ 7 自然日）
        fill_deadline = datetime.now() - timedelta(days=7)
        
        with self.db.get_session() as session:
            results = session.execute(
                select(AnalysisHistory).where(
                    and_(
                        AnalysisHistory.created_at >= cutoff,
                        AnalysisHistory.created_at <= fill_deadline,
                        AnalysisHistory.backtest_filled == 0,
                    )
                ).order_by(AnalysisHistory.created_at)
            ).scalars().all()
            # Detach from session
            return [r for r in results]

    def _backfill_records(self, records: List[AnalysisHistory]) -> int:
        """回填实际收益率（含多周期）"""
        filled = 0
        for record in records:
            try:
                code = record.code
                analysis_date = record.created_at.date() if record.created_at else None
                if not analysis_date:
                    continue

                # 获取分析日之后 20 个交易日的价格数据（支持多周期回测）
                df = self._get_prices_after(code, analysis_date, days=25)
                if df is None or len(df) < 5:
                    continue

                # 分析日的收盘价（用第一条记录）
                price_at_analysis = float(df.iloc[0]['close'])
                if price_at_analysis <= 0:
                    continue

                # 多周期收益率：5日、10日、20日
                price_5d = float(df.iloc[4]['close']) if len(df) >= 5 else float(df.iloc[-1]['close'])
                actual_pct_5d = round((price_5d - price_at_analysis) / price_at_analysis * 100, 2)
                
                actual_pct_10d = None
                if len(df) >= 10:
                    price_10d = float(df.iloc[9]['close'])
                    actual_pct_10d = round((price_10d - price_at_analysis) / price_at_analysis * 100, 2)
                
                actual_pct_20d = None
                if len(df) >= 20:
                    price_20d = float(df.iloc[19]['close'])
                    actual_pct_20d = round((price_20d - price_at_analysis) / price_at_analysis * 100, 2)

                # 检查止损/止盈是否触发（在 5 日内的最低价/最高价）
                lows_5d = df['low'].iloc[:5].astype(float)
                highs_5d = df['high'].iloc[:5].astype(float)
                
                hit_sl = 0
                hit_tp = 0
                if record.stop_loss and record.stop_loss > 0:
                    hit_sl = 1 if float(lows_5d.min()) <= record.stop_loss else 0
                if record.take_profit and record.take_profit > 0:
                    hit_tp = 1 if float(highs_5d.max()) >= record.take_profit else 0

                # 获取同期大盘收益率（用于计算alpha）
                benchmark_pct_5d = self._get_benchmark_return(analysis_date, 5)
                benchmark_pct_10d = self._get_benchmark_return(analysis_date, 10) if actual_pct_10d else None
                benchmark_pct_20d = self._get_benchmark_return(analysis_date, 20) if actual_pct_20d else None

                # 更新记录（扩展多周期数据，但暂存在原字段，避免修改表结构）
                # 实际生产中应添加新字段：actual_pct_10d, actual_pct_20d, benchmark_pct_5d等
                self._update_record(
                    record.id, actual_pct_5d, hit_sl, hit_tp,
                    actual_pct_10d=actual_pct_10d,
                    actual_pct_20d=actual_pct_20d,
                    benchmark_pct_5d=benchmark_pct_5d,
                    benchmark_pct_10d=benchmark_pct_10d,
                    benchmark_pct_20d=benchmark_pct_20d
                )
                filled += 1

            except Exception as e:
                logger.debug(f"回填 {record.code} ({record.created_at}) 失败: {e}")
                continue

        return filled

    def _get_prices_after(self, code: str, after_date: date, days: int = 10) -> Optional[pd.DataFrame]:
        """从 stock_daily 获取指定日期（含当天）起的价格数据。
        
        第一条记录为分析日当天收盘价（买入基准），
        后续 idx=4/9/19 分别对应 5/10/20 日后收益。
        """
        try:
            sql = text("""
                SELECT date, open, high, low, close, volume 
                FROM stock_daily
                WHERE code = :code AND date >= :after_date
                ORDER BY date ASC
                LIMIT :limit
            """)
            with self.db._engine.connect() as conn:
                df = pd.read_sql(sql, conn, params={"code": code, "after_date": after_date, "limit": days})
            return df if not df.empty else None
        except Exception:
            return None

    def _get_benchmark_return(self, start_date: date, holding_days: int) -> Optional[float]:
        """获取基准（沪深300）收益率
        
        Args:
            start_date: 起始日期
            holding_days: 持有天数
        
        Returns:
            基准收益率(%)，失败返回None
        """
        try:
            # 从 index_daily 表获取沪深300数据
            sql = text("""
                SELECT date, close
                FROM index_daily
                WHERE name = '沪深300' AND date >= :start_date
                ORDER BY date ASC
                LIMIT :limit
            """)
            with self.db._engine.connect() as conn:
                df = pd.read_sql(sql, conn, params={"start_date": start_date, "limit": holding_days + 2})
            
            if df.empty or len(df) < holding_days:
                return None
            
            price_start = float(df.iloc[0]['close'])
            price_end = float(df.iloc[min(holding_days - 1, len(df) - 1)]['close'])
            
            if price_start <= 0:
                return None
            
            return round((price_end - price_start) / price_start * 100, 2)
        except Exception as e:
            logger.debug(f"获取基准收益率失败: {e}")
            return None

    def _update_record(self, record_id: int, actual_pct: float, hit_sl: int, hit_tp: int,
                      actual_pct_10d: Optional[float] = None,
                      actual_pct_20d: Optional[float] = None,
                      benchmark_pct_5d: Optional[float] = None,
                      benchmark_pct_10d: Optional[float] = None,
                      benchmark_pct_20d: Optional[float] = None):
        """更新单条回测记录（含多周期数据）
        
        注：多周期数据暂存在 raw_result JSON 中，避免频繁修改表结构
        """
        with self.db.get_session() as session:
            try:
                record = session.get(AnalysisHistory, record_id)
                if record:
                    record.actual_pct_5d = actual_pct
                    record.hit_stop_loss = hit_sl
                    record.hit_take_profit = hit_tp
                    record.backtest_filled = 1
                    
                    # 扩展回测数据存入 raw_result（JSON格式，灵活扩展）
                    try:
                        import json
                        raw = json.loads(record.raw_result) if record.raw_result else {}
                        backtest_ext = {
                            'actual_pct_10d': actual_pct_10d,
                            'actual_pct_20d': actual_pct_20d,
                            'benchmark_pct_5d': benchmark_pct_5d,
                            'benchmark_pct_10d': benchmark_pct_10d,
                            'benchmark_pct_20d': benchmark_pct_20d,
                            'alpha_5d': round(actual_pct - benchmark_pct_5d, 2) if benchmark_pct_5d is not None else None,
                            'alpha_10d': round(actual_pct_10d - benchmark_pct_10d, 2) if actual_pct_10d and benchmark_pct_10d else None,
                            'alpha_20d': round(actual_pct_20d - benchmark_pct_20d, 2) if actual_pct_20d and benchmark_pct_20d else None,
                        }
                        raw['backtest_metrics'] = backtest_ext
                        record.raw_result = json.dumps(raw, ensure_ascii=False)
                    except Exception:
                        pass  # raw_result 更新失败不影响主流程
                    
                    session.commit()
            except Exception as e:
                session.rollback()
                logger.debug(f"更新回测记录 {record_id} 失败: {e}")

    def _generate_stats_report(self, lookback_days: int) -> str:
        """生成增强版回测统计报告（含夏普、信息比率、alpha等）"""
        with self.db.get_session() as session:
            cutoff = datetime.now() - timedelta(days=lookback_days)
            records = session.execute(
                select(AnalysisHistory).where(
                    and_(
                        AnalysisHistory.created_at >= cutoff,
                        AnalysisHistory.backtest_filled == 1,
                    )
                )
            ).scalars().all()

        if not records:
            return "暂无可统计的回测数据（需要至少运行 7 天后才有回填数据）"

        # === 去重：同股同日只保留最高评分的记录，避免重复分析污染统计 ===
        dedup_map: dict = {}
        for r in records:
            if r.actual_pct_5d is None:
                continue
            day_key = (r.code, r.created_at.date() if r.created_at else None)
            existing = dedup_map.get(day_key)
            if existing is None or (r.sentiment_score or 0) > (existing.sentiment_score or 0):
                dedup_map[day_key] = r
        records = list(dedup_map.values())

        # 按评分段位分组统计
        buckets = {"85+": [], "70-84": [], "50-69": [], "<50": []}
        buy_records = []

        for r in records:
            score = r.sentiment_score or 50
            pct = r.actual_pct_5d
            if pct is None:
                continue

            if score >= 85:
                buckets["85+"].append(r)
            elif score >= 70:
                buckets["70-84"].append(r)
            elif score >= 50:
                buckets["50-69"].append(r)
            else:
                buckets["<50"].append(r)

            # "买入"类建议的统计
            advice = r.operation_advice or ""
            if "买" in advice or "加仓" in advice:
                buy_records.append(r)

        # 买入信号数量（含全量对比用）
        total_filled = len([r for r in records if r.actual_pct_5d is not None])
        buy_count_total = len(buy_records)

        lines = [
            f"## 📊 回测统计报告（近 {lookback_days} 天，共 {total_filled} 条已回填，其中买入信号 {buy_count_total} 条）",
            "",
            "> ⚠️ **回测口径说明**：同股同日重复分析已去重（保留最高评分），胜率/收益以「买入/加仓」信号为统计基准，观望/减仓/卖出信号不纳入业绩计算（避免稀释）",
            "",
        ]

        # === 1. 整体业绩摘要：以买入信号为核心，附全量参考 ===
        buy_pcts_all = [r.actual_pct_5d for r in buy_records if r.actual_pct_5d is not None]
        all_pcts = [r.actual_pct_5d for r in records if r.actual_pct_5d is not None]

        if buy_pcts_all:
            buy_sharpe, buy_ir, buy_dd, buy_calmar = self._calc_performance_metrics(buy_records)
            buy_avg = sum(buy_pcts_all) / len(buy_pcts_all)
            buy_win = sum(1 for p in buy_pcts_all if p > 0) / len(buy_pcts_all) * 100

            # 全量对比（参考）
            all_avg = sum(all_pcts) / len(all_pcts) if all_pcts else 0.0
            all_win = sum(1 for p in all_pcts if p > 0) / len(all_pcts) * 100 if all_pcts else 0.0

            lines.extend([
                "### 🎯 核心业绩指标（买入信号）",
                "",
                "| 指标 | 买入信号 | 全量参考 | 说明 |",
                "|------|---------|---------|------|",
                f"| 平均5日收益 | **{buy_avg:+.2f}%** | {all_avg:+.2f}% | 买入信号持有5日的平均收益 |",
                f"| 胜率 | **{buy_win:.1f}%** | {all_win:.1f}% | 盈利交易占比 |",
                f"| 夏普比率 | **{buy_sharpe:.2f}** | - | 风险调整后收益，>1优秀 |",
                f"| 信息比率 | **{buy_ir:.2f}** | - | 相对基准的超额收益/跟踪误差 |",
                f"| 最大回撤 | **{buy_dd:.2f}%** | - | 峰谷最大跌幅 |",
                f"| 卡玛比率 | **{buy_calmar:.2f}** | - | 年化收益/最大回撤，>2优秀 |",
                "",
                "---",
                "",
            ])
        elif all_pcts:
            # 没有买入信号时退回全量展示
            sharpe, info_ratio, max_dd, calmar = self._calc_performance_metrics(records)
            total_avg = sum(all_pcts) / len(all_pcts)
            total_win = sum(1 for p in all_pcts if p > 0) / len(all_pcts) * 100
            lines.extend([
                "### 🎯 整体业绩指标（无买入信号，展示全量）",
                "",
                "| 指标 | 数值 | 说明 |",
                "|------|------|------|",
                f"| 平均5日收益 | **{total_avg:+.2f}%** | 所有信号的平均收益率 |",
                f"| 胜率 | **{total_win:.1f}%** | 盈利交易占比 |",
                f"| 夏普比率 | **{sharpe:.2f}** | 风险调整后收益，>1优秀 |",
                f"| 信息比率 | **{info_ratio:.2f}** | 相对基准的超额收益/跟踪误差 |",
                f"| 最大回撤 | **{max_dd:.2f}%** | 峰谷最大跌幅 |",
                f"| 卡玛比率 | **{calmar:.2f}** | 年化收益/最大回撤，>2优秀 |",
                "",
                "---",
                "",
            ])

        # === 2. 按评分段位分析（含alpha） ===
        lines.append("### 📈 各评分段位表现")
        lines.append("")
        lines.append("| 评分段位 | 记录数 | 平均收益 | Alpha | 胜率 | 夏普 | 止损命中 | 止盈命中 |")
        lines.append("|---------|--------|---------|-------|------|------|---------|---------|")
        
        for bucket_name, bucket_records in buckets.items():
            if not bucket_records:
                lines.append(f"| {bucket_name} | 0 | - | - | - | - | - | - |")
                continue
            
            pcts = [r.actual_pct_5d for r in bucket_records if r.actual_pct_5d is not None]
            if not pcts:
                lines.append(f"| {bucket_name} | {len(bucket_records)} | N/A | N/A | N/A | N/A | N/A | N/A |")
                continue

            avg_pct = sum(pcts) / len(pcts)
            win_rate = sum(1 for p in pcts if p > 0) / len(pcts) * 100
            
            # Alpha计算（超额收益 = 个股收益 - 基准收益）
            alphas = []
            for r in bucket_records:
                if r.actual_pct_5d is not None and r.raw_result:
                    try:
                        import json
                        raw = json.loads(r.raw_result)
                        alpha_5d = raw.get('backtest_metrics', {}).get('alpha_5d')
                        if alpha_5d is not None:
                            alphas.append(alpha_5d)
                    except Exception:
                        pass
            avg_alpha = sum(alphas) / len(alphas) if alphas else 0.0
            
            # 夏普比率（段位内）
            bucket_sharpe = self._calc_sharpe_ratio(pcts)
            
            sl_hits = sum(1 for r in bucket_records if r.hit_stop_loss == 1)
            tp_hits = sum(1 for r in bucket_records if r.hit_take_profit == 1)
            sl_rate = sl_hits / len(bucket_records) * 100
            tp_rate = tp_hits / len(bucket_records) * 100

            lines.append(
                f"| {bucket_name} | {len(bucket_records)} | {avg_pct:+.2f}% | {avg_alpha:+.2f}% | {win_rate:.0f}% | {bucket_sharpe:.2f} | {sl_rate:.0f}% | {tp_rate:.0f}% |"
            )

        # === 3. 买入信号专项验证 ===
        lines.append("")
        lines.append("---")
        lines.append("")
        if buy_records:
            buy_pcts = [r.actual_pct_5d for r in buy_records if r.actual_pct_5d is not None]
            if buy_pcts:
                buy_win = sum(1 for p in buy_pcts if p > 0) / len(buy_pcts) * 100
                buy_avg = sum(buy_pcts) / len(buy_pcts)
                buy_sharpe = self._calc_sharpe_ratio(buy_pcts)
                lines.append(f"### 💰 买入信号验证")
                lines.append(f"- 买入信号总数: **{len(buy_records)}**")
                lines.append(f"- 5日胜率: **{buy_win:.1f}%**")
                lines.append(f"- 平均5日收益: **{buy_avg:+.2f}%**")
                lines.append(f"- 夏普比率: **{buy_sharpe:.2f}**")
        else:
            lines.append("### 💰 买入信号验证")
            lines.append("*暂无买入信号记录*")

        lines.extend([
            "",
            "---",
            "",
            "### 📌 指标说明",
            "- **夏普比率**: 风险调整后收益，计算公式 = (平均收益 - 无风险利率) / 收益标准差",
            "- **信息比率**: 相对基准的超额收益/跟踪误差，衡量主动管理能力",
            "- **Alpha**: 超额收益 = 个股收益 - 同期沪深300收益",
            "- **卡玛比率**: 年化收益/最大回撤，衡量风险收益比",
        ])

        return "\n".join(lines)

    def _calc_sharpe_ratio(self, returns: List[float], rf_rate: float = 0.03) -> float:
        """计算夏普比率
        
        Args:
            returns: 收益率列表(%)
            rf_rate: 无风险利率(年化)，默认3%
        
        Returns:
            夏普比率
        """
        if not returns or len(returns) < 2:
            return 0.0
        
        returns_array = np.array(returns) / 100  # 转为小数
        avg_return = np.mean(returns_array)
        std_return = np.std(returns_array, ddof=1)
        
        if std_return == 0:
            return 0.0
        
        # 5日收益率年化：假设1年250个交易日，5日为1/50年
        # 年化收益 = 5日平均收益 * (250/5) = 平均收益 * 50
        # 年化波动 = 5日波动 * sqrt(250/5) = 波动 * sqrt(50)
        rf_5d = rf_rate / 50  # 无风险利率转为5日
        sharpe = (avg_return - rf_5d) / std_return * np.sqrt(50)
        
        return round(sharpe, 2)

    def _calc_performance_metrics(self, records: List[AnalysisHistory]) -> Tuple[float, float, float, float]:
        """计算整体业绩指标：夏普、信息比率、最大回撤、卡玛比率
        
        Returns:
            (sharpe_ratio, information_ratio, max_drawdown, calmar_ratio)
        """
        returns = [r.actual_pct_5d for r in records if r.actual_pct_5d is not None]
        if not returns:
            return 0.0, 0.0, 0.0, 0.0
        
        # 1. 夏普比率
        sharpe = self._calc_sharpe_ratio(returns)
        
        # 2. 信息比率 = (策略平均收益 - 基准平均收益) / 跟踪误差
        alphas = []
        for r in records:
            if r.actual_pct_5d is not None and r.raw_result:
                try:
                    import json
                    raw = json.loads(r.raw_result)
                    alpha_5d = raw.get('backtest_metrics', {}).get('alpha_5d')
                    if alpha_5d is not None:
                        alphas.append(alpha_5d)
                except Exception:
                    pass
        
        if alphas and len(alphas) >= 2:
            avg_alpha = np.mean(alphas)
            tracking_error = np.std(alphas, ddof=1)
            info_ratio = (avg_alpha / tracking_error * np.sqrt(50)) if tracking_error > 0 else 0.0
        else:
            info_ratio = 0.0
        
        # 3. 最大回撤（累计收益曲线的峰谷差）
        cumulative = np.cumsum([r / 100 for r in returns])  # 累计收益率（小数）
        running_max = np.maximum.accumulate(cumulative)
        drawdown = (cumulative - running_max) * 100  # 转回百分比
        max_drawdown = abs(np.min(drawdown)) if len(drawdown) > 0 else 0.0
        
        # 4. 卡玛比率 = 年化收益 / 最大回撤
        avg_return = np.mean(returns)
        annual_return = avg_return * 50  # 5日收益年化
        calmar = (annual_return / max_drawdown) if max_drawdown > 0 else 0.0
        
        return (
            round(sharpe, 2),
            round(info_ratio, 2),
            round(max_drawdown, 2),
            round(calmar, 2)
        )
