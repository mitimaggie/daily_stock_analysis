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
from typing import List, Dict, Any, Optional

import pandas as pd
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
        """回填实际收益率"""
        filled = 0
        for record in records:
            try:
                code = record.code
                analysis_date = record.created_at.date() if record.created_at else None
                if not analysis_date:
                    continue

                # 获取分析日之后 5-10 个交易日的价格数据
                df = self._get_prices_after(code, analysis_date, days=10)
                if df is None or len(df) < 5:
                    continue

                # 分析日的收盘价（用第一条记录）
                price_at_analysis = float(df.iloc[0]['close'])
                if price_at_analysis <= 0:
                    continue

                # 5 日后收盘价
                price_5d = float(df.iloc[4]['close']) if len(df) >= 5 else float(df.iloc[-1]['close'])
                actual_pct = round((price_5d - price_at_analysis) / price_at_analysis * 100, 2)

                # 检查止损/止盈是否触发（在 5 日内的最低价/最高价）
                lows_5d = df['low'].iloc[:5].astype(float)
                highs_5d = df['high'].iloc[:5].astype(float)
                
                hit_sl = 0
                hit_tp = 0
                if record.stop_loss and record.stop_loss > 0:
                    hit_sl = 1 if float(lows_5d.min()) <= record.stop_loss else 0
                if record.take_profit and record.take_profit > 0:
                    hit_tp = 1 if float(highs_5d.max()) >= record.take_profit else 0

                # 更新记录
                self._update_record(record.id, actual_pct, hit_sl, hit_tp)
                filled += 1

            except Exception as e:
                logger.debug(f"回填 {record.code} ({record.created_at}) 失败: {e}")
                continue

        return filled

    def _get_prices_after(self, code: str, after_date: date, days: int = 10) -> Optional[pd.DataFrame]:
        """从 stock_daily 获取指定日期之后的价格数据"""
        try:
            sql = text("""
                SELECT date, open, high, low, close, volume 
                FROM stock_daily
                WHERE code = :code AND date > :after_date
                ORDER BY date ASC
                LIMIT :limit
            """)
            with self.db.engine.connect() as conn:
                df = pd.read_sql(sql, conn, params={"code": code, "after_date": after_date, "limit": days})
            return df if not df.empty else None
        except Exception:
            return None

    def _update_record(self, record_id: int, actual_pct: float, hit_sl: int, hit_tp: int):
        """更新单条回测记录"""
        with self.db.get_session() as session:
            try:
                record = session.get(AnalysisHistory, record_id)
                if record:
                    record.actual_pct_5d = actual_pct
                    record.hit_stop_loss = hit_sl
                    record.hit_take_profit = hit_tp
                    record.backtest_filled = 1
                    session.commit()
            except Exception as e:
                session.rollback()
                logger.debug(f"更新回测记录 {record_id} 失败: {e}")

    def _generate_stats_report(self, lookback_days: int) -> str:
        """生成回测统计报告"""
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

        lines = [
            f"## 回测统计（近 {lookback_days} 天，共 {len(records)} 条已回填）",
            "",
        ]

        # 按评分段位
        lines.append("### 各评分段位表现")
        lines.append("")
        lines.append("| 评分段位 | 记录数 | 平均5日收益 | 胜率 | 止损命中 | 止盈命中 |")
        lines.append("|---------|--------|-----------|------|---------|---------|")
        
        for bucket_name, bucket_records in buckets.items():
            if not bucket_records:
                lines.append(f"| {bucket_name} | 0 | - | - | - | - |")
                continue
            
            pcts = [r.actual_pct_5d for r in bucket_records if r.actual_pct_5d is not None]
            if not pcts:
                lines.append(f"| {bucket_name} | {len(bucket_records)} | N/A | N/A | N/A | N/A |")
                continue

            avg_pct = sum(pcts) / len(pcts)
            win_rate = sum(1 for p in pcts if p > 0) / len(pcts) * 100
            sl_hits = sum(1 for r in bucket_records if r.hit_stop_loss == 1)
            tp_hits = sum(1 for r in bucket_records if r.hit_take_profit == 1)
            sl_rate = sl_hits / len(bucket_records) * 100
            tp_rate = tp_hits / len(bucket_records) * 100

            lines.append(
                f"| {bucket_name} | {len(bucket_records)} | {avg_pct:+.2f}% | {win_rate:.0f}% | {sl_rate:.0f}% | {tp_rate:.0f}% |"
            )

        # 买入信号胜率
        lines.append("")
        if buy_records:
            buy_pcts = [r.actual_pct_5d for r in buy_records if r.actual_pct_5d is not None]
            if buy_pcts:
                buy_win = sum(1 for p in buy_pcts if p > 0) / len(buy_pcts) * 100
                buy_avg = sum(buy_pcts) / len(buy_pcts)
                lines.append(f"### 买入信号验证")
                lines.append(f"- 买入信号总数: {len(buy_records)}")
                lines.append(f"- 5日胜率: {buy_win:.0f}%")
                lines.append(f"- 平均5日收益: {buy_avg:+.2f}%")
        else:
            lines.append("*暂无买入信号记录*")

        return "\n".join(lines)
