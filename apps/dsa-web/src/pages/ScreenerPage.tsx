import type React from 'react';
import { useState, useCallback, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { screenerApi } from '../api/screener';
import type { ScreenerResultItem } from '../api/screener';
import { mapAdviceDisplay } from '../types/analysis';

const ADVICE_OPTIONS = ['全部', '买入', '持有', '卖出', '观望'] as const;
const DAYS_OPTIONS = [1, 3, 5, 7] as const;

const ScreenerPage: React.FC = () => {
  const navigate = useNavigate();

  const [minScore, setMinScore] = useState(75);
  const [maxScore, setMaxScore] = useState(100);
  const [days, setDays] = useState(3);
  const [adviceFilter, setAdviceFilter] = useState('全部');
  const [limit, setLimit] = useState(20);

  const [results, setResults] = useState<ScreenerResultItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [searched, setSearched] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const resultsRef = useRef<HTMLDivElement>(null);

  const handleSearch = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const resp = await screenerApi.screen({
        minScore,
        maxScore,
        days,
        adviceFilter: adviceFilter === '全部' ? undefined : adviceFilter,
        limit,
      });
      setResults(resp.results);
      setTotal(resp.total);
      setSearched(true);
      setTimeout(() => resultsRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 100);
    } catch (err) {
      setError(err instanceof Error ? err.message : '筛选请求失败');
    } finally {
      setLoading(false);
    }
  }, [minScore, maxScore, days, adviceFilter, limit]);

  const handleStockClick = (code: string) => {
    navigate('/analysis?stock=' + code);
  };

  const getScoreColor = (score: number) => {
    if (score >= 80) return 'text-emerald-600';
    if (score >= 60) return 'text-yellow-400';
    return 'text-red-600';
  };

  const getScoreBg = (score: number) => {
    if (score >= 80) return 'bg-emerald-500/10 border-emerald-500/20';
    if (score >= 60) return 'bg-yellow-500/10 border-yellow-500/20';
    return 'bg-red-500/10 border-red-500/20';
  };

  const getAdviceColor = (advice: string) => {
    if (advice.includes('买入') || advice.includes('吸纳')) return 'text-emerald-600 bg-emerald-500/10';
    if (advice.includes('卖出') || advice.includes('减仓')) return 'text-red-600 bg-red-500/10';
    if (advice.includes('持有')) return 'text-cyan bg-cyan/10';
    return 'text-secondary bg-black/[0.03]';
  };

  return (
    <div className="min-h-screen pb-6">
      <div className="max-w-6xl mx-auto px-4 py-4 space-y-4">
        {/* 页面标题 */}
        <div className="flex items-center justify-between">
          <h1 className="text-[18px] font-bold text-primary">智能选股</h1>
          <span className="text-[11px] text-muted font-mono">
            {new Date().toLocaleDateString('zh-CN', { month: 'long', day: 'numeric', weekday: 'short' })}
          </span>
        </div>

        {/* 筛选条件卡片 — 横向紧凑布局 */}
        <div className="terminal-card p-4 space-y-3">
          <div className="text-[12px] text-muted font-medium tracking-wider uppercase">
            筛选条件
          </div>

          <div className="flex flex-wrap items-end gap-4">
            {/* 评分区间 */}
            <div className="space-y-1.5">
              <label className="text-[12px] text-secondary font-medium">评分区间</label>
              <div className="flex items-center gap-1.5">
                <input
                  type="number"
                  min={0}
                  max={100}
                  value={minScore}
                  onChange={(e) => setMinScore(Math.min(Number(e.target.value), maxScore))}
                  className="w-16 bg-black/[0.03] border border-black/[0.08] rounded-lg px-2 py-1.5 text-[12px] text-primary text-center font-mono
                    focus:outline-none focus:border-cyan/40 transition"
                />
                <span className="text-muted/70 text-[12px]">—</span>
                <input
                  type="number"
                  min={0}
                  max={100}
                  value={maxScore}
                  onChange={(e) => setMaxScore(Math.max(Number(e.target.value), minScore))}
                  className="w-16 bg-black/[0.03] border border-black/[0.08] rounded-lg px-2 py-1.5 text-[12px] text-primary text-center font-mono
                    focus:outline-none focus:border-cyan/40 transition"
                />
              </div>
            </div>

            {/* 回溯天数 */}
            <div className="space-y-1.5">
              <label className="text-[12px] text-secondary font-medium">回溯天数</label>
              <div className="flex gap-1">
                {DAYS_OPTIONS.map((d) => (
                  <button
                    key={d}
                    type="button"
                    onClick={() => setDays(d)}
                    className={`px-2.5 py-1.5 rounded-lg text-[12px] font-medium transition-all ${
                      days === d
                        ? 'bg-cyan/15 text-cyan border border-cyan/30'
                        : 'bg-black/[0.02] text-muted border border-black/[0.04] hover:border-black/[0.08] hover:text-secondary'
                    }`}
                  >
                    {d}天
                  </button>
                ))}
              </div>
            </div>

            {/* 操作建议 */}
            <div className="space-y-1.5">
              <label className="text-[12px] text-secondary font-medium">操作建议</label>
              <select
                value={adviceFilter}
                onChange={(e) => setAdviceFilter(e.target.value)}
                className="bg-black/[0.03] border border-black/[0.08] rounded-lg px-3 py-1.5 text-[12px] text-primary
                  focus:outline-none focus:border-cyan/40 transition appearance-none cursor-pointer"
              >
                {ADVICE_OPTIONS.map((opt) => (
                  <option key={opt} value={opt} className="bg-card text-primary">
                    {opt}
                  </option>
                ))}
              </select>
            </div>

            {/* 返回数量 */}
            <div className="space-y-1.5">
              <label className="text-[12px] text-secondary font-medium">最多返回</label>
              <div className="flex items-center gap-1">
                {[10, 20, 50].map((n) => (
                  <button
                    key={n}
                    type="button"
                    onClick={() => setLimit(n)}
                    className={`px-2.5 py-1.5 rounded-lg text-[11px] font-medium transition-all ${
                      limit === n
                        ? 'bg-black/[0.06] text-primary/80 border border-black/[0.08]'
                        : 'text-muted hover:text-secondary'
                    }`}
                  >
                    {n}条
                  </button>
                ))}
              </div>
            </div>

            {/* 搜索按钮 — 与筛选条件同行 */}
            <button
            type="button"
            onClick={handleSearch}
            disabled={loading}
            className="self-end px-5 py-1.5 rounded-lg bg-gradient-to-r from-cyan/20 to-cyan/10 border border-cyan/25
              text-cyan text-[13px] font-semibold hover:from-cyan/30 hover:to-cyan/15 hover:border-cyan/40
              disabled:opacity-50 disabled:cursor-not-allowed transition-all flex items-center gap-2 whitespace-nowrap"
          >
            {loading ? (
              <>
                <svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
                </svg>
                筛选中...
              </>
            ) : (
              <>
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 4a1 1 0 011-1h16a1 1 0 011 1v2.586a1 1 0 01-.293.707l-6.414 6.414a1 1 0 00-.293.707V17l-4 4v-6.586a1 1 0 00-.293-.707L3.293 7.293A1 1 0 013 6.586V4z" />
                </svg>
                开始筛选
              </>
            )}
          </button>
          </div>
        </div>

        {/* 错误提示 */}
        {error && (
          <div className="terminal-card p-3 border-danger/20 bg-danger/5">
            <p className="text-[13px] text-danger text-center">{error}</p>
          </div>
        )}

        {/* 结果列表 */}
        {searched && !error && (
          <div ref={resultsRef} className="space-y-3">
            <div className="flex items-center justify-between px-1">
              <span className="text-[13px] text-primary/70 font-medium">
                筛选结果
              </span>
              <span className="text-[11px] text-muted font-mono">
                共 {total} 只
              </span>
            </div>

            {results.length === 0 ? (
              <div className="terminal-card p-8 flex flex-col items-center gap-3">
                <svg className="w-10 h-10 text-muted/40" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
                    d="M9.172 16.172a4 4 0 015.656 0M9 10h.01M15 10h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
                <p className="text-[13px] text-muted">没有符合条件的股票</p>
                <p className="text-[11px] text-muted/50">试试降低评分门槛或扩大回溯天数</p>
              </div>
            ) : (
              <div className="space-y-2">
                {results.map((item) => (
                  <button
                    key={item.code}
                    type="button"
                    onClick={() => handleStockClick(item.code)}
                    className="w-full terminal-card p-3.5 flex items-center gap-3 hover:bg-black/[0.02]
                      hover:border-black/[0.08] transition-all group text-left"
                  >
                    {/* 评分圆圈 */}
                    <div className={`w-11 h-11 rounded-full border flex items-center justify-center flex-shrink-0 ${getScoreBg(item.score)}`}>
                      <span className={`text-[14px] font-bold font-mono ${getScoreColor(item.score)}`}>
                        {item.score}
                      </span>
                    </div>

                    {/* 股票信息 */}
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="text-[14px] font-semibold text-primary/90 font-mono">{item.code}</span>
                        <span className="text-[12px] text-secondary truncate">{item.name}</span>
                      </div>
                      <div className="flex items-center gap-2 mt-1">
                        <span className={`text-[10px] px-1.5 py-0.5 rounded font-medium ${getAdviceColor(item.advice)}`}>
                          {mapAdviceDisplay(item.advice)}
                        </span>
                        <span className="text-[10px] text-muted/70 font-mono">{item.analyzedAt}</span>
                      </div>
                    </div>

                    {/* 箭头 */}
                    <svg className="w-4 h-4 text-muted/50 group-hover:text-muted transition flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                    </svg>
                  </button>
                ))}
              </div>
            )}
          </div>
        )}

        {/* 初始状态引导 */}
        {!searched && !loading && (
          <div className="terminal-card p-8 flex flex-col items-center gap-3">
            <svg className="w-12 h-12 text-cyan/20" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
                d="M3 4a1 1 0 011-1h16a1 1 0 011 1v2.586a1 1 0 01-.293.707l-6.414 6.414a1 1 0 00-.293.707V17l-4 4v-6.586a1 1 0 00-.293-.707L3.293 7.293A1 1 0 013 6.586V4z" />
            </svg>
            <p className="text-[13px] text-muted font-medium">设置筛选条件，发现高分好股</p>
            <p className="text-[11px] text-muted/70 text-center leading-relaxed">
              从近期分析记录中筛选评分达标的股票<br />
              快速定位值得关注的投资机会
            </p>
          </div>
        )}
      </div>
    </div>
  );
};

export default ScreenerPage;
