import React, { useMemo } from 'react';
import type { AnalysisResult, AnalysisReport } from '../../types/analysis';
import { ReportOverview } from './ReportOverview';
import { TradeLog } from '../trade/TradeLog';
import { ReportStrategy } from './ReportStrategy';
import { ReportNews } from './ReportNews';
import { ReportDetails } from './ReportDetails';
import { QuantAnalysis } from './QuantAnalysis';
import { PositionDiagnosis } from './PositionDiagnosis';
import { QuantVsAi } from './QuantVsAi';
import { KeyPriceLevels } from './KeyPriceLevels';
import { AiDiagnosis } from './AiDiagnosis';

interface ReportSummaryProps {
  data: AnalysisResult | AnalysisReport;
  isHistory?: boolean;
  onRefresh?: () => void;
  isRefreshing?: boolean;
  shares?: number;
  totalCapital?: number;
  onPositionChange?: (shares: number, costPrice: number) => void;
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
  shares,
  totalCapital,
  onPositionChange,
}) => {
  // 兼容 AnalysisResult 和 AnalysisReport 两种数据格式
  const report: AnalysisReport = 'report' in data ? data.report : data;
  const queryId = 'queryId' in data ? data.queryId : report.meta.queryId;

  const { meta, summary, strategy, details } = report;

  // 从 rawResult 中提取 dashboard 数据（量化分析 + AI视角）
  const { quantExtras, intelligence, counterArguments, positionInfo, oneSentence, dashboardHoldingStrategy, defenseMode, scoreMomentumAdj, positionDiagnosis, actionNow, executionDifficulty, executionNote, behavioralWarning, skillUsed } = useMemo(() => {
    const raw = details?.rawResult as Record<string, any> | undefined;
    if (!raw) return { quantExtras: null, intelligence: null, counterArguments: null, positionInfo: null, oneSentence: null, dashboardHoldingStrategy: null, defenseMode: false, scoreMomentumAdj: 0, positionDiagnosis: null, actionNow: null, executionDifficulty: null, executionNote: null, behavioralWarning: null, skillUsed: null };

    const dashboard = raw.dashboard ?? raw;
    const cc = dashboard?.core_conclusion ?? dashboard?.coreConclusion ?? {};
    return {
      quantExtras: dashboard?.quant_extras ?? dashboard?.quantExtras ?? null,
      intelligence: dashboard?.intelligence ?? null,
      counterArguments: dashboard?.counter_arguments ?? dashboard?.counterArguments ?? null,
      positionInfo: dashboard?.position_info ?? dashboard?.positionInfo ?? null,
      oneSentence: cc?.one_sentence ?? cc?.oneSentence ?? null,
      dashboardHoldingStrategy: dashboard?.holding_strategy ?? dashboard?.holdingStrategy ?? null,
      defenseMode: !!(dashboard?.defense_mode ?? dashboard?.defenseMode),
      scoreMomentumAdj: dashboard?.score_momentum_adj ?? dashboard?.scoreMomentumAdj ?? 0,
      positionDiagnosis: dashboard?.position_diagnosis ?? dashboard?.positionDiagnosis ?? null,
      actionNow: dashboard?.action_now ?? null,
      executionDifficulty: dashboard?.execution_difficulty ?? null,
      executionNote: dashboard?.execution_note ?? null,
      behavioralWarning: dashboard?.behavioral_warning ?? null,
      skillUsed: dashboard?.skill_used ?? null,
    };
  }, [details?.rawResult]);

  const hasPosition = !!positionInfo;

  return (
    <div className="space-y-3 animate-fade-in">
      {/* 1. 概览区（Hero） */}
      <ReportOverview
        meta={meta}
        summary={summary}
        hasPositionInfo={hasPosition}
        oneSentence={oneSentence ?? undefined}
        costPrice={positionInfo?.cost_price ?? positionInfo?.costPrice}
        positionAmount={positionInfo?.position_amount ?? positionInfo?.positionAmount}
        shares={shares}
        totalCapital={totalCapital}
        scoreMomentumAdj={scoreMomentumAdj}
        isHistory={isHistory}
        onRefresh={onRefresh}
        isRefreshing={isRefreshing}
        onPositionChange={onPositionChange}
        actionNow={actionNow ?? undefined}
        executionDifficulty={executionDifficulty ?? undefined}
        executionNote={executionNote ?? undefined}
        behavioralWarning={behavioralWarning ?? undefined}
        skillUsed={skillUsed ?? undefined}
      />

      {/* 2. 作战计划 */}
      <ReportStrategy
        strategy={strategy}
        hasPositionInfo={hasPosition}
        costPrice={positionInfo?.cost_price ?? positionInfo?.costPrice}
        currentPrice={meta.currentPrice}
        holdingStrategy={dashboardHoldingStrategy}
        defenseMode={defenseMode}
        maxDrawdown60d={quantExtras?.max_drawdown_60d ?? quantExtras?.maxDrawdown60d}
        positionDiagnosis={positionDiagnosis}
        suggestedPositionPct={quantExtras?.suggested_position_pct ?? quantExtras?.suggestedPositionPct ?? null}
      />

      {/* 3. 盘中关键价位 */}
      {strategy?.keyPriceLevels && strategy.keyPriceLevels.length > 0 && (
        <KeyPriceLevels
          levels={strategy.keyPriceLevels}
          currentPrice={meta.currentPrice}
          riskRewardRatio={strategy.riskRewardRatio}
          takeProfitPlan={strategy.takeProfitPlan}
          hasPositionInfo={hasPosition}
          costPrice={positionInfo?.cost_price ?? positionInfo?.costPrice}
          defenseMode={defenseMode}
        />
      )}

      {/* 4. 量化 vs AI 对比（含综合研判叙述） */}
      {summary.quantVsAi && (
        <QuantVsAi data={summary.quantVsAi} />
      )}

      {/* 5. 量化诊断（细化指标） */}
      {quantExtras && <QuantAnalysis data={quantExtras} />}

      {/* 6. AI 诊断（细化分析 + 信息依据） */}
      <AiDiagnosis
        analysisSummary={summary.analysisSummary}
        intelligence={intelligence}
        counterArguments={counterArguments}
        positionAdvice={
          (details?.rawResult as Record<string, any>)?.dashboard?.core_conclusion?.position_advice ??
          (details?.rawResult as Record<string, any>)?.core_conclusion?.position_advice ??
          undefined
        }
      />

      {/* 7. 持仓诊断（有持仓信息时显示） */}
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

      {/* 8. 公告与披露 */}
      <ReportNews stockCode={meta.stockCode} />

      {/* 9. 交易日志 */}
      <TradeLog
        stockCode={meta.stockCode}
        stockName={meta.stockName}
        analysisScore={summary.sentimentScore}
        analysisAdvice={summary.operationAdvice}
        queryId={queryId}
        currentPrice={meta.currentPrice}
      />

      {/* 11. 透明度与追溯区 */}
      <ReportDetails details={details} queryId={queryId} />
    </div>
  );
};
