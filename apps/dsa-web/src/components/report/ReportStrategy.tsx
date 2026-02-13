import type React from 'react';
import type { ReportStrategy as ReportStrategyType } from '../../types/analysis';

interface ReportStrategyProps {
  strategy?: ReportStrategyType;
  hasPositionInfo?: boolean;
  costPrice?: number;
  currentPrice?: number;
  holdingStrategy?: Record<string, any> | null;
}

const fmtPrice = (v?: string | number | null): string => {
  if (v == null) return '—';
  const n = typeof v === 'string' ? parseFloat(v) : v;
  return isNaN(n) ? '—' : n.toFixed(2);
};

/**
 * 作战计划表 — PushPlus 风格 5 列表格
 */
export const ReportStrategy: React.FC<ReportStrategyProps> = ({
  strategy,
  hasPositionInfo = false,
  costPrice,
  currentPrice,
  holdingStrategy,
}) => {
  if (!strategy) return null;

  // R:R 计算：持仓时基于当前价→目标/止损，空仓时用后端原值
  const calcRR = (): { rr: number | null; label: string } => {
    if (hasPositionInfo && currentPrice && currentPrice > 0) {
      const sl = holdingStrategy?.recommended_stop
        ? Number(holdingStrategy.recommended_stop)
        : strategy.stopLoss ? parseFloat(String(strategy.stopLoss)) : 0;
      const tp = strategy.takeProfit ? parseFloat(String(strategy.takeProfit)) : 0;
      const risk = currentPrice - sl;
      const reward = tp - currentPrice;
      if (risk > 0 && reward > 0) {
        return { rr: reward / risk, label: '持仓R:R' };
      }
    }
    return { rr: strategy.riskRewardRatio ?? null, label: 'R:R' };
  };
  const { rr, label: rrLabel } = calcRR();
  const rrText = rr != null && rr > 0 ? `${rr.toFixed(1)}:1` : '—';
  const rrColor = rr == null ? '' : rr >= 2 ? 'text-green-400' : rr >= 1.5 ? 'text-yellow-400' : 'text-red-400';

  // 持仓时：使用 holdingStrategy 中推荐止损替代通用止损
  const displayStopLoss = hasPositionInfo && holdingStrategy?.recommended_stop
    ? String(holdingStrategy.recommended_stop)
    : strategy.stopLoss;

  // 浮盈亏计算
  const pnlPct = hasPositionInfo && costPrice && costPrice > 0 && currentPrice && currentPrice > 0
    ? ((currentPrice - costPrice) / costPrice * 100)
    : null;

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
              <th className="text-center py-1.5 font-medium">{hasPositionInfo ? '加仓点' : '买点'}</th>
              <th className="text-center py-1.5 font-medium">止损</th>
              <th className="text-center py-1.5 font-medium">短线目标</th>
              <th className="text-center py-1.5 font-medium">中线目标</th>
              <th className="text-center py-1.5 font-medium">{rrLabel}</th>
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
                  {fmtPrice(displayStopLoss)}
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

      {/* 持仓成本标注 */}
      {hasPositionInfo && costPrice && costPrice > 0 && (
        <div className="mt-2 pt-2 border-t border-white/[0.06] flex items-center gap-3 text-[11px] text-white/40">
          <span>💰 成本 <span className="font-mono text-white/60">{costPrice.toFixed(2)}</span></span>
          {pnlPct != null && (
            <span className={pnlPct >= 0 ? 'text-[#ff4d4d]' : 'text-[#00d46a]'}>
              {pnlPct >= 0 ? '+' : ''}{pnlPct.toFixed(2)}%
            </span>
          )}
          {holdingStrategy?.recommended_stop_reason && (
            <span className="text-white/30">止损依据: {holdingStrategy.recommended_stop_reason}</span>
          )}
        </div>
      )}

      {/* 分批止盈计划 / 持仓策略建议 */}
      {(hasPositionInfo && holdingStrategy?.advice) ? (
        <div className="mt-2 pt-2 border-t border-white/[0.06] text-[11px] text-white/50">
          📋 {holdingStrategy.advice}
        </div>
      ) : strategy.takeProfitPlan ? (
        <div className="mt-2 pt-2 border-t border-white/[0.06] text-[11px] text-white/50">
          📋 {strategy.takeProfitPlan}
        </div>
      ) : null}

    </div>
  );
};
