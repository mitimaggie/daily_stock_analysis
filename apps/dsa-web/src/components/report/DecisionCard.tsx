import React, { useState } from 'react';
import { mapAdviceDisplay } from '../../types/analysis';
import type { ReportSummary, ReportStrategy, ReportMeta } from '../../types/analysis';

interface DecisionCardProps {
  summary: ReportSummary;
  strategy?: ReportStrategy;
  meta: ReportMeta;
  totalCapital?: number;
}

const ADVICE_STYLE: Record<string, { ring: string; label: string; labelBg: string }> = {
  '买入':  { ring: 'border-emerald-500/40', label: 'text-emerald-300', labelBg: 'bg-emerald-500/15' },
  '加仓':  { ring: 'border-emerald-500/40', label: 'text-emerald-300', labelBg: 'bg-emerald-500/15' },
  '建仓':  { ring: 'border-emerald-500/35', label: 'text-emerald-300', labelBg: 'bg-emerald-500/12' },
  '持有':  { ring: 'border-yellow-500/30',  label: 'text-yellow-300',  labelBg: 'bg-yellow-500/10'  },
  '持仓':  { ring: 'border-yellow-500/30',  label: 'text-yellow-300',  labelBg: 'bg-yellow-500/10'  },
  '观望':  { ring: 'border-black/[0.08]',     label: 'text-secondary',   labelBg: 'bg-black/[0.03]'   },
  '等待':  { ring: 'border-black/[0.08]',     label: 'text-secondary',   labelBg: 'bg-black/[0.03]'   },
  '减仓':  { ring: 'border-orange-500/35',   label: 'text-orange-300',  labelBg: 'bg-orange-500/12'  },
  '清仓':  { ring: 'border-red-500/40',      label: 'text-red-300',     labelBg: 'bg-red-500/15'     },
};

function confidenceLevel(score: number): { text: string; color: string } {
  if (score >= 75) return { text: '高置信度', color: 'text-emerald-600/70' };
  if (score >= 55) return { text: '中置信度', color: 'text-yellow-400/70' };
  return { text: '低置信度', color: 'text-red-600/60' };
}

