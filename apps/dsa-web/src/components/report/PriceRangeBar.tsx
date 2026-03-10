import type React from 'react';

interface PriceRange52W {
  high?: number;
  low?: number;
  n_days?: number;
  nDays?: number;
}

interface PriceRangeBarProps {
  range?: PriceRange52W;
  currentPrice?: number;
}

/**
 * 52周价格区间可视化条
 * 显示低点→高点横向滑轨，当前价格位置标记，以及距高低点的百分比
 */
export const PriceRangeBar: React.FC<PriceRangeBarProps> = ({ range, currentPrice }) => {
  const high = range?.high;
  const low = range?.low;
  const nDays = range?.n_days ?? range?.nDays ?? 0;

  if (!high || !low || !currentPrice || high <= low) return null;

  const rangeSpan = high - low;
  // clamp position 0–100%
  const rawPct = (currentPrice - low) / rangeSpan * 100;
  const positionPct = Math.max(0, Math.min(100, rawPct));

  const distFromHigh = ((currentPrice - high) / high * 100);  // negative = below high
  const distFromLow  = ((currentPrice - low)  / low  * 100);  // positive = above low

  const label = nDays >= 200 ? '52周' : `${nDays}日`;

  // Color the marker by position
  const markerColor =
    positionPct >= 85
      ? '#f87171'   // near high: red
      : positionPct <= 15
        ? '#34d399'  // near low: green
        : '#00d4ff'; // middle: cyan

  // Zone label
  const zoneLabel =
    rawPct >= 100
      ? '突破新高'
      : rawPct <= 0
        ? '跌破新低'
        : positionPct >= 85
          ? '高位区'
          : positionPct >= 60
            ? '中高位'
            : positionPct >= 40
              ? '中位'
              : positionPct >= 15
                ? '中低位'
                : '低位区';

  const zoneCls =
    rawPct >= 100
      ? 'text-red-600'
      : rawPct <= 0
        ? 'text-emerald-600'
        : positionPct >= 85
          ? 'text-red-600'
          : positionPct <= 15
            ? 'text-emerald-600'
            : 'text-cyan-400/80';

  return (
    <div className="rounded-xl bg-card border border-black/[0.04] p-4">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold text-secondary flex items-center gap-1.5">
          <span>📐</span> {label}价格区间
        </h3>
        <span className={`text-[11px] font-mono font-semibold ${zoneCls}`}>{zoneLabel}</span>
      </div>

      {/* Range bar */}
      <div className="relative h-5 flex items-center mb-2">
        {/* Track */}
        <div className="absolute inset-x-0 h-1.5 rounded-full bg-black/[0.04]" />
        {/* Filled portion from low to current */}
        <div
          className="absolute left-0 h-1.5 rounded-full"
          style={{
            width: `${positionPct}%`,
            background: `linear-gradient(to right, rgba(0,212,255,0.25), ${markerColor}80)`,
          }}
        />
        {/* Marker dot */}
        <div
          className="absolute w-3 h-3 rounded-full border-2 border-[var(--bg-card)] -translate-x-1/2 shadow-lg"
          style={{
            left: `${positionPct}%`,
            background: markerColor,
            boxShadow: `0 0 6px ${markerColor}80`,
          }}
        />
      </div>

      {/* Labels row */}
      <div className="flex items-center justify-between text-[10px] font-mono mt-1">
        <div className="text-left">
          <div className="text-muted">低 {low.toFixed(2)}</div>
          {distFromLow > 0 && distFromLow < 200 && (
            <div className="text-emerald-600/60">+{distFromLow.toFixed(1)}%</div>
          )}
        </div>
        <div className="text-center">
          <div className="text-secondary font-semibold text-[11px]">{currentPrice.toFixed(2)}</div>
          <div className="text-muted">{positionPct.toFixed(0)}%位</div>
        </div>
        <div className="text-right">
          <div className="text-muted">高 {high.toFixed(2)}</div>
          {distFromHigh < 0 && (
            <div className="text-red-600/60">{distFromHigh.toFixed(1)}%</div>
          )}
          {distFromHigh >= 0 && (
            <div className="text-red-600/80">+{distFromHigh.toFixed(1)}% ↑新高</div>
          )}
        </div>
      </div>
    </div>
  );
};
