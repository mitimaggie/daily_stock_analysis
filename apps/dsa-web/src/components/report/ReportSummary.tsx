import React, { useMemo, useState } from 'react';
import type { AnalysisResult, AnalysisReport, HoldingHorizon } from '../../types/analysis';
import { ReportOverview } from './ReportOverview';
import { TradeLog } from '../trade/TradeLog';
import { ReportStrategy } from './ReportStrategy';
import { ReportNews } from './ReportNews';
import { QuantAnalysis } from './QuantAnalysis';
import { QuantVsAi } from './QuantVsAi';
import { KeyPriceLevels } from './KeyPriceLevels';
import { AiDiagnosis } from './AiDiagnosis';
import { ShareholderCard } from './ShareholderCard';
import { PriceRangeBar } from './PriceRangeBar';
import { TodaySnapshot } from './TodaySnapshot';
import { KeyInsights } from './KeyInsights';
import { DecisionCard } from './DecisionCard';
import { SignalLights } from './SignalLights';

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
          <span>�</span> 技术指标
        </span>
        {/* 收起时显示一行摘要 */}
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
          {quantVsAi && <QuantVsAi data={quantVsAi} skillUsed={skillUsed} />}
        </div>
      )}
    </div>
  );
};

/** 雷区警告横幅 —— 解禁/减持 强制首屏显示 */
const DangerBanners: React.FC<{
  upcomingUnlock: any;
  insiderChanges: any;
}> = ({ upcomingUnlock, insiderChanges }) => {
  const banners: Array<{ key: string; level: 'red' | 'orange'; icon: string; text: string }> = [];

  if (upcomingUnlock) {
    const u = typeof upcomingUnlock === 'string' ? upcomingUnlock : JSON.stringify(upcomingUnlock);
    const dateMatch = u.match(/\d{4}-\d{2}-\d{2}/);
    if (dateMatch) {
      const days = Math.round((new Date(dateMatch[0]).getTime() - Date.now()) / 86400000);
      if (days >= 0 && days <= 30) {
        banners.push({ key: 'unlock', level: 'red', icon: '⚠️', text: `解禁压力：${days}天后解禁（${dateMatch[0]}）` });
      } else if (days > 30 && days <= 90) {
        const sizeMatch = u.match(/(\d+\.?\d*)产南/) || u.match(/\d+\.?\d*亿/);
        banners.push({ key: 'unlock', level: 'orange', icon: '📅', text: `近31日解禁: ${dateMatch[0]}${sizeMatch ? '，规模' + sizeMatch[0] : ''}` });
      }
    }
  }

  if (insiderChanges) {
    const ic = typeof insiderChanges === 'string' ? insiderChanges : JSON.stringify(insiderChanges);
    if (/净减持|大幅减持|大量减持/.test(ic)) {
      const amtMatch = ic.match(/(\d+\.?\d*)万股/);
      banners.push({ key: 'insider', level: 'orange', icon: '📉', text: `高管在减持${amtMatch ? '（挪售' + amtMatch[0] + '）' : '，请注意内幕交易风险'}` });
    }
  }

  if (!banners.length) return null;

  return (
    <div className="space-y-1.5">
      {banners.map(b => (
        <div
          key={b.key}
          className={`flex items-center gap-2 px-3 py-2 rounded-xl text-[12px] font-medium ${
            b.level === 'red'
              ? 'bg-red-500/10 border border-red-500/25 text-red-300'
              : 'bg-orange-500/10 border border-orange-500/25 text-orange-300'
          }`}
        >
          <span>{b.icon}</span>
          <span>{b.text}</span>
        </div>
      ))}
    </div>
  );
};

const HORIZON_LABELS: Record<string, string> = { short: '短线', mid: '中线', long: '长线' };

