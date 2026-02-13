import type React from 'react';
import { useState } from 'react';

interface QuantAnalysisProps {
  data: Record<string, unknown>;
}

// ============ 结论生成器 ============

/** RSI 结论 */
function rsiVerdict(val: number, _status: string): { text: string; color: string } {
  if (val > 80) return { text: `严重超买(${val.toFixed(1)})`, color: 'text-danger' };
  if (val > 70) return { text: `超买(${val.toFixed(1)})，短线回调风险`, color: 'text-danger' };
  if (val < 20) return { text: `严重超卖(${val.toFixed(1)})`, color: 'text-success' };
  if (val < 30) return { text: `超卖(${val.toFixed(1)})，反弹机会`, color: 'text-success' };
  if (val >= 50) return { text: `偏强(${val.toFixed(1)})`, color: 'text-white/70' };
  return { text: `偏弱(${val.toFixed(1)})`, color: 'text-white/50' };
}

/** KDJ 结论 */
function kdjVerdict(k: number, j: number, kdjStatus: string): { text: string; color: string } {
  if (j > 100) return { text: `J=${j.toFixed(0)} 严重超买，回调概率大`, color: 'text-danger' };
  if (j > 80) return { text: `J=${j.toFixed(0)} 高位，注意回调`, color: 'text-[#ff8c00]' };
  if (j < 0) return { text: `J=${j.toFixed(0)} 严重超卖，反弹在即`, color: 'text-success' };
  if (j < 20) return { text: `J=${j.toFixed(0)} 低位，关注企稳信号`, color: 'text-success' };
  if (kdjStatus) return { text: `K${k.toFixed(0)}/J${j.toFixed(0)} ${kdjStatus}`, color: k > 50 ? 'text-white/70' : 'text-white/50' };
  return { text: `K${k.toFixed(0)}/J${j.toFixed(0)}`, color: 'text-white/60' };
}

/** MACD 结论 */
function macdVerdict(bar: number, status: string): { text: string; color: string } {
  const bullish = bar > 0;
  const statusMap: Record<string, { text: string; color: string }> = {
    '零轴上金叉': { text: '零轴上金叉，强买入信号', color: 'text-success' },
    '金叉': { text: '金叉，趋势转多', color: 'text-success' },
    '上穿零轴': { text: '上穿零轴，趋势转强', color: 'text-success' },
    '多头': { text: `多头(柱${bar.toFixed(3)})`, color: 'text-[#ff4d4d]' },
    '死叉': { text: '死叉，趋势转空', color: 'text-danger' },
    '下穿零轴': { text: '下穿零轴，趋势走弱', color: 'text-danger' },
    '空头': { text: `空头(柱${bar.toFixed(3)})`, color: 'text-[#00d46a]' },
  };
  if (status && statusMap[status]) return statusMap[status];
  return { text: `${bullish ? '红柱' : '绿柱'} ${bar.toFixed(3)}`, color: bullish ? 'text-[#ff4d4d]' : 'text-[#00d46a]' };
}

/** 布林带%B 结论 */
function bbVerdict(pctB: number): { text: string; color: string } {
  if (pctB > 1.0) return { text: `${pctB.toFixed(2)} 突破上轨，超强/超买`, color: 'text-danger' };
  if (pctB > 0.8) return { text: `${pctB.toFixed(2)} 接近上轨，注意回调`, color: 'text-[#ff8c00]' };
  if (pctB < 0) return { text: `${pctB.toFixed(2)} 跌破下轨，超弱/超卖`, color: 'text-success' };
  if (pctB < 0.2) return { text: `${pctB.toFixed(2)} 接近下轨，关注支撑`, color: 'text-success' };
  return { text: `${pctB.toFixed(2)} 中轨附近`, color: 'text-white/50' };
}

