import type React from 'react';
import { Card } from '../common';

interface PositionDiagnosisProps {
  positionInfo: {
    total_capital?: number;
    position_amount?: number;
    cost_price?: number;
    totalCapital?: number;
    positionAmount?: number;
    costPrice?: number;
  };
  currentPrice?: number;
  suggestedPositionPct?: number;
  stopLoss?: string;
  takeProfit?: string;
}

/**
 * 持仓诊断组件
 * 基于用户输入的持仓信息，计算浮盈浮亏、仓位占比、个性化建议
 */
export const PositionDiagnosis: React.FC<PositionDiagnosisProps> = ({
  positionInfo,
  currentPrice,
  suggestedPositionPct,
  stopLoss,
  takeProfit,
}) => {
  const totalCapital = (positionInfo.total_capital ?? positionInfo.totalCapital ?? 0);
  const posAmount = (positionInfo.position_amount ?? positionInfo.positionAmount ?? 0);
  const costPrice = (positionInfo.cost_price ?? positionInfo.costPrice ?? 0);

  if (!totalCapital && !posAmount && !costPrice) return null;

  const price = currentPrice ?? 0;

  // 浮盈浮亏
  const hasPnl = costPrice > 0 && price > 0;
  const pnlPct = hasPnl ? ((price - costPrice) / costPrice) * 100 : 0;
  const pnlAmount = hasPnl && posAmount > 0 ? posAmount * pnlPct / 100 : 0;

  // 仓位占比
  const hasPosition = totalCapital > 0 && posAmount > 0;
  const actualPct = hasPosition ? (posAmount / totalCapital) * 100 : 0;

  // 止盈距离（基于成本价）
  const stopLossNum = stopLoss ? parseFloat(stopLoss) : 0;
  const takeProfitNum = takeProfit ? parseFloat(takeProfit) : 0;
  const stopLossFromCost = costPrice > 0 && stopLossNum > 0
    ? ((stopLossNum - costPrice) / costPrice * 100) : null;
  const takeProfitFromCost = costPrice > 0 && takeProfitNum > 0
    ? ((takeProfitNum - costPrice) / costPrice * 100) : null;

  return (
    <Card variant="bordered" padding="md">
      <div className="flex items-baseline gap-2 mb-3">
        <span className="label-uppercase">PORTFOLIO</span>
        <h3 className="text-base font-semibold text-white">持仓诊断</h3>
      </div>

      <div className="space-y-3">
        {/* 浮盈浮亏 */}
        {hasPnl && (
          <div className={`p-3 rounded-lg border ${pnlPct >= 0 ? 'bg-success/5 border-success/20' : 'bg-danger/5 border-danger/20'}`}>
            <div className="flex items-center justify-between">
              <div className="text-sm text-white">
                <span className="text-muted mr-2">成本</span>
                <span className="font-mono font-bold">{costPrice.toFixed(2)}</span>
                <span className="text-muted mx-2">→</span>
                <span className="text-muted mr-2">现价</span>
                <span className="font-mono font-bold">{price.toFixed(2)}</span>
              </div>
              <div className={`text-lg font-bold font-mono ${pnlPct >= 0 ? 'text-[#ff4d4d]' : 'text-[#00d46a]'}`}>
                {pnlPct >= 0 ? '+' : ''}{pnlPct.toFixed(2)}%
              </div>
            </div>
            {posAmount > 0 && (
              <div className={`text-xs mt-1 ${pnlPct >= 0 ? 'text-success/80' : 'text-danger/80'}`}>
                {pnlPct >= 0 ? '浮盈' : '浮亏'} {Math.abs(pnlAmount / 10000).toFixed(2)} 万元
              </div>
            )}
          </div>
        )}

        {/* 仓位占比 */}
        {hasPosition && (
          <div className="grid grid-cols-3 gap-2">
            <div className="bg-surface-2 rounded-lg p-2.5 text-center">
              <div className="text-[10px] text-muted mb-1">当前仓位</div>
              <div className="text-sm font-bold font-mono text-white">{actualPct.toFixed(1)}%</div>
            </div>
            <div className="bg-surface-2 rounded-lg p-2.5 text-center">
              <div className="text-[10px] text-muted mb-1">持仓金额</div>
              <div className="text-sm font-bold font-mono text-white">{(posAmount / 10000).toFixed(1)}万</div>
            </div>
            <div className="bg-surface-2 rounded-lg p-2.5 text-center">
              <div className="text-[10px] text-muted mb-1">建议仓位</div>
              <div className="text-sm font-bold font-mono text-cyan">
                {suggestedPositionPct != null ? `${suggestedPositionPct}%` : '--'}
              </div>
            </div>
          </div>
        )}

        {/* 仓位建议 */}
        {hasPosition && suggestedPositionPct != null && suggestedPositionPct > 0 && (
          <div className="text-[11px] text-muted">
            {actualPct > suggestedPositionPct * 1.5 && (
              <span className="text-warning">⚠️ 仓位偏重（建议≤{suggestedPositionPct}%），考虑适当减仓</span>
            )}
            {actualPct < suggestedPositionPct * 0.5 && (
              <span className="text-cyan">💡 仓位偏轻（建议{suggestedPositionPct}%），可考虑逢低加仓</span>
            )}
            {actualPct >= suggestedPositionPct * 0.5 && actualPct <= suggestedPositionPct * 1.5 && (
              <span className="text-success">✅ 仓位合理（建议{suggestedPositionPct}%）</span>
            )}
          </div>
        )}

        {/* 止盈止损距离（基于成本价） */}
        {costPrice > 0 && (stopLossFromCost !== null || takeProfitFromCost !== null) && (
          <div className="grid grid-cols-2 gap-2">
            {stopLossFromCost !== null && (
              <div className="bg-surface-2 rounded-lg p-2.5">
                <div className="text-[10px] text-muted mb-1">止损距成本</div>
                <div className="flex items-baseline gap-1">
                  <span className="text-sm font-bold font-mono text-danger">{stopLossNum.toFixed(2)}</span>
                  <span className={`text-[10px] font-mono ${stopLossFromCost >= 0 ? 'text-success' : 'text-danger'}`}>
                    ({stopLossFromCost >= 0 ? '+' : ''}{stopLossFromCost.toFixed(1)}%)
                  </span>
                </div>
              </div>
            )}
            {takeProfitFromCost !== null && (
              <div className="bg-surface-2 rounded-lg p-2.5">
                <div className="text-[10px] text-muted mb-1">止盈距成本</div>
                <div className="flex items-baseline gap-1">
                  <span className="text-sm font-bold font-mono text-success">{takeProfitNum.toFixed(2)}</span>
                  <span className={`text-[10px] font-mono ${takeProfitFromCost >= 0 ? 'text-success' : 'text-danger'}`}>
                    ({takeProfitFromCost >= 0 ? '+' : ''}{takeProfitFromCost.toFixed(1)}%)
                  </span>
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </Card>
  );
};
