import type React from 'react';
import { useState, useEffect, useCallback, useRef } from 'react';
import { portfolioApi, type MonitorSignal, type WatchlistItem } from '../api/portfolio';

// ─── 信号颜色映射 ─────────────────────────────
const signalConfig = {
  stop_loss: { color: 'text-red-400', bg: 'bg-red-500/10 border-red-500/30', dot: 'bg-red-400', label: '止损' },
  reduce:    { color: 'text-amber-400', bg: 'bg-amber-500/10 border-amber-500/30', dot: 'bg-amber-400', label: '减仓' },
  add_watch: { color: 'text-emerald-400', bg: 'bg-emerald-500/10 border-emerald-500/30', dot: 'bg-emerald-400', label: '加仓' },
  hold:      { color: 'text-white/50', bg: 'bg-white/5 border-white/10', dot: 'bg-white/30', label: '持有' },
  unknown:   { color: 'text-white/30', bg: 'bg-white/5 border-white/5', dot: 'bg-white/20', label: '获取中' },
};

// ─── 添加持仓表单 ─────────────────────────────
const AddPortfolioForm: React.FC<{ onAdded: () => void }> = ({ onAdded }) => {
  const [code, setCode] = useState('');
  const [name, setName] = useState('');
  const [costPrice, setCostPrice] = useState('');
  const [shares, setShares] = useState('');
  const [entryDate, setEntryDate] = useState('');
  const [notes, setNotes] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

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
      });
      setCode(''); setName(''); setCostPrice(''); setShares(''); setEntryDate(''); setNotes('');
      onAdded();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : '添加失败');
    } finally { setLoading(false); }
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-3 p-4 rounded-lg border border-white/10 bg-white/3">
      <div className="text-[11px] text-white/40 font-medium uppercase tracking-wider">新增持仓</div>
      <div className="grid grid-cols-2 gap-2">
        <input value={code} onChange={e => setCode(e.target.value)} placeholder="股票代码*" className="col-span-1 bg-white/5 border border-white/10 rounded px-3 py-1.5 text-[13px] text-white placeholder-white/25 focus:outline-none focus:border-white/30" />
        <input value={name} onChange={e => setName(e.target.value)} placeholder="股票名称" className="col-span-1 bg-white/5 border border-white/10 rounded px-3 py-1.5 text-[13px] text-white placeholder-white/25 focus:outline-none focus:border-white/30" />
        <input value={costPrice} onChange={e => setCostPrice(e.target.value)} placeholder="成本价*" type="number" step="0.01" className="bg-white/5 border border-white/10 rounded px-3 py-1.5 text-[13px] text-white placeholder-white/25 focus:outline-none focus:border-white/30" />
        <input value={shares} onChange={e => setShares(e.target.value)} placeholder="持股数量（股）" type="number" className="bg-white/5 border border-white/10 rounded px-3 py-1.5 text-[13px] text-white placeholder-white/25 focus:outline-none focus:border-white/30" />
        <input value={entryDate} onChange={e => setEntryDate(e.target.value)} type="date" className="bg-white/5 border border-white/10 rounded px-3 py-1.5 text-[13px] text-white/70 focus:outline-none focus:border-white/30" />
        <input value={notes} onChange={e => setNotes(e.target.value)} placeholder="备注（可选）" className="bg-white/5 border border-white/10 rounded px-3 py-1.5 text-[13px] text-white placeholder-white/25 focus:outline-none focus:border-white/30" />
      </div>
      {error && <p className="text-[11px] text-red-400">{error}</p>}
      <button type="submit" disabled={loading} className="w-full py-1.5 rounded bg-emerald-600/30 border border-emerald-500/30 text-emerald-400 text-[12px] hover:bg-emerald-600/50 transition disabled:opacity-50">
        {loading ? '添加中…' : '+ 加入持仓'}
      </button>
    </form>
  );
};

