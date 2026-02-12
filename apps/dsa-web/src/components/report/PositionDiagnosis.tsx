import type React from 'react';
import type { HoldingStrategy } from '../../types/analysis';
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
  holdingStrategy?: HoldingStrategy;
}

/**
 * 持仓诊断组件
 * 基于用户输入的持仓信息，区分空仓/持仓场景展示策略
 */
export const PositionDiagnosis: React.FC<PositionDiagnosisProps> = ({
  positionInfo,
  currentPrice,
  suggestedPositionPct,
  stopLoss,
  takeProfit,
  holdingStrategy,
}) => {
  const totalCapital = (positionInfo.total_capital ?? positionInfo.totalCapital ?? 0);
  const posAmount = (positionInfo.position_amount ?? positionInfo.positionAmount ?? 0);
  const costPrice = (positionInfo.cost_price ?? positionInfo.costPrice ?? 0);

  if (!totalCapital && !posAmount && !costPrice) return null;

  const price = currentPrice ?? 0;
  const hasPosition = totalCapital > 0 && posAmount > 0;

  // 持仓者使用 holdingStrategy 的止损/止盈，空仓用默认 strategy 的
  const hs = holdingStrategy;
  const effectiveStopLoss = hasPosition && hs?.holdingTrailingStop
    ? hs.holdingTrailingStop : stopLoss;
  const effectiveTakeProfit = hasPosition && hs?.holdingTarget
    ? hs.holdingTarget : takeProfit;
  const effectiveStopLabel = hasPosition && hs?.holdingTrailingStop
    ? '移动止盈线距成本' : '止损距成本';
  const effectiveProfitLabel = hasPosition && hs?.holdingTarget
    ? '中线目标距成本' : '止盈距成本';

  // 浮盈浮亏
  const hasPnl = costPrice > 0 && price > 0;
  const pnlPct = hasPnl ? ((price - costPrice) / costPrice) * 100 : 0;
  const pnlAmount = hasPnl && posAmount > 0 ? posAmount * pnlPct / 100 : 0;

  // 仓位占比
  const actualPct = hasPosition ? (posAmount / totalCapital) * 100 : 0;

  // 止盈止损距离（基于成本价）
  const stopLossNum = effectiveStopLoss ? parseFloat(effectiveStopLoss) : 0;
  const takeProfitNum = effectiveTakeProfit ? parseFloat(effectiveTakeProfit) : 0;
  const stopLossFromCost = costPrice > 0 && stopLossNum > 0
    ? ((stopLossNum - costPrice) / costPrice * 100) : null;
  const takeProfitFromCost = costPrice > 0 && takeProfitNum > 0
    ? ((takeProfitNum - costPrice) / costPrice * 100) : null;

  // 持仓建议文本
  const holdingAdviceText = hs?.holdingAdvice;

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
            {hs?.entryPositionPct != null && (
              <div className="bg-surface-2 rounded-lg p-2.5 text-center">
                <div className="text-[10px] text-muted mb-1">空仓建议仓位</div>
                <div className="text-sm font-bold font-mono text-white/50">
                  {hs.entryPositionPct}%
                </div>
              </div>
            )}
            {!hs?.entryPositionPct && suggestedPositionPct != null && (
              <div className="bg-surface-2 rounded-lg p-2.5 text-center">
                <div className="text-[10px] text-muted mb-1">空仓建议仓位</div>
                <div className="text-sm font-bold font-mono text-white/50">
                  {suggestedPositionPct}%
                </div>
              </div>
            )}
          </div>
        )}

        {/* 持仓建议（来自 AI 持仓者策略） */}
        {hasPosition && holdingAdviceText && (
          <div className="text-[11px] p-2.5 rounded-lg bg-cyan/5 border border-cyan/15 text-white/70 leading-relaxed">
            <span className="text-cyan font-medium mr-1">持仓策略:</span>
            {holdingAdviceText}
          </div>
        )}

        {/* 止盈止损距离（基于成本价，持仓者用移动止盈线） */}
        {costPrice > 0 && (stopLossFromCost !== null || takeProfitFromCost !== null) && (
          <div className="grid grid-cols-2 gap-2">
            {stopLossFromCost !== null && (
              <div className="bg-surface-2 rounded-lg p-2.5">
                <div className="text-[10px] text-muted mb-1">{effectiveStopLabel}</div>
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
                <div className="text-[10px] text-muted mb-1">{effectiveProfitLabel}</div>
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
