import { useState, useEffect, useCallback } from 'react';
import ReactMarkdown from 'react-markdown';

// ============ 类型 ============

interface BacktestRecord {
  id: number;
  code: string;
  name: string;
  score: number;
  advice: string;
  actual_pct_5d: number | null;
  hit_stop_loss: boolean;
  hit_take_profit: boolean;
  stop_loss: number | null;
  take_profit: number | null;
  created_at: string;
}

interface BacktestStats {
  success: boolean;
  report: string;
}

interface BacktestRecordsResp {
  success: boolean;
  records: BacktestRecord[];
  total: number;
}

// ============ API ============

const API_BASE = '';

async function fetchStats(days: number): Promise<BacktestStats> {
  const r = await fetch(`${API_BASE}/api/v1/backtest/stats?lookback_days=${days}`);
  return r.json();
}

async function runBacktest(days: number): Promise<BacktestStats> {
  const r = await fetch(`${API_BASE}/api/v1/backtest/run?lookback_days=${days}`, { method: 'POST' });
  return r.json();
}

async function fetchRecords(days: number, code?: string): Promise<BacktestRecordsResp> {
  const params = new URLSearchParams({ lookback_days: String(days), limit: '100' });
  if (code) params.set('code', code);
  const r = await fetch(`${API_BASE}/api/v1/backtest/records?${params}`);
  return r.json();
}

// ============ 辅助组件 ============

function PctBadge({ pct }: { pct: number | null }) {
  if (pct === null || pct === undefined) return <span className="text-muted/70">—</span>;
  const color = pct > 0 ? 'text-green-400' : pct < 0 ? 'text-red-600' : 'text-muted';
  return <span className={`font-mono font-medium ${color}`}>{pct > 0 ? '+' : ''}{pct.toFixed(2)}%</span>;
}

function ScoreBadge({ score }: { score: number }) {
  const color = score >= 85 ? 'bg-cyan/20 text-cyan border-cyan/30'
    : score >= 70 ? 'bg-green-500/15 text-green-400 border-green-500/25'
    : score >= 50 ? 'bg-yellow-500/15 text-yellow-400 border-yellow-500/25'
    : 'bg-red-500/15 text-red-600 border-red-500/25';
  return (
    <span className={`inline-flex items-center px-1.5 py-0.5 rounded text-[11px] border font-mono ${color}`}>
      {score}
    </span>
  );
}

// ============ 主组件 ============

