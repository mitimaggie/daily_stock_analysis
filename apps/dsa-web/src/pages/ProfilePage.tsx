import type React from 'react';
import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { tradeLogApi, type TradeLogStats } from '../api/tradeLog';
import apiClient from '../api/index';

const ChevronRight = () => (
  <svg className="w-4 h-4 text-muted/70" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
    <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
  </svg>
);

const StatCell: React.FC<{ label: string; value: string; sub?: string; color?: string }> = ({ label, value, sub, color = 'text-primary/80' }) => (
  <div className="text-center">
    <div className="text-[10px] text-muted mb-1">{label}</div>
    <div className={`text-[18px] font-bold font-mono ${color}`}>{value}</div>
    {sub && <div className="text-[10px] text-muted mt-0.5">{sub}</div>}
  </div>
);

const ProfilePage: React.FC = () => {
  const navigate = useNavigate();
  const [stats, setStats] = useState<TradeLogStats | null>(null);
  const [statsLoading, setStatsLoading] = useState(true);
  const [statsError, setStatsError] = useState<string | null>(null);
  const [apiHealthy, setApiHealthy] = useState<boolean | null>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);

  useEffect(() => {
    let cancelled = false;

    const fetchStats = async () => {
      try {
        const data = await tradeLogApi.stats();
        if (!cancelled) setStats(data);
      } catch {
        if (!cancelled) setStatsError('加载失败');
      } finally {
        if (!cancelled) setStatsLoading(false);
      }
    };

    const checkHealth = async () => {
      try {
        const res = await apiClient.get('/api/health', { timeout: 5000 });
        if (!cancelled) setApiHealthy(res.status === 200);
      } catch {
        if (!cancelled) setApiHealthy(false);
      }
    };

    fetchStats();
    checkHealth();

    return () => { cancelled = true; };
  }, []);

  const winRate = stats && stats.totalTrades > 0
    ? ((stats.profitCount / stats.reviewedCount) * 100)
    : null;

  const menuItems = [
    { icon: '📋', label: '分析历史', desc: '查看所有分析报告', onClick: () => navigate('/analysis') },
    { icon: '📊', label: '回测工具', desc: '策略回测验证', onClick: () => navigate('/analysis?tab=backtest') },
  ];

  return (
    <div className="min-h-screen pb-6">
      <div className="max-w-3xl mx-auto px-4 py-4 space-y-4">
        {/* 标题 */}
        <h1 className="text-[18px] font-bold text-primary">我的</h1>

        {/* 本月战绩卡片 */}
        <div className="terminal-card p-4">
          <div className="flex items-center gap-2 mb-3">
            <span className="text-[14px]">📈</span>
            <span className="text-[13px] font-medium text-primary/70">本月战绩</span>
            {stats && stats.totalTrades > 0 && (
              <span className="text-[10px] text-muted/70 ml-auto font-mono">{stats.totalTrades}笔交易</span>
            )}
          </div>

          {statsLoading ? (
            <div className="grid grid-cols-3 gap-3 animate-pulse">
              {[1, 2, 3].map(i => (
                <div key={i} className="text-center">
                  <div className="h-3 w-10 bg-black/[0.03] rounded mx-auto mb-2" />
                  <div className="h-6 w-14 bg-black/[0.03] rounded mx-auto" />
                </div>
              ))}
            </div>
          ) : statsError ? (
            <div className="text-center py-4">
              <p className="text-[12px] text-danger">{statsError}</p>
            </div>
          ) : !stats || stats.totalTrades === 0 ? (
            <div className="text-center py-6">
              <p className="text-[13px] text-muted">暂无交易记录</p>
              <p className="text-[11px] text-muted/50 mt-1">在持仓页面记录交易后，这里会显示战绩统计</p>
            </div>
          ) : (
            <div className="grid grid-cols-3 gap-3">
              <StatCell
                label="胜率"
                value={winRate != null && stats.reviewedCount > 0 ? `${winRate.toFixed(0)}%` : '--'}
                sub={stats.reviewedCount > 0 ? `${stats.profitCount}胜/${stats.lossCount}负` : '暂无复盘'}
                color={winRate != null && winRate >= 50 ? 'text-red-600' : winRate != null ? 'text-emerald-600' : 'text-muted'}
              />
              <StatCell
                label="总盈亏"
                value={stats.totalPnl !== 0 ? `${stats.totalPnl >= 0 ? '+' : ''}${(stats.totalPnl / 10000).toFixed(2)}万` : '--'}
                sub={stats.avgPnlPct !== 0 ? `均${stats.avgPnlPct >= 0 ? '+' : ''}${stats.avgPnlPct.toFixed(1)}%` : undefined}
                color={stats.totalPnl > 0 ? 'text-red-600' : stats.totalPnl < 0 ? 'text-emerald-600' : 'text-muted'}
              />
              <StatCell
                label="纪律执行"
                value={stats.followedAdviceCount > 0 ? `${((stats.followedAdviceCount / stats.totalTrades) * 100).toFixed(0)}%` : '--'}
                sub={stats.followedAdviceCount > 0 ? `${stats.followedAdviceCount}/${stats.totalTrades}遵循` : '暂无数据'}
                color="text-cyan"
              />
            </div>
          )}
        </div>

        {/* 功能入口列表 */}
        <div className="terminal-card overflow-hidden">
          {menuItems.map((item, idx) => (
            <button
              key={item.label}
              type="button"
              onClick={item.onClick}
              className={`w-full flex items-center gap-3 px-4 py-3.5 hover:bg-black/[0.02] transition text-left ${
                idx < menuItems.length - 1 ? 'border-b border-black/[0.05]' : ''
              }`}
            >
              <span className="text-[16px] flex-shrink-0">{item.icon}</span>
              <div className="flex-1 min-w-0">
                <div className="text-[13px] text-primary/80 font-medium">{item.label}</div>
                <div className="text-[11px] text-muted">{item.desc}</div>
              </div>
              <ChevronRight />
            </button>
          ))}

          {/* 系统设置 - 可展开 */}
          <button
            type="button"
            onClick={() => setSettingsOpen(v => !v)}
            className="w-full flex items-center gap-3 px-4 py-3.5 hover:bg-black/[0.02] transition text-left border-t border-black/[0.05]"
          >
            <span className="text-[16px] flex-shrink-0">⚙️</span>
            <div className="flex-1 min-w-0">
              <div className="text-[13px] text-primary/80 font-medium">系统设置</div>
              <div className="text-[11px] text-muted">版本与服务状态</div>
            </div>
            <svg
              className={`w-4 h-4 text-muted/70 transition-transform duration-200 ${settingsOpen ? 'rotate-90' : ''}`}
              fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24"
            >
              <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
            </svg>
          </button>

          {/* 系统设置展开区域 */}
          {settingsOpen && (
            <div className="px-4 pb-4 pt-1 space-y-2.5 animate-slide-up">
              <div className="flex items-center justify-between">
                <span className="text-[12px] text-muted">版本号</span>
                <span className="text-[12px] text-secondary font-mono">v1.0.0</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-[12px] text-muted">API 状态</span>
                <span className="flex items-center gap-1.5">
                  <span className={`w-2 h-2 rounded-full ${
                    apiHealthy === null ? 'bg-muted/70 animate-pulse' : apiHealthy ? 'bg-emerald-400' : 'bg-red-400'
                  }`} />
                  <span className={`text-[12px] font-mono ${
                    apiHealthy === null ? 'text-muted' : apiHealthy ? 'text-emerald-400' : 'text-red-400'
                  }`}>
                    {apiHealthy === null ? '检查中' : apiHealthy ? '正常' : '离线'}
                  </span>
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-[12px] text-muted">数据源</span>
                <span className="text-[12px] text-secondary font-mono">A股 · 实时</span>
              </div>
            </div>
          )}
        </div>

        {/* 底部提示 */}
        <p className="text-[10px] text-muted/40 text-center pt-2">
          DSA · A股散户智能分析助手
        </p>
      </div>
    </div>
  );
};

export default ProfilePage;
