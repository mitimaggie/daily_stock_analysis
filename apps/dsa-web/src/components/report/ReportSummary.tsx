import React, { useMemo, useState } from 'react';
import type { AnalysisResult, AnalysisReport } from '../../types/analysis';
import { ReportOverview } from './ReportOverview';
import { TradeLog } from '../trade/TradeLog';
import { ReportStrategy } from './ReportStrategy';
import { ReportNews } from './ReportNews';
import { QuantAnalysis } from './QuantAnalysis';
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

/** 持仓快照条：紧凑展示成本/浮盈/持仓天数 */
const PositionSnapshotBar: React.FC<{
  positionInfo: Record<string, any>;
  currentPrice?: number;
}> = ({ positionInfo, currentPrice }) => {
  const costPrice = positionInfo.cost_price ?? positionInfo.costPrice ?? 0;
  const holdingDays = positionInfo.holding_days ?? null;

  if (!costPrice) return null;

  const pnlPct = currentPrice && costPrice > 0
    ? ((currentPrice - costPrice) / costPrice * 100)
    : null;
  const pnlColor = pnlPct == null ? 'text-white/40' : pnlPct >= 0 ? 'text-emerald-400' : 'text-red-400';
  const pnlSign = pnlPct != null && pnlPct >= 0 ? '+' : '';

  return (
    <div className="rounded-xl bg-[var(--bg-card)] border border-white/[0.06] px-4 py-2.5 flex items-center gap-4 flex-wrap">
      <span className="text-[11px] text-white/30 font-medium tracking-wide uppercase">持仓</span>
      <span className="text-[13px] text-white/70">成本 <span className="text-white/90 font-medium">{costPrice.toFixed(2)}</span></span>
      {pnlPct != null && (
        <span className={`text-[13px] font-medium ${pnlColor}`}>
          {pnlSign}{pnlPct.toFixed(2)}%
        </span>
      )}
      {holdingDays != null && (
        <span className="text-[13px] text-white/50">持有 <span className="text-white/70">{holdingDays}</span> 天</span>
      )}
    </div>
  );
};

/** 可折叠的量化数据面板 */
const QuantPanel: React.FC<{
  quantExtras: Record<string, any> | null;
  quantVsAi: any;
  skillUsed?: string;
}> = ({ quantExtras, quantVsAi, skillUsed }) => {
  const [open, setOpen] = useState(false);
  if (!quantExtras && !quantVsAi) return null;

  return (
    <div className="rounded-xl bg-[var(--bg-card)] border border-white/[0.06] overflow-hidden">
      <button
        type="button"
        className="w-full flex items-center justify-between px-4 py-3 hover:bg-white/[0.02] transition"
        onClick={() => setOpen(v => !v)}
      >
        <span className="text-sm font-semibold text-white/60 flex items-center gap-1.5">
          <span>📊</span> 量化数据
        </span>
        <span className="text-xs text-white/25">{open ? '▲ 收起' : '▼ 展开'}</span>
      </button>
      {open && (
        <div className="border-t border-white/[0.04] space-y-3 p-3">
          {quantExtras && <QuantAnalysis data={quantExtras} />}
          {quantVsAi && <QuantVsAi data={quantVsAi} skillUsed={skillUsed} />}
        </div>
      )}
    </div>
  );
};

/**
 * 报告展示组件 — AI优先布局
 *
 * 设计原则：
 * - AI分析是主角，默认展开，置于页面核心位置
 * - 持仓信息用紧凑快照条展示，不占大量空间
 * - 量化数据折叠，需要时展开
 * - 移除透明度追溯区（ReportDetails）和独立的 QuantVsAi 顶层展示
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
  const report: AnalysisReport = 'report' in data ? data.report : data;
  const queryId = 'queryId' in data ? data.queryId : report.meta.queryId;

  const { meta, summary, strategy, details } = report;

  const {
    quantExtras, intelligence, counterArguments, positionInfo,
    oneSentence, dashboardHoldingStrategy, defenseMode,
    scoreMomentumAdj, positionDiagnosis, actionNow,
    executionDifficulty, executionNote, behavioralWarning,
    skillUsed, resonanceLevel, capitalConflictWarning,
  } = useMemo(() => {
    const raw = details?.rawResult as Record<string, any> | undefined;
    if (!raw) return {
      quantExtras: null, intelligence: null, counterArguments: null, positionInfo: null,
      oneSentence: null, dashboardHoldingStrategy: null, defenseMode: false,
      scoreMomentumAdj: 0, positionDiagnosis: null, actionNow: null,
      executionDifficulty: null, executionNote: null, behavioralWarning: null,
      skillUsed: null, resonanceLevel: null, capitalConflictWarning: null,
    };
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
      resonanceLevel: (dashboard?.quant_extras ?? dashboard?.quantExtras)?.resonance_level ?? null,
      capitalConflictWarning: dashboard?.capital_conflict_warning ?? null,
    };
  }, [details?.rawResult]);

  const hasPosition = !!positionInfo;
  const positionAdvice =
    (details?.rawResult as Record<string, any>)?.dashboard?.core_conclusion?.position_advice ??
    (details?.rawResult as Record<string, any>)?.core_conclusion?.position_advice ??
    undefined;

  return (
    <div className="space-y-3 animate-fade-in">
      {/* 1. 股票概览（紧凑 Hero）*/}
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
        resonanceLevel={resonanceLevel ?? undefined}
        capitalConflictWarning={capitalConflictWarning ?? undefined}
      />

      {/* 2. 持仓快照（有持仓时：紧凑一行，成本/浮盈/持有天数）*/}
      {positionInfo && (
        <PositionSnapshotBar
          positionInfo={positionInfo}
          currentPrice={meta.currentPrice}
        />
      )}

      {/* 3. AI 分析（主角：默认展开）*/}
      <AiDiagnosis
        analysisSummary={summary.analysisSummary}
        intelligence={intelligence}
        counterArguments={counterArguments}
        positionAdvice={positionAdvice}
        defaultExpanded={true}
      />

      {/* 4. 操作计划（止损/止盈/仓位）*/}
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

      {/* 5. 关键价位（有时才显示）*/}
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

      {/* 6. 量化数据（折叠）*/}
      <QuantPanel
        quantExtras={quantExtras}
        quantVsAi={summary.quantVsAi}
        skillUsed={skillUsed ?? undefined}
      />

      {/* 7. 公告与资讯 */}
      <ReportNews stockCode={meta.stockCode} />

      {/* 8. 交易日志 */}
      <TradeLog
        stockCode={meta.stockCode}
        stockName={meta.stockName}
        analysisScore={summary.sentimentScore}
        analysisAdvice={summary.operationAdvice}
        queryId={queryId}
        currentPrice={meta.currentPrice}
      />
    </div>
  );
};
