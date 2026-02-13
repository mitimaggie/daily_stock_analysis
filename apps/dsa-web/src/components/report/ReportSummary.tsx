import React, { useMemo } from 'react';
import type { AnalysisResult, AnalysisReport } from '../../types/analysis';
import { ReportOverview } from './ReportOverview';
import { ScoreTrend } from './ScoreTrend';
import { TradeLog } from '../trade/TradeLog';
import { ReportStrategy } from './ReportStrategy';
import { ReportNews } from './ReportNews';
import { ReportDetails } from './ReportDetails';
import { QuantAnalysis } from './QuantAnalysis';
import { PositionDiagnosis } from './PositionDiagnosis';
import { QuantVsAi } from './QuantVsAi';
import { TodaySnapshot } from './TodaySnapshot';
import { KeyPriceLevels } from './KeyPriceLevels';
import { KeyInsights } from './KeyInsights';

interface ReportSummaryProps {
  data: AnalysisResult | AnalysisReport;
  isHistory?: boolean;
  onRefresh?: () => void;
  isRefreshing?: boolean;
}

/**
 * 完整报告展示组件
 * 整合概览、量化分析、AI视角、策略、资讯、详情六个区域
 */
export const ReportSummary: React.FC<ReportSummaryProps> = ({
  data,
  isHistory = false,
  onRefresh,
  isRefreshing,
}) => {
  // 兼容 AnalysisResult 和 AnalysisReport 两种数据格式
  const report: AnalysisReport = 'report' in data ? data.report : data;
  const queryId = 'queryId' in data ? data.queryId : report.meta.queryId;

  const { meta, summary, strategy, todaySnapshot, details } = report;

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
    <div className="space-y-3 animate-fade-in">
      {/* 概览区（首屏） */}
      <ReportOverview
        meta={meta}
        summary={summary}
        isHistory={isHistory}
        onRefresh={onRefresh}
        isRefreshing={isRefreshing}
      />

      {/* 量化 vs AI 对比（紧跟概览） */}
      {summary.quantVsAi && (
        <QuantVsAi data={summary.quantVsAi} />
      )}

      {/* 当日行情快照 */}
      {todaySnapshot && Object.keys(todaySnapshot).length > 2 && (
        <TodaySnapshot data={todaySnapshot} />
      )}

      {/* 作战计划（始终展示） */}
      <ReportStrategy strategy={strategy} />

      {/* 盘中关键价位（有数据时展示） */}
      {strategy?.keyPriceLevels && strategy.keyPriceLevels.length > 0 && (
        <KeyPriceLevels
          levels={strategy.keyPriceLevels}
          currentPrice={meta.currentPrice}
          riskRewardRatio={strategy.riskRewardRatio}
          takeProfitPlan={strategy.takeProfitPlan}
        />
      )}

      {/* 持仓诊断（有持仓信息时显示） */}
      {positionInfo && (
        <PositionDiagnosis
          positionInfo={positionInfo}
          currentPrice={meta.currentPrice}
          suggestedPositionPct={quantExtras?.suggested_position_pct ?? quantExtras?.suggestedPositionPct}
          stopLoss={strategy?.stopLoss}
          takeProfit={strategy?.takeProfit}
          holdingStrategy={strategy?.holdingStrategy}
        />
      )}

      {/* 重要信息汇总（合并 AI 分析 + 量化风险因子） */}
      <KeyInsights
        intelligence={intelligence}
        counterArguments={counterArguments}
        quantExtras={quantExtras}
      />

      {/* 量化分析 */}
      {quantExtras && <QuantAnalysis data={quantExtras} />}

      {/* 资讯区 */}
      <ReportNews queryId={queryId} newsContentFallback={effectiveNewsContent} />

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

      {/* 透明度与追溯区 */}
      <ReportDetails details={details} queryId={queryId} />
    </div>
  );
};
