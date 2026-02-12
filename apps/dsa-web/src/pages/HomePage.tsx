import type React from 'react';
import { useState, useEffect, useCallback, useRef } from 'react';
import type { HistoryItem, AnalysisReport, TaskInfo, PositionInfo } from '../types/analysis';
import { historyApi } from '../api/history';
import { analysisApi, DuplicateTaskError } from '../api/analysis';
import { validateStockCode } from '../utils/validation';
import { getRecentStartDate, toDateInputValue } from '../utils/format';
import { useAnalysisStore } from '../stores/analysisStore';
import { ReportSummary } from '../components/report';
import { HistoryList } from '../components/history';
import { TaskPanel } from '../components/tasks';
import { Watchlist } from '../components/watchlist';
import { useTaskStream } from '../hooks';

/**
 * 首页 - 重新设计的布局
 * 顶部品牌 + 搜索栏 | 左侧边栏 | 右侧报告
 */
const HomePage: React.FC = () => {
  const { setLoading, setError: setStoreError, error: storeError } = useAnalysisStore();

  // 输入状态
  const [stockCode, setStockCode] = useState('');
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [inputError, setInputError] = useState<string>();

  // 持仓信息状态（从 localStorage 恢复）
  const [showPosition, setShowPosition] = useState(() => {
    return localStorage.getItem('dsa_show_position') === 'true';
  });
  const [totalCapital, setTotalCapital] = useState(() => {
    return localStorage.getItem('dsa_total_capital') || '';
  });
  const [positionAmount, setPositionAmount] = useState('');
  const [costPrice, setCostPrice] = useState('');

  // 历史列表状态
  const [historyItems, setHistoryItems] = useState<HistoryItem[]>([]);
  const [isLoadingHistory, setIsLoadingHistory] = useState(false);
  const [isLoadingMore, setIsLoadingMore] = useState(false);
  const [hasMore, setHasMore] = useState(true);
  const [currentPage, setCurrentPage] = useState(1);
  const pageSize = 20;

  // 报告详情状态
  const [selectedReport, setSelectedReport] = useState<AnalysisReport | null>(null);
  const [isLoadingReport, setIsLoadingReport] = useState(false);

  // 任务队列状态
  const [activeTasks, setActiveTasks] = useState<TaskInfo[]>([]);
  const [duplicateError, setDuplicateError] = useState<string | null>(null);

  // 用于跟踪当前分析请求，避免竞态条件
  const analysisRequestIdRef = useRef<number>(0);

  // 移动端侧边栏状态
  const [sidebarOpen, setSidebarOpen] = useState(false);

  // 持久化总资金和展开状态
  useEffect(() => {
    localStorage.setItem('dsa_show_position', String(showPosition));
  }, [showPosition]);
  useEffect(() => {
    if (totalCapital) localStorage.setItem('dsa_total_capital', totalCapital);
  }, [totalCapital]);

  // 构建持仓信息（有任意一项有效值时才传递）
  const buildPositionInfo = (): PositionInfo | undefined => {
    const tc = totalCapital ? parseFloat(totalCapital) * 10000 : undefined;
    const pa = positionAmount ? parseFloat(positionAmount) * 10000 : undefined;
    const cp = costPrice ? parseFloat(costPrice) : undefined;
    if (tc || pa || cp) {
      return { totalCapital: tc, positionAmount: pa, costPrice: cp };
    }
    return undefined;
  };

  // 更新任务列表中的任务
  const updateTask = useCallback((updatedTask: TaskInfo) => {
    setActiveTasks((prev) => {
      const index = prev.findIndex((t) => t.taskId === updatedTask.taskId);
      if (index >= 0) {
        const newTasks = [...prev];
        newTasks[index] = updatedTask;
        return newTasks;
      }
      return prev;
    });
  }, []);

  // 移除已完成/失败的任务
  const removeTask = useCallback((taskId: string) => {
    setActiveTasks((prev) => prev.filter((t) => t.taskId !== taskId));
  }, []);

  // SSE 任务流
  useTaskStream({
    onTaskCreated: (task) => {
      setActiveTasks((prev) => {
        if (prev.some((t) => t.taskId === task.taskId)) return prev;
        return [...prev, task];
      });
    },
    onTaskStarted: updateTask,
    onTaskCompleted: (task) => {
      fetchHistory();
      setTimeout(() => removeTask(task.taskId), 2000);
    },
    onTaskFailed: (task) => {
      updateTask(task);
      setStoreError(task.error || '分析失败');
      setTimeout(() => removeTask(task.taskId), 5000);
    },
    onError: () => {
      console.warn('SSE 连接断开，正在重连...');
    },
    enabled: true,
  });

  // 加载历史列表
  const fetchHistory = useCallback(async (autoSelectFirst = false, reset = true) => {
    if (reset) {
      setIsLoadingHistory(true);
      setCurrentPage(1);
    } else {
      setIsLoadingMore(true);
    }

    const page = reset ? 1 : currentPage + 1;

    try {
      const response = await historyApi.getList({
        startDate: getRecentStartDate(30),
        endDate: toDateInputValue(new Date()),
        page,
        limit: pageSize,
      });

      if (reset) {
        setHistoryItems(response.items);
      } else {
        setHistoryItems(prev => [...prev, ...response.items]);
      }

      const totalLoaded = reset ? response.items.length : historyItems.length + response.items.length;
      setHasMore(totalLoaded < response.total);
      setCurrentPage(page);

      if (autoSelectFirst && response.items.length > 0 && !selectedReport) {
        const firstItem = response.items[0];
        setIsLoadingReport(true);
        try {
          const report = await historyApi.getDetail(firstItem.queryId);
          setSelectedReport(report);
        } catch (err) {
          console.error('Failed to fetch first report:', err);
        } finally {
          setIsLoadingReport(false);
        }
      }
    } catch (err) {
      console.error('Failed to fetch history:', err);
    } finally {
      setIsLoadingHistory(false);
      setIsLoadingMore(false);
    }
  }, [selectedReport, currentPage, historyItems.length, pageSize]);

  // 加载更多历史记录
  const handleLoadMore = useCallback(() => {
    if (!isLoadingMore && hasMore) {
      fetchHistory(false, false);
    }
  }, [fetchHistory, isLoadingMore, hasMore]);

  // 初始加载 - 自动选择第一条
  useEffect(() => {
    fetchHistory(true);
  }, []);

  // 点击历史项加载报告
  const handleHistoryClick = async (queryId: string) => {
    analysisRequestIdRef.current += 1;
    setIsLoadingReport(true);
    try {
      const report = await historyApi.getDetail(queryId);
      setSelectedReport(report);
    } catch (err) {
      console.error('Failed to fetch report:', err);
    } finally {
      setIsLoadingReport(false);
    }
  };

  // 分析股票（异步模式）
  const handleAnalyze = async () => {
    const { valid, message, normalized } = validateStockCode(stockCode);
    if (!valid) {
      setInputError(message);
      return;
    }

    setInputError(undefined);
    setDuplicateError(null);
    setIsAnalyzing(true);
    setLoading(true);
    setStoreError(null);

    const currentRequestId = ++analysisRequestIdRef.current;

    try {
      const response = await analysisApi.analyzeAsync({
        stockCode: normalized,
        reportType: 'detailed',
        positionInfo: buildPositionInfo(),
      });

      if (currentRequestId === analysisRequestIdRef.current) {
        setStockCode('');
      }

      console.log('Task submitted:', response.taskId);
    } catch (err) {
      console.error('Analysis failed:', err);
      if (currentRequestId === analysisRequestIdRef.current) {
        if (err instanceof DuplicateTaskError) {
          setDuplicateError(`股票 ${err.stockCode} 正在分析中，请等待完成`);
        } else {
          setStoreError(err instanceof Error ? err.message : '分析失败');
        }
      }
    } finally {
      setIsAnalyzing(false);
      setLoading(false);
    }
  };

  // 回车提交
  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && stockCode && !isAnalyzing) {
      handleAnalyze();
    }
  };

  // 自选股：单只分析
  const handleWatchlistAnalyze = useCallback((code: string) => {
    setStockCode(code);
    setTimeout(() => {
      const btn = document.querySelector('[data-analyze-btn]') as HTMLButtonElement;
      if (btn) btn.click();
    }, 50);
  }, []);

  // 自选股：批量分析
  const handleBatchAnalyze = useCallback(async (codes: string[]) => {
    setDuplicateError(null);
    setStoreError(null);
    for (const code of codes) {
      try {
        await analysisApi.analyzeAsync({
          stockCode: code,
          reportType: 'detailed',
          positionInfo: buildPositionInfo(),
        });
      } catch (err) {
        if (!(err instanceof DuplicateTaskError)) {
          console.error(`Batch analyze ${code} failed:`, err);
        }
      }
    }
  }, [buildPositionInfo]);

  return (
    <div className="h-screen flex flex-col overflow-hidden">
      {/* ========== 错误 Toast ========== */}
      {storeError && (
        <div className="flex-shrink-0 px-4 py-2 bg-danger/10 border-b border-danger/20 flex items-center justify-between gap-2 animate-slide-up">
          <span className="text-[13px] text-danger">{storeError}</span>
          <button
            type="button"
            onClick={() => setStoreError(null)}
            className="text-danger/70 hover:text-danger text-xs px-2 py-0.5 rounded hover:bg-danger/10 transition-colors"
            aria-label="关闭"
          >
            ✕
          </button>
        </div>
      )}

      {/* ========== 顶部导航栏 ========== */}
      <header className="flex-shrink-0 header-bar relative z-50">
        <div className="flex items-center gap-3 h-full px-4">
          {/* Logo + 品牌 */}
          <div className="flex items-center gap-2 flex-shrink-0">
            <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-cyan/80 to-cyan/40 flex items-center justify-center shadow-lg shadow-cyan/20">
              <svg className="w-4 h-4 text-black" fill="none" stroke="currentColor" strokeWidth={2.5} viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" d="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6" />
              </svg>
            </div>
            <span className="text-[15px] font-bold text-white/90 hidden sm:block tracking-tight">DSA</span>
          </div>

          {/* 分隔线 */}
          <div className="w-px h-5 bg-white/10 hidden sm:block" />

          {/* 移动端侧边栏切换 */}
          <button
            type="button"
            onClick={() => setSidebarOpen(v => !v)}
            className="lg:hidden text-muted hover:text-white p-1.5 rounded-lg hover:bg-white/5 transition-colors"
            aria-label="切换侧边栏"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
            </svg>
          </button>

          {/* 搜索输入 */}
          <div className="flex-1 max-w-xl relative">
            <div className="relative">
              <svg className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-white/20" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
              </svg>
              <input
                type="text"
                value={stockCode}
                onChange={(e) => {
                  setStockCode(e.target.value.toUpperCase());
                  setInputError(undefined);
                  setDuplicateError(null);
                }}
                onKeyDown={handleKeyDown}
                placeholder="股票代码  600519 / HK00700 / AAPL"
                disabled={isAnalyzing}
                className={`header-input w-full pl-9 ${inputError ? 'border-danger/40' : ''}`}
              />
            </div>
            {(inputError || duplicateError) && (
              <p className={`absolute -bottom-5 left-0 text-[11px] ${inputError ? 'text-danger' : 'text-warning'}`}>
                {inputError || duplicateError}
              </p>
            )}
          </div>

          {/* 操作按钮组 */}
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => setShowPosition((v) => !v)}
              className={`header-btn-icon ${showPosition ? 'text-cyan border-cyan/30 bg-cyan/8' : ''}`}
              title="持仓信息"
            >
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M21 13.255A23.931 23.931 0 0112 15c-3.183 0-6.22-.62-9-1.745M16 6V4a2 2 0 00-2-2h-4a2 2 0 00-2 2v2m4 6h.01M5 20h14a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
              </svg>
            </button>

            <button
              type="button"
              onClick={handleAnalyze}
              disabled={!stockCode || isAnalyzing}
              data-analyze-btn
              className="header-btn-primary"
            >
              {isAnalyzing ? (
                <svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
                </svg>
              ) : (
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
                </svg>
              )}
              <span className="hidden sm:inline">{isAnalyzing ? '分析中' : '分析'}</span>
            </button>
          </div>
        </div>

        {/* 持仓信息面板（可折叠） */}
        {showPosition && (
          <div className="flex items-center gap-4 px-4 pb-3 pt-1 border-t border-white/5 animate-slide-up">
            <div className="flex items-center gap-1.5">
              <label className="text-[11px] text-white/30 whitespace-nowrap">总资金(万)</label>
              <input
                type="number"
                value={totalCapital}
                onChange={(e) => setTotalCapital(e.target.value)}
                placeholder="100"
                className="header-input w-20 text-xs py-1.5"
              />
            </div>
            <div className="flex items-center gap-1.5">
              <label className="text-[11px] text-white/30 whitespace-nowrap">持仓(万)</label>
              <input
                type="number"
                value={positionAmount}
                onChange={(e) => setPositionAmount(e.target.value)}
                placeholder="10"
                className="header-input w-20 text-xs py-1.5"
              />
            </div>
            <div className="flex items-center gap-1.5">
              <label className="text-[11px] text-white/30 whitespace-nowrap">成本价</label>
              <input
                type="number"
                step="0.01"
                value={costPrice}
                onChange={(e) => setCostPrice(e.target.value)}
                placeholder="35.00"
                className="header-input w-24 text-xs py-1.5"
              />
            </div>
            {(totalCapital || positionAmount) && (
              <span className="text-[11px] text-white/40 font-mono">
                仓位 {totalCapital && positionAmount
                  ? `${((parseFloat(positionAmount) / parseFloat(totalCapital)) * 100).toFixed(1)}%`
                  : '--'}
              </span>
            )}
          </div>
        )}
      </header>

      {/* ========== 主内容区 ========== */}
      <div className="flex-1 flex overflow-hidden relative">
        {/* 移动端遮罩 */}
        {sidebarOpen && (
          <div
            className="fixed inset-0 bg-black/60 backdrop-blur-sm z-30 lg:hidden animate-fade-in"
            onClick={() => setSidebarOpen(false)}
          />
        )}

        {/* 左侧边栏 */}
        <aside className={`sidebar-panel
          fixed lg:static inset-y-0 left-0 z-40 bg-base lg:bg-transparent
          transform transition-transform duration-200 ease-out
          ${sidebarOpen ? 'translate-x-0' : '-translate-x-full lg:translate-x-0'}
        `}>
          <div className="flex flex-col gap-2 h-full p-3 lg:p-0 lg:py-3 lg:pl-3 overflow-y-auto">
            {/* 自选股 */}
            <Watchlist
              currentCode={stockCode}
              onAnalyze={handleWatchlistAnalyze}
              onBatchAnalyze={handleBatchAnalyze}
              isAnalyzing={isAnalyzing}
            />

            {/* 任务面板 */}
            <TaskPanel tasks={activeTasks} />

            {/* 历史列表 */}
            <HistoryList
              items={historyItems}
              isLoading={isLoadingHistory}
              isLoadingMore={isLoadingMore}
              hasMore={hasMore}
              selectedQueryId={selectedReport?.meta.queryId}
              onItemClick={(queryId) => {
                handleHistoryClick(queryId);
                setSidebarOpen(false);
              }}
              onLoadMore={handleLoadMore}
              className="flex-1 min-h-0 overflow-hidden"
            />
          </div>
        </aside>

        {/* 右侧报告区 */}
        <section className="flex-1 overflow-y-auto p-3 lg:p-4">
          {isLoadingReport ? (
            <div className="flex flex-col items-center justify-center h-full gap-3">
              <div className="w-10 h-10 border-[3px] border-cyan/15 border-t-cyan rounded-full animate-spin" />
              <p className="text-[13px] text-white/30">加载报告中...</p>
            </div>
          ) : selectedReport ? (
            <div className="max-w-4xl mx-auto animate-fade-in">
              <ReportSummary data={selectedReport} isHistory />
            </div>
          ) : (
            <div className="flex flex-col items-center justify-center h-full text-center gap-4">
              <div className="w-16 h-16 rounded-2xl bg-white/[0.03] border border-white/[0.06] flex items-center justify-center">
                <svg className="w-7 h-7 text-white/15" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
                </svg>
              </div>
              <div>
                <h3 className="text-[15px] font-semibold text-white/80 mb-1">开始分析</h3>
                <p className="text-[12px] text-white/25 max-w-[260px] leading-relaxed">
                  输入股票代码进行 AI 智能分析，或从左侧选择历史报告
                </p>
              </div>
            </div>
          )}
        </section>
      </div>
    </div>
  );
};

export default HomePage;
