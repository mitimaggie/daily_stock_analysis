import type React from 'react';
import type { ReportStrategy as ReportStrategyType } from '../../types/analysis';

interface ProfitTakeStage {
  stage: number;
  label: string;
  exit_price: number;
  exit_pct: number;
  condition: string;
  source: string;
}

interface ProfitTakePlan {
  current_price: number;
  cost_price: number;
  pnl_pct: number;
  atr: number;
  atr_trailing_stop: number;
  highest_price: number;
  urgency: 'HIGH' | 'MEDIUM' | 'LOW';
  urgency_note: string;
  stages: ProfitTakeStage[];
}

interface ReportStrategyProps {
  strategy?: ReportStrategyType;
  hasPositionInfo?: boolean;
  costPrice?: number;
  currentPrice?: number;
  holdingStrategy?: Record<string, any> | null;
  defenseMode?: boolean;
  maxDrawdown60d?: number;
  positionDiagnosis?: Record<string, any> | null;
  suggestedPositionPct?: number | null;
  profitTakePlan?: ProfitTakePlan | null;
  analysisScene?: string;
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
  defenseMode = false,
  maxDrawdown60d,
  positionDiagnosis,
  suggestedPositionPct,
  profitTakePlan,
  analysisScene,
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
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold text-white/90 flex items-center gap-1.5">
          <span>{defenseMode ? '🛡️' : '🎯'}</span> {defenseMode ? '防守作战' : '作战计划'}
        </h3>
        {defenseMode && (
          <span className="text-[10px] px-2 py-0.5 rounded bg-red-500/15 text-red-400 font-medium">防守模式</span>
        )}
      </div>

