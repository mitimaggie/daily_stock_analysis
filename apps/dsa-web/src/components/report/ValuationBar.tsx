import type React from 'react';

interface ValuationBarProps {
  quantExtras?: Record<string, any> | null;
}

export const ValuationBar: React.FC<ValuationBarProps> = ({ quantExtras }) => {
  if (!quantExtras) return null;

  const peRatio = quantExtras.pe_ratio ?? quantExtras.peRatio;
  const pbRatio = quantExtras.pb_ratio ?? quantExtras.pbRatio;
  const pePercentile = quantExtras.pe_percentile ?? quantExtras.pePercentile;
  const verdict = quantExtras.valuation_verdict ?? quantExtras.valuationVerdict;

  if (pePercentile == null && !verdict) return null;

  const pctValue = pePercentile != null ? Math.min(100, Math.max(0, pePercentile)) : null;
  const barColor = pctValue == null
    ? 'bg-white/20'
    : pctValue <= 30
      ? 'bg-emerald-400'
      : pctValue <= 70
        ? 'bg-yellow-400'
        : 'bg-red-400';
  const textColor = pctValue == null
    ? 'text-white/40'
    : pctValue <= 30
      ? 'text-emerald-400'
      : pctValue <= 70
        ? 'text-yellow-400'
        : 'text-red-400';

  return (
    <div className="rounded-xl bg-[var(--bg-card)] border border-white/[0.06] p-4">
      <div className="flex items-center justify-between mb-2">
        <h3 className="text-sm font-semibold text-white/70 flex items-center gap-1.5">
          <span>📊</span> 估值定位
        </h3>
        {verdict && (
          <span className={`text-[11px] font-medium ${textColor}`}>{verdict}</span>
        )}
      </div>

      {pctValue != null && (
        <div className="mb-2">
          <div className="flex items-center justify-between mb-1">
            <span className="text-[10px] text-white/30">低估</span>
            <span className="text-[10px] text-white/30">高估</span>
          </div>
          <div className="h-2 rounded-full bg-white/[0.06] overflow-hidden relative">
            <div
              className={`h-full rounded-full transition-all duration-500 ${barColor}`}
              style={{ width: `${pctValue}%` }}
            />
            <div
              className="absolute top-1/2 -translate-y-1/2 w-2.5 h-2.5 rounded-full bg-white border-2 border-[var(--bg-card)]"
              style={{ left: `calc(${pctValue}% - 5px)` }}
            />
          </div>
          <div className="text-center mt-1.5">
            <span className={`text-[12px] font-mono font-bold ${textColor}`}>
              PE分位 {pctValue.toFixed(0)}%
            </span>
          </div>
        </div>
      )}

      <div className="flex items-center gap-4 text-[11px] text-white/40">
        {peRatio != null && (
          <span>PE <span className="font-mono text-white/60">{Number(peRatio).toFixed(1)}</span></span>
        )}
        {pbRatio != null && (
          <span>PB <span className="font-mono text-white/60">{Number(pbRatio).toFixed(1)}</span></span>
        )}
      </div>
    </div>
  );
};
