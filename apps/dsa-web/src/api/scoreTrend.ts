import apiClient from './index';

export interface ScoreTrend {
  scores: Array<{ date: string; score: number; advice: string }>;
  trend_direction: 'improving' | 'declining' | 'stable';
  inflection: string;
  avg_score: number;
  score_change: number;
  consecutive_up: number;
  consecutive_down: number;
  summary: string;
}

export interface ScoreTrendResponse {
  stock_code: string;
  trend: ScoreTrend;
}

export const scoreTrendApi = {
  getTrend: async (stockCode: string, days = 10): Promise<ScoreTrendResponse> => {
    const resp = await apiClient.get<ScoreTrendResponse>(
      `/api/v1/stocks/${stockCode}/score-trend`,
      { params: { days } },
    );
    return resp.data;
  },
};