      {/* 5 列表格 */}
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="text-white/40 border-b border-white/[0.06]">
              <th className="text-center py-1.5 font-medium">{defenseMode ? (hasPositionInfo ? '反弹出货' : '反弹位') : (hasPositionInfo ? '加仓点' : '买点')}</th>
              <th className="text-center py-1.5 font-medium">止损</th>
              <th className="text-center py-1.5 font-medium">{defenseMode ? '减仓目标' : '短线目标'}</th>
              <th className="text-center py-1.5 font-medium">{defenseMode ? '清仓价' : '中线目标'}</th>
              <th className="text-center py-1.5 font-medium">{defenseMode ? '回撤风险' : rrLabel}</th>
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
                {defenseMode && maxDrawdown60d != null ? (
                  <span className="font-mono font-bold text-sm text-red-400">
                    {maxDrawdown60d.toFixed(1)}%
                  </span>
                ) : (
                  <span className={`font-mono font-bold text-sm ${rrColor}`}>
                    {rrText}
                  </span>
                )}
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      {/* 持仓成本标注 + 仓位动态建议 */}
      {hasPositionInfo && costPrice && costPrice > 0 && (
        <div className="mt-2 pt-2 border-t border-white/[0.06] flex items-center flex-wrap gap-3 text-[11px] text-white/40">
          <span>💰 成本 <span className="font-mono text-white/60">{costPrice.toFixed(2)}</span></span>
          {pnlPct != null && (
            <span className={pnlPct >= 0 ? 'text-[#ff4d4d]' : 'text-[#00d46a]'}>
              {pnlPct >= 0 ? '+' : ''}{pnlPct.toFixed(2)}%
            </span>
          )}
          {(() => {
            const actPct = positionDiagnosis?.actual_pct ?? positionDiagnosis?.actualPct;
            const sugPct = positionDiagnosis?.suggested_pct ?? positionDiagnosis?.suggestedPct;
            const delPct = positionDiagnosis?.delta_pct ?? positionDiagnosis?.deltaPct;
            if (positionDiagnosis?.action && positionDiagnosis.action !== '维持') {
              return (
                <span className={`font-medium ${
                  positionDiagnosis.action === '加仓' ? 'text-green-400/80' : 'text-red-400/80'
                }`}>
                  {positionDiagnosis.action === '清仓' ? '🚨' : positionDiagnosis.action === '减仓' ? '⚠' : '💡'}
                  {' '}{actPct != null ? `当前${actPct}%` : ''}
                  {' → '}建议{sugPct ?? 0}%
                  {delPct != null && delPct !== 0 && (
                    <span className="text-white/40 ml-1">({delPct > 0 ? '+' : ''}{delPct}%)</span>
                  )}
                </span>
              );
            }
            if (positionDiagnosis?.action === '维持' && actPct != null) {
              return (
                <span className="text-white/30">
                  仓位{actPct}% ≈ 建议{sugPct ?? 0}%，合理
                </span>
              );
            }
            return null;
          })()}
          {holdingStrategy?.recommended_stop_reason && (
            <span className="text-white/30">止损: {holdingStrategy.recommended_stop_reason}</span>
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

      {/* 止盈退出计划（profit_take 场景专用）*/}
      {profitTakePlan && analysisScene === 'profit_take' && (
        <div className="mt-3 pt-3 border-t border-white/[0.06]">
          <div className="flex items-center justify-between mb-2">
            <span className="text-[11px] font-semibold text-yellow-400/90 flex items-center gap-1">
              💰 分阶段退出计划
            </span>
            <span className={`text-[10px] px-2 py-0.5 rounded font-medium ${
              profitTakePlan.urgency === 'HIGH'
                ? 'bg-red-500/15 text-red-400'
                : profitTakePlan.urgency === 'MEDIUM'
                ? 'bg-yellow-500/15 text-yellow-400'
                : 'bg-blue-500/15 text-blue-400'
            }`}>
              {profitTakePlan.urgency === 'HIGH' ? '⚡ 高紧迫' : profitTakePlan.urgency === 'MEDIUM' ? '⚠️ 中紧迫' : '📊 低紧迫'}
            </span>
          </div>
          <div className="text-[10px] text-white/40 mb-2">{profitTakePlan.urgency_note}</div>
          <div className="flex flex-col gap-1.5">
            {profitTakePlan.stages.map((s) => (
              <div key={s.stage} className="flex items-center gap-2 text-[11px]">
                <span className="w-5 h-5 rounded-full flex items-center justify-center text-[9px] font-bold bg-white/10 text-white/60 shrink-0">
                  {s.stage}
                </span>
                <span className="text-white/50 shrink-0">{s.label}</span>
                <span className="font-mono font-bold text-yellow-400">{s.exit_price.toFixed(2)}</span>
                <span className={`text-[10px] shrink-0 ${
                  s.exit_pct >= 0 ? 'text-green-400/70' : 'text-red-400/70'
                }`}>{s.exit_pct >= 0 ? '+' : ''}{s.exit_pct.toFixed(1)}%</span>
                <span className="text-white/30 text-[10px] truncate">{s.condition}</span>
              </div>
            ))}
          </div>
          <div className="mt-2 text-[10px] text-white/30">
            🛡️ ATR追踪止损（底仓保护线）：<span className="font-mono text-white/50">{profitTakePlan.atr_trailing_stop.toFixed(2)}</span>
            &nbsp;|&nbsp;ATR={profitTakePlan.atr.toFixed(2)}
          </div>
        </div>
      )}

      {/* 仓位-评分矩阵（A股专用） */}
      {suggestedPositionPct != null && (
        <div className="mt-3 pt-3 border-t border-white/[0.06]">
          <div className="flex items-center justify-between mb-2">
            <span className="text-[11px] text-white/30 font-medium">仓位参考（大盘×评分矩阵）</span>
            <span className="text-[11px] font-mono font-bold text-cyan/80">
              建议 {suggestedPositionPct}%
            </span>
          </div>
          <div className="text-[10px] text-white/20 leading-relaxed">
            <span className="text-emerald-400/60">≥80分（胜率81%）</span>：牛市50-60% · 震荡30-40% · 弱势15-20%
            &nbsp;·&nbsp;
            <span className="text-yellow-400/60">70-79分（胜率约38%）</span>：≤15%试仓，等信号确认
            &nbsp;·&nbsp;
            <span className="text-red-400/50">&lt;70分</span>：0%，禁止新建仓
          </div>
        </div>
      )}

    </div>
  );
};
