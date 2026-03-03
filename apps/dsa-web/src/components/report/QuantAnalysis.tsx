import type React from 'react';
import { useState } from 'react';

interface QuantAnalysisProps {
  data: Record<string, unknown>;
}

// ============ 结论生成器 ============

/** RSI 结论 */
function rsiVerdict(val: number, _status: string): { text: string; color: string } {
  if (typeof val !== 'number' || isNaN(val)) return { text: '--', color: 'text-white/40' };
  if (val > 80) return { text: `严重超买(${val.toFixed(1)})`, color: 'text-danger' };
  if (val > 70) return { text: `超买(${val.toFixed(1)})，短线回调风险`, color: 'text-danger' };
  if (val < 20) return { text: `严重超卖(${val.toFixed(1)})`, color: 'text-success' };
  if (val < 30) return { text: `超卖(${val.toFixed(1)})，反弹机会`, color: 'text-success' };
  if (val >= 50) return { text: `偏强(${val.toFixed(1)})`, color: 'text-white/70' };
  return { text: `偏弱(${val.toFixed(1)})`, color: 'text-white/50' };
}

/** KDJ 结论 */
function kdjVerdict(k: number, j: number, kdjStatus: string): { text: string; color: string } {
  if (typeof k !== 'number' || typeof j !== 'number' || isNaN(k) || isNaN(j)) return { text: '--', color: 'text-white/40' };
  if (j > 100) return { text: `J=${j.toFixed(0)} 严重超买，回调概率大`, color: 'text-danger' };
  if (j > 80) return { text: `J=${j.toFixed(0)} 高位，注意回调`, color: 'text-[#ff8c00]' };
  if (j < 0) return { text: `J=${j.toFixed(0)} 严重超卖，反弹在即`, color: 'text-success' };
  if (j < 20) return { text: `J=${j.toFixed(0)} 低位，关注企稳信号`, color: 'text-success' };
  if (kdjStatus) return { text: `K${k.toFixed(0)}/J${j.toFixed(0)} ${kdjStatus}`, color: k > 50 ? 'text-white/70' : 'text-white/50' };
  return { text: `K${k.toFixed(0)}/J${j.toFixed(0)}`, color: 'text-white/60' };
}

