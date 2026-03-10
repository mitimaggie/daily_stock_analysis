import apiClient from './index';
import { toCamelCase } from './utils';

// ─── 类型定义 ─────────────────────────────────

export interface PortfolioItem {
  id: number;
  code: string;
  name: string;
  costPrice: number;
  shares: number;
  entryDate: string | null;
  notes: string;
  atrStopLoss: number | null;
  highestPrice: number | null;
  lastSignal: string;
  lastSignalReason: string;
  lastMonitoredAt: string | null;
  holdingHorizonLabel: string | null;
  createdAt: string | null;
}

export interface PortfolioLog {
  id: number;
  code: string;
  action: string;
  price: number | null;
  shares: number | null;
  reason: string;
  triggeredBy: string;
  createdAt: string | null;
}

export interface MonitorSignal {
  code: string;
  name: string;
  costPrice: number;
  shares: number;
  entryDate: string | null;
  currentPrice: number | null;
  pnlPct: number | null;
  atr: number;
  atrStop: number;
  highestPrice: number;
  stopPnlPct: number;
  signal: 'hold' | 'reduce' | 'stop_loss' | 'add_watch' | 'unknown';
  signalText: string;
  reasons: string[];
  intraday: {
    monitorSignal: string;
    vwap: number;
    vwapPosition: string;
    intradayTrend: string;
    volumeDistribution: string;
    momentum: string;
    summary: string;
  };
  lastMonitoredAt: string;
}

export interface WatchlistItem {
  id: number;
  code: string;
  name: string;
  notes: string;
  lastScore: number | null;
  lastAdvice: string;
  lastSummary: string;
  lastAnalyzedAt: string | null;
  prevScore: number | null;
  scoreChange: number | null;
  createdAt: string | null;
}

export interface SimpleViewData {
  code: string;
  name: string;
  signal: string;
  signal_color: string;
  signal_emoji: string;
  signal_text: string;
  current_price: number | null;
  pnl_pct: number | null;
  atr_stop: number | null;
  cost_price: number | null;
  holding_horizon_label: string | null;
  next_review_at: string | null;
  advice_short: string;
  analysis_summary: string;
  score: number | null;
  analyzed_at: string | null;
}

// ─── API 客户端 ───────────────────────────────