export function BacktestPanel() {
  const [lookbackDays, setLookbackDays] = useState(60);
  const [statsReport, setStatsReport] = useState<string>('');
  const [records, setRecords] = useState<BacktestRecord[]>([]);
  const [loadingStats, setLoadingStats] = useState(false);
  const [loadingRun, setLoadingRun] = useState(false);
  const [loadingRecords, setLoadingRecords] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<'stats' | 'records'>('stats');
  const [filterCode, setFilterCode] = useState('');

  const loadStats = useCallback(async () => {
    setLoadingStats(true);
    setError(null);
    try {
      const res = await fetchStats(lookbackDays);
      if (res.success) {
        setStatsReport(res.report);
      } else {
        setError('获取统计失败');
      }
    } catch (e) {
      setError(String(e));
    } finally {
      setLoadingStats(false);
    }
  }, [lookbackDays]);

  const loadRecords = useCallback(async () => {
    setLoadingRecords(true);
    try {
      const res = await fetchRecords(lookbackDays, filterCode || undefined);
      if (res.success) setRecords(res.records);
    } catch (e) {
      console.error(e);
    } finally {
      setLoadingRecords(false);
    }
  }, [lookbackDays, filterCode]);

  const handleRun = async () => {
    setLoadingRun(true);
    setError(null);
    try {
      const res = await runBacktest(lookbackDays);
      if (res.success) {
        setStatsReport(res.report);
        await loadRecords();
      } else {
        setError('回测执行失败');
      }
    } catch (e) {
      setError(String(e));
    } finally {
      setLoadingRun(false);
    }
  };

  useEffect(() => {
    loadStats();
    loadRecords();
  }, [lookbackDays]);

  useEffect(() => {
    if (activeTab === 'records') loadRecords();
  }, [activeTab, filterCode]);

  return (
    <div className="flex flex-col h-full gap-4 p-4 max-w-5xl mx-auto">
      {/* 标题栏 */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h2 className="text-[15px] font-semibold text-primary">回测统计</h2>
          <p className="text-[11px] text-muted mt-0.5">验证分析系统的实际胜率与超额收益</p>
        </div>
        <div className="flex items-center gap-2">
          {/* 回溯天数选择 */}
          <select
            value={lookbackDays}
            onChange={e => setLookbackDays(Number(e.target.value))}
            className="bg-elevated border border-black/[0.06] rounded-lg px-2.5 py-1.5 text-[12px] text-primary/70 focus:outline-none focus:border-cyan/30"
          >
            <option value={30}>近30天</option>
            <option value={60}>近60天</option>
            <option value={90}>近90天</option>
            <option value={180}>近180天</option>
          </select>

          {/* 执行回填按钮 */}
          <button
            type="button"
            onClick={handleRun}
            disabled={loadingRun}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-cyan/15 border border-cyan/25 text-cyan text-[12px] hover:bg-cyan/25 transition-colors disabled:opacity-50"
          >
            {loadingRun ? (
              <svg className="w-3.5 h-3.5 animate-spin" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
            ) : (
              <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
              </svg>
            )}
            {loadingRun ? '回填中...' : '执行回填'}
          </button>
        </div>
      </div>

      {/* 错误提示 */}
      {error && (
        <div className="text-[12px] text-red-600 bg-red-600/10 border border-red-400/20 rounded-lg px-3 py-2">
          {error}
        </div>
      )}

      {/* 标签页切换 */}
      <div className="flex gap-1 border-b border-black/[0.05]">
        {(['stats', 'records'] as const).map(tab => (
          <button
            key={tab}
            type="button"
            onClick={() => setActiveTab(tab)}
            className={`px-3 py-2 text-[12px] font-medium transition-colors border-b-2 -mb-px ${
              activeTab === tab
                ? 'border-cyan text-cyan'
                : 'border-transparent text-muted hover:text-secondary'
            }`}
          >
            {tab === 'stats' ? '📊 统计报告' : '📋 明细记录'}
          </button>
        ))}
      </div>

      {/* 统计报告 */}
      {activeTab === 'stats' && (
        <div className="flex-1 overflow-y-auto">
          {loadingStats ? (
            <div className="flex items-center justify-center h-40 gap-2 text-muted text-[13px]">
              <svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
              加载中...
            </div>
          ) : statsReport ? (
            <div className="prose prose-invert prose-sm max-w-none backtest-markdown">
              <ReactMarkdown>{statsReport}</ReactMarkdown>
            </div>
          ) : (
            <div className="flex flex-col items-center justify-center h-40 gap-2 text-muted text-[13px]">
              <svg className="w-8 h-8 opacity-30" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
              </svg>
              暂无回测数据，点击「执行回填」开始
            </div>
          )}
        </div>
      )}

      {/* 明细记录 */}
      {activeTab === 'records' && (
        <div className="flex flex-col gap-3 flex-1 overflow-hidden">
          {/* 过滤栏 */}
          <div className="flex items-center gap-2">
            <input
              type="text"
              value={filterCode}
              onChange={e => setFilterCode(e.target.value.toUpperCase())}
              placeholder="按股票代码过滤..."
              className="bg-elevated border border-black/[0.06] rounded-lg px-3 py-1.5 text-[12px] text-primary/70 placeholder-muted/70 focus:outline-none focus:border-cyan/30 w-40"
            />
            <span className="text-[11px] text-muted">共 {records.length} 条</span>
          </div>

          {/* 表格 */}
          <div className="flex-1 overflow-auto rounded-xl border border-black/[0.05]">
            {loadingRecords ? (
              <div className="flex items-center justify-center h-32 text-muted text-[13px]">加载中...</div>
            ) : records.length === 0 ? (
              <div className="flex items-center justify-center h-32 text-muted text-[13px]">暂无已回填记录</div>
            ) : (
              <table className="w-full text-[12px]">
                <thead>
                  <tr className="border-b border-black/[0.05] bg-black/[0.02]">
                    <th className="text-left px-3 py-2.5 text-muted font-medium">股票</th>
                    <th className="text-center px-3 py-2.5 text-muted font-medium">评分</th>
                    <th className="text-left px-3 py-2.5 text-muted font-medium">建议</th>
                    <th className="text-right px-3 py-2.5 text-muted font-medium">5日收益</th>
                    <th className="text-center px-3 py-2.5 text-muted font-medium">止损</th>
                    <th className="text-center px-3 py-2.5 text-muted font-medium">止盈</th>
                    <th className="text-right px-3 py-2.5 text-muted font-medium">分析时间</th>
                  </tr>
                </thead>
                <tbody>
                  {records.map((r, i) => (
                    <tr
                      key={r.id}
                      className={`border-b border-black/[0.03] hover:bg-black/[0.02] transition-colors ${
                        i % 2 === 0 ? '' : 'bg-black/[0.02]'
                      }`}
                    >
                      <td className="px-3 py-2">
                        <div className="font-medium text-primary/80">{r.name || r.code}</div>
                        <div className="text-[10px] text-muted font-mono">{r.code}</div>
                      </td>
                      <td className="px-3 py-2 text-center">
                        <ScoreBadge score={r.score || 0} />
                      </td>
                      <td className="px-3 py-2 text-secondary">{r.advice || '—'}</td>
                      <td className="px-3 py-2 text-right">
                        <PctBadge pct={r.actual_pct_5d} />
                      </td>
                      <td className="px-3 py-2 text-center">
                        {r.hit_stop_loss ? (
                          <span className="text-red-600 text-[11px]">触发</span>
                        ) : (
                          <span className="text-muted/70 text-[11px]">未触</span>
                        )}
                      </td>
                      <td className="px-3 py-2 text-center">
                        {r.hit_take_profit ? (
                          <span className="text-green-400 text-[11px]">触发</span>
                        ) : (
                          <span className="text-muted/70 text-[11px]">未触</span>
                        )}
                      </td>
                      <td className="px-3 py-2 text-right text-muted font-mono text-[10px]">
                        {r.created_at ? new Date(r.created_at).toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }) : '—'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
