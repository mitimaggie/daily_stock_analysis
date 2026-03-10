import type React from 'react';
import type { ReportMeta } from '../../types/analysis';

interface PnLHeaderProps {
  meta: ReportMeta;
  shares?: number;
  costPrice?: number;
  holdingDays?: number | null;
  livePrice?: number;
  liveChangePct?: number;
}

export const PnLHeader: React.FC<PnLHeaderProps> = ({
  meta,
  shares,
  costPrice,
  holdingDays,
  livePrice,
  liveChangePct,
}) => {
  const price = livePrice ?? meta.currentPrice ?? 0;
  const changePct = liveChangePct ?? meta.changePct;
  const cost = costPrice ?? 0;

  const pnlPct = cost > 0 && price > 0 ? ((price - cost) / cost) * 100 : null;
  const pnlAmt = cost > 0 && price > 0 && shares && shares > 0
    ? (price - cost) * shares
    : null;

  const isProfit = pnlPct != null && pnlPct >= 0;
  const pnlColor = pnlPct == null
    ? 'text-muted'
    : isProfit
      ? 'text-[#ff4d4d]'
      : 'text-[#00d46a]';

  const priceColor = changePct == null
    ? 'text-primary/80'
    : changePct > 0
      ? 'text-[#ff4d4d]'
      : changePct < 0
        ? 'text-[#00d46a]'
        : 'text-primary/80';

  const formatPct = (v: number) => `${v >= 0 ? '+' : ''}${v.toFixed(2)}%`;
  const formatMoney = (v: number) => {
    const abs = Math.abs(v);
    const sign = v >= 0 ? '+' : '-';
    if (abs >= 10000) return `${sign}¥${(abs / 10000).toFixed(2)}万`;
    return `${sign}¥${abs.toFixed(0)}`;
  };

  return (
    <div className="rounded-xl bg-[var(--bg-card)] border border-black/[0.06] p-4">
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <span className="text-[14px] font-bold text-primary">{meta.stockName || meta.stockCode}</span>
          <span className="text-[11px] text-muted font-mono">{meta.stockCode}</span>
        </div>
        {price > 0 && (
          <div className={`text-[14px] font-bold font-mono ${priceColor}`}>
            {price.toFixed(2)}
            {changePct != null && (
              <span className="text-[11px] ml-1">{formatPct(changePct)}</span>
            )}
          </div>
        )}
      </div>

      <div className="flex items-end gap-3 flex-wrap">
        {pnlPct != null && (
          <div>
            <div className="text-[11px] text-muted mb-0.5">浮盈亏</div>
            <div className={`text-[24px] font-black font-mono leading-none ${pnlColor}`}>
              {pnlAmt != null ? formatMoney(pnlAmt) : ''}
              <span className="text-[16px] ml-1.5">{formatPct(pnlPct)}</span>
            </div>
          </div>
        )}
        <div className="flex items-center gap-3 text-[12px] text-secondary ml-auto">
          {holdingDays != null && (
            <span>持有 <span className="text-primary/70 font-mono">{holdingDays}</span> 天</span>
          )}
          {cost > 0 && (
            <span>成本 <span className="text-primary/70 font-mono">{cost.toFixed(2)}</span></span>
          )}
          {shares != null && shares > 0 && (
            <span className="text-muted font-mono">{shares}股</span>
          )}
        </div>
      </div>
    </div>
  );
};
