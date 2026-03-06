import type React from 'react';

interface InsiderChanges {
  has_data?: boolean;
  hasData?: boolean;
  buy_count?: number;
  buyCount?: number;
  sell_count?: number;
  sellCount?: number;
  net_direction?: string;
  netDirection?: string;
  buy_qty_wan?: number;
  buyQtyWan?: number;
  sell_qty_wan?: number;
  sellQtyWan?: number;
  latest_date?: string;
  latestDate?: string;
  summary?: string;
}

interface UpcomingUnlock {
  has_data?: boolean;
  hasData?: boolean;
  next_unlock_date?: string;
  nextUnlockDate?: string;
  next_unlock_qty_yi?: number;
  nextUnlockQtyYi?: number;
  next_unlock_mv_yi?: number;
  nextUnlockMvYi?: number;
  next_unlock_float_pct?: number;
  nextUnlockFloatPct?: number;
  unlock_type?: string;
  unlockType?: string;
  summary?: string;
}

interface Repurchase {
  has_data?: boolean;
  hasData?: boolean;
  amount_upper?: number;
  amountUpper?: number;
  progress_pct?: number;
  progressPct?: number;
  price_upper?: number;
  priceUpper?: number;
  summary?: string;
}

interface ShareholderCardProps {
  insiderChanges?: InsiderChanges;
  upcomingUnlock?: UpcomingUnlock;
  repurchase?: Repurchase;
}

/** 高管增减持方向 badge */
const InsiderBadge: React.FC<{ direction?: string }> = ({ direction }) => {
  if (!direction) return null;
  const isNet = direction.includes('净增持');
  const isSell = direction.includes('净减持');
  const cls = isNet
    ? 'bg-emerald-500/15 text-emerald-400 border-emerald-500/25'
    : isSell
      ? 'bg-red-500/15 text-red-400 border-red-500/25'
      : 'bg-white/[0.06] text-white/40 border-white/10';
  const icon = isNet ? '↑' : isSell ? '↓' : '—';
  return (
    <span className={`inline-flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded border font-mono font-semibold ${cls}`}>
      {icon} {direction}
    </span>
  );
};

/** 解禁风险 badge（按占流通盘比例着色） */
const UnlockRiskBadge: React.FC<{ floatPct?: number }> = ({ floatPct }) => {
  if (floatPct == null) return null;
  const isHigh = floatPct >= 5;
  const isMid = floatPct >= 1;
  const cls = isHigh
    ? 'bg-red-500/15 text-red-400 border-red-500/25'
    : isMid
      ? 'bg-amber-500/15 text-amber-400 border-amber-500/25'
      : 'bg-white/[0.06] text-white/35 border-white/10';
  const label = isHigh ? '高风险' : isMid ? '中风险' : '低风险';
  return (
    <span className={`text-[10px] px-1.5 py-0.5 rounded border font-mono ${cls}`}>{label} {floatPct.toFixed(1)}%</span>
  );
};

/**
 * 股东动态卡片 - 展示 P3 股东资金博弈数据
 * 数据来源：context_snapshot.insider_changes / upcoming_unlock / repurchase
 */
