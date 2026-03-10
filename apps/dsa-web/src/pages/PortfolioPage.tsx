import type React from 'react';
import { useState, useEffect, useCallback, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { portfolioApi, type MonitorSignal, type WatchlistItem, type PortfolioLog } from '../api/portfolio';
import { scoreTrendApi } from '../api/scoreTrend';
import PortfolioHeatScan from '../components/portfolio/PortfolioHeatScan';
import { safeFixed, isMarketOpen } from '../utils/format';

const HORIZON_OPTIONS = ['短线(1-3日)', '短线(3-5日)', '中线(1-4周)', '中线(1-3月)', '长线(3月以上)'];

const actionLabel: Record<string, string> = {
  buy: '买入', add: '加仓', reduce: '减仓', stop_exit: '止损出场',
  take_profit: '止盈出场', manual: '手动记录',
};
const actionColor: Record<string, string> = {
  buy: 'text-red-600', add: 'text-red-300', reduce: 'text-emerald-600',
  stop_exit: 'text-amber-400', take_profit: 'text-sky-400', manual: 'text-muted',
};

// ─── 信号颜色映射 ─────────────────────────────
const signalConfig = {
  stop_loss: { color: 'text-red-600', bg: 'bg-red-500/10 border-red-500/30', dot: 'bg-red-600', label: '止损' },
  reduce:    { color: 'text-amber-400', bg: 'bg-amber-500/10 border-amber-500/30', dot: 'bg-amber-400', label: '减仓' },
  add_watch: { color: 'text-emerald-600', bg: 'bg-emerald-500/10 border-emerald-500/30', dot: 'bg-emerald-600', label: '加仓' },
  hold:      { color: 'text-secondary', bg: 'bg-black/[0.03] border-black/[0.08]', dot: 'bg-black/[0.15]', label: '持有' },
  unknown:   { color: 'text-muted', bg: 'bg-black/[0.03] border-black/[0.05]', dot: 'bg-black/[0.1]', label: '获取中' },
};

// ─── 添加持仓表单 ─────────────────────────────
const AddPortfolioForm: React.FC<{ onAdded: () => void }> = ({ onAdded }) => {
  const [code, setCode] = useState('');
  const [name, setName] = useState('');
  const [costPrice, setCostPrice] = useState('');
  const [shares, setShares] = useState('');
  const [entryDate, setEntryDate] = useState('');
  const [notes, setNotes] = useState('');
  const [horizonLabel, setHorizonLabel] = useState('');
  const [horizonSuggestion, setHorizonSuggestion] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const handleCodeBlur = async () => {
    if (!code.trim()) return;
    const suggestion = await portfolioApi.getHorizonSuggestion(code.trim());
    if (suggestion) {
      setHorizonSuggestion(suggestion);
      if (!horizonLabel) setHorizonLabel(suggestion);
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!code || !costPrice) { setError('代码和成本价必填'); return; }
    setLoading(true); setError('');
    try {
      await portfolioApi.add({
        code: code.trim(),
        name: name.trim(),
        costPrice: parseFloat(costPrice),
        shares: shares ? parseInt(shares) : 0,
        entryDate: entryDate || undefined,
        notes: notes.trim(),
        holdingHorizonLabel: horizonLabel || undefined,
      });
      setCode(''); setName(''); setCostPrice(''); setShares(''); setEntryDate(''); setNotes(''); setHorizonLabel(''); setHorizonSuggestion(null);
      onAdded();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : '添加失败');
    } finally { setLoading(false); }
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-3 p-4 rounded-lg border border-black/[0.08] bg-black/[0.02]">
      <div className="text-[11px] text-muted font-medium uppercase tracking-wider">新增持仓</div>
      <div className="grid grid-cols-2 gap-2">
        <input value={code} onChange={e => setCode(e.target.value)} onBlur={handleCodeBlur} placeholder="股票代码*" className="col-span-1 bg-black/[0.03] border border-black/[0.08] rounded px-3 py-1.5 text-[13px] text-primary placeholder-muted focus:outline-none focus:border-black/[0.15]" />
        <input value={name} onChange={e => setName(e.target.value)} placeholder="股票名称" className="col-span-1 bg-black/[0.03] border border-black/[0.08] rounded px-3 py-1.5 text-[13px] text-primary placeholder-muted focus:outline-none focus:border-black/[0.15]" />
        <input value={costPrice} onChange={e => setCostPrice(e.target.value)} placeholder="成本价*" type="number" step="0.01" className="bg-black/[0.03] border border-black/[0.08] rounded px-3 py-1.5 text-[13px] text-primary placeholder-muted focus:outline-none focus:border-black/[0.15]" />
        <input value={shares} onChange={e => setShares(e.target.value)} placeholder="持股数量（股）" type="number" className="bg-black/[0.03] border border-black/[0.08] rounded px-3 py-1.5 text-[13px] text-primary placeholder-muted focus:outline-none focus:border-black/[0.15]" />
        <input value={entryDate} onChange={e => setEntryDate(e.target.value)} type="date" className="bg-black/[0.03] border border-black/[0.08] rounded px-3 py-1.5 text-[13px] text-primary/70 focus:outline-none focus:border-black/[0.15]" />
        <input value={notes} onChange={e => setNotes(e.target.value)} placeholder="备注（可选）" className="bg-black/[0.03] border border-black/[0.08] rounded px-3 py-1.5 text-[13px] text-primary placeholder-muted focus:outline-none focus:border-black/[0.15]" />
      </div>
      {/* 持仓周期 */}
      <div className="space-y-1">
        <div className="flex items-center gap-2">
          <span className="text-[11px] text-muted">持仓周期意图</span>
          {horizonSuggestion && (
            <span className="text-[10px] text-sky-400/70">AI建议: {horizonSuggestion}</span>
          )}
        </div>
        <div className="flex flex-wrap gap-1.5">
          {HORIZON_OPTIONS.map(h => (
            <button key={h} type="button" onClick={() => setHorizonLabel(h)}
              className={`text-[11px] px-2 py-0.5 rounded border transition ${
                horizonLabel === h
                  ? 'border-sky-500/40 bg-sky-500/15 text-sky-400'
                  : 'border-black/[0.06] text-muted hover:text-secondary hover:border-black/[0.1]'
              }`}>{h}</button>
          ))}
        </div>
      </div>
      {error && <p className="text-[11px] text-red-600">{error}</p>}
      <button type="submit" disabled={loading} className="w-full py-1.5 rounded bg-emerald-600/30 border border-emerald-500/30 text-emerald-600 text-[12px] hover:bg-emerald-600/50 transition disabled:opacity-50">
        {loading ? '添加中…' : '+ 加入持仓'}
      </button>
    </form>
  );
};

