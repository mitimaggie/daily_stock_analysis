import type React from 'react';
import { useState } from 'react';

interface QuantAnalysisProps {
  data: Record<string, unknown>;
}

/** 量化指标行：有结论时结论放大数字缩小，无结论时数字正常显示 */
const MetricRow: React.FC<{
  label: string;
  value?: string | number | undefined;
  color?: string;
  sub?: string;
}> = ({ label, value, color, sub }) => (
  <div className="flex items-center justify-between py-1.5 border-b border-white/5 last:border-0">
    <span className="text-[11px] text-muted">{label}</span>
    <div className="flex items-baseline gap-1.5">
      {sub ? (
        <>
          <span className="text-[10px] font-mono text-white/40">{value ?? '--'}</span>
          <span className={`text-[13px] font-bold ${color || 'text-white'}`}>{sub}</span>
        </>
      ) : (
        <span className={`text-[13px] font-bold font-mono ${color || 'text-white'}`}>{value ?? '--'}</span>
      )}
    </div>
  </div>
);

/** 核心指标卡片 */
const CoreMetric: React.FC<{
  label: string;
  value: string | number | undefined;
  color?: string;
  sub?: string;
}> = ({ label, value, color, sub }) => (
  <div className="bg-white/[0.03] rounded-lg p-2.5 text-center">
    <div className="text-[10px] text-white/30 mb-0.5">{label}</div>
    <div className="text-[12px] font-mono text-white/40">{value ?? '--'}</div>
    {sub && <div className={`text-[12px] font-semibold mt-0.5 truncate ${color || 'text-white/80'}`}>{sub}</div>}
  </div>
);


const getScoreColor = (score: number): string => {
  if (score >= 70) return 'text-success';
  if (score >= 40) return 'text-warning';
  return 'text-danger';
};

const getRsiColor = (rsi: number): string => {
  if (rsi > 70) return 'text-danger';
  if (rsi < 30) return 'text-success';
  return 'text-white';
};

/**
 * 量化分析详情组件
 * 展示技术指标、估值、资金面、筹码等量化数据
 */
