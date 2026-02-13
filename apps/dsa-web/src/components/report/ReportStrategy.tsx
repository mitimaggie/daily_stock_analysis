import type React from 'react';
import type { ReportStrategy as ReportStrategyType } from '../../types/analysis';

interface ReportStrategyProps {
  strategy?: ReportStrategyType;
}

const fmtPrice = (v?: string | number | null): string => {
  if (v == null) return '—';
  const n = typeof v === 'string' ? parseFloat(v) : v;
  return isNaN(n) ? '—' : n.toFixed(2);
};

/**
 * 作战计划表 — PushPlus 风格 5 列表格
 */
export const ReportStrategy: React.FC<ReportStrategyProps> = ({ strategy }) => {
  if (!strategy) return null;

  const hs = strategy.holdingStrategy;
  const hasAnyAnchor = hs != null && (
    (hs.stopLossShort != null && hs.stopLossShort > 0) ||
    (hs.stopLossMid != null && hs.stopLossMid > 0) ||
    (hs.trailingStop != null && hs.trailingStop > 0) ||
    (hs.targetShort != null && hs.targetShort > 0) ||
    (hs.targetMid != null && hs.targetMid > 0)
  );
  // 当所有锚点为 0 时，advice 中的 "0.00" 无意义，不显示
  const hasValidAdvice = hs != null && !!hs.advice && !hs.advice.includes('0.00');
  const hasHoldingData = hasAnyAnchor || hasValidAdvice;

  const rr = strategy.riskRewardRatio;
  const rrText = rr != null && rr > 0 ? `${rr.toFixed(1)}:1` : '—';
  const rrColor = rr == null ? '' : rr >= 2 ? 'text-green-400' : rr >= 1.5 ? 'text-yellow-400' : 'text-red-400';

  return (
    <div className="rounded-xl bg-[var(--bg-card)] border border-white/[0.06] p-4">
      <h3 className="text-sm font-semibold text-white/90 flex items-center gap-1.5 mb-3">
        <span>🎯</span> 作战计划
      </h3>

      {/* 5 列表格 */}
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="text-white/40 border-b border-white/[0.06]">
              <th className="text-center py-1.5 font-medium">买点</th>
              <th className="text-center py-1.5 font-medium">止损</th>
              <th className="text-center py-1.5 font-medium">短线目标</th>
              <th className="text-center py-1.5 font-medium">中线目标</th>
              <th className="text-center py-1.5 font-medium">R:R</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td className="text-center py-2">
                <span className="font-mono font-bold text-sm text-green-400">
                  {fmtPrice(strategy.idealBuy)}
                </span>
              </td>
              <td className="text-center py-2">
                <span className="font-mono font-bold text-sm text-red-400">
                  {fmtPrice(strategy.stopLoss)}
                </span>
              </td>
              <td className="text-center py-2">
                <span className="font-mono font-bold text-sm text-yellow-400">
                  {fmtPrice(strategy.takeProfit)}
                </span>
              </td>
              <td className="text-center py-2">
                <span className="font-mono font-bold text-sm text-orange-300">
                  {fmtPrice(strategy.takeProfitMid)}
                </span>
              </td>
              <td className="text-center py-2">
                <span className={`font-mono font-bold text-sm ${rrColor}`}>
                  {rrText}
                </span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      {/* 分批止盈计划 */}
      {strategy.takeProfitPlan && (
        <div className="mt-2 pt-2 border-t border-white/[0.06] text-[11px] text-white/50">
          📋 {strategy.takeProfitPlan}
        </div>
      )}

      {/* 持仓者策略 */}
      {hs && hasHoldingData && (
        <div className="mt-3 pt-3 border-t border-white/[0.06]">
          <div className="text-[11px] text-white/50 mb-2 flex items-center gap-1">
            <span>🛡</span> 持仓者专属策略
          </div>

          {/* 止损/止盈三档 */}
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 mb-2">
            {hs.stopLossShort != null && hs.stopLossShort > 0 && (
              <div className="bg-surface-2 rounded-lg p-2 text-center">
                <div className="text-[9px] text-red-400/70 mb-0.5">短线止损</div>
                <div className="text-xs font-mono font-bold text-red-400">{hs.stopLossShort.toFixed(2)}</div>
              </div>
            )}
            {hs.stopLossMid != null && hs.stopLossMid > 0 && (
              <div className="bg-surface-2 rounded-lg p-2 text-center">
                <div className="text-[9px] text-orange-400/70 mb-0.5">中线止损</div>
                <div className="text-xs font-mono font-bold text-orange-400">{hs.stopLossMid.toFixed(2)}</div>
              </div>
            )}
            {hs.trailingStop != null && hs.trailingStop > 0 && (
              <div className="bg-surface-2 rounded-lg p-2 text-center">
                <div className="text-[9px] text-cyan-400/70 mb-0.5">移动止盈线</div>
                <div className="text-xs font-mono font-bold text-cyan-400">{hs.trailingStop.toFixed(2)}</div>
              </div>
            )}
            {hs.targetShort != null && hs.targetShort > 0 && (
              <div className="bg-surface-2 rounded-lg p-2 text-center">
                <div className="text-[9px] text-green-400/70 mb-0.5">短线目标</div>
                <div className="text-xs font-mono font-bold text-green-400">{hs.targetShort.toFixed(2)}</div>
              </div>
            )}
            {hs.targetMid != null && hs.targetMid > 0 && (
              <div className="bg-surface-2 rounded-lg p-2 text-center">
                <div className="text-[9px] text-yellow-400/70 mb-0.5">中线目标</div>
                <div className="text-xs font-mono font-bold text-yellow-400">{hs.targetMid.toFixed(2)}</div>
              </div>
            )}
          </div>

          {/* 持仓建议 */}
          {hasValidAdvice && hs.advice && (
            <div className="text-[11px] p-2 rounded-lg bg-cyan-500/5 border border-cyan-500/15 text-white/60 leading-relaxed">
              <span className="text-cyan-400 font-medium mr-1">建议:</span>{hs.advice}
            </div>
          )}
        </div>
      )}
    </div>
  );
};
