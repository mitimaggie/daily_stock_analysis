import React, { useMemo, useState } from 'react';
import type { AnalysisResult, AnalysisReport, HoldingHorizon } from '../../types/analysis';
import { ReportOverview } from './ReportOverview';
import { TradeLog } from '../trade/TradeLog';
import { ReportStrategy } from './ReportStrategy';
import { ReportNews } from './ReportNews';
import { QuantAnalysis } from './QuantAnalysis';
import { AiDiagnosis } from './AiDiagnosis';
import { SignalLights } from './SignalLights';
import { ConceptBadge } from './ConceptBadge';
import { EntryConditionCard } from './EntryConditionCard';
import { AiDigestCard } from './AiDigestCard';
import { ValuationBar } from './ValuationBar';
import { PnLHeader } from './PnLHeader';
import { HoldDecisionCard } from './HoldDecisionCard';
import { RiskAlertCard } from './RiskAlertCard';

interface ReportSummaryProps {
  data: AnalysisResult | AnalysisReport;
  isHistory?: boolean;
  onRefresh?: () => void;
  isRefreshing?: boolean;
  shares?: number;
  totalCapital?: number;
  onPositionChange?: (shares: number, costPrice: number) => void;
}

/** 可折叠的量化数据面板 */
const QuantPanel: React.FC<{
  quantExtras: Record<string, any> | null;
  skillUsed?: string;
}> = ({ quantExtras, skillUsed: _skillUsed }) => {
  const [open, setOpen] = useState(false);
  if (!quantExtras) return null;

  const qe = quantExtras as Record<string, any> | null;
  const maAlignment = qe?.ma_alignment ?? qe?.maAlignment;
  const valuationVerdict = qe?.valuation_verdict ?? qe?.valuationVerdict;
  const capitalFlow = qe?.capital_flow_signal ?? qe?.capitalFlowSignal;
  const isBullMa = maAlignment && (maAlignment.includes('多头') || maAlignment.includes('偏多'));
  const isBearMa = maAlignment && (maAlignment.includes('空头') || maAlignment.includes('偏空'));

  return (
    <div className="rounded-xl bg-[var(--bg-card)] border border-white/[0.06] overflow-hidden">
      <button
        type="button"
        className="w-full flex items-center justify-between px-4 py-3 hover:bg-white/[0.02] transition"
        onClick={() => setOpen(v => !v)}
      >
        <span className="text-sm font-semibold text-white/60 flex items-center gap-1.5">
          <span>📉</span> 技术指标
        </span>
        {!open && (
          <div className="flex items-center gap-2 text-[11px] font-mono">
            {maAlignment && (
              <span className={isBullMa ? 'text-emerald-400/80' : isBearMa ? 'text-red-400/70' : 'text-white/35'}>
                {maAlignment.length > 8 ? maAlignment.slice(0, 8) : maAlignment}
              </span>
            )}
            {valuationVerdict && (
              <span className="text-white/30 truncate max-w-[100px]">{valuationVerdict}</span>
            )}
            {capitalFlow && capitalFlow !== '资金面数据正常' && (
              <span className="text-amber-400/60 truncate max-w-[80px]">{capitalFlow}</span>
            )}
            <span className="text-white/20 ml-1">▼</span>
          </div>
        )}
        {open && <span className="text-xs text-white/25">▲ 收起</span>}
      </button>
      {open && (
        <div className="border-t border-white/[0.04] space-y-3 p-3">
          {quantExtras && <QuantAnalysis data={quantExtras} />}
        </div>
      )}
    </div>
  );
};

const HORIZON_LABELS: Record<string, string> = { short: '短线', mid: '中线', long: '长线' };

