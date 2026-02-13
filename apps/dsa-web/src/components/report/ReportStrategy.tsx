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
    </div>
  );
};