/** MACD 结论 */
function macdVerdict(bar: number, status: string): { text: string; color: string } {
  if (typeof bar !== 'number' || isNaN(bar)) return { text: '--', color: 'text-white/40' };
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
  if (typeof pctB !== 'number' || isNaN(pctB)) return { text: '--', color: 'text-white/40' };
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

/**
 * 量化分析详情组件
 * 展示技术指标、估值、资金面、筹码等量化数据
 */
export const QuantAnalysis: React.FC<QuantAnalysisProps> = ({ data }) => {
  const [expanded, setExpanded] = useState(false);

  const qe = data as Record<string, any>;
  if (!qe || Object.keys(qe).length === 0) return null;

  const signalScore = qe.signal_score ?? qe.signalScore;

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
        {/* 信号冲突警告 */}
        {(() => {
          const conflicts: string[] = qe.signal_conflicts ?? qe.signalConflicts ?? [];
          if (!conflicts.length) return null;
          return (
            <div className="mt-2 space-y-1">
              {conflicts.map((c: string, i: number) => (
                <div key={i} className="flex items-start gap-1.5 px-2 py-1.5 rounded bg-orange-500/10 border border-orange-500/20">
                  <span className="text-orange-400 text-[11px] leading-relaxed">{c}</span>
                </div>
              ))}
            </div>
          );
        })()}
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
        {typeof rsiVal === 'number' && (
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
        {(qe.sector_name ?? qe.sectorName) && (() => {
          const sp = qe.sector_pct ?? qe.sectorPct;
          const s5d = qe.sector_5d_pct ?? qe.sector5dPct;
          const sRank = qe.sector_rank ?? qe.sectorRank;
          const sTotal = qe.sector_rank_total ?? qe.sectorRankTotal;
          return <><span className="text-white/20">|</span>
          <span>板块:<span className="text-white/70">{qe.sector_name ?? qe.sectorName}
            {typeof sp === 'number' && ` ${sp >= 0 ? '+' : ''}${sp.toFixed(2)}%`}
            {typeof sRank === 'number' && typeof sTotal === 'number' && ` 排名${sRank}/${sTotal}`}
            {typeof s5d === 'number' && ` 5日${s5d >= 0 ? '+' : ''}${s5d.toFixed(1)}%`}
          </span></span></>;
        })()}
        {(qe.market_regime ?? qe.marketRegime) && (() => {
          const regimeMap: Record<string, { label: string; color: string }> = {
            bull: { label: '牛市/强势', color: 'text-success' },
            bear: { label: '熊市/弱势', color: 'text-danger' },
            sideways: { label: '震荡市', color: 'text-warning' },
            recovery: { label: '修复中', color: 'text-cyan-400' },
          };
          const r = regimeMap[qe.market_regime ?? qe.marketRegime] ?? { label: qe.market_regime ?? qe.marketRegime, color: 'text-white/50' };
          return <><span className="text-white/20">|</span><span>大盘:<span className={r.color}>{r.label}</span></span></>;
        })()}
      </div>

      {expanded && (
        <div className="space-y-4">
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

          {/* ===== P0/P1 新增：周线趋势 + 经典形态 + 黄金分割 + 量价结构 ===== */}
          {/* 周线趋势 */}
          {(qe.weekly_trend) && (
            <div>
              <h4 className="text-[11px] font-medium text-white/40 mb-2">周线大背景</h4>
              <div className="bg-white/[0.03] rounded-lg p-3 border border-white/[0.04]">
                <div className="flex items-center justify-between mb-1.5">
                  <span className={`text-[13px] font-bold ${
                    qe.weekly_trend === '多头' ? 'text-success' :
                    qe.weekly_trend === '空头' ? 'text-danger' : 'text-warning'
                  }`}>
                    周线{qe.weekly_trend}
                    {(qe.weekly_trend_adj ?? 0) !== 0 && (
                      <span className={`ml-2 text-[11px] font-mono ${(qe.weekly_trend_adj ?? 0) > 0 ? 'text-success/70' : 'text-danger/70'}`}>
                        {(qe.weekly_trend_adj ?? 0) > 0 ? `+${qe.weekly_trend_adj}` : qe.weekly_trend_adj}分
                      </span>
                    )}
                  </span>
                  {qe.weekly_rsi != null && (
                    <span className="text-[10px] text-white/30 font-mono">周RSI {(qe.weekly_rsi as number).toFixed(0)}</span>
                  )}
                </div>
                {qe.weekly_trend_note && (
                  <div className="text-[10px] text-white/40 leading-relaxed">{qe.weekly_trend_note}</div>
                )}
                {(qe.weekly_ma5 || qe.weekly_ma10 || qe.weekly_ma20) && (
                  <div className="text-[10px] text-white/25 mt-1 font-mono">
                    周MA5={qe.weekly_ma5?.toFixed(2) ?? '--'} MA10={qe.weekly_ma10?.toFixed(2) ?? '--'} MA20={qe.weekly_ma20?.toFixed(2) ?? '--'}
                  </div>
                )}
              </div>
            </div>
          )}

          {/* 经典形态 */}
          {qe.chart_pattern && (
            <div>
              <h4 className="text-[11px] font-medium text-white/40 mb-2">经典形态识别</h4>
              <div className={`rounded-lg p-3 border ${
                qe.chart_pattern_signal === '看多' ? 'bg-success/10 border-success/20' :
                qe.chart_pattern_signal === '看空' ? 'bg-danger/10 border-danger/20' :
                'bg-white/[0.03] border-white/[0.04]'
              }`}>
                <div className="flex items-center gap-2 mb-1">
                  <span className={`text-[13px] font-bold ${
                    qe.chart_pattern_signal === '看多' ? 'text-success' :
                    qe.chart_pattern_signal === '看空' ? 'text-danger' : 'text-white/80'
                  }`}>
                    {qe.chart_pattern}
                  </span>
                  {qe.chart_pattern_signal && (
                    <span className={`text-[10px] px-1.5 py-0.5 rounded font-semibold ${
                      qe.chart_pattern_signal === '看多' ? 'bg-success/20 text-success' : 'bg-danger/20 text-danger'
                    }`}>{qe.chart_pattern_signal}</span>
                  )}
                  {(qe.chart_pattern_adj ?? 0) !== 0 && (
                    <span className={`text-[11px] font-mono ml-auto ${(qe.chart_pattern_adj ?? 0) > 0 ? 'text-success/70' : 'text-danger/70'}`}>
                      {(qe.chart_pattern_adj ?? 0) > 0 ? `+${qe.chart_pattern_adj}` : qe.chart_pattern_adj}分
                    </span>
                  )}
                </div>
                {qe.chart_pattern_note && (
                  <div className="text-[10px] text-white/40 leading-relaxed">{qe.chart_pattern_note}</div>
                )}
              </div>
            </div>
          )}

          {/* 黄金分割回撤位 */}
          {(qe.fib_level_382 || qe.fib_swing_high) && (
            <div>
              <h4 className="text-[11px] font-medium text-white/40 mb-2">黄金分割回撤位</h4>
              <div className="bg-white/[0.03] rounded-lg p-3 border border-white/[0.04]">
                <div className="flex items-center justify-between mb-2">
                  <span className={`text-[12px] font-semibold ${
                    qe.fib_signal?.includes('支撑') ? 'text-success' :
                    qe.fib_signal?.includes('阻力') ? 'text-danger' :
                    qe.fib_signal?.includes('结构破坏') ? 'text-danger' : 'text-white/60'
                  }`}>
                    {qe.fib_current_zone || qe.fib_signal || '区间中部'}
                  </span>
                  {(qe.fib_adj ?? 0) !== 0 && (
                    <span className={`text-[11px] font-mono ${(qe.fib_adj ?? 0) > 0 ? 'text-success/70' : 'text-danger/70'}`}>
                      {(qe.fib_adj ?? 0) > 0 ? `+${qe.fib_adj}` : qe.fib_adj}分
                    </span>
                  )}
                </div>
                <div className="grid grid-cols-3 gap-2 text-center">
                  {[
                    { label: '0.382', val: qe.fib_level_382 },
                    { label: '0.500', val: qe.fib_level_500 },
                    { label: '0.618', val: qe.fib_level_618 },
                  ].map(({ label, val }) => (
                    <div key={label} className="bg-white/[0.02] rounded p-1.5">
                      <div className="text-[9px] text-white/25">{label}</div>
                      <div className="text-[11px] font-mono text-white/70">{(val as number)?.toFixed(2) ?? '--'}</div>
                    </div>
                  ))}
                </div>
                {qe.fib_note && (
                  <div className="text-[10px] text-white/25 mt-1.5 font-mono truncate">{qe.fib_note}</div>
                )}
              </div>
            </div>
          )}

          {/* 量价结构 */}
          {qe.vol_price_structure && (
            <div>
              <h4 className="text-[11px] font-medium text-white/40 mb-2">量价结构</h4>
              <div className={`rounded-lg p-3 border ${
                ['放量突破', '缩量回踩'].includes(qe.vol_price_structure as string) ? 'bg-success/10 border-success/20' :
                ['放量下跌', '突破失败', '缩量反弹'].includes(qe.vol_price_structure as string) ? 'bg-danger/10 border-danger/20' :
                'bg-white/[0.03] border-white/[0.04]'
              }`}>
                <div className="flex items-center justify-between mb-1">
                  <span className={`text-[13px] font-bold ${
                    ['放量突破', '缩量回踩'].includes(qe.vol_price_structure as string) ? 'text-success' :
                    ['放量下跌', '突破失败', '缩量反弹'].includes(qe.vol_price_structure as string) ? 'text-danger' : 'text-white/70'
                  }`}>
                    {qe.vol_price_structure}
                  </span>
                  {(qe.vol_price_structure_adj ?? 0) !== 0 && (
                    <span className={`text-[11px] font-mono ${(qe.vol_price_structure_adj ?? 0) > 0 ? 'text-success/70' : 'text-danger/70'}`}>
                      {(qe.vol_price_structure_adj ?? 0) > 0 ? `+${qe.vol_price_structure_adj}` : qe.vol_price_structure_adj}分
                    </span>
                  )}
                </div>
                {qe.vol_price_structure_note && (
                  <div className="text-[10px] text-white/40 font-mono leading-relaxed">{qe.vol_price_structure_note}</div>
                )}
              </div>
            </div>
          )}

          {/* 天量/地量异常检测 */}
          {qe.vol_anomaly && (
            <div>
              <h4 className="text-[11px] font-medium text-white/40 mb-2">量能异常检测</h4>
              <div className={`rounded-lg p-3 border ${
                qe.vol_anomaly === '天量' && (qe.vol_anomaly_adj ?? 0) > 0 ? 'bg-success/10 border-success/20' :
                qe.vol_anomaly === '天量' && (qe.vol_anomaly_adj ?? 0) < 0 ? 'bg-danger/10 border-danger/20' :
                ['地量', '次地量'].includes(qe.vol_anomaly as string) && (qe.vol_anomaly_adj ?? 0) > 0 ? 'bg-success/10 border-success/20' :
                ['地量', '次地量'].includes(qe.vol_anomaly as string) && (qe.vol_anomaly_adj ?? 0) < 0 ? 'bg-warning/10 border-warning/20' :
                'bg-white/[0.03] border-white/[0.04]'
              }`}>
                <div className="flex items-center justify-between mb-1">
                  <span className={`text-[13px] font-bold ${
                    (qe.vol_anomaly_adj ?? 0) > 0 ? 'text-success' :
                    (qe.vol_anomaly_adj ?? 0) < 0 ? 'text-danger' : 'text-warning'
                  }`}>
                    {qe.vol_anomaly}
                    {qe.vol_percentile_60d != null && (qe.vol_percentile_60d as number) >= 0 && (
                      <span className="ml-2 text-[10px] font-mono text-white/30">
                        近60日{(qe.vol_percentile_60d as number).toFixed(0)}%分位
                      </span>
                    )}
                  </span>
                  {(qe.vol_anomaly_adj ?? 0) !== 0 && (
                    <span className={`text-[11px] font-mono ${(qe.vol_anomaly_adj ?? 0) > 0 ? 'text-success/70' : 'text-danger/70'}`}>
                      {(qe.vol_anomaly_adj ?? 0) > 0 ? `+${qe.vol_anomaly_adj}` : qe.vol_anomaly_adj}分
                    </span>
                  )}
                </div>
                {qe.vol_anomaly_note && (
                  <div className="text-[10px] text-white/40 font-mono leading-relaxed">{qe.vol_anomaly_note}</div>
                )}
              </div>
            </div>
          )}

          {/* P5-D: 黄金分割回撤位 */}
          {(qe.fib_signal && qe.fib_signal !== '中性') && (
            <div>
              <h4 className="text-[11px] font-medium text-white/40 mb-2">黄金分割回撤位（P5-D）</h4>
              <div className="rounded-lg p-3 border bg-white/[0.03] border-white/[0.06] space-y-2">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className={`text-[12px] font-bold px-2 py-0.5 rounded ${
                    (qe.fib_signal as string).includes('支撑') ? 'bg-success/15 text-success' :
                    (qe.fib_signal as string).includes('阻力') || (qe.fib_signal as string).includes('结构破坏') ? 'bg-danger/15 text-danger' :
                    'bg-white/10 text-white/50'
                  }`}>{qe.fib_current_zone || qe.fib_signal}</span>
                  {qe.fib_validity && (
                    <span className={`text-[10px] px-1.5 py-0.5 rounded font-mono ${
                      (qe.fib_validity as string).includes('高') ? 'bg-success/10 text-success/70' :
                      (qe.fib_validity as string).includes('中') ? 'bg-warning/10 text-warning/70' :
                      'bg-white/[0.05] text-white/35'
                    }`}>{qe.fib_validity}（{qe.fib_test_count}次测试）</span>
                  )}
                  {(qe.fib_window as number) > 0 && (
                    <span className="text-[10px] text-white/30 font-mono">{qe.fib_window}日窗口</span>
                  )}
                </div>
                <div className="grid grid-cols-3 gap-1.5 text-center">
                  {(qe.fib_level_382 as number) > 0 && (
                    <div className="p-1.5 rounded bg-white/[0.04]">
                      <div className="text-[12px] font-mono text-white/60">{(qe.fib_level_382 as number).toFixed(2)}</div>
                      <div className="text-[9px] text-white/30">0.382</div>
                    </div>
                  )}
                  {(qe.fib_level_500 as number) > 0 && (
                    <div className="p-1.5 rounded bg-white/[0.04]">
                      <div className="text-[12px] font-mono text-white/60">{(qe.fib_level_500 as number).toFixed(2)}</div>
                      <div className="text-[9px] text-white/30">0.500</div>
                    </div>
                  )}
                  {(qe.fib_level_618 as number) > 0 && (
                    <div className="p-1.5 rounded bg-white/[0.04]">
                      <div className="text-[12px] font-mono text-white/60">{(qe.fib_level_618 as number).toFixed(2)}</div>
                      <div className="text-[9px] text-white/30">0.618</div>
                    </div>
                  )}
                </div>
              </div>
            </div>
          )}

          {/* P3: 行情预判 */}
          {(qe.forecast_scenario || qe.resonance_level) && (
            <div>
              <h4 className="text-[11px] font-medium text-white/40 mb-2">行情预判（1-5日）</h4>
              <div className="rounded-lg p-3 border bg-white/[0.03] border-white/[0.06] space-y-2">
                {/* 共振级别 + 操作意图 */}
                {qe.resonance_level && (
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className={`text-[12px] font-bold px-2 py-0.5 rounded ${
                      (qe.resonance_level as string).includes('做多') ? 'bg-success/15 text-success' :
                      (qe.resonance_level as string).includes('做空') ? 'bg-danger/15 text-danger' :
                      (qe.resonance_level as string).includes('分歧') ? 'bg-warning/15 text-warning' :
                      'bg-white/10 text-white/50'
                    }`}>{qe.resonance_level}</span>
                    {qe.resonance_intent && (
                      <span className="text-[11px] text-white/50 font-mono">意图：{qe.resonance_intent}</span>
                    )}
                    {(qe.resonance_score_adj ?? 0) !== 0 && (
                      <span className={`text-[10px] font-mono ${(qe.resonance_score_adj as number) > 0 ? 'text-success/60' : 'text-danger/60'}`}>
                        {(qe.resonance_score_adj as number) > 0 ? `+${qe.resonance_score_adj}` : qe.resonance_score_adj}分
                      </span>
                    )}
                  </div>
                )}
                {/* 行为链标签 */}
                {(qe.seq_behaviors as string[])?.length > 0 && (
                  <div className="flex flex-wrap gap-1">
                    {(qe.seq_behaviors as string[]).map((b: string, i: number) => (
                      <span key={i} className="text-[10px] px-1.5 py-0.5 rounded bg-white/[0.06] text-white/50 font-mono">{b}</span>
                    ))}
                  </div>
                )}
                {/* 主情景 + 概率条 */}
                {qe.forecast_scenario && (
                  <div>
                    <div className="flex items-center justify-between mb-1">
                      <span className="text-[11px] text-white/60 font-medium">主情景：{qe.forecast_scenario}</span>
                    </div>
                    <div className="flex gap-0.5 h-4 rounded overflow-hidden">
                      {(qe.forecast_prob_up as number) > 0 && (
                        <div className="bg-success/60 flex items-center justify-center text-[9px] text-white/80 font-mono"
                             style={{width: `${qe.forecast_prob_up}%`}}>
                          {(qe.forecast_prob_up as number) >= 20 ? `涨${qe.forecast_prob_up}%` : ''}
                        </div>
                      )}
                      {(qe.forecast_prob_sideways as number) > 0 && (
                        <div className="bg-white/20 flex items-center justify-center text-[9px] text-white/60 font-mono"
                             style={{width: `${qe.forecast_prob_sideways}%`}}>
                          {(qe.forecast_prob_sideways as number) >= 20 ? `震${qe.forecast_prob_sideways}%` : ''}
                        </div>
                      )}
                      {(qe.forecast_prob_down as number) > 0 && (
                        <div className="bg-danger/60 flex items-center justify-center text-[9px] text-white/80 font-mono"
                             style={{width: `${qe.forecast_prob_down}%`}}>
                          {(qe.forecast_prob_down as number) >= 20 ? `跌${qe.forecast_prob_down}%` : ''}
                        </div>
                      )}
                    </div>
                  </div>
                )}
                {/* 触发条件 */}
                {qe.forecast_trigger && (
                  <div className="text-[10px] text-white/35 font-mono leading-relaxed border-t border-white/[0.05] pt-1.5">
                    触发：{qe.forecast_trigger}
                  </div>
                )}
                {/* 共振明细 */}
                {qe.resonance_detail && (
                  <div className="text-[10px] text-white/30 font-mono leading-relaxed">
                    {qe.resonance_detail}
                  </div>
                )}
              </div>
            </div>
          )}

          {/* P4: 主力资金追踪 */}
          {(qe.capital_flow_trend || (typeof qe.capital_flow_days === 'number' && qe.capital_flow_days !== 0) || (typeof qe.capital_flow_5d_total === 'number' && qe.capital_flow_5d_total !== 0)) && (
            <div>
              <h4 className="text-[11px] font-medium text-white/40 mb-2">主力资金追踪</h4>
              <div className="rounded-lg p-3 border bg-white/[0.03] border-white/[0.06] space-y-2">
                {/* 趋势 + 强度 + 加速 */}
                <div className="flex items-center gap-2 flex-wrap">
                  {qe.capital_flow_trend && (
                    <span className={`text-[12px] font-bold px-2 py-0.5 rounded ${
                      (qe.capital_flow_trend as string).includes('流入') ? 'bg-success/15 text-success' :
                      (qe.capital_flow_trend as string).includes('流出') ? 'bg-danger/15 text-danger' :
                      'bg-white/10 text-white/50'
                    }`}>{qe.capital_flow_trend}</span>
                  )}
                  {qe.capital_flow_intensity && (
                    <span className="text-[11px] text-white/50 font-mono">{qe.capital_flow_intensity}</span>
                  )}
                  {qe.capital_flow_acceleration && (
                    <span className={`text-[11px] font-mono px-1.5 py-0.5 rounded ${
                      (qe.capital_flow_acceleration as string).includes('流入') ? 'text-success/70 bg-success/10' :
                      (qe.capital_flow_acceleration as string).includes('流出') ? 'text-danger/70 bg-danger/10' :
                      'text-white/40 bg-white/[0.05]'
                    }`}>{qe.capital_flow_acceleration}</span>
                  )}
                </div>
                {/* 连续天数 + 近5日累计 */}
                <div className="grid grid-cols-2 gap-2">
                  {typeof qe.capital_flow_days === 'number' && qe.capital_flow_days !== 0 && (
                    <div className="text-center p-2 rounded bg-white/[0.04]">
                      <div className={`text-[16px] font-bold font-mono ${
                        (qe.capital_flow_days as number) > 0 ? 'text-success' : 'text-danger'
                      }`}>
                        {(qe.capital_flow_days as number) > 0 ? '+' : ''}{qe.capital_flow_days}天
                      </div>
                      <div className="text-[9px] text-white/30 mt-0.5">连续{(qe.capital_flow_days as number) > 0 ? '净流入' : '净流出'}</div>
                    </div>
                  )}
                  {typeof qe.capital_flow_5d_total === 'number' && qe.capital_flow_5d_total !== 0 && (
                    <div className="text-center p-2 rounded bg-white/[0.04]">
                      <div className={`text-[14px] font-bold font-mono ${
                        (qe.capital_flow_5d_total as number) > 0 ? 'text-success' : 'text-danger'
                      }`}>
                        {(qe.capital_flow_5d_total as number) > 0 ? '+' : ''}
                        {Math.abs(qe.capital_flow_5d_total as number) >= 10000
                          ? `${((qe.capital_flow_5d_total as number)/10000).toFixed(1)}亿`
                          : `${(qe.capital_flow_5d_total as number).toFixed(0)}万`}
                      </div>
                      <div className="text-[9px] text-white/30 mt-0.5">近5日累计</div>
                    </div>
                  )}
                </div>
                {/* 聪明钱信号 */}
                {qe.capital_smart_money && (
                  <div className={`text-[11px] font-mono px-2 py-1 rounded ${
                    (qe.capital_smart_money as string).includes('买入') ? 'bg-success/10 text-success/80' : 'bg-danger/10 text-danger/80'
                  }`}>
                    🔍 {qe.capital_smart_money}
                  </div>
                )}
              </div>
            </div>
          )}

          {/* P5-B: VWAP 机构成本线 */}
          {qe.vwap_trend && (
            <div>
              <h4 className="text-[11px] font-medium text-white/40 mb-2">机构成本线（VWAP）</h4>
              <div className="rounded-lg p-3 border bg-white/[0.03] border-white/[0.06] space-y-2">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className={`text-[12px] font-bold px-2 py-0.5 rounded ${
                    (qe.vwap_trend as string).includes('上移') ? 'bg-success/15 text-success' :
                    (qe.vwap_trend as string).includes('下移') ? 'bg-danger/15 text-danger' :
                    'bg-white/10 text-white/50'
                  }`}>{qe.vwap_trend}</span>
                  {qe.vwap_position && (
                    <span className={`text-[11px] font-mono ${
                      (qe.vwap_position as string).includes('上方') ? 'text-success/70' : 'text-danger/70'
                    }`}>{qe.vwap_position}</span>
                  )}
                </div>
                {((qe.vwap10 as number) > 0 || (qe.vwap20 as number) > 0) && (
                  <div className="grid grid-cols-2 gap-2">
                    {(qe.vwap10 as number) > 0 && (
                      <div className="text-center p-1.5 rounded bg-white/[0.04]">
                        <div className="text-[13px] font-mono text-white/70">{(qe.vwap10 as number).toFixed(2)}</div>
                        <div className="text-[9px] text-white/30">10日VWAP</div>
                      </div>
                    )}
                    {(qe.vwap20 as number) > 0 && (
                      <div className="text-center p-1.5 rounded bg-white/[0.04]">
                        <div className="text-[13px] font-mono text-white/70">{(qe.vwap20 as number).toFixed(2)}</div>
                        <div className="text-[9px] text-white/30">20日VWAP</div>
                      </div>
                    )}
                  </div>
                )}
              </div>
            </div>
          )}

          {/* P5-C: 龙虎榜情绪 */}
          {(qe.lhb_signal || (qe.lhb_times as number) > 0) && (
            <div>
              <h4 className="text-[11px] font-medium text-white/40 mb-2">龙虎榜情绪（近一月）</h4>
              <div className="rounded-lg p-3 border bg-white/[0.03] border-white/[0.06] space-y-2">
                <div className="flex items-center gap-2 flex-wrap">
                  {qe.lhb_signal && (
                    <span className={`text-[12px] font-bold px-2 py-0.5 rounded ${
                      (qe.lhb_signal as string).includes('买入') ? 'bg-success/15 text-success' :
                      (qe.lhb_signal as string).includes('卖出') ? 'bg-danger/15 text-danger' :
                      'bg-warning/15 text-warning'
                    }`}>{qe.lhb_signal}</span>
                  )}
                  {(qe.lhb_times as number) > 0 && (
                    <span className="text-[11px] text-white/40 font-mono">上榜{qe.lhb_times}次</span>
                  )}
                </div>
                {((qe.lhb_institution_net as number) !== 0) && (
                  <div className="text-center p-2 rounded bg-white/[0.04]">
                    <div className={`text-[14px] font-bold font-mono ${
                      (qe.lhb_institution_net as number) > 0 ? 'text-success' : 'text-danger'
                    }`}>
                      {(qe.lhb_institution_net as number) > 0 ? '+' : ''}
                      {Math.abs(qe.lhb_institution_net as number) >= 1e8
                        ? `${((qe.lhb_institution_net as number)/1e8).toFixed(2)}亿`
                        : `${((qe.lhb_institution_net as number)/1e4).toFixed(0)}万`}
                    </div>
                    <div className="text-[9px] text-white/30 mt-0.5">机构净买额</div>
                  </div>
                )}
              </div>
            </div>
          )}

          {/* P5-C补充: 大宗交易折溢价 + 股东人数 */}
          {(qe.dzjy_signal || qe.holder_signal) && (
            <div>
              <h4 className="text-[11px] font-medium text-white/40 mb-2">微观结构（大宗/股东）</h4>
              <div className="rounded-lg p-3 border bg-white/[0.03] border-white/[0.06] space-y-2">
                {qe.dzjy_signal && (
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className={`text-[12px] font-bold px-2 py-0.5 rounded ${
                      (qe.dzjy_signal as string).includes('溢价') ? 'bg-success/15 text-success' :
                      'bg-danger/15 text-danger'
                    }`}>{qe.dzjy_signal}</span>
                    {(qe.dzjy_times as number) > 0 && (
                      <span className="text-[10px] text-white/40 font-mono">
                        近30日{qe.dzjy_times}笔
                        {(qe.dzjy_avg_premium as number) !== 0 && (
                          ` · 均折溢率${((qe.dzjy_avg_premium as number)*100).toFixed(2)}%`
                        )}
                      </span>
                    )}
                  </div>
                )}
                {qe.holder_signal && (
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className={`text-[12px] font-bold px-2 py-0.5 rounded ${
                      (qe.holder_signal as string).includes('集中') ? 'bg-success/15 text-success' :
                      'bg-danger/15 text-danger'
                    }`}>{qe.holder_signal}</span>
                    {(qe.holder_change_pct as number) !== 0 && (
                      <span className={`text-[11px] font-mono ${
                        (qe.holder_change_pct as number) < 0 ? 'text-success/70' : 'text-danger/70'
                      }`}>
                        {(qe.holder_change_pct as number) > 0 ? '+' : ''}{(qe.holder_change_pct as number).toFixed(2)}%
                      </span>
                    )}
                  </div>
                )}
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
    </div>
  );
};
