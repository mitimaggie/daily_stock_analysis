import apiClient from './index';
import { toCamelCase } from './utils';
import type { MarketOverview, MarketTodoList } from '../types/market';

export const marketApi = {
  getOverview: async (): Promise<MarketOverview> => {
    const { data } = await apiClient.get('/api/v1/market/overview');
    return toCamelCase<MarketOverview>(data);
  },
  getTodoList: async (): Promise<MarketTodoList> => {
    const { data } = await apiClient.get('/api/v1/market/todo-list');
    return toCamelCase<MarketTodoList>(data);
  },
  getConceptHoldings: async (codes: string[]): Promise<Record<string, string[]>> => {
    try {
      const { data } = await apiClient.post<{ mapping: Record<string, string[]> }>('/api/v1/market/concept-holdings', { codes });
      return data.mapping || {};
    } catch {
      return {};
    }
  },
};
