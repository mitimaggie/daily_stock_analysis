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
  }): Promise<PortfolioItem> => {
    const body = {
      code: params.code,
      name: params.name || '',
      cost_price: params.costPrice,
      shares: params.shares || 0,
      entry_date: params.entryDate || null,
      notes: params.notes || '',
    };
    const res = await apiClient.post<{ item: unknown }>('/api/v1/portfolio', body);
    return toCamelCase<PortfolioItem>(res.data.item as Record<string, unknown>);
  },

  remove: async (code: string): Promise<void> => {
    await apiClient.delete(`/api/v1/portfolio/${code}`);
  },

  // 持仓监控
  monitor: async (): Promise<MonitorSignal[]> => {
    const res = await apiClient.get<{ signals: unknown[] }>('/api/v1/portfolio/monitor/signals');
    return (res.data.signals || []).map(s => toCamelCase<MonitorSignal>(s as Record<string, unknown>));
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
};