export const ShareholderCard: React.FC<ShareholderCardProps> = ({
  insiderChanges,
  upcomingUnlock,
  repurchase,
}) => {
  const insiderHas = insiderChanges?.has_data ?? insiderChanges?.hasData;
  const unlockHas = upcomingUnlock?.has_data ?? upcomingUnlock?.hasData;
  const repurchaseHas = repurchase?.has_data ?? repurchase?.hasData;

  if (!insiderHas && !unlockHas && !repurchaseHas) return null;

  const netDir = insiderChanges?.net_direction ?? insiderChanges?.netDirection;
  const buyCount = insiderChanges?.buy_count ?? insiderChanges?.buyCount ?? 0;
  const sellCount = insiderChanges?.sell_count ?? insiderChanges?.sellCount ?? 0;
  const buyQty = insiderChanges?.buy_qty_wan ?? insiderChanges?.buyQtyWan;
  const sellQty = insiderChanges?.sell_qty_wan ?? insiderChanges?.sellQtyWan;
  const latestDate = insiderChanges?.latest_date ?? insiderChanges?.latestDate;

  const unlockDate = upcomingUnlock?.next_unlock_date ?? upcomingUnlock?.nextUnlockDate;
  const unlockMv = upcomingUnlock?.next_unlock_mv_yi ?? upcomingUnlock?.nextUnlockMvYi;
  const unlockFloatPct = upcomingUnlock?.next_unlock_float_pct ?? upcomingUnlock?.nextUnlockFloatPct;
  const unlockType = upcomingUnlock?.unlock_type ?? upcomingUnlock?.unlockType;

  const repurchaseAmt = repurchase?.amount_upper ?? repurchase?.amountUpper;
  const repurchaseProgress = repurchase?.progress_pct ?? repurchase?.progressPct;

  return (
    <div className="rounded-xl bg-[var(--bg-card)] border border-white/[0.06] p-4">
      <h3 className="text-sm font-semibold text-white/60 flex items-center gap-1.5 mb-3">
        <span>👥</span> 股东动态
      </h3>

      <div className="space-y-3">
        {/* 高管增减持 */}
        {insiderHas && (
          <div className="flex items-start gap-3">
            <span className="text-[10px] text-white/25 w-16 flex-shrink-0 pt-0.5">增减持</span>
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 flex-wrap mb-1">
                <InsiderBadge direction={netDir} />
                <span className="text-[11px] text-white/35 font-mono">
                  增{buyCount}次{buyQty != null ? ` ${buyQty}万股` : ''} / 减{sellCount}次{sellQty != null ? ` ${sellQty}万股` : ''}
                </span>
                {latestDate && (
                  <span className="text-[10px] text-white/20 font-mono ml-auto">{latestDate}</span>
                )}
              </div>
            </div>
          </div>
        )}

        {/* 限售解禁 */}
        {unlockHas && unlockDate && (
          <div className="flex items-start gap-3">
            <span className="text-[10px] text-white/25 w-16 flex-shrink-0 pt-0.5">限售解禁</span>
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 flex-wrap">
                <span className="text-[12px] text-white/70 font-mono font-medium">{unlockDate}</span>
                {unlockMv != null && (
                  <span className="text-[11px] text-white/40 font-mono">{unlockMv.toFixed(2)}亿元</span>
                )}
                <UnlockRiskBadge floatPct={unlockFloatPct} />
                {unlockType && (
                  <span className="text-[10px] text-white/25 truncate max-w-[140px]">{unlockType}</span>
                )}
              </div>
            </div>
          </div>
        )}

        {/* 股票回购 */}
        {repurchaseHas && repurchaseAmt != null && (
          <div className="flex items-start gap-3">
            <span className="text-[10px] text-white/25 w-16 flex-shrink-0 pt-0.5">股票回购</span>
            <div className="flex-1 min-w-0 flex items-center gap-2 flex-wrap">
              <span className="inline-flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded border font-mono bg-emerald-500/10 text-emerald-400/80 border-emerald-500/20">
                ↻ 回购中
              </span>
              <span className="text-[11px] text-white/40 font-mono">上限{repurchaseAmt.toFixed(2)}亿</span>
              {repurchaseProgress != null && (
                <div className="flex items-center gap-1.5">
                  <div className="w-20 h-1.5 rounded-full bg-white/[0.06] overflow-hidden">
                    <div
                      className="h-full rounded-full bg-emerald-500/50"
                      style={{ width: `${Math.min(100, repurchaseProgress)}%` }}
                    />
                  </div>
                  <span className="text-[10px] text-white/30 font-mono">{repurchaseProgress.toFixed(0)}%</span>
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
