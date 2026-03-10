import type React from 'react';
import type { EntryConditions, ReportStrategy } from '../../types/analysis';

interface EntryConditionCardProps {
  entryConditions?: EntryConditions | null;
  strategy?: ReportStrategy;
  currentPrice?: number;
}

function buildFallback(strategy: ReportStrategy, currentPrice?: number): EntryConditions | null {
  const idealBuy = strategy.idealBuy ? parseFloat(strategy.idealBuy) : null;
  const secondaryBuy = strategy.secondaryBuy ? parseFloat(strategy.secondaryBuy) : null;
  const hs = strategy.holdingStrategy;

  if (!idealBuy && !hs?.entryAdvice) return null;

  const low = secondaryBuy ?? (idealBuy ? idealBuy * 0.97 : undefined);
  const high = idealBuy ?? undefined;

  let currentVsEntry: string | undefined;
  if (idealBuy && currentPrice && currentPrice > 0) {
    const diff = ((currentPrice - idealBuy) / idealBuy) * 100;
    if (diff > 1) {
      currentVsEntry = `当前价高于入场区间 ${diff.toFixed(1)}%，耐心等回调`;
    } else if (diff < -1) {
      currentVsEntry = `当前价低于入场区间 ${Math.abs(diff).toFixed(1)}%，已进入买入区`;
    } else {
      currentVsEntry = '当前价在理想入场区间附近';
    }
  }

  return {
    priceRangeLow: low,
    priceRangeHigh: high,
    currentVsEntry,
    conditions: [],
    suggestedPositionPct: hs?.entryPositionPct,
    summary: hs?.entryAdvice,
  };
}

export const EntryConditionCard: React.FC<EntryConditionCardProps> = ({
  entryConditions,
  strategy,
  currentPrice,
}) => {
  const data = entryConditions ?? (strategy ? buildFallback(strategy, currentPrice) : null);
  if (!data) return null;

  const hasRange = data.priceRangeLow != null || data.priceRangeHigh != null;

  return (
    <div className="rounded-xl bg-card border border-emerald-500/15 p-4">
      <h3 className="text-sm font-semibold text-primary/80 mb-3 flex items-center gap-1.5">
        <span>🎯</span> 建仓条件
      </h3>

      {hasRange && (
        <div className="mb-3">
          <div className="text-[11px] text-muted mb-1">理想入场区间</div>
          <div className="text-[22px] font-bold font-mono text-emerald-600 tracking-tight">
            {data.priceRangeLow != null ? data.priceRangeLow.toFixed(2) : '—'}
            <span className="text-muted/70 mx-1.5 text-[16px]">–</span>
            {data.priceRangeHigh != null ? data.priceRangeHigh.toFixed(2) : '—'}
            <span className="text-[13px] text-muted ml-1.5">元</span>
          </div>
          {data.priceRangeDesc && (
            <div className="text-[11px] text-muted mt-1">{data.priceRangeDesc}</div>
          )}
          {data.currentVsEntry && (
            <div className="text-[12px] text-amber-400/80 mt-1.5">{data.currentVsEntry}</div>
          )}
        </div>
      )}

      {data.conditions.length > 0 && (
        <div className="space-y-1.5 mb-3">
          {data.conditions.map((c, i) => (
            <div key={i} className="flex items-center gap-2 text-[12px]">
              <span className={c.met ? 'text-emerald-600' : 'text-muted/70'}>
                {c.met ? '✅' : '⬜'}
              </span>
              <span className={c.met ? 'text-primary/70' : 'text-muted'}>{c.label}</span>
            </div>
          ))}
        </div>
      )}

      {data.suggestedPositionPct != null && (
        <div className="text-[12px] text-secondary">
          建议首次仓位：<span className="font-semibold text-primary/70">{data.suggestedPositionPct}%</span>
        </div>
      )}

      {data.summary && (
        <div className="mt-2 pt-2 border-t border-black/[0.04] text-[11px] text-secondary leading-relaxed">
          {data.summary}
        </div>
      )}
    </div>
  );
};
