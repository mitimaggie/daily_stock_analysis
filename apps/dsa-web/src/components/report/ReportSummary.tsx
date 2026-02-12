import React from 'react';
import type { AnalysisResult, AnalysisReport } from '../../types/analysis';
import { ReportOverview } from './ReportOverview';
import { ScoreTrend } from './ScoreTrend';
import { TradeLog } from '../trade/TradeLog';
import { ReportStrategy } from './ReportStrategy';
import { ReportNews } from './ReportNews';
import { ReportDetails } from './ReportDetails';

interface ReportSummaryProps {
  data: AnalysisResult | AnalysisReport;
  isHistory?: boolean;
}

/**
 * 完整报告展示组件
 * 整合概览、策略、资讯、详情四个区域
 */
export const ReportSummary: React.FC<ReportSummaryProps> = ({
  data,
  isHistory = false,
}) => {
  // 兼容 AnalysisResult 和 AnalysisReport 两种数据格式
  const report: AnalysisReport = 'report' in data ? data.report : data;
  const queryId = 'queryId' in data ? data.queryId : report.meta.queryId;

  const { meta, summary, strategy, details } = report;

  return (
    <div className="space-y-4 animate-fade-in">
      {/* 概览区（首屏） */}
      <ReportOverview
        meta={meta}
        summary={summary}
        isHistory={isHistory}
      />

      {/* 历史评分趋势 */}
      <ScoreTrend stockCode={meta.stockCode} currentQueryId={queryId} />

      {/* 交易日志 */}
      <TradeLog
        stockCode={meta.stockCode}
        stockName={meta.stockName}
        analysisScore={summary.sentimentScore}
        analysisAdvice={summary.operationAdvice}
        queryId={queryId}
        currentPrice={meta.currentPrice}
      />

      {/* 策略点位区 */}
      <ReportStrategy strategy={strategy} />

      {/* 资讯区 */}
      <ReportNews queryId={queryId} />

      {/* 透明度与追溯区 */}
      <ReportDetails details={details} queryId={queryId} />
    </div>
  );
};
