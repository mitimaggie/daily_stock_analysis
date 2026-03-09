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
};