// ─── 操作日志面板 ─────────────────────────────
const LogPanel: React.FC<{ code: string }> = ({ code }) => {
  const [logs, setLogs] = useState<PortfolioLog[]>([]);
  const [loading, setLoading] = useState(true);
  const [addAction, setAddAction] = useState('manual');
  const [addPrice, setAddPrice] = useState('');
  const [addReason, setAddReason] = useState('');
  const [saving, setSaving] = useState(false);

  const loadLogs = useCallback(async () => {
    setLoading(true);
    try { setLogs(await portfolioApi.getLogs(code, 10)); }
    finally { setLoading(false); }
  }, [code]);

  useEffect(() => { loadLogs(); }, [loadLogs]);

  const handleAdd = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    try {
      await portfolioApi.addLog(code, { action: addAction, price: addPrice ? parseFloat(addPrice) : undefined, reason: addReason });
      setAddPrice(''); setAddReason('');
      await loadLogs();
    } finally { setSaving(false); }
  };

  return (
    <div className="border-t border-black/[0.05] pt-2 space-y-2">
      <div className="text-[10px] text-muted font-medium uppercase tracking-wider">操作日志</div>
      {loading ? <div className="text-[11px] text-muted/70">加载中…</div> : (
        <div className="space-y-1">
          {logs.length === 0 && <div className="text-[11px] text-muted/70">暂无记录</div>}
          {logs.map(log => (
            <div key={log.id} className="flex items-center gap-2 text-[11px]">
              <span className={`font-medium ${actionColor[log.action] || 'text-muted'}`}>{actionLabel[log.action] || log.action}</span>
              {log.price != null && <span className="font-mono text-secondary">{log.price.toFixed(2)}</span>}
              {log.reason && <span className="text-muted truncate">{log.reason}</span>}
              <span className="ml-auto text-muted/50 flex-shrink-0">{log.createdAt ? new Date(log.createdAt).toLocaleDateString('zh-CN') : ''}</span>
            </div>
          ))}
        </div>
      )}
      {/* 快速记录 */}
      <form onSubmit={handleAdd} className="flex gap-1.5 pt-1">
        <select value={addAction} onChange={e => setAddAction(e.target.value)}
          className="bg-black/[0.03] border border-black/[0.06] rounded px-2 py-1 text-[11px] text-secondary focus:outline-none">
          {Object.entries(actionLabel).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
        <input value={addPrice} onChange={e => setAddPrice(e.target.value)} placeholder="价格" type="number" step="0.01"
          className="w-20 bg-black/[0.03] border border-black/[0.06] rounded px-2 py-1 text-[11px] text-primary placeholder-muted/70 focus:outline-none" />
        <input value={addReason} onChange={e => setAddReason(e.target.value)} placeholder="备注"
          className="flex-1 bg-black/[0.03] border border-black/[0.06] rounded px-2 py-1 text-[11px] text-primary placeholder-muted/70 focus:outline-none" />
        <button type="submit" disabled={saving}
          className="px-2 py-1 rounded border border-black/[0.08] text-[11px] text-muted hover:text-secondary transition disabled:opacity-40">记录</button>
      </form>
    </div>
  );
};

