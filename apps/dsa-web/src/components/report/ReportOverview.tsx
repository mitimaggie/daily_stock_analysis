import type React from 'react';
import { useState, useEffect, useRef, useCallback } from 'react';
import type { ReportMeta, ReportSummary as ReportSummaryType } from '../../types/analysis';
import { ScoreGauge } from '../common';
import { formatDateTime } from '../../utils/format';
import apiClient from '../../api';
import { scoreTrendApi } from '../../api/scoreTrend';
import type { ScoreTrend } from '../../api/scoreTrend';

interface ReportOverviewProps {
  meta: ReportMeta;
  summary: ReportSummaryType;
  isHistory?: boolean;
  hasPositionInfo?: boolean;
  oneSentence?: string;
  costPrice?: number;
  positionAmount?: number;
  shares?: number;
  totalCapital?: number;
  scoreMomentumAdj?: number;
  onRefresh?: () => void;
  isRefreshing?: boolean;
  onPositionChange?: (shares: number, costPrice: number) => void;
  actionNow?: string;
  executionDifficulty?: string;
  executionNote?: string;
  behavioralWarning?: string;
  skillUsed?: string;
}

/**
 * 报告概览区组件 - 终端风格
 */
const SKILL_LABEL: Record<string, string> = {
  druckenmiller: 'Druckenmiller',
  lynch: 'Lynch',
  buffett: 'Buffett',
  soros: 'Soros',
  default: '通用',
};

const DIFFICULTY_COLOR: Record<string, string> = {
  低: 'text-emerald-400 bg-emerald-500/10 border-emerald-500/20',
  中: 'text-amber-400 bg-amber-500/10 border-amber-500/20',
  高: 'text-red-400 bg-red-500/10 border-red-500/20',
};

