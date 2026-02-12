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

const STOP_TYPE_LABELS: Record<string, string> = {
  trailing: '移动止盈线',
  mid: '中线止损',
  short: '短线止损',
};

/**
 * 持仓诊断组件
 * 基于用户输入的持仓信息 + 统一 holdingStrategy 展示策略
 */
export const PositionDiagnosis: React.FC<PositionDiagnosisProps> = ({
  positionInfo,
  currentPrice,
  suggestedPositionPct,
  stopLoss,
  takeProfit,
  holdingStrategy: hs,
}) => {
  const totalCapital = (positionInfo.total_capital ?? positionInfo.totalCapital ?? 0);
  const posAmount = (positionInfo.position_amount ?? positionInfo.positionAmount ?? 0);
  const costPrice = (positionInfo.cost_price ?? positionInfo.costPrice ?? 0);

  if (!totalCapital && !posAmount && !costPrice) return null;

  const price = currentPrice ?? 0;
  const hasPosition = totalCapital > 0 && posAmount > 0;

  // 推荐止损/止盈（持仓者用 holdingStrategy 推荐值，空仓用 strategy 的）
  const recStop = hasPosition && hs?.recommendedStop ? hs.recommendedStop : (stopLoss ? parseFloat(stopLoss) : 0);
  const recTarget = hasPosition && hs?.recommendedTarget ? hs.recommendedTarget : (takeProfit ? parseFloat(takeProfit) : 0);
  const recStopType = hasPosition ? (hs?.recommendedStopType || '') : '';
  const recStopLabel = hasPosition && recStopType
    ? `推荐止损 (${STOP_TYPE_LABELS[recStopType] || recStopType})`
    : '止损距成本';
  const recTargetLabel = hasPosition
    ? `推荐止盈 (${hs?.recommendedTargetType === 'mid' ? '中线目标' : '短线目标'})`
    : '止盈距成本';

  // 浮盈浮亏
  const hasPnl = costPrice > 0 && price > 0;
  const pnlPct = hasPnl ? ((price - costPrice) / costPrice) * 100 : 0;
  const pnlAmount = hasPnl && posAmount > 0 ? posAmount * pnlPct / 100 : 0;

  // 仓位占比
  const actualPct = hasPosition ? (posAmount / totalCapital) * 100 : 0;

  // 距成本百分比
  const stopFromCost = costPrice > 0 && recStop > 0
    ? ((recStop - costPrice) / costPrice * 100) : null;
  const targetFromCost = costPrice > 0 && recTarget > 0
    ? ((recTarget - costPrice) / costPrice * 100) : null;

  // 持仓建议文本
  const adviceText = hs?.advice;
  const adviceReason = hasPosition ? hs?.recommendedStopReason : undefined;
  const entryPct = hs?.entryPositionPct ?? suggestedPositionPct;

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
            {entryPct != null && entryPct > 0 && (
              <div className="bg-surface-2 rounded-lg p-2.5 text-center">
                <div className="text-[10px] text-muted mb-1">空仓建议仓位</div>
                <div className="text-sm font-bold font-mono text-white/50">{entryPct}%</div>
              </div>
            )}
          </div>
        )}

        {/* 持仓策略建议 */}
        {hasPosition && adviceText && (
          <div className="text-[11px] p-2.5 rounded-lg bg-cyan/5 border border-cyan/15 text-white/70 leading-relaxed">
            <span className="text-cyan font-medium mr-1">持仓策略:</span>
            {adviceText}
          </div>
        )}

        {/* 推荐止损/止盈（基于成本价） */}
        {costPrice > 0 && (stopFromCost !== null || targetFromCost !== null) && (
          <div className="grid grid-cols-2 gap-2">
            {stopFromCost !== null && (
              <div className="bg-surface-2 rounded-lg p-2.5">
                <div className="text-[10px] text-muted mb-1">{recStopLabel}</div>
                <div className="flex items-baseline gap-1">
                  <span className="text-sm font-bold font-mono text-danger">{recStop.toFixed(2)}</span>
                  <span className={`text-[10px] font-mono ${stopFromCost >= 0 ? 'text-success' : 'text-danger'}`}>
                    ({stopFromCost >= 0 ? '+' : ''}{stopFromCost.toFixed(1)}%)
                  </span>
                </div>
              </div>
            )}
            {targetFromCost !== null && (
              <div className="bg-surface-2 rounded-lg p-2.5">
                <div className="text-[10px] text-muted mb-1">{recTargetLabel}</div>
                <div className="flex items-baseline gap-1">
                  <span className="text-sm font-bold font-mono text-success">{recTarget.toFixed(2)}</span>
                  <span className={`text-[10px] font-mono ${targetFromCost >= 0 ? 'text-success' : 'text-danger'}`}>
                    ({targetFromCost >= 0 ? '+' : ''}{targetFromCost.toFixed(1)}%)
                  </span>
                </div>
              </div>
            )}
          </div>
        )}

        {/* 推荐理由 */}
        {hasPosition && adviceReason && (
          <div className="text-[10px] text-muted/70 px-1">
            💡 {adviceReason}
          </div>
        )}

        {/* 所有量化锚点参考 */}
        {hasPosition && hs && (hs.stopLossShort || hs.trailingStop || hs.stopLossMid) && (
          <div className="border-t border-white/5 pt-2">
            <div className="text-[10px] text-muted mb-1.5">全部止损止盈锚点</div>
            <div className="flex flex-wrap gap-x-4 gap-y-1 text-[10px] font-mono text-white/40">
              {hs.trailingStop ? <span>移动止盈 <span className="text-white/60">{hs.trailingStop.toFixed(2)}</span></span> : null}
              {hs.stopLossShort ? <span>短线止损 <span className="text-white/60">{hs.stopLossShort.toFixed(2)}</span></span> : null}
              {hs.stopLossMid ? <span>中线止损 <span className="text-white/60">{hs.stopLossMid.toFixed(2)}</span></span> : null}
              {hs.targetShort ? <span>短线目标 <span className="text-white/60">{hs.targetShort.toFixed(2)}</span></span> : null}
              {hs.targetMid ? <span>中线目标 <span className="text-white/60">{hs.targetMid.toFixed(2)}</span></span> : null}
            </div>
          </div>
        )}
      </div>
    </Card>
  );
};
