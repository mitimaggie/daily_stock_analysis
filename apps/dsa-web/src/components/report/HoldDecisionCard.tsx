import type React from 'react';
import { mapAdviceDisplay } from '../../types/analysis';
import type { ReportSummary, ReportStrategy, HoldingStrategy } from '../../types/analysis';

interface HoldDecisionCardProps {
  summary: ReportSummary;
  strategy?: ReportStrategy;
  holdingStrategy?: HoldingStrategy | Record<string, any> | null;
  currentPrice?: number;
  costPrice?: number;
}

export const HoldDecisionCard: React.FC<HoldDecisionCardProps> = ({
  summary,
  strategy,
  holdingStrategy,
  currentPrice,
  costPrice: _costPrice,
}) => {
  const rawAdvice = summary.operationAdvice || '持有';
  const advice = mapAdviceDisplay(rawAdvice);
  const isBuy = rawAdvice.includes('买入') || rawAdvice.includes('加仓') || rawAdvice.includes('吸纳');
  const isSell = rawAdvice.includes('卖出') || rawAdvice.includes('减仓') || rawAdvice.includes('清仓');
  const isHold = !isBuy && !isSell;

  const borderColor = isBuy
    ? 'border-emerald-500/25'
    : isSell
      ? 'border-red-500/25'
      : 'border-yellow-500/20';
  const adviceBg = isBuy
    ? 'bg-emerald-500/15 text-emerald-300'
    : isSell
      ? 'bg-red-500/15 text-red-300'
      : 'bg-yellow-500/12 text-yellow-300';

  const hs = holdingStrategy ?? strategy?.holdingStrategy;
  const hsAny = hs as Record<string, any> | null | undefined;
  const stopLoss = hsAny?.recommendedStop ?? hsAny?.recommended_stop
    ?? (strategy?.stopLoss ? parseFloat(strategy.stopLoss) : null);
  const target = hsAny?.recommendedTarget ?? hsAny?.recommended_target
    ?? (strategy?.takeProfit ? parseFloat(strategy.takeProfit) : null);

  const slPct = stopLoss && currentPrice && currentPrice > 0
    ? ((stopLoss - currentPrice) / currentPrice * 100)
    : null;
  const tpPct = target && currentPrice && currentPrice > 0
    ? ((target - currentPrice) / currentPrice * 100)
    : null;

  const risk = stopLoss && currentPrice ? Math.abs(currentPrice - stopLoss) : 0;
  const reward = target && currentPrice ? Math.abs(target - currentPrice) : 0;
  const rrRatio = risk > 0 && reward > 0 ? (reward / risk) : null;

  const holdAdvice = hsAny?.advice ?? hsAny?.holdAdvice ?? summary.positionAdvice?.hasPosition;

  return (
    <div className={`rounded-xl bg-card border ${borderColor} p-4`}>
      <div className="flex items-center gap-2 mb-3">
        <span className={`text-[13px] px-2.5 py-0.5 rounded font-bold ${adviceBg}`}>
          📋 {advice}
        </span>
        {rrRatio != null && (
          <span className={`text-[11px] font-mono ml-auto ${
            rrRatio >= 2 ? 'text-emerald-600/70' : rrRatio >= 1.5 ? 'text-yellow-400/70' : 'text-red-600/60'
          }`}>
            风险收益比 1:{rrRatio.toFixed(1)}
          </span>
        )}
      </div>

      {(stopLoss || target) && (
        <div className="grid grid-cols-2 gap-3 mb-3">
          {stopLoss && (
            <div className="rounded-lg bg-red-500/[0.06] border border-red-500/15 px-3 py-2">
              <div className="text-[10px] text-red-600/50 mb-0.5">止损价</div>
              <div className="text-[16px] font-bold font-mono text-red-600">
                ¥{stopLoss.toFixed(2)}
              </div>
              {slPct != null && (
                <div className="text-[10px] text-red-600/50">{slPct.toFixed(1)}%</div>
              )}
            </div>
          )}
          {target && (
            <div className="rounded-lg bg-emerald-500/[0.06] border border-emerald-500/15 px-3 py-2">
              <div className="text-[10px] text-emerald-600/50 mb-0.5">止盈价</div>
              <div className="text-[16px] font-bold font-mono text-emerald-600">
                ¥{target.toFixed(2)}
              </div>
              {tpPct != null && (
                <div className="text-[10px] text-emerald-600/50">+{tpPct.toFixed(1)}%</div>
              )}
            </div>
          )}
        </div>
      )}

      {holdAdvice && (
        <div className="pt-2 border-t border-black/[0.04] text-[12px] text-secondary leading-relaxed">
          {isHold ? '📌 ' : ''}{holdAdvice}
        </div>
      )}
    </div>
  );
};