export const portfolioApi = {
  // 持仓 CRUD
  list: async (): Promise<PortfolioItem[]> => {
    const res = await apiClient.get<{ items: unknown[] }>('/api/v1/portfolio');
    return (res.data.items || []).map(i => toCamelCase<PortfolioItem>(i as Record<string, unknown>));
  },

  add: async (params: {
    code: string; name?: string; costPrice: number;
    shares?: number; entryDate?: string; notes?: string;
    holdingHorizonLabel?: string;
  }): Promise<PortfolioItem> => {
    const body = {
      code: params.code,
      name: params.name || '',
      cost_price: params.costPrice,
      shares: params.shares || 0,
      entry_date: params.entryDate || null,
      notes: params.notes || '',
      holding_horizon_label: params.holdingHorizonLabel || null,
    };
    const res = await apiClient.post<{ item: unknown }>('/api/v1/portfolio', body);
    return toCamelCase<PortfolioItem>(res.data.item as Record<string, unknown>);
  },

  get: async (code: string): Promise<PortfolioItem | null> => {
    try {
      const res = await apiClient.get<{ item: unknown }>(`/api/v1/portfolio/${code}`);
      return toCamelCase<PortfolioItem>(res.data.item as Record<string, unknown>);
    } catch {
      return null;
    }
  },

  remove: async (code: string): Promise<void> => {
    await apiClient.delete(`/api/v1/portfolio/${code}`);
  },

  // 持仓监控
  monitor: async (): Promise<{ signals: MonitorSignal[]; concentrationWarnings: string[]; portfolioSize: number; totalMarketValue: number }> => {
    const res = await apiClient.get<{ signals: unknown[]; concentration_warnings?: string[]; portfolio_size?: number; total_market_value?: number }>('/api/v1/portfolio/monitor/signals');
    return {
      signals: (res.data.signals || []).map(s => toCamelCase<MonitorSignal>(s as Record<string, unknown>)),
      concentrationWarnings: res.data.concentration_warnings || [],
      portfolioSize: res.data.portfolio_size || 0,
      totalMarketValue: res.data.total_market_value || 0,
    };
  },

  // 更新总资金配置
  updateCapital: async (value: number): Promise<boolean> => {
    try {
      const res = await apiClient.post<{ success: boolean }>('/api/v1/config/update', {
        PORTFOLIO_SIZE: String(value),
      });
      return res.data.success;
    } catch { return false; }
  },

  // 关注股 CRUD
  watchlistList: async (sortBy: string = 'score'): Promise<WatchlistItem[]> => {
    const res = await apiClient.get<{ items: unknown[] }>('/api/v1/watchlist', {
      params: { sort_by: sortBy },
    });
    return (res.data.items || []).map(i => toCamelCase<WatchlistItem>(i as Record<string, unknown>));
  },

  watchlistAdd: async (params: { code: string; name?: string; notes?: string }): Promise<WatchlistItem> => {
    const res = await apiClient.post<{ item: unknown }>('/api/v1/watchlist', {
      code: params.code,
      name: params.name || '',
      notes: params.notes || '',
    });
    return toCamelCase<WatchlistItem>(res.data.item as Record<string, unknown>);
  },

  watchlistRemove: async (code: string): Promise<void> => {
    await apiClient.delete(`/api/v1/watchlist/${code}`);
  },

  watchlistSync: async (code: string, score: number, advice: string, summary: string): Promise<void> => {
    await apiClient.post(`/api/v1/watchlist/${code}/sync`, null, {
      params: { score, advice, summary },
    });
  },

  // P6: 散户简化视图
  getSimpleView: async (code: string): Promise<SimpleViewData> => {
    const res = await apiClient.get<SimpleViewData>(`/api/v1/portfolio/${code}/simple`);
    return res.data;
  },

  // P5: 刷新再分析日期
  refreshReviewDate: async (code: string): Promise<string | null> => {
    try {
      const res = await apiClient.post<{ next_review_at: string | null }>(`/api/v1/portfolio/${code}/refresh-review-date`);
      return res.data.next_review_at;
    } catch { return null; }
  },

  // 操作日志
  getLogs: async (code: string, limit = 20): Promise<PortfolioLog[]> => {
    const res = await apiClient.get<{ logs: unknown[] }>(`/api/v1/portfolio/${code}/logs`, { params: { limit } });
    return (res.data.logs || []).map(l => toCamelCase<PortfolioLog>(l as Record<string, unknown>));
  },

  addLog: async (code: string, params: {
    action: string; price?: number; shares?: number; reason?: string; triggeredBy?: string;
  }): Promise<PortfolioLog> => {
    const res = await apiClient.post<{ log: unknown }>(`/api/v1/portfolio/${code}/logs`, {
      action: params.action,
      price: params.price ?? null,
      shares: params.shares ?? null,
      reason: params.reason || '',
      triggered_by: params.triggeredBy || 'manual',
    });
    return toCamelCase<PortfolioLog>(res.data.log as Record<string, unknown>);
  },

  // 持仓周期
  getHorizonSuggestion: async (code: string): Promise<string | null> => {
    try {
      const res = await apiClient.get<{ suggestion: string | null }>(`/api/v1/portfolio/${code}/horizon-suggestion`);
      return res.data.suggestion;
    } catch { return null; }
  },

  updateHorizon: async (code: string, label: string): Promise<void> => {
    await apiClient.put(`/api/v1/portfolio/${code}/horizon`, { holding_horizon_label: label });
  },

  recordTrade: async (code: string, data: { action: string; shares: number; price: number; reason?: string }): Promise<void> => {
    await apiClient.post(`/api/v1/portfolio/${code}/trade`, data);
  },

  updateCost: async (code: string, data: { cost_price: number; shares?: number }): Promise<void> => {
    await apiClient.put(`/api/v1/portfolio/${code}/cost`, data);
  },
};