export const DecisionCard: React.FC<DecisionCardProps> = ({ summary, strategy, meta, totalCapital }) => {
  const [showCalc, setShowCalc] = useState(false);
  const [calcAmount, setCalcAmount] = useState<string>(
    totalCapital ? String(Math.round(totalCapital * 0.1 / 1000) * 1000 || 50000) : '50000'
  );

  const rawAdvice = summary.operationAdvice || '观望';
  const advice = mapAdviceDisplay(rawAdvice);
  const s = ADVICE_STYLE[rawAdvice] ?? ADVICE_STYLE['观望'];
  const conf = confidenceLevel(summary.sentimentScore ?? 50);

  const stopLoss   = strategy?.stopLoss   ? parseFloat(strategy.stopLoss)   : null;
  const takeProfit = strategy?.takeProfit ? parseFloat(strategy.takeProfit) : null;
  const idealBuy   = strategy?.idealBuy   ? parseFloat(strategy.idealBuy)   : null;
  const rr         = strategy?.riskRewardRatio;
  const price      = meta.currentPrice || 0;

  const tradeAdvice    = summary.positionAdvice?.tradeAdvice;
  const winRate        = tradeAdvice?.winRate;
  const scenarioLabel  = tradeAdvice?.scenarioLabel;
  const expectedReturn = tradeAdvice?.expectedReturn20d;

  const stopLossPct    = stopLoss   && price > 0 ? ((stopLoss   - price) / price * 100) : null;
  const takeProfitPct  = takeProfit && price > 0 ? ((takeProfit - price) / price * 100) : null;

  const amount  = parseFloat(calcAmount) || 50000;
  const maxLoss = stopLoss   && price > 0 ? Math.round(amount * Math.abs(price - stopLoss)   / price) : null;
  const maxGain = takeProfit && price > 0 ? Math.round(amount * Math.abs(takeProfit - price) / price) : null;

  const hasPrices = !!(stopLoss || takeProfit || idealBuy);

  return (
    <div className={`rounded-xl bg-[var(--bg-card)] border ${s.ring} p-4`}>
      {/* ── Row 1: 操作建议 + 置信度 + 历史胜率 ── */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2.5">
          <span className={`text-[22px] font-black tracking-tight ${s.label}`}>{advice}</span>
          {scenarioLabel && (
            <span className="text-[11px] text-muted">{scenarioLabel}</span>
          )}
          <span className={`text-[10px] ${conf.color}`}>{conf.text}</span>
        </div>
        <div className="flex items-center gap-1.5">
          {winRate && (
            <span className="text-[10px] px-1.5 py-0.5 rounded bg-black/[0.04] text-muted font-mono">
              胜率 {winRate}
            </span>
          )}
          {expectedReturn && (
            <span className="text-[10px] px-1.5 py-0.5 rounded bg-black/[0.03] text-muted font-mono">
              预期 {expectedReturn}
            </span>
          )}
          {hasPrices && (
            <button
              type="button"
              onClick={() => setShowCalc(v => !v)}
              className="text-[10px] px-1.5 py-0.5 rounded border border-black/[0.08] text-muted hover:text-secondary transition-colors"
            >
              {showCalc ? '收起' : '💰 盈亏'}
            </button>
          )}
        </div>
      </div>

      {/* ── Row 2: 关键价格三格 ── */}
      {hasPrices && (
        <div className="grid grid-cols-3 gap-2 mb-3">
          <div className="text-center">
            <div className="text-[9px] text-muted mb-0.5 uppercase tracking-wider">买入参考</div>
            <div className="text-[16px] font-bold font-mono text-primary/80">
              {idealBuy ? idealBuy.toFixed(2) : '—'}
            </div>
          </div>
          <div className="text-center border-x border-black/[0.06]">
            <div className="text-[9px] text-muted mb-0.5 uppercase tracking-wider">止损</div>
            <div className="text-[16px] font-bold font-mono text-red-600">
              {stopLoss ? stopLoss.toFixed(2) : '—'}
            </div>
            {stopLossPct != null && (
              <div className="text-[9px] text-red-600/50">{stopLossPct.toFixed(1)}%</div>
            )}
          </div>
          <div className="text-center">
            <div className="text-[9px] text-muted mb-0.5 uppercase tracking-wider">目标</div>
            <div className="text-[16px] font-bold font-mono text-emerald-600">
              {takeProfit ? takeProfit.toFixed(2) : '—'}
            </div>
            {takeProfitPct != null && (
              <div className="text-[9px] text-emerald-600/50">+{takeProfitPct.toFixed(1)}%</div>
            )}
          </div>
        </div>
      )}

      {/* R/R ratio */}
      {rr && (
        <div className="text-[10px] text-muted mb-2">
          风险/回报比 = 1:{typeof rr === 'number' ? rr.toFixed(1) : rr}
        </div>
      )}

      {/* ── 盈亏计算器（可展开）── */}
      {showCalc && hasPrices && (
        <div className="mt-3 pt-3 border-t border-black/[0.07]">
          <div className="flex items-center gap-2 mb-2.5">
            <span className="text-[11px] text-muted">投入金额</span>
            <input
              type="number"
              value={calcAmount}
              onChange={e => setCalcAmount(e.target.value)}
              className="w-28 px-2 py-1 rounded bg-black/[0.04] border border-black/[0.08] text-primary/80 text-[12px] font-mono text-right outline-none focus:border-black/[0.15]"
              step="10000"
              min="0"
            />
            <span className="text-[10px] text-muted">元</span>
          </div>
          <div className="grid grid-cols-2 gap-2">
            {maxLoss != null && (
              <div className="px-3 py-2 rounded-lg bg-red-500/8 border border-red-500/15">
                <div className="text-[9px] text-red-600/50 mb-0.5">触止损最大亏损</div>
                <div className="text-[15px] font-bold text-red-600 font-mono">
                  ¥{maxLoss.toLocaleString()}
                </div>
              </div>
            )}
            {maxGain != null && (
              <div className="px-3 py-2 rounded-lg bg-emerald-500/8 border border-emerald-500/15">
                <div className="text-[9px] text-emerald-600/50 mb-0.5">触目标最大收益</div>
                <div className="text-[15px] font-bold text-emerald-600 font-mono">
                  ¥{maxGain.toLocaleString()}
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
};