export const ReportOverview: React.FC<ReportOverviewProps> = ({
  meta,
  summary,
  hasPositionInfo = false,
  oneSentence,
  costPrice,
  positionAmount,
  shares,
  totalCapital,
  scoreMomentumAdj = 0,
  onRefresh,
  isRefreshing = false,
  onPositionChange,
  actionNow,
  executionDifficulty,
  executionNote,
  behavioralWarning,
  skillUsed,
}) => {
  // 内联持仓编辑状态
  const [editingPosition, setEditingPosition] = useState(false);
  const [editShares, setEditShares] = useState('');
  const [editCost, setEditCost] = useState('');
  // 盘中自动刷新价格
  const [livePrice, setLivePrice] = useState<number | undefined>(meta.currentPrice ?? undefined);
  const [liveChangePct, setLiveChangePct] = useState<number | undefined>(meta.changePct ?? undefined);
  const [lastUpdate, setLastUpdate] = useState<string>('');
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const [scoreTrend, setScoreTrend] = useState<ScoreTrend | null>(null);

  useEffect(() => {
    setLivePrice(meta.currentPrice ?? undefined);
    setLiveChangePct(meta.changePct ?? undefined);
    setLastUpdate('');
    setScoreTrend(null);
  }, [meta.stockCode, meta.currentPrice, meta.changePct]);

  const fetchScoreTrend = useCallback(async () => {
    if (!meta.stockCode) return;
    try {
      const res = await scoreTrendApi.getTrend(meta.stockCode, 10);
      if (res?.trend) setScoreTrend(res.trend);
    } catch {
      // 静默失败，评分趋势非关键数据
    }
  }, [meta.stockCode]);

  useEffect(() => {
    fetchScoreTrend();
  }, [fetchScoreTrend]);

  useEffect(() => {
    const isTrading = () => {
      const now = new Date();
      const day = now.getDay();
      if (day === 0 || day === 6) return false;
      const h = now.getHours(), m = now.getMinutes();
      const t = h * 60 + m;
      return t >= 9 * 60 + 15 && t <= 15 * 60;
    };

    const fetchQuote = async () => {
      if (!isTrading() || !meta.stockCode) return;
      try {
        const res = await apiClient.get(`/api/v1/stocks/${meta.stockCode}/quote`);
        const d = res.data;
        if (d.current_price) {
          setLivePrice(d.current_price);
          setLiveChangePct(d.change_percent ?? undefined);
          setLastUpdate(new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' }));
        }
      } catch { /* 静默失败 */ }
    };

    if (isTrading() && meta.stockCode) {
      fetchQuote();
      timerRef.current = setInterval(fetchQuote, 30000);
    }
    return () => { if (timerRef.current) clearInterval(timerRef.current); };
  }, [meta.stockCode]);

  const displayPrice = livePrice ?? meta.currentPrice;
  const displayChangePct = liveChangePct ?? meta.changePct;
  // 根据涨跌幅获取颜色
  const getPriceChangeColor = (changePct: number | undefined): string => {
    if (changePct === undefined || changePct === null) return 'text-muted';
    if (changePct > 0) return 'text-[#ff4d4d]'; // 红涨
    if (changePct < 0) return 'text-[#00d46a]'; // 绿跌
    return 'text-muted';
  };

  // 格式化涨跌幅
  const formatChangePct = (changePct: number | undefined): string => {
    if (changePct === undefined || changePct === null) return '--';
    const sign = changePct > 0 ? '+' : '';
    return `${sign}${changePct.toFixed(2)}%`;
  };

  return (
    <div className="rounded-xl bg-[var(--bg-card)] border border-white/[0.06] p-4 space-y-3">
      {/* 第一行：股票名 + 价格 + 评分 */}
      <div className="flex items-center justify-between">
        <div className="flex items-baseline gap-2 flex-wrap">
          <span className="text-[15px] font-bold text-white">{meta.stockName || meta.stockCode}</span>
          {displayPrice != null && (
            <>
              <span className={`text-[15px] font-bold font-mono ${getPriceChangeColor(displayChangePct)}`}>
                {displayPrice.toFixed(2)}
              </span>
              <span className={`text-[12px] font-mono ${getPriceChangeColor(displayChangePct)}`}>
                {formatChangePct(displayChangePct)}
              </span>
            </>
          )}
          <span className="text-[11px] text-white/20">{meta.stockCode} · {formatDateTime(meta.createdAt)}</span>
          {lastUpdate && <span className="text-[10px] text-white/20 font-mono">{lastUpdate}</span>}
        </div>
        <div className="flex items-center gap-2">
          {onRefresh && (
            <button
              type="button"
              onClick={onRefresh}
              disabled={isRefreshing}
              className="p-1.5 rounded-lg hover:bg-white/[0.06] text-white/30 hover:text-white/60 transition-colors disabled:opacity-40"
              title="刷新分析"
            >
              <svg
                className={`w-4 h-4 ${isRefreshing ? 'animate-spin' : ''}`}
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
              </svg>
            </button>
          )}
          <div className="flex items-center gap-1.5">
            <ScoreGauge score={summary.sentimentScore} size="xs" showLabel={false} />
            {meta.scoreChange != null && meta.scoreChange !== 0 && (
              <span className={`text-[11px] font-mono font-semibold ${meta.scoreChange > 0 ? 'text-[#ff4d4d]' : 'text-[#00d46a]'}`}>
                {meta.scoreChange > 0 ? '▲' : '▼'}{Math.abs(meta.scoreChange)}
              </span>
            )}
            {scoreMomentumAdj !== 0 && (
              <span className={`text-[10px] px-1 py-0.5 rounded ${scoreMomentumAdj > 0 ? 'bg-green-500/10 text-green-400' : 'bg-red-500/10 text-red-400'}`}>
                惯性{scoreMomentumAdj > 0 ? '+' : ''}{scoreMomentumAdj}
              </span>
            )}
            {/* 评分趋势信号 */}
            {scoreTrend && (() => {
              const { consecutive_up: up, consecutive_down: dn, inflection, trend_direction: dir } = scoreTrend;
              if (inflection) {
                const isBull = inflection.includes('看多');
                return (
                  <span className={`text-[10px] px-1.5 py-0.5 rounded font-semibold ${isBull ? 'bg-emerald-500/15 text-emerald-400 border border-emerald-500/20' : 'bg-red-500/15 text-red-400 border border-red-500/20'}`}>
                    {isBull ? '↗' : '↘'} {inflection}
                  </span>
                );
              }
              if (up >= 3) {
                return (
                  <span className="text-[10px] px-1.5 py-0.5 rounded bg-emerald-500/10 text-emerald-400 border border-emerald-500/15">
                    连升{up}日
                  </span>
                );
              }
              if (dn >= 3) {
                return (
                  <span className="text-[10px] px-1.5 py-0.5 rounded bg-red-500/10 text-red-400 border border-red-500/15">
                    连降{dn}日
                  </span>
                );
              }
              if (dir === 'improving' && up >= 2) {
                return <span className="text-[10px] text-emerald-400/70 font-mono">↑↑</span>;
              }
              if (dir === 'declining' && dn >= 2) {
                return <span className="text-[10px] text-red-400/70 font-mono">↓↓</span>;
              }
              return null;
            })()}
          </div>
        </div>
      </div>

      {/* 持仓成本 & 浮盈亏（有持仓时显示，支持内联编辑） */}
      {hasPositionInfo && costPrice != null && costPrice > 0 && (() => {
        const price = displayPrice ?? meta.currentPrice;
        const pnlPct = price && price > 0 ? ((price - costPrice) / costPrice * 100) : null;
        const sharesVal = shares ?? (positionAmount && costPrice > 0 ? Math.round(positionAmount / costPrice) : undefined);
        const posVal = sharesVal && sharesVal > 0 && costPrice > 0 ? sharesVal * costPrice : null;
        const pctOfCapital = posVal && totalCapital && totalCapital > 0 ? (posVal / totalCapital * 100).toFixed(1) : null;
        const pnlAmt = price && sharesVal && sharesVal > 0 ? (price - costPrice) * sharesVal : null;
        return editingPosition ? (
          <div className="flex items-center gap-2 flex-wrap">
            <input
              type="number" step="1" value={editShares}
              onChange={e => setEditShares(e.target.value)}
              placeholder="持股（股）"
              className="w-24 bg-white/5 border border-white/15 rounded px-2 py-0.5 text-[12px] text-white font-mono placeholder-white/25 focus:outline-none focus:border-cyan-500/50"
            />
            <input
              type="number" step="0.01" value={editCost}
              onChange={e => setEditCost(e.target.value)}
              placeholder="成本价"
              className="w-24 bg-white/5 border border-white/15 rounded px-2 py-0.5 text-[12px] text-white font-mono placeholder-white/25 focus:outline-none focus:border-cyan-500/50"
            />
            <button
              type="button"
              onClick={() => {
                const s = parseInt(editShares) || 0;
                const c = parseFloat(editCost) || 0;
                if (s > 0 && c > 0 && onPositionChange) onPositionChange(s, c);
                setEditingPosition(false);
              }}
              className="text-[11px] px-2 py-0.5 rounded bg-cyan-500/15 border border-cyan-500/30 text-cyan-400 hover:bg-cyan-500/25 transition"
            >确认 →重新分析</button>
            <button type="button" onClick={() => setEditingPosition(false)} className="text-[11px] text-white/25 hover:text-white/50">取消</button>
          </div>
        ) : (
          <div className="flex items-center gap-3 text-[12px] text-white/50 flex-wrap">
            <span>成本 <span className="font-mono text-white/70">{costPrice.toFixed(2)}</span></span>
            {sharesVal != null && <span className="font-mono text-white/40">{sharesVal}股</span>}
            {posVal && <span className="font-mono text-white/40">{(posVal / 10000).toFixed(2)}万</span>}
            {pctOfCapital && <span className="font-mono text-white/40">仓位{pctOfCapital}%</span>}
            {pnlPct != null && (
              <span className={`font-mono font-semibold ${pnlPct >= 0 ? 'text-[#ff4d4d]' : 'text-[#00d46a]'}`}>
                {pnlPct >= 0 ? '+' : ''}{pnlPct.toFixed(2)}%
              </span>
            )}
            {pnlAmt != null && (
              <span className={`font-mono text-[11px] ${pnlAmt >= 0 ? 'text-[#ff4d4d]/70' : 'text-[#00d46a]/70'}`}>
                {pnlAmt >= 0 ? '+' : ''}{(pnlAmt / 10000).toFixed(2)}万
              </span>
            )}
            {onPositionChange && (
              <button
                type="button"
                onClick={() => { setEditShares(String(sharesVal ?? '')); setEditCost(String(costPrice)); setEditingPosition(true); }}
                className="text-[10px] px-1.5 py-0.5 rounded border border-white/10 text-white/25 hover:text-white/50 hover:border-white/20 transition ml-1"
              >修改</button>
            )}
          </div>
        );
      })()}

      {/* 操作建议 + 趋势预测（紧凑两行） */}
      <div className="grid grid-cols-2 gap-x-4 text-[13px]">
        <div>
          <span className="text-white/30 text-[11px]">操作建议</span>
          <p className="text-white/90 leading-snug mt-0.5">{summary.operationAdvice || '暂无'}</p>
        </div>
        <div>
          <span className="text-white/30 text-[11px]">趋势预测</span>
          <p className="text-white/90 leading-snug mt-0.5">{summary.trendPrediction || '暂无'}</p>
        </div>
      </div>

      {/* 分割线 */}
      <div className="border-t border-white/5" />

      {/* 一句话核心结论 */}
      <p className="text-[13px] text-white/70 leading-relaxed whitespace-pre-wrap text-left">
        {oneSentence || summary.analysisSummary || '暂无分析结论'}
      </p>

      {/* 立即行动卡片（actionNow 有值时显示） */}
      {actionNow && (
        <div className="border-t border-white/5 pt-3">
          <div className="rounded-lg p-3 border border-cyan-500/20 bg-cyan-500/5 space-y-2">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-[10px] font-bold px-1.5 py-0.5 rounded bg-cyan-500/15 text-cyan-400 font-mono">立即行动</span>
              {executionDifficulty && (
                <span className={`text-[10px] px-1.5 py-0.5 rounded border font-mono ${DIFFICULTY_COLOR[executionDifficulty] ?? 'text-white/40 bg-white/5 border-white/10'}`}>
                  操作难度：{executionDifficulty}
                </span>
              )}
              {skillUsed && skillUsed !== 'default' && (
                <span className="text-[10px] px-1.5 py-0.5 rounded border border-violet-500/20 bg-violet-500/5 text-violet-400 font-mono ml-auto">
                  {SKILL_LABEL[skillUsed] ?? skillUsed} 框架
                </span>
              )}
            </div>
            <p className="text-[13px] text-white/90 leading-relaxed font-medium">{actionNow}</p>
            {executionNote && (
              <p className="text-[11px] text-white/50 leading-relaxed">{executionNote}</p>
            )}
          </div>
        </div>
      )}

      {/* 心理陷阱预警（behavioralWarning 有值时显示） */}
      {behavioralWarning && (
        <div className={`rounded-lg px-3 py-2 border border-amber-500/20 bg-amber-500/5 text-[12px] text-amber-300/90 leading-relaxed ${actionNow ? '' : 'border-t border-white/5 mt-2 pt-0'}`}>
          {behavioralWarning}
        </div>
      )}

      {/* 场景识别卡片（有场景时展示） */}
      {summary.positionAdvice?.tradeAdvice?.scenarioId && summary.positionAdvice.tradeAdvice.scenarioId !== 'none' && (() => {
        const ta = summary.positionAdvice!.tradeAdvice!;
        const isPositive = !ta.scenarioId?.startsWith('E');
        const confColor = ta.scenarioConfidence === '高' ? 'text-emerald-400' : ta.scenarioConfidence === '中' ? 'text-amber-400' : 'text-white/40';
        const borderColor = isPositive ? 'border-emerald-500/20 bg-emerald-500/5' : 'border-red-500/20 bg-red-500/5';
        const isIntraday = ta.turnoverPercentileConfidence === '盘中折算估算' || (ta.scenarioLabel?.includes('盘中') ?? false);
        const tpDisplay = ta.turnoverPercentile !== undefined ? `${Math.round(ta.turnoverPercentile * 100)}%分位` : '';
        return (
          <div className={`border-t border-white/5 pt-3`}>
            <div className={`rounded-lg p-3 border ${borderColor} space-y-2`}>
              {/* 场景标题行 */}
              <div className="flex items-center gap-2 flex-wrap">
                <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded font-mono ${isPositive ? 'bg-emerald-500/15 text-emerald-400' : 'bg-red-500/15 text-red-400'}`}>
                  场景{ta.scenarioId}
                </span>
                <span className="text-[12px] text-white/80 font-medium">{ta.scenarioLabel}</span>
                <span className={`text-[10px] ml-auto ${confColor}`}>置信度: {ta.scenarioConfidence}</span>
              </div>
              {/* 换手率分位 + 数据来源标注 */}
              <div className="flex items-center gap-3 flex-wrap">
                {tpDisplay && (
                  <span className="text-[11px] text-white/40">
                    换手率历史分位: <span className="font-mono text-white/60">{tpDisplay}</span>
                  </span>
                )}
                {ta.turnoverPercentileConfidence && (
                  <span className={`text-[10px] px-1.5 py-0.5 rounded border ${isIntraday ? 'border-amber-500/30 text-amber-400/70 bg-amber-500/5' : 'border-emerald-500/20 text-emerald-400/60 bg-emerald-500/5'}`}>
                    {ta.turnoverPercentileConfidence}
                  </span>
                )}
              </div>
              {/* 预期收益 + 胜率 */}
              {(ta.expectedReturn20d || ta.winRate) && (
                <div className="flex gap-4 text-[11px]">
                  {ta.expectedReturn20d && (
                    <span className="text-white/50">20日预期: <span className={`font-mono font-semibold ${isPositive ? 'text-emerald-400' : 'text-red-400'}`}>{ta.expectedReturn20d}</span></span>
                  )}
                  {ta.winRate && (
                    <span className="text-white/50">历史胜率: <span className="font-mono text-white/70">{ta.winRate}</span></span>
                  )}
                </div>
              )}
              {/* 操作建议 */}
              {(hasPositionInfo ? ta.adviceHolding : ta.adviceEmpty) && (
                <p className="text-[12px] text-white/70 leading-relaxed">
                  {hasPositionInfo ? ta.adviceHolding : ta.adviceEmpty}
                </p>
              )}
            </div>
          </div>
        );
      })()}

      {/* 持仓建议：兜底展示（无场景时显示）*/}
      {(!summary.positionAdvice?.tradeAdvice?.scenarioId || summary.positionAdvice?.tradeAdvice?.scenarioId === 'none') &&
        (hasPositionInfo ? summary.positionAdvice?.hasPosition : summary.positionAdvice?.noPosition) && (
        <div className="border-t border-white/5 pt-3 space-y-2">
          {hasPositionInfo && summary.positionAdvice?.hasPosition && (
            <div className="flex gap-2 items-start text-[13px]">
              <span className="text-[10px] text-white/40 bg-white/5 px-1.5 py-0.5 rounded flex-shrink-0">策略</span>
              <p className="text-white/70 leading-relaxed">{summary.positionAdvice.hasPosition}</p>
            </div>
          )}
          {!hasPositionInfo && summary.positionAdvice?.noPosition && (
            <div className="flex gap-2 items-start text-[13px]">
              <span className="text-[10px] text-white/40 bg-white/5 px-1.5 py-0.5 rounded flex-shrink-0">空仓</span>
              <p className="text-white/70 leading-relaxed">{summary.positionAdvice.noPosition}</p>
            </div>
          )}
        </div>
      )}
    </div>
  );
};
