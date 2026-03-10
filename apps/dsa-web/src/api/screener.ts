import apiClient from './index';
import { toCamelCase } from './utils';

export interface ScreenerParams {
  minScore?: number;
  maxScore?: number;
  days?: number;
  adviceFilter?: string;
  limit?: number;
}

export interface ScreenerResultItem {
  code: string;
  name: string;
  score: number;
  advice: string;
  analyzedAt: string;
}

export interface ScreenerResponse {
  total: number;
  results: ScreenerResultItem[];
}

export const screenerApi = {
  screen: async (params: ScreenerParams = {}): Promise<ScreenerResponse> => {
    const queryParams: Record<string, string | number> = {};
    if (params.minScore !== undefined) queryParams.min_score = params.minScore;
    if (params.maxScore !== undefined) queryParams.max_score = params.maxScore;
    if (params.days !== undefined) queryParams.days = params.days;
    if (params.adviceFilter) queryParams.advice_filter = params.adviceFilter;
    if (params.limit !== undefined) queryParams.limit = params.limit;

    const { data } = await apiClient.get<Record<string, unknown>>('/api/v1/screener/screen', {
      params: queryParams,
    });

    const result = toCamelCase<ScreenerResponse>(data);
    return {
      total: result.total,
      results: (result.results || []).map(item => toCamelCase<ScreenerResultItem>(item)),
    };
  },
};