/** 持仓时间维度建议卡片 */
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
              {/* 进度条 */}
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

  // P3/P4 data from contextSnapshot
  const { insiderChanges, upcomingUnlock, repurchase, priceRange52w, predictionAccuracy } = useMemo(() => {
    const ctx = details?.contextSnapshot as Record<string, any> | undefined;
    if (!ctx) return { insiderChanges: undefined, upcomingUnlock: undefined, repurchase: undefined, priceRange52w: undefined, predictionAccuracy: undefined };
    return {
      insiderChanges: ctx.insider_changes ?? ctx.insiderChanges,
      upcomingUnlock: ctx.upcoming_unlock ?? ctx.upcomingUnlock,
      repurchase: ctx.repurchase,
      priceRange52w: ctx.price_range_52w ?? ctx.priceRange52w,
      predictionAccuracy: ctx.prediction_accuracy ?? ctx.predictionAccuracy,
    };
  }, [details?.contextSnapshot]);

  const {
    quantExtras, intelligence, counterArguments, positionInfo,
    oneSentence, dashboardHoldingStrategy, defenseMode,
    scoreMomentumAdj, positionDiagnosis, actionNow,
    executionDifficulty, executionNote, behavioralWarning,
    skillUsed, resonanceLevel, capitalConflictWarning,
    profitTakePlan, analysisScene,
  } = useMemo(() => {
    const raw = details?.rawResult as Record<string, any> | undefined;
    if (!raw) return {
      quantExtras: null, intelligence: null, counterArguments: null, positionInfo: null,
      oneSentence: null, dashboardHoldingStrategy: null, defenseMode: false,
      scoreMomentumAdj: 0, positionDiagnosis: null, actionNow: null,
      executionDifficulty: null, executionNote: null, behavioralWarning: null,
      skillUsed: null, resonanceLevel: null, capitalConflictWarning: null,
      profitTakePlan: null, analysisScene: null,
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
    };
  }, [details?.rawResult]);

  const hasPosition = !!positionInfo;
  const positionAdvice =
    (details?.rawResult as Record<string, any>)?.dashboard?.core_conclusion?.position_advice ??
    (details?.rawResult as Record<string, any>)?.core_conclusion?.position_advice ??
    undefined;

  return (
    <div className="space-y-3 animate-fade-in">
      {/* 0. 雷区预警（解禁/减持，如有强制首屏）*/}
      <DangerBanners upcomingUnlock={upcomingUnlock} insiderChanges={insiderChanges} />

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

      {/* 1.5 三秒决策卡（操作/价格区间/止损/目标/盈交计算器）*/}
      <DecisionCard
        summary={summary}
        strategy={strategy}
        meta={meta}
        totalCapital={totalCapital}
      />

      {/* 1.7 三色信号灯（技术面/基本面/资金面）*/}
      <SignalLights quantExtras={quantExtras} />

      {/* 2. 持仓快照（有持仓时：紧凑一行，成本/浮盈/持有天数）*/}
      {positionInfo && (
        <PositionSnapshotBar
          positionInfo={positionInfo}
          currentPrice={meta.currentPrice}
        />
      )}

      {/* 1.5 历史准确率信任条（散户心理安全感）*/}
      {predictionAccuracy && (() => {
        const pa = predictionAccuracy as Record<string, any>;
        const wr = pa.bullish_win_rate ?? pa.bullishWinRate;
        const cnt = pa.bullish_count ?? pa.bullishCount ?? pa.total_records ?? pa.totalRecords;
        const avg = pa.avg_5d_return ?? pa.avg5dReturn;
        if (wr == null && avg == null) return null;
        const wrGood = wr != null && wr >= 60;
        const wrBad = wr != null && wr < 40;
        const wrColor = wrGood ? 'text-emerald-400' : wrBad ? 'text-red-400/70' : 'text-amber-400/80';
        return (
          <div className="flex items-center gap-3 px-4 py-2.5 rounded-xl bg-white/[0.03] border border-white/[0.05] text-[11px]">
            <span className="text-white/25 flex-shrink-0">📊 该股历史准确率</span>
            {wr != null && (
              <span className={`font-mono font-semibold ${wrColor}`}>
                看多胜率 {wr.toFixed(0)}%
                {cnt != null && <span className="text-white/25 font-normal ml-1">({cnt}次)</span>}
              </span>
            )}
            {avg != null && (
              <span className={`font-mono ${avg >= 0 ? 'text-emerald-400/70' : 'text-red-400/60'}`}>
                5日均益 {avg >= 0 ? '+' : ''}{avg.toFixed(1)}%
              </span>
            )}
            <span className="text-white/15 text-[10px] ml-auto">90日回填</span>
          </div>
        );
      })()}

      {/* 2.5 当日行情快照（成交量/中/振幅/换手率/量比）*/}
      {report.todaySnapshot && (
        <TodaySnapshot data={report.todaySnapshot} />
      )}

      {/* 3. AI 分析（主角：默认展开）*/}
      <AiDiagnosis
        analysisSummary={summary.analysisSummary}
        intelligence={intelligence}
        counterArguments={counterArguments}
        positionAdvice={positionAdvice}
        defaultExpanded={true}
      />

      {/* 3.25 重要信号（AI风险+正面摔化+量化指标）*/}
      <KeyInsights
        intelligence={intelligence ?? undefined}
        counterArguments={counterArguments ?? undefined}
        quantExtras={quantExtras ?? undefined}
      />

      {/* 3.5 52周价格区间（散户直观感知价格高低位）*/}
      <PriceRangeBar
        range={priceRange52w}
        currentPrice={meta.currentPrice}
      />

      {/* 3.6 股东动态（P3 增减持/解禁/回购）*/}
      <ShareholderCard
        insiderChanges={insiderChanges}
        upcomingUnlock={upcomingUnlock}
        repurchase={repurchase}
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
        profitTakePlan={profitTakePlan}
        analysisScene={analysisScene ?? undefined}
      />

      {/* 4.5 持仓周期建议（短线/中线/长线）*/}
      {strategy?.holdingHorizon && strategy.holdingHorizon.recommended !== 'none' && (
        <HoldingHorizonCard horizon={strategy.holdingHorizon} />
      )}

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