/** 持仓周期建议 —— 进度条可视化版 */
const HoldingHorizonCard: React.FC<{ horizon: HoldingHorizon }> = ({ horizon }) => {
  const items = (['short', 'mid', 'long'] as const).map(k => ({
    key: k,
    label: HORIZON_LABELS[k],
    item: horizon[k],
    isRec: horizon.recommended === k,
  }));

  const BAR_COLOR: Record<number, string> = {
    0: 'bg-white/10',
    1: 'bg-yellow-500/50',
    2: 'bg-yellow-400/75',
    3: 'bg-emerald-400',
    4: 'bg-emerald-400',
    5: 'bg-emerald-300',
  };

  return (
    <div className="rounded-xl bg-[var(--bg-card)] border border-white/[0.06] p-4">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold text-white/70">持仓周期建议</h3>
        {horizon.summary && <span className="text-[10px] text-white/25">{horizon.summary}</span>}
      </div>
      <div className="space-y-3">
        {items.map(({ key, label, item, isRec }) => {
          const pct = Math.round((item.score / 5) * 100);
          const barColor = BAR_COLOR[item.stars] ?? 'bg-white/20';
          return (
            <div key={key} className={`p-2.5 rounded-lg border ${
              isRec ? 'bg-emerald-500/8 border-emerald-500/20' : 'bg-white/[0.02] border-white/[0.04]'
            }`}>
              <div className="flex items-center gap-2 mb-2">
                <span className={`text-xs font-semibold w-8 ${isRec ? 'text-emerald-400' : 'text-white/50'}`}>{label}</span>
                <span className="text-[10px] text-white/25">{item.horizon}</span>
                {isRec && (
                  <span className="text-[9px] px-1.5 py-0.5 rounded bg-emerald-500/15 text-emerald-400 font-medium ml-auto">推荐</span>
                )}
              </div>
              <div className="flex items-center gap-2 mb-1.5">
                <div className="flex-1 h-1.5 rounded-full bg-white/[0.06] overflow-hidden">
                  <div
                    className={`h-full rounded-full transition-all duration-500 ${barColor}`}
                    style={{ width: `${pct}%` }}
                  />
                </div>
                <span className={`text-[11px] font-bold font-mono w-8 text-right ${isRec ? 'text-emerald-400' : 'text-white/40'}`}>
                  {item.score}/5
                </span>
              </div>
              {item.reasons?.length > 0 && (
                <div className="text-[10px] text-white/35 leading-relaxed">
                  {item.reasons.slice(0, 3).join(' · ')}
                </div>
              )}
              {item.warnings && item.warnings.length > 0 && (
                <div className="mt-1.5 space-y-0.5">
                  {item.warnings.map((w: string, i: number) => (
                    <div key={i} className="text-[10px] text-orange-400/70 flex items-start gap-1">
                      <span>⚠️</span><span>{w}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
};

/** 折叠区 —— 包裹 "更多分析" 内容 */
const CollapsibleSection: React.FC<{
  title: string;
  children: React.ReactNode;
  defaultOpen?: boolean;
}> = ({ title, children, defaultOpen = false }) => {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="rounded-xl bg-[var(--bg-card)] border border-white/[0.06] overflow-hidden">
      <button
        type="button"
        className="w-full flex items-center justify-between px-4 py-3 hover:bg-white/[0.02] transition"
        onClick={() => setOpen(v => !v)}
      >
        <span className="text-sm font-semibold text-white/50">{title}</span>
        <span className="text-xs text-white/25">{open ? '▲ 收起' : '▼ 展开'}</span>
      </button>
      {open && (
        <div className="border-t border-white/[0.04] p-3 space-y-3">
          {children}
        </div>
      )}
    </div>
  );
};

/**
 * 报告展示组件 — 持仓/未持仓双模式自动切换
 *
 * 未持仓：关注"该不该进" → ReportOverview > ConceptBadge > EntryConditionCard > AiDigestCard > ValuationBar > 折叠区
 * 持仓：关注"该走还是该留" → PnLHeader > HoldDecisionCard > HoldingHorizonCard > RiskAlertCard > ReportStrategy > 折叠区
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

  const { insiderChanges, upcomingUnlock, northboundHolding, conceptContext } = useMemo(() => {
    const ctx = details?.contextSnapshot as Record<string, any> | undefined;
    if (!ctx) return { insiderChanges: undefined, upcomingUnlock: undefined, northboundHolding: null, conceptContext: undefined };
    return {
      insiderChanges: ctx.insider_changes ?? ctx.insiderChanges,
      upcomingUnlock: ctx.upcoming_unlock ?? ctx.upcomingUnlock,
      northboundHolding: ctx.northbound_holding ?? ctx.northboundHolding ?? null,
      conceptContext: ctx.concept_context ?? ctx.conceptContext ?? undefined,
    };
  }, [details?.contextSnapshot]);

  const {
    quantExtras, intelligence, counterArguments, positionInfo,
    oneSentence, dashboardHoldingStrategy, defenseMode,
    scoreMomentumAdj, positionDiagnosis, actionNow,
    executionDifficulty, executionNote, behavioralWarning,
    skillUsed, resonanceLevel, capitalConflictWarning,
    profitTakePlan, analysisScene, skillAnalysis: _skillAnalysis,
  } = useMemo(() => {
    const raw = details?.rawResult as Record<string, any> | undefined;
    if (!raw) return {
      quantExtras: null, intelligence: null, counterArguments: null, positionInfo: null,
      oneSentence: null, dashboardHoldingStrategy: null, defenseMode: false,
      scoreMomentumAdj: 0, positionDiagnosis: null, actionNow: null,
      executionDifficulty: null, executionNote: null, behavioralWarning: null,
      skillUsed: null, resonanceLevel: null, capitalConflictWarning: null,
      profitTakePlan: null, analysisScene: null, skillAnalysis: null,
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
      profitTakePlan: dashboard?.profit_take_plan ?? null,
      analysisScene: dashboard?.analysis_scene ?? null,
      skillAnalysis: dashboard?.skill_analysis ?? null,
    };
  }, [details?.rawResult]);

  const hasPosition = (shares != null && shares > 0) || !!positionInfo;
  const costPrice = positionInfo?.cost_price ?? positionInfo?.costPrice;
  const holdingDays = positionInfo?.holding_days ?? positionInfo?.holdingDays ?? null;
  const positionAdvice =
    (details?.rawResult as Record<string, any>)?.dashboard?.core_conclusion?.position_advice ??
    (details?.rawResult as Record<string, any>)?.core_conclusion?.position_advice ??
    undefined;

  // ---------- 持仓模式 ----------
  if (hasPosition) {
    return (
      <div className="space-y-3 animate-fade-in">
        {/* 1. 浮盈亏 + 持有天数 + 成本价 */}
        <PnLHeader
          meta={meta}
          shares={shares}
          costPrice={costPrice}
          holdingDays={holdingDays}
        />

        {/* 2. 决策卡：继续持有/止盈/止损/加仓/减仓 */}
        <HoldDecisionCard
          summary={summary}
          strategy={strategy}
          holdingStrategy={dashboardHoldingStrategy}
          currentPrice={meta.currentPrice}
          costPrice={costPrice}
        />

        {/* 3. 持仓周期建议 */}
        {strategy?.holdingHorizon && strategy.holdingHorizon.recommended !== 'none' && (
          <HoldingHorizonCard horizon={strategy.holdingHorizon} />
        )}

        {/* 4. 风险预警 */}
        <RiskAlertCard
          upcomingUnlock={upcomingUnlock}
          insiderChanges={insiderChanges}
          conceptContext={conceptContext}
        />

        {/* 5. 作战计划（分阶段止盈） */}
        <ReportStrategy
          strategy={strategy}
          hasPositionInfo={true}
          costPrice={costPrice}
          currentPrice={meta.currentPrice}
          holdingStrategy={dashboardHoldingStrategy}
          defenseMode={defenseMode}
          maxDrawdown60d={quantExtras?.max_drawdown_60d ?? quantExtras?.maxDrawdown60d}
          positionDiagnosis={positionDiagnosis}
          suggestedPositionPct={quantExtras?.suggested_position_pct ?? quantExtras?.suggestedPositionPct ?? null}
          profitTakePlan={profitTakePlan}
          analysisScene={analysisScene ?? undefined}
          totalShares={positionInfo?.shares ?? positionInfo?.position_shares ?? undefined}
        />

        {/* 6. 折叠区：AI诊断、信号灯、量化、新闻 */}
        <CollapsibleSection title="📊 更多分析">
          <AiDiagnosis
            analysisSummary={summary.analysisSummary}
            intelligence={intelligence}
            counterArguments={counterArguments}
            positionAdvice={positionAdvice}
            defaultExpanded={false}
          />
          <SignalLights quantExtras={quantExtras} northboundHolding={northboundHolding} />
          <QuantPanel quantExtras={quantExtras} skillUsed={skillUsed ?? undefined} />
          <ReportNews stockCode={meta.stockCode} />
        </CollapsibleSection>

        {/* 7. 交易日志 */}
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
  }

  // ---------- 未持仓模式 ----------
  return (
    <div className="space-y-3 animate-fade-in">
      {/* 1. 股票概览（精简：名称+价格+涨跌+操作建议+评分） */}
      <ReportOverview
        meta={meta}
        summary={summary}
        hasPositionInfo={false}
        oneSentence={oneSentence ?? undefined}
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
        analysisScene={analysisScene ?? undefined}
      />

      {/* 2. 概念标签 */}
      <ConceptBadge conceptContext={conceptContext} />

      {/* 3. 建仓条件卡 */}
      <EntryConditionCard
        entryConditions={report.entryConditions}
        strategy={strategy}
        currentPrice={meta.currentPrice}
      />

      {/* 4. AI 精简诊断 */}
      <AiDigestCard analysisSummary={summary.analysisSummary} />

      {/* 5. 估值定位 */}
      <ValuationBar quantExtras={quantExtras} />

      {/* 6. 折叠区：信号灯、量化、新闻、交易日志 */}
      <CollapsibleSection title="📊 更多分析">
        <SignalLights quantExtras={quantExtras} northboundHolding={northboundHolding} />
        <QuantPanel quantExtras={quantExtras} skillUsed={skillUsed ?? undefined} />
        <ReportNews stockCode={meta.stockCode} />
        <TradeLog
          stockCode={meta.stockCode}
          stockName={meta.stockName}
          analysisScore={summary.sentimentScore}
          analysisAdvice={summary.operationAdvice}
          queryId={queryId}
          currentPrice={meta.currentPrice}
        />
      </CollapsibleSection>
    </div>
  );
};