export const QuantAnalysis: React.FC<QuantAnalysisProps> = ({ data }) => {
  const [expanded, setExpanded] = useState(true);

  const qe = data as Record<string, any>;
  if (!qe || Object.keys(qe).length === 0) return null;

  const signalScore = qe.signal_score ?? qe.signalScore;
  const trendStrength = qe.trend_strength ?? qe.trendStrength;

  return (
    <div className="rounded-xl bg-[var(--bg-card)] border border-white/[0.06] p-4">
      <button
        type="button"
        className="w-full flex items-center justify-between text-left mb-3"
        onClick={() => setExpanded(!expanded)}
      >
        <h3 className="text-sm font-semibold text-white/70">量化分析</h3>
        <span className="text-xs text-white/30">{expanded ? '▲' : '▼'}</span>
      </button>

      {expanded && (
        <div className="space-y-4">
          {/* 信号共振（置顶，一目了然） */}
          {(qe.resonance_signals ?? qe.resonanceSignals)?.length > 0 && (
            <div className="bg-surface-2 rounded-lg p-3">
              <h4 className="text-xs font-medium text-cyan mb-2">
                信号共振 ({qe.resonance_count ?? qe.resonanceCount ?? 0}项)
              </h4>
              <div className="flex flex-wrap gap-2">
                {(qe.resonance_signals ?? qe.resonanceSignals)?.map((s: string, i: number) => (
                  <span key={i} className="inline-block text-sm font-bold px-3 py-1 rounded-full border bg-success/15 text-success border-success/20">
                    {s}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* 核心指标（结论突出） */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
            <CoreMetric
              label="综合评分"
              value={signalScore}
              color={getScoreColor(signalScore)}
              sub={qe.buy_signal ?? qe.buySignal}
            />
            <CoreMetric
              label="趋势强度"
              value={trendStrength}
              color={getScoreColor(trendStrength)}
              sub={qe.trend_status ?? qe.trendStatus}
            />
            <CoreMetric
              label="量比"
              value={(qe.volume_ratio ?? qe.volumeRatio)?.toFixed(2)}
              color={(qe.volume_ratio ?? qe.volumeRatio) > 2 ? 'text-warning' : 'text-white'}
              sub={qe.volume_status ?? qe.volumeStatus}
            />
            <CoreMetric
              label="风险收益比"
              value={(qe.risk_reward_ratio ?? qe.riskRewardRatio)?.toFixed(2)}
              color={(qe.risk_reward_ratio ?? qe.riskRewardRatio) >= 2 ? 'text-success' : 'text-warning'}
              sub={qe.risk_reward_verdict ?? qe.riskRewardVerdict}
            />
          </div>

          {/* 技术指标（两列紧凑） */}
          <div className="grid grid-cols-2 gap-x-4 bg-white/[0.03] rounded-lg p-3">
            <MetricRow label="RSI(12)" value={(qe.rsi ?? qe.rsi12)?.toFixed(1)} color={getRsiColor(qe.rsi ?? qe.rsi12 ?? 50)} sub={qe.rsi_status ?? qe.rsiStatus} />
            <MetricRow label="MACD" value={(qe.macd_bar ?? qe.macdBar)?.toFixed(3)} color={(qe.macd_bar ?? qe.macdBar) > 0 ? 'text-[#ff4d4d]' : 'text-[#00d46a]'} sub={qe.macd_status ?? qe.macdStatus} />
            <MetricRow label="KDJ" value={`K${(qe.kdj_k ?? qe.kdjK)?.toFixed(0) ?? '--'}/J${(qe.kdj_j ?? qe.kdjJ)?.toFixed(0) ?? '--'}`} color={(qe.kdj_j ?? qe.kdjJ) > 100 ? 'text-danger' : (qe.kdj_j ?? qe.kdjJ) < 0 ? 'text-success' : 'text-white'} />
            <MetricRow label="布林%B" value={(qe.bb_pct_b ?? qe.bbPctB)?.toFixed(2)} color={(qe.bb_pct_b ?? qe.bbPctB) > 0.8 ? 'text-danger' : (qe.bb_pct_b ?? qe.bbPctB) < 0.2 ? 'text-success' : 'text-white'} />
            <MetricRow label="ATR" value={(qe.atr14)?.toFixed(2)} />
            {(qe.ma_alignment ?? qe.maAlignment) && (
              <MetricRow label="均线" sub={qe.ma_alignment ?? qe.maAlignment} />
            )}
          </div>

          {/* 估值 + 资金面 + 筹码（结论简洁） */}
          <div className="grid grid-cols-3 gap-2">
            <div className="bg-white/[0.03] rounded-lg p-2.5">
              <div className="text-[10px] text-white/30 mb-1">估值</div>
              <div className={`text-[13px] font-semibold ${(qe.valuation_score ?? qe.valuationScore) <= 3 ? 'text-[#ff4d4d]' : (qe.valuation_score ?? qe.valuationScore) >= 7 ? 'text-[#00d46a]' : 'text-white/80'}`}>
                {qe.valuation_verdict ?? qe.valuationVerdict ?? '--'}
              </div>
              <div className="text-[10px] text-white/25 mt-1">PE {(qe.pe_ratio ?? qe.peRatio)?.toFixed(1) ?? '--'} · PB {(qe.pb_ratio ?? qe.pbRatio)?.toFixed(2) ?? '--'}</div>
            </div>
            <div className="bg-white/[0.03] rounded-lg p-2.5">
              <div className="text-[10px] text-white/30 mb-1">资金面</div>
              <div className={`text-[13px] font-semibold ${(qe.capital_flow_score ?? qe.capitalFlowScore) >= 7 ? 'text-[#00d46a]' : (qe.capital_flow_score ?? qe.capitalFlowScore) <= 3 ? 'text-[#ff4d4d]' : 'text-white/80'}`}>
                {qe.capital_flow_signal ?? qe.capitalFlowSignal ?? '--'}
              </div>
              <div className="text-[10px] text-white/25 mt-1">{qe.capital_flow_score ?? qe.capitalFlowScore ?? '--'}/10{(qe.suggested_position_pct ?? qe.suggestedPositionPct) != null ? ` · 仓位${qe.suggested_position_pct ?? qe.suggestedPositionPct}%` : ''}</div>
            </div>
            <div className="bg-white/[0.03] rounded-lg p-2.5">
              <div className="text-[10px] text-white/30 mb-1">筹码</div>
              <div className={`text-[13px] font-semibold ${(qe.chip_score ?? qe.chipScore) >= 7 ? 'text-[#00d46a]' : (qe.chip_score ?? qe.chipScore) <= 3 ? 'text-[#ff4d4d]' : 'text-white/80'}`}>
                {qe.chip_signal ?? qe.chipSignal ?? '--'}
              </div>
              <div className="text-[10px] text-white/25 mt-1">{qe.chip_score ?? qe.chipScore ?? '--'}/10{(qe.profit_ratio ?? qe.profitRatio) != null ? ` · 获利${(qe.profit_ratio ?? qe.profitRatio)?.toFixed(0)}%` : ''}</div>
            </div>
          </div>

          {/* 风险因子 */}
          {(qe.risk_factors ?? qe.riskFactors)?.length > 0 && (
            <div>
              <h4 className="text-xs font-medium text-danger mb-2">风险因子</h4>
              <div className="space-y-1">
                {(qe.risk_factors ?? qe.riskFactors)?.map((r: string, i: number) => (
                  <div key={i} className="text-[11px] text-danger/80 flex items-start gap-1.5">
                    <span className="text-danger mt-0.5">⚠</span>
                    <span>{r}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* P0 风控警告 */}
          {(qe.no_trade ?? qe.noTrade) && (
            <div className="p-3 rounded-lg bg-danger/10 border border-danger/30">
              <div className="text-xs font-bold text-danger mb-1">🚫 禁止交易</div>
              <div className="text-[11px] text-danger/80">
                {(qe.no_trade_reasons ?? qe.noTradeReasons)?.join('；')}
              </div>
            </div>
          )}

          {(qe.stop_loss_breached ?? qe.stopLossBreached) && (
            <div className="p-3 rounded-lg bg-warning/10 border border-warning/30">
              <div className="text-xs font-bold text-warning mb-1">🚨 止损预警</div>
              <div className="text-[11px] text-warning/80">
                {qe.stop_loss_breach_detail ?? qe.stopLossBreachDetail}
              </div>
            </div>
          )}

          {(qe.sentiment_extreme ?? qe.sentimentExtreme) && (
            <div className="p-3 rounded-lg bg-warning/10 border border-warning/30">
              <div className="text-xs font-bold text-warning mb-1">
                {(qe.sentiment_extreme ?? qe.sentimentExtreme) === '极度贪婪' ? '🔴' : '🟢'} {qe.sentiment_extreme ?? qe.sentimentExtreme}
              </div>
              <div className="text-[11px] text-warning/80">
                {qe.sentiment_extreme_detail ?? qe.sentimentExtremeDetail}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
};
