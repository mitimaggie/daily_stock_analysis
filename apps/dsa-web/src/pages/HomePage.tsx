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
import { ChatPanel } from '../components/chat/ChatPanel';
import { BacktestPanel } from '../components/backtest/BacktestPanel';
import { portfolioApi } from '../api/portfolio';

/** 报告页「加入持仓/关注」快捷栏 */
const QuickAddBar: React.FC<{ report: AnalysisReport }> = ({ report }) => {
  const code = report?.meta?.stockCode ?? '';
  const name = report?.meta?.stockName ?? '';
  const [addingP, setAddingP] = useState(false);
  const [addingW, setAddingW] = useState(false);
  const [msgP, setMsgP] = useState('');
  const [msgW, setMsgW] = useState('');
  const [showCostInput, setShowCostInput] = useState(false);
  const [costPrice, setCostPriceInput] = useState('');

  const handleAddPortfolio = async () => {
    if (!costPrice) { setShowCostInput(true); return; }
    setAddingP(true);
    try {
      await portfolioApi.add({ code, name, costPrice: parseFloat(costPrice) });
      setMsgP('✅ 已加入持仓');
      setShowCostInput(false);
      setCostPriceInput('');
      setTimeout(() => setMsgP(''), 3000);
    } catch { setMsgP('❌ 添加失败'); setTimeout(() => setMsgP(''), 3000); }
    finally { setAddingP(false); }
  };

  const handleAddWatchlist = async () => {
    setAddingW(true);
    try {
      await portfolioApi.watchlistAdd({ code, name });
      const score = report?.summary?.sentimentScore;
      const advice = report?.summary?.operationAdvice || '';
      const summary = report?.summary?.analysisSummary || '';
      if (score != null) await portfolioApi.watchlistSync(code, score, advice, summary);
      setMsgW('✅ 已加入关注');
      setTimeout(() => setMsgW(''), 3000);
    } catch { setMsgW('❌ 添加失败'); setTimeout(() => setMsgW(''), 3000); }
    finally { setAddingW(false); }
  };

  if (!code) return null;

  return (
    <div className="mt-3 mb-1 flex items-center gap-3 px-1">
      {showCostInput ? (
        <div className="flex items-center gap-2">
          <input value={costPrice} onChange={e => setCostPriceInput(e.target.value)}
            placeholder="输入成本价" type="number" step="0.01" autoFocus
            className="w-28 bg-white/5 border border-white/15 rounded px-2 py-1 text-[12px] text-white placeholder-white/25 focus:outline-none focus:border-white/30" />
          <button onClick={handleAddPortfolio} disabled={addingP}
            className="text-[11px] px-2 py-1 rounded bg-emerald-600/20 border border-emerald-500/30 text-emerald-400 hover:bg-emerald-600/30 transition disabled:opacity-50">
            {addingP ? '…' : '确认加入持仓'}
          </button>
          <button onClick={() => setShowCostInput(false)} className="text-[11px] text-white/25 hover:text-white/50">取消</button>
        </div>
      ) : (
        <button onClick={handleAddPortfolio} disabled={addingP}
          className="text-[11px] px-2.5 py-1 rounded border border-emerald-500/20 text-emerald-400/70 hover:border-emerald-500/40 hover:text-emerald-400 transition disabled:opacity-50">
          {msgP || (addingP ? '…' : '+ 加入持仓')}
        </button>
      )}
      <button onClick={handleAddWatchlist} disabled={addingW}
        className="text-[11px] px-2.5 py-1 rounded border border-white/10 text-white/40 hover:border-white/20 hover:text-white/60 transition disabled:opacity-50">
        {msgW || (addingW ? '…' : '+ 加入关注')}
      </button>
      <a href="/portfolio" className="text-[11px] text-white/20 hover:text-white/40 transition ml-auto">持仓管理 →</a>
    </div>
  );
};

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

  // 按股票代码从 portfolio 表加载/保存持仓信息
  const syncTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const loadPositionTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const loadPositionForStock = useCallback(async (code: string) => {
    if (!code) return;
    try {
      const item = await portfolioApi.get(code);
      if (item) {
        setPositionAmount(String(item.shares || ''));
        setCostPrice(String(item.costPrice || ''));
        return;
      }
    } catch { /* 未在持仓表中，尝试 localStorage */ }
    const key = `dsa_pos_${code.replace(/\./g, '_')}`;
    try {
      const raw = localStorage.getItem(key);
      if (raw) {
        const { pa, cp } = JSON.parse(raw);
        setPositionAmount(pa || '');
        setCostPrice(cp || '');
        return;
      }
    } catch { /* ignore */ }
    setPositionAmount('');
    setCostPrice('');
  }, []);

  // debounce 同步持仓到数据库
  const syncPositionToDb = useCallback((code: string, shares: string, cp: string, name: string) => {
    if (syncTimerRef.current) clearTimeout(syncTimerRef.current);
    syncTimerRef.current = setTimeout(async () => {
      if (!code || !cp || !shares) return;
      try {
        await portfolioApi.add({
          code,
          name: name || code,
          costPrice: parseFloat(cp),
          shares: parseInt(shares) || 0,
        });
      } catch { /* 静默失败 */ }
    }, 1000);
  }, []);

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

  // AI 对话面板状态
  const [chatOpen, setChatOpen] = useState(false);

  // 主视图标签
  const [mainTab, setMainTab] = useState<'analysis' | 'backtest'>('analysis');

  // 持久化总资金和展开状态
  useEffect(() => {
    localStorage.setItem('dsa_show_position', String(showPosition));
  }, [showPosition]);
  useEffect(() => {
    if (totalCapital) localStorage.setItem('dsa_total_capital', totalCapital);
  }, [totalCapital]);

  // 构建持仓信息（持仓（股）× 成本价 = 持仓金额（元））
  const buildPositionInfo = (): PositionInfo | undefined => {
    const tc = totalCapital ? parseFloat(totalCapital) * 10000 : undefined;
    const shares = positionAmount ? parseInt(positionAmount) : 0;
    const cp = costPrice ? parseFloat(costPrice) : undefined;
    const pa = (shares > 0 && cp && cp > 0) ? shares * cp : undefined;
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
      fetchHistory(true);
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

  // 轮询兜底：当有活跃任务时，定期检查任务状态（防止 SSE 丢失事件）
  const pollCallbacksRef = useRef<{ fetchHistory: (autoSelectFirst?: boolean) => void; removeTask: (id: string) => void; setError: (e: string) => void }>({
    fetchHistory: () => {},
    removeTask: () => {},
    setError: () => {},
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

      if (autoSelectFirst && response.items.length > 0) {
        const firstItem = response.items[0];
        loadPositionForStock(firstItem.stockCode);
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

  // 更新轮询回调 ref（fetchHistory 已定义）
  useEffect(() => {
    pollCallbacksRef.current.fetchHistory = fetchHistory;
  });

  // 实际轮询 effect
  useEffect(() => {
    const pending = activeTasks.filter(
      (t) => t.status === 'pending' || t.status === 'processing'
    );
    if (pending.length === 0) return;

    const interval = setInterval(async () => {
      for (const task of pending) {
        try {
          const s = await analysisApi.getStatus(task.taskId);
          if (s.status === 'completed') {
            pollCallbacksRef.current.fetchHistory(true);
            setTimeout(() => pollCallbacksRef.current.removeTask(task.taskId), 1000);
          } else if (s.status === 'failed') {
            pollCallbacksRef.current.setError(s.error || '分析失败');
            setTimeout(() => pollCallbacksRef.current.removeTask(task.taskId), 3000);
          }
        } catch {
          // 静默，等下一轮
        }
      }
    }, 5000);

    return () => clearInterval(interval);
  }, [activeTasks]);

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
  const handleHistoryClick = async (queryId: string, itemStockCode?: string) => {
    analysisRequestIdRef.current += 1;
    setIsLoadingReport(true);
    // 加载该股票的持仓信息
    if (itemStockCode) loadPositionForStock(itemStockCode);
    try {
      const report = await historyApi.getDetail(queryId);
      setSelectedReport(report);
      // 若未传 stockCode，从报告中加载
      if (!itemStockCode && report.meta?.stockCode) {
        loadPositionForStock(report.meta.stockCode);
      }
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

    // 先尝试从 localStorage 恢复该股票的持仓信息（用户可能之前填过）
    // 只有当前表单为空时才自动加载，避免覆盖用户正在编辑的值
    if (!positionAmount && !costPrice) {
      loadPositionForStock(normalized);
    }
    // 持仓信息通过 syncPositionToDb 实时同步到数据库，此处无需额外保存

    const currentRequestId = ++analysisRequestIdRef.current;

    // 只使用当前表单中用户明确填写的持仓信息，不自动读取历史数据
    const effectivePositionInfo: PositionInfo | undefined = buildPositionInfo();

    try {
      const response = await analysisApi.analyzeAsync({
        stockCode: normalized,
        reportType: 'detailed',
        positionInfo: effectivePositionInfo,
      });

      // 直接添加任务到侧边栏（不依赖 SSE）
      setActiveTasks((prev) => {
        if (prev.some((t) => t.taskId === response.taskId)) return prev;
        return [...prev, {
          taskId: response.taskId,
          stockCode: normalized,
          stockName: undefined,
          status: 'pending' as const,
          progress: 0,
          message: response.message || '任务已加入队列',
          reportType: 'detailed',
          createdAt: new Date().toISOString(),
        }];
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

  // 刷新当前报告（重新分析同一只股票）
  const handleRefreshReport = useCallback(async () => {
    if (!selectedReport?.meta?.stockCode) return;
    const code = selectedReport.meta.stockCode;

    setIsAnalyzing(true);
    setDuplicateError(null);
    setStoreError(null);

    // 只使用当前表单中用户明确填写的持仓信息，不自动读取历史数据
    const posInfo: PositionInfo | undefined = buildPositionInfo();

    try {
      const response = await analysisApi.analyzeAsync({
        stockCode: code,
        reportType: 'detailed',
        forceRefresh: true,
        positionInfo: posInfo,
      });

      // 直接添加任务到侧边栏（不依赖 SSE）
      setActiveTasks((prev) => {
        if (prev.some((t) => t.taskId === response.taskId)) return prev;
        return [...prev, {
          taskId: response.taskId,
          stockCode: code,
          stockName: selectedReport?.meta?.stockName,
          status: 'pending' as const,
          progress: 0,
          message: '正在重新分析...',
          reportType: 'detailed',
          createdAt: new Date().toISOString(),
        }];
      });
    } catch (err) {
      if (err instanceof DuplicateTaskError) {
        setDuplicateError(`股票 ${err.stockCode} 正在分析中，请等待完成`);
      } else {
        setStoreError(err instanceof Error ? err.message : '刷新失败');
      }
    } finally {
      setIsAnalyzing(false);
    }
  }, [selectedReport, buildPositionInfo]);

  // 持仓变更：更新 state + 同步数据库 + 触发重新分析
  const handlePositionChange = useCallback(async (newShares: number, newCostPrice: number) => {
    setPositionAmount(String(newShares));
    setCostPrice(String(newCostPrice));
    const code = stockCode || (selectedReport?.meta?.stockCode ?? '');
    if (code) {
      try {
        await portfolioApi.add({
          code,
          name: selectedReport?.meta?.stockName || code,
          costPrice: newCostPrice,
          shares: newShares,
        });
      } catch { /* 静默失败 */ }
    }
    handleRefreshReport();
  }, [stockCode, selectedReport, handleRefreshReport]);

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
        // 批量分析时按各股票的 localStorage 持仓读取，而非全局表单
        const normalized = code;
        const key = `dsa_pos_${normalized.replace(/\./g, '_')}`;
        let stockPositionInfo: import('../types/analysis').PositionInfo | undefined;
        try {
          const raw = localStorage.getItem(key);
          if (raw) {
            const { pa, cp } = JSON.parse(raw);
            const pa_val = pa ? parseFloat(pa) * 10000 : undefined;
            const cp_val = cp ? parseFloat(cp) : undefined;
            if (pa_val || cp_val) {
              stockPositionInfo = { positionAmount: pa_val, costPrice: cp_val };
            }
          }
        } catch { /* ignore */ }
        await analysisApi.analyzeAsync({
          stockCode: code,
          reportType: 'detailed',
          positionInfo: stockPositionInfo,
        });
      } catch (err) {
        if (!(err instanceof DuplicateTaskError)) {
          console.error(`Batch analyze ${code} failed:`, err);
        }
      }
    }
  }, []);

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

          {/* 主视图标签 */}
          <div className="hidden sm:flex items-center gap-0.5 bg-white/[0.04] rounded-lg p-0.5">
            <button
              type="button"
              onClick={() => setMainTab('analysis')}
              className={`px-2.5 py-1 rounded-md text-[12px] font-medium transition-all ${
                mainTab === 'analysis'
                  ? 'bg-white/10 text-white/90'
                  : 'text-white/35 hover:text-white/60'
              }`}
            >
              分析
            </button>
            <button
              type="button"
              onClick={() => setMainTab('backtest')}
              className={`px-2.5 py-1 rounded-md text-[12px] font-medium transition-all ${
                mainTab === 'backtest'
                  ? 'bg-white/10 text-white/90'
                  : 'text-white/35 hover:text-white/60'
              }`}
            >
              回测
            </button>
          </div>

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
                  const val = e.target.value.toUpperCase();
                  setStockCode(val);
                  setInputError(undefined);
                  setDuplicateError(null);
                  // 代码输入完整（≥5位）时 debounce 加载持仓信息
                  if (loadPositionTimerRef.current) clearTimeout(loadPositionTimerRef.current);
                  if (val.length >= 5) {
                    loadPositionTimerRef.current = setTimeout(() => {
                      if (!positionAmount && !costPrice) loadPositionForStock(val);
                    }, 500);
                  }
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
            {/* 持仓按钮 + 弹出浮窗 */}
            <div className="relative">
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

              {/* 持仓信息浮窗 */}
              {showPosition && (
                <div className="absolute top-full right-0 mt-2 w-64 p-3 rounded-xl bg-[#111118] border border-white/10 shadow-xl shadow-black/40 animate-slide-up z-[60]">
                  <div className="text-[11px] text-white/40 font-medium mb-2.5 tracking-wider uppercase">持仓信息</div>
                  <div className="flex flex-col gap-2">
                    <div className="flex items-center justify-between gap-2">
                      <label className="text-[11px] text-white/30 whitespace-nowrap w-16">总资金(万)</label>
                      <input type="number" value={totalCapital} onChange={(e) => setTotalCapital(e.target.value)} placeholder="100" className="header-input flex-1 text-xs py-1.5" />
                    </div>
                    <div className="flex items-center justify-between gap-2">
                      <label className="text-[11px] text-white/30 whitespace-nowrap w-16">持仓(股)</label>
                      <input type="number" value={positionAmount} onChange={(e) => {
                        setPositionAmount(e.target.value);
                        syncPositionToDb(stockCode, e.target.value, costPrice, '');
                      }} placeholder="100" className="header-input flex-1 text-xs py-1.5" />
                    </div>
                    <div className="flex items-center justify-between gap-2">
                      <label className="text-[11px] text-white/30 whitespace-nowrap w-16">成本价</label>
                      <input type="number" step="0.01" value={costPrice} onChange={(e) => {
                        setCostPrice(e.target.value);
                        syncPositionToDb(stockCode, positionAmount, e.target.value, '');
                      }} placeholder="35.00" className="header-input flex-1 text-xs py-1.5" />
                    </div>
                  </div>
                  {(totalCapital || positionAmount) && (() => {
                    const shares = positionAmount ? parseInt(positionAmount) : 0;
                    const cp = costPrice ? parseFloat(costPrice) : 0;
                    const tc = totalCapital ? parseFloat(totalCapital) * 10000 : 0;
                    const posVal = shares > 0 && cp > 0 ? shares * cp : 0;
                    const pct = tc > 0 && posVal > 0 ? (posVal / tc * 100).toFixed(1) : '--';
                    return (
                      <div className="mt-2 pt-2 border-t border-white/5 text-[11px] text-white/40 font-mono text-right">
                        仓位 {pct !== '--' ? `${pct}%` : '--'}
                        {posVal > 0 && <span className="ml-2">持仓市值 {(posVal / 10000).toFixed(2)}万</span>}
                      </div>
                    );
                  })()}
                </div>
              )}
            </div>

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
                const item = historyItems.find(h => h.queryId === queryId);
                handleHistoryClick(queryId, item?.stockCode);
                setSidebarOpen(false);
              }}
              onLoadMore={handleLoadMore}
              className="flex-1 min-h-0 overflow-hidden"
            />
          </div>
        </aside>

        {/* 右侧报告区 */}
        <section className={`flex-1 overflow-y-auto transition-all duration-200 ${mainTab === 'backtest' ? '' : 'p-3 lg:p-4'} ${chatOpen ? 'mr-0' : ''}`}>
          {/* 回测面板 */}
          {mainTab === 'backtest' && <BacktestPanel />}

          {/* 分析面板 */}
          {mainTab === 'analysis' && (
            isLoadingReport ? (
              <div className="flex flex-col items-center justify-center h-full gap-3">
                <div className="w-10 h-10 border-[3px] border-cyan/15 border-t-cyan rounded-full animate-spin" />
                <p className="text-[13px] text-white/30">加载报告中...</p>
              </div>
            ) : selectedReport ? (
              <>
                <div className="max-w-4xl mx-auto animate-fade-in">
                  <ReportSummary
                    data={selectedReport}
                    isHistory
                    onRefresh={handleRefreshReport}
                    isRefreshing={isAnalyzing}
                    shares={positionAmount ? parseInt(positionAmount) : undefined}
                    totalCapital={totalCapital ? parseFloat(totalCapital) * 10000 : undefined}
                    onPositionChange={handlePositionChange}
                  />
                  {/* 加入持仓/关注 快捷操作 */}
                  <QuickAddBar report={selectedReport} />
                </div>

                {/* AI 对话浮动按钮 */}
                {!chatOpen && (
                  <button
                    onClick={() => setChatOpen(true)}
                    className="fixed bottom-6 right-6 z-50 w-12 h-12 rounded-full bg-cyan/20 border border-cyan/30 text-cyan hover:bg-cyan/30 hover:scale-105 shadow-lg shadow-cyan/10 transition-all flex items-center justify-center"
                    title="AI 深度探讨"
                  >
                    <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
                    </svg>
                  </button>
                )}
              </>
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
            )
          )}
        </section>

        {/* AI 对话侧边栏 */}
        {chatOpen && selectedReport?.meta?.queryId && (
          <aside className="w-[380px] flex-shrink-0 h-full animate-slide-left hidden md:block">
            <ChatPanel
              queryId={selectedReport.meta.queryId}
              onClose={() => setChatOpen(false)}
            />
          </aside>
        )}

        {/* 移动端: 对话全屏覆盖 */}
        {chatOpen && selectedReport?.meta?.queryId && (
          <div className="fixed inset-0 z-50 md:hidden">
            <ChatPanel
              queryId={selectedReport.meta.queryId}
              onClose={() => setChatOpen(false)}
            />
          </div>
        )}
      </div>
    </div>
  );
};

export default HomePage;