// ─── 持仓监控卡片 ─────────────────────────────
const MonitorCard: React.FC<{ signal: MonitorSignal; onRemove: (code: string) => void }> = ({ signal, onRemove }) => {
  const cfg = signalConfig[signal.signal] || signalConfig.unknown;
  const pnl = signal.pnlPct;
  const pnlColor = pnl == null ? 'text-white/40' : pnl >= 0 ? 'text-emerald-400' : 'text-red-400';
  const pnlStr = pnl == null ? '--' : `${pnl >= 0 ? '+' : ''}${pnl.toFixed(2)}%`;

  return (
    <div className={`rounded-lg border p-3 space-y-2 ${cfg.bg}`}>
      {/* 头部：代码、名称、信号 */}
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className={`w-2 h-2 rounded-full flex-shrink-0 ${cfg.dot}`} />
          <span className="font-mono text-[13px] text-white/80">{signal.code}</span>
          <span className="text-[12px] text-white/50">{signal.name}</span>
        </div>
        <div className="flex items-center gap-2">
          <span className={`text-[11px] font-medium px-1.5 py-0.5 rounded border ${cfg.bg} ${cfg.color}`}>
            {cfg.label}
          </span>
          <button onClick={() => onRemove(signal.code)} className="text-[11px] text-white/20 hover:text-red-400 transition">×</button>
        </div>
      </div>

      {/* 价格行 */}
      <div className="flex items-center gap-4 text-[12px]">
        <span className="text-white/40">成本 <span className="text-white/70 font-mono">{signal.costPrice.toFixed(2)}</span></span>
        <span className="text-white/40">现价 <span className={`font-mono ${signal.currentPrice ? 'text-white/80' : 'text-white/30'}`}>{signal.currentPrice?.toFixed(2) ?? '--'}</span></span>
        <span className="text-white/40">浮盈 <span className={`font-mono font-medium ${pnlColor}`}>{pnlStr}</span></span>
      </div>

      {/* ATR 止损线 */}
      {signal.atrStop > 0 && (
        <div className="flex items-center gap-4 text-[11px] text-white/40">
          <span>ATR止损 <span className="font-mono text-amber-400/80">{signal.atrStop.toFixed(2)}</span></span>
          <span>锁住浮盈 <span className={`font-mono ${signal.stopPnlPct >= 0 ? 'text-emerald-400/70' : 'text-red-400/70'}`}>{signal.stopPnlPct >= 0 ? '+' : ''}{signal.stopPnlPct.toFixed(1)}%</span></span>
          {signal.highestPrice > 0 && <span>持仓高点 <span className="font-mono text-white/50">{signal.highestPrice.toFixed(2)}</span></span>}
        </div>
      )}

      {/* 分时简报 */}
      {signal.intraday?.summary && (
        <div className="text-[11px] text-white/40 border-t border-white/5 pt-1.5">
          分时: {signal.intraday.summary}
        </div>
      )}

      {/* 信号原因 */}
      {signal.reasons?.map((r, i) => (
        <p key={i} className="text-[12px] text-white/60 leading-relaxed">{r}</p>
      ))}
    </div>
  );
};

