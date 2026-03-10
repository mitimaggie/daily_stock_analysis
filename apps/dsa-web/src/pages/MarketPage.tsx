import type React from 'react';
import { useState, useEffect } from 'react';
import { marketApi } from '../api/market';
import type { MarketOverview, MarketTodoList } from '../types/market';
import TrafficLight from '../components/market/TrafficLight';
import TodoListCard from '../components/market/TodoListCard';
import ConceptHeatMap from '../components/market/ConceptHeatMap';
import LimitPoolStats from '../components/market/LimitPoolStats';

const SkeletonCard: React.FC<{ height?: string }> = ({ height = 'h-40' }) => (
  <div className={`terminal-card p-4 ${height} animate-pulse`}>
    <div className="h-4 w-32 bg-black/[0.03] rounded mb-4" />
    <div className="space-y-3">
      <div className="h-3 bg-black/[0.03] rounded w-3/4" />
      <div className="h-3 bg-black/[0.03] rounded w-1/2" />
    </div>
  </div>
);

const MarketPage: React.FC = () => {
  const [overview, setOverview] = useState<MarketOverview | null>(null);
  const [todoList, setTodoList] = useState<MarketTodoList | null>(null);
  const [loadingOverview, setLoadingOverview] = useState(true);
  const [loadingTodo, setLoadingTodo] = useState(true);
  const [overviewError, setOverviewError] = useState<string | null>(null);
  const [todoError, setTodoError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    const fetchOverview = async () => {
      try {
        const data = await marketApi.getOverview();
        if (!cancelled) setOverview(data);
      } catch (err) {
        if (!cancelled) setOverviewError(err instanceof Error ? err.message : '加载失败');
      } finally {
        if (!cancelled) setLoadingOverview(false);
      }
    };

    const fetchTodo = async () => {
      try {
        const data = await marketApi.getTodoList();
        if (!cancelled) setTodoList(data);
      } catch (err) {
        if (!cancelled) setTodoError(err instanceof Error ? err.message : '加载失败');
      } finally {
        if (!cancelled) setLoadingTodo(false);
      }
    };

    fetchOverview();
    fetchTodo();

    return () => { cancelled = true; };
  }, []);

  return (
    <div className="min-h-screen pb-6">
      <div className="max-w-7xl mx-auto px-4 py-4 space-y-4">
        {/* 页面标题 */}
        <div className="flex items-center justify-between">
          <h1 className="text-[18px] font-bold text-primary">市场概览</h1>
          <span className="text-[11px] text-muted font-mono">
            {new Date().toLocaleDateString('zh-CN', { month: 'long', day: 'numeric', weekday: 'short' })}
          </span>
        </div>

        {/* 双栏布局：lg 以上左右分栏 */}
        <div className="lg:grid lg:grid-cols-2 lg:gap-6 space-y-4 lg:space-y-0">
          {/* 左栏 */}
          <div className="space-y-4">
            {/* 红绿灯 */}
            {loadingOverview ? (
              <SkeletonCard height="h-56" />
            ) : overviewError ? (
              <div className="terminal-card p-4">
                <p className="text-[13px] text-danger text-center">{overviewError}</p>
              </div>
            ) : overview?.trafficLight ? (
              <TrafficLight data={overview.trafficLight} sentiment={overview.sentiment} />
            ) : null}

            {/* 今日操作清单 */}
            {loadingTodo ? (
              <SkeletonCard height="h-32" />
            ) : todoError ? (
              <div className="terminal-card p-4">
                <p className="text-[13px] text-danger text-center">{todoError}</p>
              </div>
            ) : (
              <TodoListCard todos={todoList?.todos ?? []} />
            )}
          </div>

          {/* 右栏 */}
          <div className="space-y-4">
            {/* 概念热度 */}
            {loadingOverview ? (
              <SkeletonCard height="h-64" />
            ) : (
              <ConceptHeatMap concepts={overview?.concepts ?? null} />
            )}

            {/* 涨跌停统计 */}
            {loadingOverview ? (
              <SkeletonCard height="h-48" />
            ) : overview?.sentiment ? (
              <LimitPoolStats data={overview.sentiment} />
            ) : null}
          </div>
        </div>
      </div>
    </div>
  );
};

export default MarketPage;
