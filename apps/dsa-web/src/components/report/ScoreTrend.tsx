import type React from 'react';
import { useState, useEffect } from 'react';
import { historyApi } from '../../api/history';
import type { HistoryItem } from '../../types/analysis';
import { Card } from '../common';

interface ScoreTrendProps {
  stockCode: string;
  currentQueryId?: string;
}

/**
 * 历史评分趋势组件
 * 展示同一只股票最近的评分变化
 */
export const ScoreTrend: React.FC<ScoreTrendProps> = ({ stockCode, currentQueryId }) => {
  const [items, setItems] = useState<HistoryItem[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    const fetch = async () => {
      setLoading(true);
      try {
        const res = await historyApi.getList({ stockCode, limit: 10 });
        if (!cancelled) setItems(res.items);
      } catch { /* ignore */ }
      if (!cancelled) setLoading(false);
    };
    if (stockCode) fetch();
    return () => { cancelled = true; };
  }, [stockCode]);

  // 至少需要2条记录才有趋势意义
  if (loading || items.length < 2) return null;

  // 按时间正序（旧→新）
  const sorted = [...items].reverse();
  const scores = sorted.map(i => i.sentimentScore ?? 50);
  const maxScore = Math.max(...scores, 80);
  const minScore = Math.min(...scores, 20);
  const range = Math.max(maxScore - minScore, 20);

  return (
    <Card variant="bordered" padding="sm">
      <h4 className="text-xs font-medium text-cyan mb-2">历史评分趋势（近{sorted.length}次）</h4>
      <div className="flex items-end gap-1 h-16">
        {sorted.map((item) => {
          const score = item.sentimentScore ?? 50;
          const height = Math.max(((score - minScore) / range) * 100, 8);
          const isCurrent = item.queryId === currentQueryId;
          const color = score >= 60 ? 'bg-success' : score >= 40 ? 'bg-warning' : 'bg-danger';
          return (
            <div
              key={item.queryId}
              className="flex-1 flex flex-col items-center gap-0.5"
              title={`${item.createdAt?.slice(0, 10)} | ${item.operationAdvice} | 评分 ${score}`}
            >
              <span className="text-[9px] text-muted font-mono">{score}</span>
              <div
                className={`w-full rounded-t ${color} ${isCurrent ? 'ring-1 ring-cyan' : ''} transition-all`}
                style={{ height: `${height}%` }}
              />
              <span className="text-[8px] text-muted/50 font-mono truncate w-full text-center">
                {item.createdAt?.slice(5, 10) || ''}
              </span>
            </div>
          );
        })}
      </div>
      {/* 趋势摘要 */}
      {scores.length >= 2 && (() => {
        const latest = scores[scores.length - 1];
        const prev = scores[scores.length - 2];
        const diff = latest - prev;
        if (diff === 0) return null;
        const arrow = diff > 0 ? '↑' : '↓';
        const color = diff > 0 ? 'text-success' : 'text-danger';
        return (
          <p className={`text-[10px] mt-1 ${color}`}>
            较上次 {arrow}{Math.abs(diff)} 分
          </p>
        );
      })()}
    </Card>
  );
};