/** 均线排列结论 */
function maVerdict(alignment: string): { text: string; color: string } {
  if (!alignment) return { text: '--', color: 'text-white/40' };
  const lower = alignment.toLowerCase();
  if (lower.includes('强势多头') || lower.includes('多头排列'))
    return { text: alignment, color: 'text-success' };
  if (lower.includes('多头') || lower.includes('偏多'))
    return { text: alignment, color: 'text-success/80' };
  if (lower.includes('强势空头') || lower.includes('空头排列'))
    return { text: alignment, color: 'text-danger' };
  if (lower.includes('空头') || lower.includes('偏空'))
    return { text: alignment, color: 'text-danger/80' };
  return { text: alignment, color: 'text-warning' };
}

const getScoreColor = (score: number): string => {
  if (score >= 70) return 'text-success';
  if (score >= 40) return 'text-warning';
  return 'text-danger';
};

// ============ 子组件 ============

/** 技术指标卡片：结论+数值+解读 */
const IndicatorCard: React.FC<{
  label: string;
  conclusion: string;
  color: string;
  detail?: string;
}> = ({ label, conclusion, color, detail }) => (
  <div className="bg-white/[0.02] rounded-lg p-2.5 border border-white/[0.04]">
    <div className="flex items-center justify-between mb-1">
      <span className="text-[10px] text-white/30 font-medium">{label}</span>
    </div>
    <div className={`text-[12px] font-bold leading-snug ${color}`}>{conclusion}</div>
    {detail && <div className="text-[10px] text-white/25 mt-1">{detail}</div>}
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

  // 提取指标值（兼容 snake_case / camelCase）
  const rsiVal = qe.rsi ?? qe.rsi12 ?? 50;
  const rsiStatus = qe.rsi_status ?? qe.rsiStatus ?? '';
  const kdjK = qe.kdj_k ?? qe.kdjK ?? 50;
  const kdjJ = qe.kdj_j ?? qe.kdjJ ?? 50;
  const kdjStatus = qe.kdj_status ?? qe.kdjStatus ?? '';
  const macdBar = qe.macd_bar ?? qe.macdBar ?? 0;
  const macdStatus = qe.macd_status ?? qe.macdStatus ?? '';
  const bbPctB = qe.bb_pct_b ?? qe.bbPctB;
  const maAlignment = qe.ma_alignment ?? qe.maAlignment ?? '';
  const atr14 = qe.atr14;

  // 生成结论
  const rsiV = rsiVerdict(rsiVal, rsiStatus);
  const kdjV = kdjVerdict(kdjK, kdjJ, kdjStatus);
  const macdV = macdVerdict(macdBar, macdStatus);
  const bbV = bbPctB != null ? bbVerdict(bbPctB) : null;
  const maV = maVerdict(maAlignment);

  return (
    <div className="rounded-xl bg-[var(--bg-card)] border border-white/[0.06] p-4">
      <button
        type="button"
        className="w-full flex items-center justify-between text-left mb-3"
        onClick={() => setExpanded(!expanded)}
      >
        <h3 className="text-sm font-semibold text-white/70">量化诊断</h3>
        <span className="text-xs text-white/30">{expanded ? '▲' : '▼'}</span>
      </button>

      {/* 量化诊断结论（始终可见） */}
      <div className="p-2.5 rounded-lg bg-white/[0.03] border border-white/[0.05] mb-3">
        <div className="flex items-center gap-2 mb-1.5">
          <span className={`text-lg font-bold font-mono ${getScoreColor(signalScore)}`}>{signalScore ?? '--'}</span>
          <span className="text-[11px] text-white/40">分</span>
          {(qe.buy_signal ?? qe.buySignal) && (
            <span className={`text-xs font-semibold px-2 py-0.5 rounded ${signalScore >= 60 ? 'bg-green-500/15 text-green-400' : signalScore <= 40 ? 'bg-red-500/15 text-red-400' : 'bg-yellow-500/15 text-yellow-400'}`}>
              {qe.buy_signal ?? qe.buySignal}
            </span>
          )}
        </div>
        {/* 信号理由 */}
        {(qe.signal_reasons ?? qe.signalReasons)?.length > 0 && (
          <div className="text-[11px] text-white/50 leading-relaxed">
            {(qe.signal_reasons ?? qe.signalReasons).slice(0, 4).join(' · ')}
          </div>
        )}
      </div>

      {/* 指标一行摘要 */}
      <div className="text-[11px] text-white/60 leading-relaxed mb-2 font-mono flex flex-wrap gap-x-2 gap-y-0.5">
        {(qe.trend_status ?? qe.trendStatus) && (
          <span>趋势:<span className={maV.color}>{qe.trend_status ?? qe.trendStatus}</span></span>
        )}
        {macdStatus && (
          <span className="text-white/20">|</span>
        )}
        {macdStatus && (
          <span>MACD:<span className={macdV.color}>{macdStatus}</span></span>
        )}
        {rsiVal != null && (
          <><span className="text-white/20">|</span><span>RSI:<span className={rsiV.color}>{rsiVal.toFixed(0)}</span></span></>
        )}
        {kdjStatus && (
          <><span className="text-white/20">|</span><span>KDJ:<span className={kdjV.color}>{kdjStatus}</span></span></>
        )}
        {(qe.volume_status ?? qe.volumeStatus) && (
          <><span className="text-white/20">|</span><span>量能:<span className="text-white/70">{qe.volume_status ?? qe.volumeStatus}{(qe.volume_ratio ?? qe.volumeRatio) != null ? `(${(qe.volume_ratio ?? qe.volumeRatio).toFixed(2)})` : ''}</span></span></>
        )}
        {(qe.chip_signal ?? qe.chipSignal) && (
          <><span className="text-white/20">|</span><span>筹码:<span className="text-white/70">{qe.chip_signal ?? qe.chipSignal}</span></span></>
        )}
        {(qe.valuation_verdict ?? qe.valuationVerdict) && (
          <><span className="text-white/20">|</span><span>估值:<span className="text-white/70">{qe.valuation_verdict ?? qe.valuationVerdict}</span></span></>
        )}
        {(qe.capital_flow_signal ?? qe.capitalFlowSignal) && (qe.capital_flow_signal ?? qe.capitalFlowSignal) !== '资金面数据正常' && (
          <><span className="text-white/20">|</span><span>资金:<span className="text-white/70">{qe.capital_flow_signal ?? qe.capitalFlowSignal}</span></span></>
        )}
        {(qe.sector_name ?? qe.sectorName) && (
          <><span className="text-white/20">|</span><span>板块:<span className="text-white/70">{qe.sector_name ?? qe.sectorName} {qe.sector_signal ?? qe.sectorSignal ?? ''}</span></span></>
        )}
      </div>

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

          {/* 技术指标（每个都带结论） */}
          <div>
            <h4 className="text-[11px] font-medium text-white/40 mb-2">技术指标</h4>
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
              <IndicatorCard
                label="RSI(12)"
                conclusion={rsiV.text}
                color={rsiV.color}
                detail={rsiStatus && rsiStatus !== rsiV.text ? rsiStatus : undefined}
              />
              <IndicatorCard
                label="MACD"
                conclusion={macdV.text}
                color={macdV.color}
              />
              <IndicatorCard
                label="KDJ"
                conclusion={kdjV.text}
                color={kdjV.color}
                detail={kdjStatus && !kdjV.text.includes(kdjStatus) ? kdjStatus : undefined}
              />
              {bbV && (
                <IndicatorCard
                  label="布林%B"
                  conclusion={bbV.text}
                  color={bbV.color}
                />
              )}
              <IndicatorCard
                label="均线排列"
                conclusion={maV.text}
                color={maV.color}
                detail={
                  (qe.ma5 || qe.ma10 || qe.ma20)
                    ? `MA5=${(qe.ma5)?.toFixed(2) ?? '--'} MA10=${(qe.ma10)?.toFixed(2) ?? '--'} MA20=${(qe.ma20)?.toFixed(2) ?? '--'}`
                    : undefined
                }
              />
              {atr14 != null && (
                <IndicatorCard
                  label="ATR(14)"
                  conclusion={`${atr14.toFixed(2)}`}
                  color="text-white/60"
                  detail={`日波幅 ≈ ${atr14.toFixed(2)} 元`}
                />
              )}
            </div>
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
