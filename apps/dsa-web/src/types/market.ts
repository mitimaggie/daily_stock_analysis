/** 市场概览相关类型定义 */

export interface TrafficLightData {
  signal: 'active' | 'cautious' | 'wait' | 'cash' | 'unavailable';
  signalLabel: string;
  signalColor: string;
  reason: string;
  score: number | null;
}

export interface SentimentData {
  limitUp: number;
  limitDown: number;
  broken: number;
  brokenRate: number;
  emotionTemp: number | null;
  advanceCount: number;
  declineCount: number;
  flatCount: number;
  emotionLabel?: string;
}

export interface ConceptItem {
  name: string;
  code: string;
  pctChg: number;
  amount: number;
  leadingStock: string;
  rank: number;
  heatType: string;
}

export interface MarketOverview {
  trafficLight: TrafficLightData;
  sentiment: SentimentData;
  concepts: ConceptItem[] | null;
}

export interface TodoItem {
  type: 'stop_loss' | 'concept_decay' | 'entry_ready' | 'score_change';
  priority: 'high' | 'medium' | 'low';
  code: string;
  name: string;
  message: string;
  detail?: string;
  analyzedAt?: string;
}

export interface MarketTodoList {
  todos: TodoItem[];
}
