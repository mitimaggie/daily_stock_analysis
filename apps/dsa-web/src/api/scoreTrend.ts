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

export interface TimeframeWinrates {
  stock_code: string;
  signal_score: number;
  score_range: string;
  weekly_trend: string;
  n: number;
  wr5d: number | null;
  avg5d: number | null;
  wr10d: number | null;
  avg10d: number | null;
  wr20d: number | null;
  avg20d: number | null;
  best_horizon: '5d' | '10d' | '20d' | null;
}

export const scoreTrendApi = {
  getTrend: async (stockCode: string, days = 10): Promise<ScoreTrendResponse> => {
    const resp = await apiClient.get<ScoreTrendResponse>(
      `/api/v1/stocks/${stockCode}/score-trend`,
      { params: { days } },
    );
    return resp.data;
  },

  getTimeframeWinrates: async (
    stockCode: string,
    signalScore: number,
    weeklyTrend = '',
  ): Promise<TimeframeWinrates> => {
    const resp = await apiClient.get<TimeframeWinrates>(
      `/api/v1/stocks/${stockCode}/timeframe-winrates`,
      { params: { signal_score: signalScore, weekly_trend: weeklyTrend } },
    );
    return resp.data;
  },

  getLastSkill: async (stockCode: string): Promise<{ last_skill: string | null; prev_skill: string | null }> => {
    const resp = await apiClient.get<{ stock_code: string; last_skill: string | null; prev_skill: string | null }>(
      `/api/v1/stocks/${stockCode}/last-skill`,
    );
    return resp.data;
  },
};