// ─── 持仓监控卡片 ─────────────────────────────
const MonitorCard: React.FC<{ signal: MonitorSignal; onRemove: (code: string) => void }> = ({ signal, onRemove }) => {
  const navigate = useNavigate();
  const cfg = signalConfig[signal.signal] || signalConfig.unknown;
  const pnl = signal.pnlPct;
  const pnlColor = pnl == null ? 'text-muted' : pnl >= 0 ? 'text-red-600' : 'text-emerald-600';
  const pnlStr = pnl == null ? '--' : `${pnl >= 0 ? '+' : ''}${pnl.toFixed(2)}%`;
  const [showLogs, setShowLogs] = useState(false);

  const [scoreTrend, setScoreTrend] = useState<{ score: number; change: number; direction: string } | null>(null);
  useEffect(() => {
    let cancelled = false;
    scoreTrendApi.getTrend(signal.code, 5).then(resp => {
      if (cancelled || !resp?.trend) return;
      const t = resp.trend;
      const latest = t.scores?.[t.scores.length - 1];
      if (latest) setScoreTrend({ score: latest.score, change: t.score_change, direction: t.trend_direction });
    }).catch(() => {});
    return () => { cancelled = true; };
  }, [signal.code]);

  return (
    <div className={`rounded-lg border p-3 space-y-2 ${cfg.bg}`}>
      {/* 头部：代码、名称、信号 */}
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className={`w-2 h-2 rounded-full flex-shrink-0 ${cfg.dot}`} />
          <span className="font-mono text-[13px] text-primary/80">{signal.code}</span>
          <span className="text-[12px] text-secondary">{signal.name}</span>
          {(signal as MonitorSignal & { holdingHorizonLabel?: string }).holdingHorizonLabel && (
            <span className="text-[10px] px-1.5 py-0.5 rounded border border-sky-500/20 bg-sky-500/8 text-sky-400/70">
              {(signal as MonitorSignal & { holdingHorizonLabel?: string }).holdingHorizonLabel}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <span className={`text-[11px] font-medium px-1.5 py-0.5 rounded border ${cfg.bg} ${cfg.color}`}>
            {cfg.label}
          </span>
          <button onClick={() => setShowLogs(v => !v)} className="text-[11px] text-muted/70 hover:text-secondary transition" title="操作日志">📋</button>
          <button onClick={() => window.open(`/portfolio/${signal.code}/simple`, '_blank')} className="text-[11px] text-muted/70 hover:text-sky-400 transition" title="简化视图">📊</button>
          <button onClick={() => navigate(`/analysis?stock=${signal.code}`)} className="text-[11px] text-muted/70 hover:text-cyan transition" title="AI分析">🔍</button>
          <button onClick={() => onRemove(signal.code)} className="text-[11px] text-muted/70 hover:text-red-600 transition">×</button>
        </div>
      </div>

      {/* 价格行 */}
      <div className="flex items-center gap-4 text-[12px]">
        <span className="text-muted">成本 <span className="text-primary/70 font-mono">{safeFixed(signal.costPrice, 2)}</span></span>
        <span className="text-muted">现价 <span className={`font-mono ${signal.currentPrice ? 'text-primary/80' : 'text-muted'}`}>{signal.currentPrice?.toFixed(2) ?? '--'}</span></span>
        <span className="text-muted">浮盈 <span className={`font-mono font-medium ${pnlColor}`}>{pnlStr}</span></span>
        {scoreTrend && (
          <span className="text-muted">评分 <span className={`font-mono font-medium ${scoreTrend.change > 0 ? 'text-red-600' : scoreTrend.change < 0 ? 'text-emerald-600' : 'text-secondary'}`}>{scoreTrend.score}{scoreTrend.change !== 0 && <span className="text-[10px] ml-0.5">({scoreTrend.change > 0 ? '+' : ''}{scoreTrend.change})</span>}</span></span>
        )}
      </div>

      {/* ATR 止损线 */}
      {signal.atrStop > 0 && (
        <div className="flex items-center gap-4 text-[11px] text-muted">
          <span>ATR止损 <span className="font-mono text-amber-400/80">{safeFixed(signal.atrStop, 2)}</span></span>
          <span>锁住浮盈 <span className={`font-mono ${(signal.stopPnlPct ?? 0) >= 0 ? 'text-red-600/70' : 'text-emerald-600/70'}`}>{(signal.stopPnlPct ?? 0) >= 0 ? '+' : ''}{safeFixed(signal.stopPnlPct, 1)}%</span></span>
          {signal.highestPrice > 0 && <span>持仓高点 <span className="font-mono text-secondary">{safeFixed(signal.highestPrice, 2)}</span></span>}
        </div>
      )}

      {/* 再分析提醒日期 */}
      {(signal as MonitorSignal & { nextReviewAt?: string }).nextReviewAt && (
        <div className="text-[11px] text-muted flex items-center gap-1">
          <span>📅 再分析提醒:</span>
          <span className="font-mono">{(signal as MonitorSignal & { nextReviewAt?: string }).nextReviewAt}</span>
        </div>
      )}

      {/* 分时简报 */}
      {signal.intraday?.summary && (
        <div className="text-[11px] text-muted border-t border-black/[0.05] pt-1.5">
          分时: {signal.intraday.summary}
        </div>
      )}

      {/* 信号原因 */}
      {signal.reasons?.map((r, i) => (
        <p key={i} className="text-[12px] text-secondary leading-relaxed">{r}</p>
      ))}

      {/* P&L 可视化条 */}
      {pnl != null && (
        <div className="pt-1">
          <div className="relative h-1 rounded-full bg-black/[0.04] overflow-hidden">
            <div
              className={`absolute inset-y-0 ${pnl >= 0 ? 'left-1/2' : 'right-1/2'} ${pnl >= 0 ? 'bg-red-600/40' : 'bg-emerald-600/40'} rounded-full`}
              style={{ width: `${Math.min(50, Math.abs(pnl) * 2)}%` }}
            />
            <div className="absolute left-1/2 inset-y-0 w-px bg-black/[0.08]" />
          </div>
          <div className="flex justify-between mt-0.5 text-[9px] text-muted/50 font-mono">
            <span>-25%</span><span>0</span><span>+25%</span>
          </div>
        </div>
      )}

      {/* 操作日志面板（按需展开） */}
      {showLogs && <LogPanel code={signal.code} />}
    </div>
  );
};

// ─── 关注股卡片 ───────────────────────────────
const WatchlistCard: React.FC<{
  item: WatchlistItem;
  onRemove: (code: string) => void;
  onAnalyze: (code: string) => void;
}> = ({ item, onRemove, onAnalyze }) => {
  const scoreColor = item.lastScore == null ? 'text-muted'
    : item.lastScore >= 70 ? 'text-red-600'
    : item.lastScore >= 50 ? 'text-amber-400'
    : 'text-emerald-600';

  const changeColor = item.scoreChange == null ? ''
    : item.scoreChange > 0 ? 'text-red-600'
    : item.scoreChange < 0 ? 'text-emerald-600'
    : 'text-muted';

  return (
    <div className="rounded-lg border border-black/[0.08] bg-black/[0.02] p-3 space-y-2">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className="font-mono text-[13px] text-primary/80">{item.code}</span>
          <span className="text-[12px] text-secondary">{item.name}</span>
        </div>
        <div className="flex items-center gap-2">
          {item.lastScore != null && (
            <span className={`font-mono text-[13px] font-bold ${scoreColor}`}>{item.lastScore}</span>
          )}
          {item.scoreChange != null && (
            <span className={`text-[11px] font-mono ${changeColor}`}>
              {item.scoreChange > 0 ? '+' : ''}{item.scoreChange}
            </span>
          )}
          <button onClick={() => onAnalyze(item.code)} className="text-[11px] px-2 py-0.5 rounded border border-black/[0.08] text-muted hover:text-primary/70 hover:border-black/[0.12] transition">分析</button>
          <button onClick={() => onRemove(item.code)} className="text-[11px] text-muted/70 hover:text-red-600 transition">×</button>
        </div>
      </div>
      {item.lastScore != null && (
        <div className="text-xs text-muted mt-1">
          评分 <span className={`font-mono font-bold ${scoreColor}`}>{item.lastScore}</span>
          {item.lastAdvice ? ` · ${item.lastAdvice}` : ' · 待分析'}
        </div>
      )}
      {item.lastSummary && (
        <p className="text-[11px] text-muted line-clamp-2">{item.lastSummary}</p>
      )}
      {item.lastAnalyzedAt && (
        <p className="text-[10px] text-muted/70">
          更新: {new Date(item.lastAnalyzedAt).toLocaleString('zh-CN')}
        </p>
      )}
    </div>
  );
};

// ─── 主页面 ───────────────────────────────────
const PortfolioPage: React.FC = () => {
  const [tab, setTab] = useState<'monitor' | 'watchlist'>('monitor');
  const [signals, setSignals] = useState<MonitorSignal[]>([]);
  const [concentrationWarnings, setConcentrationWarnings] = useState<string[]>([]);
  const [portfolioSize, setPortfolioSize] = useState(0);
  const [capitalInput, setCapitalInput] = useState('');
  const [watchlist, setWatchlist] = useState<WatchlistItem[]>([]);
  const [sortBy, setSortBy] = useState<'score' | 'change'>('score');
  const [loadingSignals, setLoadingSignals] = useState(false);
  const [loadingWatchlist, setLoadingWatchlist] = useState(false);
  const [showAddForm, setShowAddForm] = useState(false);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const [addWatchCode, setAddWatchCode] = useState('');
  const [addWatchName, setAddWatchName] = useState('');
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const fetchSignals = useCallback(async () => {
    setLoadingSignals(true);
    try {
      const data = await portfolioApi.monitor();
      const signalPriority: Record<string, number> = {
        stop_loss: 1, reduce: 2, add_watch: 3, hold: 4,
      };
      const sorted = [...data.signals].sort((a, b) => {
        const pa = signalPriority[a.signal] || 99;
        const pb = signalPriority[b.signal] || 99;
        return pa - pb;
      });
      setSignals(sorted);
      setConcentrationWarnings(data.concentrationWarnings);
      setPortfolioSize(data.portfolioSize);
      setLastUpdated(new Date());
    } catch (e) {
      console.error('监控信号获取失败', e);
    } finally { setLoadingSignals(false); }
  }, []);

  const handleSaveCapital = async () => {
    const val = parseFloat(capitalInput);
    if (!val || val <= 0) return;
    const ok = await portfolioApi.updateCapital(val * 10000);
    if (ok) {
      setPortfolioSize(val * 10000);
      setCapitalInput('');
      fetchSignals();
    }
  };

  const fetchWatchlist = useCallback(async () => {
    setLoadingWatchlist(true);
    try {
      const data = await portfolioApi.watchlistList(sortBy);
      setWatchlist(data);
    } catch (e) { console.error('关注股获取失败', e); }
    finally { setLoadingWatchlist(false); }
  }, [sortBy]);

  useEffect(() => {
    fetchSignals();
    fetchWatchlist();
    if (isMarketOpen()) {
      timerRef.current = setInterval(fetchSignals, 2 * 60 * 1000);
    }
    return () => { if (timerRef.current) clearInterval(timerRef.current); };
  }, [fetchSignals, fetchWatchlist]);

  useEffect(() => { fetchWatchlist(); }, [sortBy, fetchWatchlist]);

  const handleRemovePortfolio = async (code: string) => {
    if (!confirm(`确认从持仓中移除 ${code}？`)) return;
    await portfolioApi.remove(code);
    fetchSignals();
  };

  const handleRemoveWatchlist = async (code: string) => {
    await portfolioApi.watchlistRemove(code);
    fetchWatchlist();
  };

  const handleAnalyze = (code: string) => {
    window.location.href = `/?code=${code}`;
  };

  const handleAddWatchlist = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!addWatchCode) return;
    await portfolioApi.watchlistAdd({ code: addWatchCode.trim(), name: addWatchName.trim() });
    setAddWatchCode(''); setAddWatchName('');
    fetchWatchlist();
  };

  const stopLossCount = signals.filter(s => s.signal === 'stop_loss').length;
  const reduceCount = signals.filter(s => s.signal === 'reduce').length;

  return (
    <div className="min-h-screen bg-base text-primary pb-20">
      {/* 顶部导航 */}
      <div className="border-b border-black/[0.05] px-6 py-3 flex items-center justify-between">
        <div className="flex items-center gap-4">
          <a href="/analysis" className="text-[12px] text-muted hover:text-secondary transition">← 返回分析</a>
          <h1 className="text-[14px] font-semibold text-primary/80">持仓管理</h1>
          {stopLossCount > 0 && (
            <span className="text-[11px] px-2 py-0.5 rounded-full bg-red-500/20 border border-red-500/30 text-red-600 animate-pulse">
              {stopLossCount} 只触发止损
            </span>
          )}
          {reduceCount > 0 && (
            <span className="text-[11px] px-2 py-0.5 rounded-full bg-amber-500/20 border border-amber-500/30 text-amber-400">
              {reduceCount} 只建议减仓
            </span>
          )}
        </div>
        {lastUpdated && (
          <span className="text-[10px] text-muted/70">
            更新于 {lastUpdated.toLocaleTimeString('zh-CN')}
          </span>
        )}
      </div>

      <div className="max-w-7xl mx-auto px-4 py-6 space-y-6">
        {/* Tab 切换 */}
        <div className="flex gap-1 p-1 rounded-lg bg-black/[0.03] border border-black/[0.06] w-fit">
          {(['monitor', 'watchlist'] as const).map(t => (
            <button key={t} onClick={() => setTab(t)}
              className={`px-4 py-1.5 rounded text-[12px] transition ${tab === t ? 'bg-black/[0.06] text-primary' : 'text-muted hover:text-secondary'}`}>
              {t === 'monitor' ? `持仓监控（${signals.length}）` : `关注股（${watchlist.length}）`}
            </button>
          ))}
        </div>

        {/* 持仓监控 Tab */}
        {tab === 'monitor' && (
          <div className="space-y-4">
            {/* 添加持仓按钮 */}
            <div className="flex justify-end">
              <button onClick={() => setShowAddForm(v => !v)}
                className="text-[12px] px-3 py-1.5 rounded border border-emerald-500/20 text-emerald-600/70 hover:border-emerald-500/40 hover:text-emerald-600 transition">
                {showAddForm ? '收起' : '+ 新增持仓'}
              </button>
            </div>
            {showAddForm && <AddPortfolioForm onAdded={() => { setShowAddForm(false); fetchSignals(); }} />}

            {/* 刷新按钮 */}
            <div className="flex justify-between items-center">
              <span className="text-[11px] text-muted/70">每2分钟自动刷新 · 盘中分时信号实时更新</span>
              <button onClick={fetchSignals} disabled={loadingSignals}
                className="text-[11px] px-2 py-1 rounded border border-black/[0.08] text-muted hover:text-secondary transition disabled:opacity-50">
                {loadingSignals ? '刷新中…' : '立即刷新'}
              </button>
            </div>

            {/* 总资金引导横幅 */}
            {portfolioSize <= 0 && signals.length > 0 && (
              <div className="bg-cyan-500/5 border border-cyan-500/20 rounded-lg p-4 flex items-center justify-between">
                <div>
                  <p className="text-sm font-medium text-primary">设置总资金后，仓位占比和风控建议会更准确</p>
                  <p className="text-xs text-muted mt-1">当前按持仓市值计算相对占比</p>
                </div>
                <div className="flex items-center gap-2">
                  <input
                    type="number"
                    placeholder="总资金（万）"
                    className="bg-black/[0.03] border border-black/[0.08] rounded px-3 py-2 w-32 text-sm text-primary placeholder-muted focus:outline-none focus:border-black/[0.15]"
                    value={capitalInput}
                    onChange={e => setCapitalInput(e.target.value)}
                  />
                  <button className="px-4 py-2 rounded bg-cyan-500/20 border border-cyan-500/30 text-cyan-600 text-sm font-medium hover:bg-cyan-500/30 transition" onClick={handleSaveCapital}>
                    确认
                  </button>
                </div>
              </div>
            )}

            {/* 组合盈亏汇总卡片 — 两行六格布局 */}
            {signals.length > 0 && (() => {
              const validSignals = signals.filter(s => s.currentPrice != null && s.shares > 0);
              const totalCost = validSignals.reduce((sum, s) => sum + s.costPrice * s.shares, 0);
              const totalMarket = validSignals.reduce((sum, s) => sum + (s.currentPrice ?? s.costPrice) * s.shares, 0);
              const totalPnlAmt = totalMarket - totalCost;
              const totalPnlPct = totalCost > 0 ? totalPnlAmt / totalCost * 100 : 0;
              const isProfit = totalPnlAmt >= 0;
              const pnlTextColor = isProfit ? 'text-red-600' : 'text-emerald-600';
              const pnlBgColor = isProfit ? 'border-red-500/20 bg-red-500/[0.04]' : 'border-emerald-500/20 bg-emerald-500/[0.04]';

              const hasCapital = portfolioSize > 0;
              const positionPct = hasCapital ? totalMarket / portfolioSize * 100 : 0;
              const cashAmount = hasCapital ? portfolioSize - totalMarket : 0;

              const todayPnlAmt = validSignals.reduce((sum, s) => {
                const price = s.currentPrice ?? 0;
                const prevClose = s.intraday?.vwap ? price : 0;
                if (!prevClose || !s.shares) return sum;
                return sum;
              }, 0);

              const weightBars = validSignals
                .map(s => ({
                  code: s.code,
                  name: s.name,
                  mv: (s.currentPrice ?? s.costPrice) * s.shares,
                  pnlPct: s.pnlPct ?? 0,
                }))
                .sort((a, b) => b.mv - a.mv);

              const riskCount = signals.filter(s => s.signal === 'stop_loss' || s.signal === 'reduce').length;

              return (
                <div className="rounded-xl border border-black/[0.07] bg-card p-4 space-y-4">
                  {/* 第一行：总资金 / 持仓市值 / 空仓资金 */}
                  <div className="grid grid-cols-3 gap-3">
                    <div className="rounded-lg border border-black/[0.04] bg-black/[0.02] p-3 text-center">
                      <div className="text-[10px] text-muted mb-1">总资金</div>
                      {hasCapital ? (
                        <div className="text-[16px] font-bold font-mono text-primary/80">
                          {(portfolioSize / 10000).toFixed(2)}<span className="text-[11px] text-muted ml-0.5">万</span>
                        </div>
                      ) : (
                        <div className="text-[13px] text-muted/70">未设置</div>
                      )}
                      {!hasCapital && (
                        <button
                          onClick={() => {
                            const banner = document.querySelector<HTMLInputElement>('input[placeholder="总资金（万）"]');
                            if (banner) banner.focus();
                          }}
                          className="mt-1 text-[10px] text-cyan-500/80 hover:text-cyan-500 transition"
                        >去设置 →</button>
                      )}
                    </div>
                    <div className="rounded-lg border border-black/[0.04] bg-black/[0.02] p-3 text-center">
                      <div className="text-[10px] text-muted mb-1">持仓市值</div>
                      <div className="text-[16px] font-bold font-mono text-primary/80">
                        {(totalMarket / 10000).toFixed(2)}<span className="text-[11px] text-muted ml-0.5">万</span>
                      </div>
                      <div className="text-[11px] text-muted font-mono">
                        {hasCapital ? `仓位 ${positionPct.toFixed(1)}%` : `成本 ${(totalCost / 10000).toFixed(2)}万`}
                      </div>
                    </div>
                    <div className="rounded-lg border border-black/[0.04] bg-black/[0.02] p-3 text-center">
                      <div className="text-[10px] text-muted mb-1">空仓资金</div>
                      {hasCapital ? (
                        <>
                          <div className={`text-[16px] font-bold font-mono ${cashAmount >= 0 ? 'text-primary/80' : 'text-amber-400'}`}>
                            {(cashAmount / 10000).toFixed(2)}<span className="text-[11px] text-muted ml-0.5">万</span>
                          </div>
                          <div className="text-[11px] text-muted font-mono">
                            空仓 {(100 - positionPct).toFixed(1)}%
                          </div>
                        </>
                      ) : (
                        <div className="text-[13px] text-muted/70">—</div>
                      )}
                    </div>
                  </div>

                  {/* 第二行：总浮盈亏 / 今日盈亏 / 风险信号 */}
                  <div className="grid grid-cols-3 gap-3">
                    <div className={`rounded-lg border p-3 text-center ${pnlBgColor}`}>
                      <div className="text-[10px] text-muted mb-1">总浮盈亏</div>
                      <div className={`text-[18px] font-bold font-mono ${pnlTextColor}`}>
                        {isProfit ? '+' : ''}{totalPnlPct.toFixed(2)}%
                      </div>
                      <div className={`text-[11px] font-mono ${pnlTextColor} opacity-70`}>
                        {isProfit ? '+' : ''}{(totalPnlAmt / 10000).toFixed(2)}万
                      </div>
                    </div>
                    <div className="rounded-lg border border-black/[0.04] bg-black/[0.02] p-3 text-center">
                      <div className="text-[10px] text-muted mb-1">今日盈亏</div>
                      <div className="text-[13px] text-muted/70 font-mono">
                        {todayPnlAmt !== 0
                          ? <span className={todayPnlAmt >= 0 ? 'text-red-600' : 'text-emerald-600'}>{todayPnlAmt >= 0 ? '+' : ''}{(todayPnlAmt / 10000).toFixed(2)}万</span>
                          : '—'}
                      </div>
                      <div className="text-[11px] text-muted">盘中实时</div>
                    </div>
                    <div className={`rounded-lg border p-3 text-center ${riskCount > 0 ? 'border-amber-500/20 bg-amber-500/[0.04]' : 'border-black/[0.04] bg-black/[0.02]'}`}>
                      <div className="text-[10px] text-muted mb-1">风险信号</div>
                      <div className={`text-[18px] font-bold font-mono ${riskCount > 0 ? 'text-amber-400' : 'text-muted'}`}>
                        {riskCount}
                      </div>
                      <div className="text-[11px] text-muted">{signals.length}只持仓</div>
                    </div>
                  </div>

                  {/* 持仓权重分布条 */}
                  {totalMarket > 0 && weightBars.length > 1 && (
                    <div>
                      <div className="text-[10px] text-muted mb-1.5">持仓权重分布</div>
                      <div className="flex h-2 rounded-full overflow-hidden gap-px">
                        {weightBars.map((b, i) => {
                          const pct = totalMarket > 0 ? b.mv / totalMarket * 100 : 0;
                          const colors = ['bg-cyan-500/50', 'bg-blue-500/50', 'bg-violet-500/50', 'bg-pink-500/50', 'bg-amber-500/50', 'bg-emerald-500/50'];
                          return (
                            <div
                              key={b.code}
                              className={`${colors[i % colors.length]} flex-shrink-0 transition-all`}
                              style={{ width: `${pct}%` }}
                              title={`${b.name || b.code} ${pct.toFixed(1)}%`}
                            />
                          );
                        })}
                      </div>
                      <div className="flex flex-wrap gap-x-3 gap-y-0.5 mt-1.5">
                        {weightBars.slice(0, 5).map((b, i) => {
                          const pct = totalMarket > 0 ? b.mv / totalMarket * 100 : 0;
                          const dotColors = ['bg-cyan-500/60', 'bg-blue-500/60', 'bg-violet-500/60', 'bg-pink-500/60', 'bg-amber-500/60'];
                          return (
                            <span key={b.code} className="flex items-center gap-1 text-[10px] text-muted">
                              <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${dotColors[i % dotColors.length]}`} />
                              {b.name || b.code} {pct.toFixed(0)}%
                            </span>
                          );
                        })}
                      </div>
                    </div>
                  )}
                </div>
              );
            })()}

            {/* 持仓概念热度扫描 */}
            {signals.length > 0 && (
              <PortfolioHeatScan
                portfolioItems={signals.map(s => ({ code: s.code, name: s.name }))}
              />
            )}

            {/* 组合集中度预警横幅 */}
            {concentrationWarnings.length > 0 && (
              <div className="space-y-2">
                {concentrationWarnings.map((w, i) => (
                  <div key={i} className="flex items-start gap-2 rounded-lg px-3 py-2 border border-amber-500/25 bg-amber-500/8 text-[12px] text-amber-300/90 leading-relaxed">
                    <span className="flex-shrink-0 mt-0.5">⚠️</span>
                    <span>{w.replace(/^⚠️\s*/, '')}</span>
                  </div>
                ))}
              </div>
            )}

            {/* 持仓卡片列表 */}
            {signals.length === 0 ? (
              <div className="text-center py-12 text-muted/70 text-[13px]">
                暂无持仓，点击「新增持仓」添加
              </div>
            ) : (
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
                {signals.map(s => (
                  <MonitorCard key={s.code} signal={s} onRemove={handleRemovePortfolio} />
                ))}
              </div>
            )}
          </div>
        )}

        {/* 关注股 Tab */}
        {tab === 'watchlist' && (
          <div className="space-y-4">
            {/* 添加关注股 */}
            <form onSubmit={handleAddWatchlist} className="flex gap-2">
              <input value={addWatchCode} onChange={e => setAddWatchCode(e.target.value)} placeholder="股票代码" className="flex-1 bg-black/[0.03] border border-black/[0.08] rounded px-3 py-1.5 text-[13px] text-primary placeholder-muted focus:outline-none focus:border-black/[0.15]" />
              <input value={addWatchName} onChange={e => setAddWatchName(e.target.value)} placeholder="名称（可选）" className="flex-1 bg-black/[0.03] border border-black/[0.08] rounded px-3 py-1.5 text-[13px] text-primary placeholder-muted focus:outline-none focus:border-black/[0.15]" />
              <button type="submit" className="px-3 py-1.5 rounded bg-black/[0.03] border border-black/[0.08] text-[12px] text-secondary hover:text-primary/70 hover:border-black/[0.12] transition">
                + 关注
              </button>
            </form>

            {/* 排序 */}
            <div className="flex items-center gap-2">
              <span className="text-[11px] text-muted">排序:</span>
              {(['score', 'change'] as const).map(s => (
                <button key={s} onClick={() => setSortBy(s)}
                  className={`text-[11px] px-2 py-0.5 rounded border transition ${sortBy === s ? 'border-black/[0.12] text-primary/70' : 'border-black/[0.06] text-muted hover:text-secondary'}`}>
                  {s === 'score' ? '评分' : '变化幅度'}
                </button>
              ))}
            </div>

            {/* 关注股列表 */}
            {loadingWatchlist ? (
              <div className="text-center py-8 text-muted/70 text-[13px]">加载中…</div>
            ) : watchlist.length === 0 ? (
              <div className="text-center py-12 text-muted/70 text-[13px]">
                暂无关注股，在报告页点击「加入关注」添加
              </div>
            ) : (
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
                {watchlist.map(item => (
                  <WatchlistCard key={item.code} item={item} onRemove={handleRemoveWatchlist} onAnalyze={handleAnalyze} />
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
};

export default PortfolioPage;