// ─── 关注股卡片 ───────────────────────────────
const WatchlistCard: React.FC<{
  item: WatchlistItem;
  onRemove: (code: string) => void;
  onAnalyze: (code: string) => void;
}> = ({ item, onRemove, onAnalyze }) => {
  const scoreColor = item.lastScore == null ? 'text-white/30'
    : item.lastScore >= 70 ? 'text-emerald-400'
    : item.lastScore >= 50 ? 'text-amber-400'
    : 'text-red-400';

  const changeColor = item.scoreChange == null ? ''
    : item.scoreChange > 0 ? 'text-emerald-400'
    : item.scoreChange < 0 ? 'text-red-400'
    : 'text-white/40';

  return (
    <div className="rounded-lg border border-white/10 bg-white/3 p-3 space-y-2">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className="font-mono text-[13px] text-white/80">{item.code}</span>
          <span className="text-[12px] text-white/50">{item.name}</span>
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
          <button onClick={() => onAnalyze(item.code)} className="text-[11px] px-2 py-0.5 rounded border border-white/10 text-white/40 hover:text-white/70 hover:border-white/20 transition">分析</button>
          <button onClick={() => onRemove(item.code)} className="text-[11px] text-white/20 hover:text-red-400 transition">×</button>
        </div>
      </div>
      {item.lastAdvice && (
        <div className="text-[11px]">
          <span className="text-white/30">建议: </span>
          <span className="text-white/60">{item.lastAdvice}</span>
        </div>
      )}
      {item.lastSummary && (
        <p className="text-[11px] text-white/40 line-clamp-2">{item.lastSummary}</p>
      )}
      {item.lastAnalyzedAt && (
        <p className="text-[10px] text-white/20">
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
      setSignals(data.signals);
      setConcentrationWarnings(data.concentrationWarnings);
      setLastUpdated(new Date());
    } catch (e) {
      console.error('监控信号获取失败', e);
    } finally { setLoadingSignals(false); }
  }, []);

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
    // 每2分钟自动刷新持仓信号
    timerRef.current = setInterval(fetchSignals, 2 * 60 * 1000);
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
    <div className="min-h-screen bg-[#0a0a0f] text-white">
      {/* 顶部导航 */}
      <div className="border-b border-white/5 px-6 py-3 flex items-center justify-between">
        <div className="flex items-center gap-4">
          <a href="/" className="text-[12px] text-white/30 hover:text-white/60 transition">← 返回分析</a>
          <h1 className="text-[14px] font-semibold text-white/80">持仓管理</h1>
          {stopLossCount > 0 && (
            <span className="text-[11px] px-2 py-0.5 rounded-full bg-red-500/20 border border-red-500/30 text-red-400 animate-pulse">
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
          <span className="text-[10px] text-white/20">
            更新于 {lastUpdated.toLocaleTimeString('zh-CN')}
          </span>
        )}
      </div>

      <div className="max-w-3xl mx-auto px-4 py-6 space-y-6">
        {/* Tab 切换 */}
        <div className="flex gap-1 p-1 rounded-lg bg-white/5 border border-white/8 w-fit">
          {(['monitor', 'watchlist'] as const).map(t => (
            <button key={t} onClick={() => setTab(t)}
              className={`px-4 py-1.5 rounded text-[12px] transition ${tab === t ? 'bg-white/10 text-white' : 'text-white/40 hover:text-white/60'}`}>
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
                className="text-[12px] px-3 py-1.5 rounded border border-emerald-500/20 text-emerald-400/70 hover:border-emerald-500/40 hover:text-emerald-400 transition">
                {showAddForm ? '收起' : '+ 新增持仓'}
              </button>
            </div>
            {showAddForm && <AddPortfolioForm onAdded={() => { setShowAddForm(false); fetchSignals(); }} />}

            {/* 刷新按钮 */}
            <div className="flex justify-between items-center">
              <span className="text-[11px] text-white/20">每2分钟自动刷新 · 盘中分时信号实时更新</span>
              <button onClick={fetchSignals} disabled={loadingSignals}
                className="text-[11px] px-2 py-1 rounded border border-white/10 text-white/40 hover:text-white/60 transition disabled:opacity-50">
                {loadingSignals ? '刷新中…' : '立即刷新'}
              </button>
            </div>

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
              <div className="text-center py-12 text-white/20 text-[13px]">
                暂无持仓，点击「新增持仓」添加
              </div>
            ) : (
              <div className="space-y-3">
                {/* 止损警告置顶 */}
                {signals.filter(s => s.signal === 'stop_loss').map(s => (
                  <MonitorCard key={s.code} signal={s} onRemove={handleRemovePortfolio} />
                ))}
                {/* 减仓提示 */}
                {signals.filter(s => s.signal === 'reduce').map(s => (
                  <MonitorCard key={s.code} signal={s} onRemove={handleRemovePortfolio} />
                ))}
                {/* 持有 */}
                {signals.filter(s => !['stop_loss', 'reduce'].includes(s.signal)).map(s => (
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
              <input value={addWatchCode} onChange={e => setAddWatchCode(e.target.value)} placeholder="股票代码" className="flex-1 bg-white/5 border border-white/10 rounded px-3 py-1.5 text-[13px] text-white placeholder-white/25 focus:outline-none focus:border-white/30" />
              <input value={addWatchName} onChange={e => setAddWatchName(e.target.value)} placeholder="名称（可选）" className="flex-1 bg-white/5 border border-white/10 rounded px-3 py-1.5 text-[13px] text-white placeholder-white/25 focus:outline-none focus:border-white/30" />
              <button type="submit" className="px-3 py-1.5 rounded bg-white/5 border border-white/10 text-[12px] text-white/50 hover:text-white/70 hover:border-white/20 transition">
                + 关注
              </button>
            </form>

            {/* 排序 */}
            <div className="flex items-center gap-2">
              <span className="text-[11px] text-white/30">排序:</span>
              {(['score', 'change'] as const).map(s => (
                <button key={s} onClick={() => setSortBy(s)}
                  className={`text-[11px] px-2 py-0.5 rounded border transition ${sortBy === s ? 'border-white/20 text-white/70' : 'border-white/8 text-white/30 hover:text-white/50'}`}>
                  {s === 'score' ? '评分' : '变化幅度'}
                </button>
              ))}
            </div>

            {/* 关注股列表 */}
            {loadingWatchlist ? (
              <div className="text-center py-8 text-white/20 text-[13px]">加载中…</div>
            ) : watchlist.length === 0 ? (
              <div className="text-center py-12 text-white/20 text-[13px]">
                暂无关注股，在报告页点击「加入关注」添加
              </div>
            ) : (
              <div className="space-y-3">
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
