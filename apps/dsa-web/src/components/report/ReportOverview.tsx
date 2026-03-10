import type React from 'react';
import { useState, useEffect, useRef, useCallback } from 'react';
import { mapAdviceDisplay } from '../../types/analysis';
import type { ReportMeta, ReportSummary as ReportSummaryType } from '../../types/analysis';
import apiClient from '../../api';
import { scoreTrendApi } from '../../api/scoreTrend';
import type { ScoreTrend, TimeframeWinrates } from '../../api/scoreTrend';

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
  resonanceLevel?: string;
  capitalConflictWarning?: string;
  analysisScene?: string;
}

/**
 * 报告概览区组件 - 终端风格
 */
const SKILL_LABEL: Record<string, string> = {
  policy_tailwind: '政策顺风',
  northbound_smart: '北向聪明钱',
  ashare_growth_value: 'A股成长价值',
  default: '通用',
  druckenmiller: 'Druckenmiller',
  lynch: 'Lynch',
  soros: 'Soros',
};

const SKILL_DESC: Record<string, string> = {
  policy_tailwind: 'A股政策催化框架',
  northbound_smart: '北向外资方向框架',
  ashare_growth_value: 'A股成长价值框架',
  default: '综合框架',
  druckenmiller: '宏观流动性框架',
  soros: '反身性情绪框架',
  lynch: '成长股侦察框架',
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
  scoreMomentumAdj: _scoreMomentumAdj = 0,
  onRefresh,
  isRefreshing = false,
  onPositionChange,
  actionNow,
  executionDifficulty,
  executionNote,
  behavioralWarning,
  skillUsed,
  resonanceLevel,
  capitalConflictWarning,
  analysisScene,
}) => {

  const SCENE_CONFIG: Record<string, { label: string; color: string; icon: string }> = {
    profit_take: { label: '止盈模式', color: 'bg-yellow-500/15 text-yellow-300 border-yellow-500/30', icon: '💰' },
    crisis:      { label: '危机应对', color: 'bg-red-500/15 text-red-300 border-red-500/30', icon: '🚨' },
    holding:     { label: '持仓管理', color: 'bg-blue-500/10 text-blue-300/80 border-blue-500/20', icon: '📊' },
    entry:       { label: '入场侦察', color: 'bg-emerald-500/10 text-emerald-300/80 border-emerald-500/20', icon: '🎯' },
    post_mortem: { label: '复盘总结', color: 'bg-purple-500/10 text-purple-300/80 border-purple-500/20', icon: '🔍' },
  };
  // 内联持仓编辑状态
  const [editingPosition, setEditingPosition] = useState(false);
  const [editShares, setEditShares] = useState('');
  const [editCost, setEditCost] = useState('');
  const [detailExpanded, setDetailExpanded] = useState(false);
  const [sceneExpanded, setSceneExpanded] = useState(false);
  // 盘中自动刷新价格
  const [livePrice, setLivePrice] = useState<number | undefined>(meta.currentPrice ?? undefined);
  const [liveChangePct, setLiveChangePct] = useState<number | undefined>(meta.changePct ?? undefined);
  const [lastUpdate, setLastUpdate] = useState<string>('');
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const [scoreTrend, setScoreTrend] = useState<ScoreTrend | null>(null);
  const [timeframeWr, setTimeframeWr] = useState<TimeframeWinrates | null>(null);
  const [prevSkill, setPrevSkill] = useState<string | null>(null);

  useEffect(() => {
    setLivePrice(meta.currentPrice ?? undefined);
    setLiveChangePct(meta.changePct ?? undefined);
    setLastUpdate('');
    setScoreTrend(null);
    setTimeframeWr(null);
    setPrevSkill(null);
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

  const fetchTimeframeWr = useCallback(async () => {
    if (!meta.stockCode || !summary.sentimentScore) return;
    try {
      const res = await scoreTrendApi.getTimeframeWinrates(
        meta.stockCode,
        summary.sentimentScore,
      );
      if (res?.n > 0) setTimeframeWr(res);
    } catch {
      // 静默失败
    }
  }, [meta.stockCode, summary.sentimentScore]);

  const fetchLastSkill = useCallback(async () => {
    if (!meta.stockCode || !skillUsed) return;
    try {
      const res = await scoreTrendApi.getLastSkill(meta.stockCode);
      if (res?.prev_skill && res.prev_skill !== skillUsed) {
        setPrevSkill(res.prev_skill);
      }
    } catch {
      // 静默失败
    }
  }, [meta.stockCode, skillUsed]);

  useEffect(() => {
    fetchScoreTrend();
  }, [fetchScoreTrend]);

  useEffect(() => {
    fetchTimeframeWr();
  }, [fetchTimeframeWr]);

  useEffect(() => {
    fetchLastSkill();
  }, [fetchLastSkill]);

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
      {/* 第一行：股票名 + 价格 + 评分（紧凑 header） */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-[14px] font-bold text-white">{meta.stockName || meta.stockCode}</span>
          <span className="text-[11px] text-white/25 font-mono">{meta.stockCode}</span>
          {displayPrice != null && (
            <span className={`text-[14px] font-bold font-mono ${getPriceChangeColor(displayChangePct)}`}>
              {displayPrice.toFixed(2)}
              <span className="text-[11px] ml-1">{formatChangePct(displayChangePct)}</span>
            </span>
          )}
          {lastUpdate && <span className="text-[10px] text-white/20 font-mono">{lastUpdate}</span>}
          {/* 场景模式 badge（紧跟股票名）*/}
          {analysisScene && SCENE_CONFIG[analysisScene] && (
            <span className={`text-[10px] px-2 py-0.5 rounded border font-medium ${SCENE_CONFIG[analysisScene].color}`}>
              {SCENE_CONFIG[analysisScene].icon} {SCENE_CONFIG[analysisScene].label}
            </span>
          )}
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
              <svg className={`w-4 h-4 ${isRefreshing ? 'animate-spin' : ''}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
              </svg>
            </button>
          )}
          {/* 操作建议 badge（替代评分，散户只关心做什么） */}
          <div className="flex items-center gap-1.5">
            {summary.operationAdvice && (() => {
              const adv = summary.operationAdvice;
              const displayAdv = mapAdviceDisplay(adv);
              const isBuy = adv.includes('买入') || adv.includes('吸纳');
              const isSell = adv.includes('卖出') || adv.includes('减仓');
              const colorClass = isBuy
                ? 'bg-emerald-500/20 text-emerald-300 border-emerald-500/35'
                : isSell
                  ? 'bg-red-500/15 text-red-300 border-red-500/30'
                  : 'bg-white/[0.07] text-white/50 border-white/10';
              return (
                <span className={`text-[11px] px-2 py-0.5 rounded font-mono font-semibold border ${colorClass}`}>
                  {displayAdv}
                </span>
              );
            })()}
            {/* 共振信号（重要信号保留） */}
            {resonanceLevel && (
              resonanceLevel.includes('中度共振做多') || resonanceLevel.includes('强共振做多')
                ? <span className="text-[10px] px-1.5 py-0.5 rounded font-mono font-semibold bg-emerald-500/20 text-emerald-300 border border-emerald-500/30">🔥共振</span>
                : resonanceLevel.includes('强共振做空')
                  ? <span className="text-[10px] px-1.5 py-0.5 rounded font-mono font-semibold bg-red-500/20 text-red-300 border border-red-500/30">强空</span>
                  : resonanceLevel.includes('分歧')
                    ? <span className="text-[10px] px-1.5 py-0.5 rounded font-mono bg-amber-500/15 text-amber-400 border border-amber-500/25">⚡分歧</span>
                    : null
            )}
          </div>
        </div>
      </div>

      {/* ⚠️ 追涨风险警告（当日涨幅>5%且有买入类建议时醒目提示） */}
      {(() => {
        const todayPctChg = displayChangePct;
        const adv = summary.operationAdvice ?? '';
        const isBuyAdvice = adv.includes('买入') || adv.includes('吸纳') || adv.includes('做多') || adv.includes('加仓');
        if (todayPctChg != null && todayPctChg > 5 && isBuyAdvice) {
          return (
            <div className="rounded-lg px-3 py-2.5 border border-red-500/30 bg-red-500/[0.08] flex items-start gap-2">
              <span className="text-red-400 text-sm flex-shrink-0 leading-5">⚠️</span>
              <p className="text-[12px] text-red-300/90 leading-relaxed">
                该股今日已涨 <span className="font-mono font-semibold text-red-300">{todayPctChg.toFixed(1)}%</span>，追高买入风险较大，历史追涨胜率偏低。建议等待回调再考虑入场。
              </p>
            </div>
          );
        }
        return null;
      })()}

      {/* ★ 核心决策卡（立即行动 + 一句话结论） */}
      {(actionNow || oneSentence) && (
        <div className={`rounded-lg p-3 border ${
          actionNow
            ? 'border-cyan-500/30 bg-cyan-500/[0.06]'
            : 'border-white/[0.08] bg-white/[0.03]'
        }`}>
          {actionNow && (
            <div className="mb-2">
              <div className="flex items-center gap-2 flex-wrap mb-1.5">
                <span className="text-[10px] font-bold px-2 py-0.5 rounded bg-cyan-500/20 text-cyan-400 font-mono tracking-wider">今日操作</span>
                {skillUsed && (
                  <span className="text-[10px] px-1.5 py-0.5 rounded border border-violet-500/25 bg-violet-500/[0.08] text-violet-300/80 font-mono">
                    {SKILL_LABEL[skillUsed] ?? skillUsed} · {SKILL_DESC[skillUsed] ?? 'AI研判'}
                    {prevSkill && <span className="ml-1 text-amber-400/70">⚡切换自 {SKILL_LABEL[prevSkill] ?? prevSkill}</span>}
                  </span>
                )}
                {executionDifficulty && (
                  <span className={`text-[10px] px-1.5 py-0.5 rounded border font-mono ml-auto ${DIFFICULTY_COLOR[executionDifficulty] ?? 'text-white/40 bg-white/5 border-white/10'}`}>
                    难度{executionDifficulty}
                  </span>
                )}
              </div>
              <p className="text-[14px] text-white font-semibold leading-snug">{actionNow}</p>
              {executionNote && <p className="text-[11px] text-white/45 mt-1 leading-relaxed">{executionNote}</p>}
            </div>
          )}
          {oneSentence && (
            <p className={`text-[13px] leading-relaxed ${
              actionNow ? 'text-white/55 border-t border-white/[0.07] pt-2 mt-1' : 'text-white/80'
            }`}>{oneSentence}</p>
          )}
        </div>
      )}

      {/* ⚠️ 心理陷阱预警（紧跟决策卡） */}
      {behavioralWarning && (
        <div className="rounded-lg px-3 py-2 border border-amber-500/20 bg-amber-500/5 text-[12px] text-amber-300/90 leading-relaxed">
          ⚠️ {behavioralWarning}
        </div>
      )}
      {/* P3-新: 信号分歧警告（回测数据：分歧状态5日胜率43%，20日39%，低于随机基准） */}
      {resonanceLevel && resonanceLevel.includes('分歧') && (
        <div className="rounded-lg px-3 py-2 border border-amber-500/25 bg-amber-500/[0.06] text-[12px] text-amber-300/85 leading-relaxed">
          ⚡ 当前多空信号存在分歧，历史数据显示此状态5日胜率43%、20日胜率39%，低于基准水平。建议等待信号方向明朗后再操作。
        </div>
      )}
      {/* P3: 资金面与量化信号冲突提示 */}
      {capitalConflictWarning && (
        <div className="rounded-lg px-3 py-2 border border-orange-500/25 bg-orange-500/[0.06] text-[12px] text-orange-300/85 leading-relaxed">
          ⚠️ {capitalConflictWarning}
        </div>
      )}
      {/* P2: 多时间线胜率（只在有操作意义的信号下展示，n>=20才显示） */}
      {timeframeWr && timeframeWr.n >= 20 && summary.sentimentScore != null && summary.sentimentScore >= 75 && (
        <div className="rounded-lg px-3 py-2.5 border border-white/[0.07] bg-white/[0.025]">
          <div className="text-[10px] text-white/25 mb-2 font-mono">
            历史同类信号 <span className="text-white/40">n={timeframeWr.n}</span>
            {timeframeWr.weekly_trend && <span className="ml-1 text-white/20">· {timeframeWr.weekly_trend}</span>}
          </div>
          <div className="flex gap-3">
            {[
              { label: '5日', wr: timeframeWr.wr5d, key: '5d' },
              { label: '10日', wr: timeframeWr.wr10d, key: '10d' },
              { label: '20日', wr: timeframeWr.wr20d, key: '20d' },
            ].map(({ label, wr, key }) => {
              const isBest = timeframeWr.best_horizon === key;
              const isGood = (wr ?? 0) >= 55;
              const isPoor = (wr ?? 0) < 45;
              return (
                <div key={key} className={`flex-1 text-center rounded p-1.5 ${isBest ? 'bg-emerald-500/10 border border-emerald-500/20' : 'bg-white/[0.03]'}`}>
                  <div className="text-[9px] text-white/30 mb-0.5">{label}胜率</div>
                  <div className={`text-[13px] font-bold font-mono ${isBest ? 'text-emerald-400' : isGood ? 'text-white/70' : isPoor ? 'text-red-400/70' : 'text-white/50'}`}>
                    {wr != null ? `${wr}%` : '-'}
                  </div>
                  {isBest && <div className="text-[8px] text-emerald-400/60 mt-0.5">最优</div>}
                </div>
              );
            })}
          </div>
        </div>
      )}

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

      {/* 操作建议摘要（紧凑单行） */}
      <div className="flex items-center gap-3 text-[12px] text-white/50 flex-wrap">
        {summary.operationAdvice && (
          <span>建议：<span className="text-white/75">{mapAdviceDisplay(summary.operationAdvice)}</span></span>
        )}
        <button
          type="button"
          onClick={() => setDetailExpanded(!detailExpanded)}
          className="ml-auto text-[10px] text-white/25 hover:text-white/50 transition-colors"
        >
          {detailExpanded ? '收起详情 ▲' : '更多详情 ▼'}
        </button>
      </div>

      {/* 详情折叠区（评分趋势 + 趋势预测 + 场景识别 + 持仓建议） */}
      {detailExpanded && (
        <div className="space-y-3 pt-1">

          {/* 评分历史折线图 */}
          {scoreTrend && scoreTrend.scores.length >= 3 && (() => {
            const scores = scoreTrend.scores;
            const W = 120, H = 28, PAD = 2;
            const vals = scores.map(s => s.score);
            const minV = Math.max(0, Math.min(...vals) - 5);
            const maxV = Math.min(100, Math.max(...vals) + 5);
            const range = maxV - minV || 1;
            const pts = vals.map((v, i) => {
              const x = PAD + (i / (vals.length - 1)) * (W - PAD * 2);
              const y = H - PAD - ((v - minV) / range) * (H - PAD * 2);
              return `${x.toFixed(1)},${y.toFixed(1)}`;
            }).join(' ');
            const lastScore = vals[vals.length - 1];
            const firstScore = vals[0];
            const improving = lastScore > firstScore;
            const lineColor = improving ? '#34d399' : lastScore < firstScore ? '#f87171' : '#94a3b8';
            const dir = scoreTrend.trend_direction;
            return (
              <div className="flex items-center gap-3">
                <svg width={W} height={H} className="flex-none overflow-visible">
                  <polyline points={pts} fill="none" stroke={lineColor} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" opacity="0.85" />
                  {(() => {
                    const [lx, ly] = pts.split(' ').pop()!.split(',').map(Number);
                    return <circle cx={lx} cy={ly} r="2.5" fill={lineColor} />;
                  })()}
                </svg>
                <div className="flex items-center gap-1.5 text-[10px] font-mono">
                  <span className="text-white/25">{scores[0].date.slice(5)}</span>
                  <span className="text-white/20">→</span>
                  <span className="text-white/25">{scores[scores.length - 1].date.slice(5)}</span>
                  <span className={`ml-1 ${dir === 'improving' ? 'text-emerald-400' : dir === 'declining' ? 'text-red-400' : 'text-white/35'}`}>
                    {dir === 'improving' ? '↗' : dir === 'declining' ? '↘' : '→'}
                    {scoreTrend.avg_score.toFixed(0)}均
                  </span>
                </div>
              </div>
            );
          })()}

          {/* 趋势预测 */}
          {summary.trendPrediction && (
            <div className="text-[12px]">
              <span className="text-white/30 text-[11px]">趋势预测 </span>
              <span className="text-white/70">{summary.trendPrediction}</span>
            </div>
          )}

          {/* 场景识别（可折叠） */}
          {summary.positionAdvice?.tradeAdvice?.scenarioId &&
            summary.positionAdvice.tradeAdvice.scenarioId !== 'none' && (
            <>
              <button
                type="button"
                onClick={() => setSceneExpanded(!sceneExpanded)}
                className="text-[11px] text-white/30 hover:text-white/55 transition-colors text-left"
              >
                {sceneExpanded ? '▲ 收起场景识别' : '▼ 场景识别'}
                {summary.positionAdvice.tradeAdvice.scenarioLabel
                  ? ` · ${summary.positionAdvice.tradeAdvice.scenarioLabel}`
                  : ''}
              </button>
              {sceneExpanded && (() => {
                const ta = summary.positionAdvice!.tradeAdvice!;
                const isPositive = !ta.scenarioId?.startsWith('E');
                const confColor = ta.scenarioConfidence === '高' ? 'text-emerald-400' : ta.scenarioConfidence === '中' ? 'text-amber-400' : 'text-white/40';
                const borderColor = isPositive ? 'border-emerald-500/20 bg-emerald-500/5' : 'border-red-500/20 bg-red-500/5';
                const isIntraday = ta.turnoverPercentileConfidence === '盘中折算估算' || (ta.scenarioLabel?.includes('盘中') ?? false);
                const tpDisplay = ta.turnoverPercentile !== undefined ? `${Math.round(ta.turnoverPercentile * 100)}%分位` : '';
                return (
                  <div className={`rounded-lg p-3 border ${borderColor} space-y-2`}>
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded font-mono ${isPositive ? 'bg-emerald-500/15 text-emerald-400' : 'bg-red-500/15 text-red-400'}`}>
                        场景{ta.scenarioId}
                      </span>
                      <span className="text-[12px] text-white/80 font-medium">{ta.scenarioLabel}</span>
                      <span className={`text-[10px] ml-auto ${confColor}`}>置信度: {ta.scenarioConfidence}</span>
                    </div>
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
                    {(hasPositionInfo ? ta.adviceHolding : ta.adviceEmpty) && (
                      <p className="text-[12px] text-white/70 leading-relaxed">
                        {hasPositionInfo ? ta.adviceHolding : ta.adviceEmpty}
                      </p>
                    )}
                  </div>
                );
              })()}
            </>
          )}

          {/* 持仓建议兜底（无场景时） */}
          {(!summary.positionAdvice?.tradeAdvice?.scenarioId || summary.positionAdvice?.tradeAdvice?.scenarioId === 'none') &&
            (hasPositionInfo ? summary.positionAdvice?.hasPosition : summary.positionAdvice?.noPosition) && (
            <div className="space-y-2">
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
      )}
    </div>
  );
};
