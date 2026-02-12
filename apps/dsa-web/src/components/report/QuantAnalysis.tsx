import type React from 'react';
import { useState } from 'react';
import { Card } from '../common';

interface QuantAnalysisProps {
  data: Record<string, unknown>;
}

/** 量化指标卡片 */
const MetricCard: React.FC<{
  label: string;
  value: string | number | undefined;
  color?: string;
  sub?: string;
}> = ({ label, value, color, sub }) => (
  <div className="bg-surface-2 rounded-lg p-2.5 text-center">
    <div className="text-[10px] text-muted mb-1">{label}</div>
    <div className={`text-sm font-bold font-mono ${color || 'text-white'}`}>
      {value ?? '--'}
    </div>
    {sub && <div className="text-[9px] text-muted mt-0.5">{sub}</div>}
  </div>
);

/** 信号标签 */
const SignalTag: React.FC<{ text: string; type?: 'positive' | 'negative' | 'neutral' }> = ({ text, type = 'neutral' }) => {
  const colors = {
    positive: 'bg-success/15 text-success border-success/20',
    negative: 'bg-danger/15 text-danger border-danger/20',
    neutral: 'bg-cyan/10 text-cyan border-cyan/20',
  };
  return (
    <span className={`inline-block text-[10px] px-2 py-0.5 rounded-full border ${colors[type]}`}>
      {text}
    </span>
  );
};

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
    <Card variant="bordered" padding="md">
      <button
        type="button"
        className="w-full flex items-center justify-between text-left mb-3"
        onClick={() => setExpanded(!expanded)}
      >
        <div className="flex items-baseline gap-2">
          <span className="label-uppercase">QUANT ANALYSIS</span>
          <h3 className="text-base font-semibold text-white">量化分析</h3>
        </div>
        <span className="text-xs text-muted">{expanded ? '▲' : '▼'}</span>
      </button>

      {expanded && (
        <div className="space-y-4">
          {/* 综合评分 + 趋势 */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
            <MetricCard
              label="综合评分"
              value={signalScore}
              color={getScoreColor(signalScore)}
              sub={qe.buy_signal ?? qe.buySignal}
            />
            <MetricCard
              label="趋势强度"
              value={trendStrength}
              color={getScoreColor(trendStrength)}
              sub={qe.trend_status ?? qe.trendStatus}
            />
            <MetricCard
              label="量比"
              value={(qe.volume_ratio ?? qe.volumeRatio)?.toFixed(2)}
              color={(qe.volume_ratio ?? qe.volumeRatio) > 2 ? 'text-warning' : 'text-white'}
              sub={qe.volume_status ?? qe.volumeStatus}
            />
            <MetricCard
              label="风险收益比"
              value={(qe.risk_reward_ratio ?? qe.riskRewardRatio)?.toFixed(2)}
              color={(qe.risk_reward_ratio ?? qe.riskRewardRatio) >= 2 ? 'text-success' : 'text-warning'}
              sub={qe.risk_reward_verdict ?? qe.riskRewardVerdict}
            />
          </div>

          {/* 技术指标 */}
          <div>
            <h4 className="text-xs font-medium text-cyan mb-2">技术指标</h4>
            <div className="grid grid-cols-3 sm:grid-cols-6 gap-2">
              <MetricCard label="RSI(12)" value={(qe.rsi ?? qe.rsi12)?.toFixed(1)} color={getRsiColor(qe.rsi ?? qe.rsi12 ?? 50)} sub={qe.rsi_status ?? qe.rsiStatus} />
              <MetricCard label="KDJ-K" value={(qe.kdj_k ?? qe.kdjK)?.toFixed(1)} color={getRsiColor(qe.kdj_k ?? qe.kdjK ?? 50)} />
              <MetricCard label="KDJ-J" value={(qe.kdj_j ?? qe.kdjJ)?.toFixed(1)} color={(qe.kdj_j ?? qe.kdjJ) > 100 ? 'text-danger' : (qe.kdj_j ?? qe.kdjJ) < 0 ? 'text-success' : 'text-white'} />
              <MetricCard label="MACD" value={(qe.macd_bar ?? qe.macdBar)?.toFixed(3)} color={(qe.macd_bar ?? qe.macdBar) > 0 ? 'text-[#ff4d4d]' : 'text-[#00d46a]'} sub={qe.macd_status ?? qe.macdStatus} />
              <MetricCard label="布林%B" value={(qe.bb_pct_b ?? qe.bbPctB)?.toFixed(2)} color={(qe.bb_pct_b ?? qe.bbPctB) > 0.8 ? 'text-danger' : (qe.bb_pct_b ?? qe.bbPctB) < 0.2 ? 'text-success' : 'text-white'} />
              <MetricCard label="ATR(14)" value={(qe.atr14)?.toFixed(2)} sub="波动率" />
            </div>
          </div>

          {/* 均线系统 */}
          <div>
            <h4 className="text-xs font-medium text-cyan mb-2">均线系统</h4>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
              <MetricCard label="MA5" value={(qe.ma5)?.toFixed(2)} />
              <MetricCard label="MA10" value={(qe.ma10)?.toFixed(2)} />
              <MetricCard label="MA20" value={(qe.ma20)?.toFixed(2)} />
              <MetricCard label="MA60" value={(qe.ma60)?.toFixed(2)} />
            </div>
            <div className="mt-1.5 text-[11px] text-muted">
              {qe.ma_alignment ?? qe.maAlignment}
            </div>
          </div>

          {/* 估值 + 资金面 + 筹码 */}
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            {/* 估值 */}
            <div className="bg-surface-2 rounded-lg p-3">
              <h5 className="text-[10px] text-cyan mb-2 font-medium">估值分析</h5>
              <div className="space-y-1.5 text-[11px]">
                <div className="flex justify-between">
                  <span className="text-muted">PE(TTM)</span>
                  <span className="text-white font-mono">{(qe.pe_ratio ?? qe.peRatio)?.toFixed(1) ?? '--'}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted">PB</span>
                  <span className="text-white font-mono">{(qe.pb_ratio ?? qe.pbRatio)?.toFixed(2) ?? '--'}</span>
                </div>
                {(qe.pe_percentile ?? qe.pePercentile) != null && (
                  <div className="flex justify-between">
                    <span className="text-muted">PE分位数</span>
                    <span className={`font-mono ${(qe.pe_percentile ?? qe.pePercentile) > 80 ? 'text-danger' : (qe.pe_percentile ?? qe.pePercentile) < 20 ? 'text-success' : 'text-white'}`}>
                      {(qe.pe_percentile ?? qe.pePercentile)?.toFixed(0)}%
                    </span>
                  </div>
                )}
                <div className="flex justify-between">
                  <span className="text-muted">估值判断</span>
                  <span className={`font-medium ${(qe.valuation_score ?? qe.valuationScore) <= 3 ? 'text-danger' : (qe.valuation_score ?? qe.valuationScore) >= 7 ? 'text-success' : 'text-warning'}`}>
                    {qe.valuation_verdict ?? qe.valuationVerdict ?? '--'}
                  </span>
                </div>
              </div>
            </div>

            {/* 资金面 */}
            <div className="bg-surface-2 rounded-lg p-3">
              <h5 className="text-[10px] text-cyan mb-2 font-medium">资金面</h5>
              <div className="space-y-1.5 text-[11px]">
                <div className="flex justify-between">
                  <span className="text-muted">资金评分</span>
                  <span className={`font-mono ${(qe.capital_flow_score ?? qe.capitalFlowScore) >= 7 ? 'text-success' : (qe.capital_flow_score ?? qe.capitalFlowScore) <= 3 ? 'text-danger' : 'text-white'}`}>
                    {qe.capital_flow_score ?? qe.capitalFlowScore ?? '--'}/10
                  </span>
                </div>
                <div className="text-muted leading-relaxed">
                  {qe.capital_flow_signal ?? qe.capitalFlowSignal ?? '--'}
                </div>
                {(qe.suggested_position_pct ?? qe.suggestedPositionPct) != null && (
                  <div className="flex justify-between">
                    <span className="text-muted">建议仓位</span>
                    <span className="text-cyan font-mono">{qe.suggested_position_pct ?? qe.suggestedPositionPct}%</span>
                  </div>
                )}
              </div>
            </div>

            {/* 筹码 */}
            <div className="bg-surface-2 rounded-lg p-3">
              <h5 className="text-[10px] text-cyan mb-2 font-medium">筹码分布</h5>
              <div className="space-y-1.5 text-[11px]">
                <div className="flex justify-between">
                  <span className="text-muted">筹码评分</span>
                  <span className={`font-mono ${(qe.chip_score ?? qe.chipScore) >= 7 ? 'text-success' : (qe.chip_score ?? qe.chipScore) <= 3 ? 'text-danger' : 'text-white'}`}>
                    {qe.chip_score ?? qe.chipScore ?? '--'}/10
                  </span>
                </div>
                {(qe.profit_ratio ?? qe.profitRatio) != null && (
                  <div className="flex justify-between">
                    <span className="text-muted">获利盘</span>
                    <span className={`font-mono ${(qe.profit_ratio ?? qe.profitRatio) > 90 ? 'text-danger' : 'text-white'}`}>
                      {(qe.profit_ratio ?? qe.profitRatio)?.toFixed(1)}%
                    </span>
                  </div>
                )}
                <div className="text-muted leading-relaxed">
                  {qe.chip_signal ?? qe.chipSignal ?? '--'}
                </div>
              </div>
            </div>
          </div>

          {/* 信号共振 */}
          {(qe.resonance_signals ?? qe.resonanceSignals)?.length > 0 && (
            <div>
              <h4 className="text-xs font-medium text-cyan mb-2">
                信号共振 ({qe.resonance_count ?? qe.resonanceCount ?? 0}项)
              </h4>
              <div className="flex flex-wrap gap-1.5">
                {(qe.resonance_signals ?? qe.resonanceSignals)?.map((s: string, i: number) => (
                  <SignalTag key={i} text={s} type="positive" />
                ))}
              </div>
            </div>
          )}

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
    </Card>
  );
};
