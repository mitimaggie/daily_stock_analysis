/**
 * 交易日志 API
 */
import apiClient from './index';
import { toCamelCase } from './utils';

export interface TradeLogCreate {
  stock_code: string;
  stock_name?: string;
  action: 'buy' | 'sell' | 'hold' | 'watch';
  price?: number;
  shares?: number;
  amount?: number;
  reason?: string;
  analysis_score?: number;
  analysis_advice?: string;
  query_id?: string;
  note?: string;
}

export interface TradeLogItem {
  id: string;
  stockCode: string;
  stockName: string;
  action: string;
  price: number;
  shares: number;
  amount: number;
  reason: string;
  analysisScore: number | null;
  analysisAdvice: string;
  queryId: string;
  note: string;
  createdAt: string;
  reviewResult: string;
  reviewPnl: number;
  reviewPnlPct: number;
  reviewNote: string;
  reviewedAt: string;
}

export interface TradeLogStats {
  totalTrades: number;
  buyCount: number;
  sellCount: number;
  reviewedCount: number;
  profitCount: number;
  lossCount: number;
  winRate: number;
  totalPnl: number;
  avgPnlPct: number;
  followedAdviceCount: number;
}

export interface TradeLogReview {
  review_result: 'profit' | 'loss' | 'flat';
  review_pnl?: number;
  review_pnl_pct?: number;
  review_note?: string;
}

export const tradeLogApi = {
  async create(data: TradeLogCreate): Promise<TradeLogItem> {
    const res = await apiClient.post('/api/v1/trade-log/', data);
    return toCamelCase<TradeLogItem>(res.data);
  },

  async list(params?: { stock_code?: string; action?: string; limit?: number }): Promise<TradeLogItem[]> {
    const res = await apiClient.get('/api/v1/trade-log/', { params });
    return (res.data as unknown[]).map(item => toCamelCase<TradeLogItem>(item));
  },

  async stats(stockCode?: string): Promise<TradeLogStats> {
    const res = await apiClient.get('/api/v1/trade-log/stats', {
      params: stockCode ? { stock_code: stockCode } : undefined,
    });
    return toCamelCase<TradeLogStats>(res.data);
  },

  async review(logId: string, data: TradeLogReview): Promise<TradeLogItem> {
    const res = await apiClient.put(`/api/v1/trade-log/${logId}/review`, data);
    return toCamelCase<TradeLogItem>(res.data);
  },

  async delete(logId: string): Promise<void> {
    await apiClient.delete(`/api/v1/trade-log/${logId}`);
  },
};
