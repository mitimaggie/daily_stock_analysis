import React, { useMemo } from 'react';
import type { AnalysisResult, AnalysisReport } from '../../types/analysis';
import { ReportOverview } from './ReportOverview';
import { ScoreTrend } from './ScoreTrend';
import { TradeLog } from '../trade/TradeLog';
import { ReportStrategy } from './ReportStrategy';
import { ReportNews } from './ReportNews';
import { ReportDetails } from './ReportDetails';
import { QuantAnalysis } from './QuantAnalysis';
import { AIAnalysis } from './AIAnalysis';
import { PositionDiagnosis } from './PositionDiagnosis';

interface ReportSummaryProps {
  data: AnalysisResult | AnalysisReport;
  isHistory?: boolean;
}

/**
 * 完整报告展示组件
 * 整合概览、量化分析、AI视角、策略、资讯、详情六个区域
 */
export const ReportSummary: React.FC<ReportSummaryProps> = ({
  data,
  isHistory = false,
}) => {
  // 兼容 AnalysisResult 和 AnalysisReport 两种数据格式
  const report: AnalysisReport = 'report' in data ? data.report : data;
  const queryId = 'queryId' in data ? data.queryId : report.meta.queryId;

  const { meta, summary, strategy, details } = report;

  // 从 rawResult 中提取 dashboard 数据（量化分析 + AI视角）
  const { quantExtras, intelligence, counterArguments, positionInfo, newsContent } = useMemo(() => {
    const raw = details?.rawResult as Record<string, any> | undefined;
    if (!raw) return { quantExtras: null, intelligence: null, counterArguments: null, positionInfo: null, newsContent: null };

    const dashboard = raw.dashboard ?? raw;
    return {
      quantExtras: dashboard?.quant_extras ?? dashboard?.quantExtras ?? null,
      intelligence: dashboard?.intelligence ?? null,
      counterArguments: dashboard?.counter_arguments ?? dashboard?.counterArguments ?? null,
      positionInfo: dashboard?.position_info ?? dashboard?.positionInfo ?? null,
      newsContent: null,
    };
  }, [details?.rawResult]);

  // news_content 优先从 details.newsContent（DB字段）获取
  const effectiveNewsContent = details?.newsContent ?? newsContent;

  return (
    <div className="space-y-4 animate-fade-in">
      {/* 概览区（首屏） */}
      <ReportOverview
        meta={meta}
        summary={summary}
        isHistory={isHistory}
      />

      {/* 持仓诊断（有持仓信息时显示） */}
      {positionInfo && (
        <PositionDiagnosis
          positionInfo={positionInfo}
          currentPrice={meta.currentPrice}
          suggestedPositionPct={quantExtras?.suggested_position_pct ?? quantExtras?.suggestedPositionPct}
          stopLoss={strategy?.stopLoss}
          takeProfit={strategy?.takeProfit}
        />
      )}

      {/* 量化分析详情 */}
      {quantExtras && <QuantAnalysis data={quantExtras} />}

      {/* AI 分析视角 */}
      {intelligence && (
        <AIAnalysis
          intelligence={intelligence}
          counterArguments={counterArguments}
        />
      )}

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
      <ReportNews queryId={queryId} newsContentFallback={effectiveNewsContent} />

      {/* 透明度与追溯区 */}
      <ReportDetails details={details} queryId={queryId} />
    </div>
  );
};
