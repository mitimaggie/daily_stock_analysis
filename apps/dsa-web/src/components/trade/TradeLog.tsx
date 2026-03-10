import React, { useState, useEffect, useCallback } from 'react';
import { tradeLogApi } from '../../api/tradeLog';
import type { TradeLogItem, TradeLogStats, TradeLogCreate } from '../../api/tradeLog';
import { Card } from '../common';

interface TradeLogProps {
  stockCode?: string;
  stockName?: string;
  analysisScore?: number;
  analysisAdvice?: string;
  queryId?: string;
  currentPrice?: number;
}

const ACTION_LABELS: Record<string, { label: string; emoji: string; color: string }> = {
  buy: { label: '买入', emoji: '🟢', color: 'text-success' },
  sell: { label: '卖出', emoji: '🔴', color: 'text-danger' },
  hold: { label: '持有', emoji: '🟡', color: 'text-warning' },
  watch: { label: '观望', emoji: '⚪', color: 'text-muted' },
};

/**
 * 交易日志组件
 * 记录操作 + 事后回顾 + 统计
 */
export const TradeLog: React.FC<TradeLogProps> = ({
  stockCode, stockName, analysisScore, analysisAdvice, queryId, currentPrice,
}) => {
  const [logs, setLogs] = useState<TradeLogItem[]>([]);
  const [stats, setStats] = useState<TradeLogStats | null>(null);
  const [expanded, setExpanded] = useState(false);
  const [showForm, setShowForm] = useState(false);
  const [loading, setLoading] = useState(false);

  // 表单状态
  const [action, setAction] = useState<'buy' | 'sell' | 'hold' | 'watch'>('buy');
  const [price, setPrice] = useState(currentPrice || 0);
  const [shares, setShares] = useState(0);
  const [reason, setReason] = useState('');

  // 复盘状态
  const [reviewingId, setReviewingId] = useState<string | null>(null);
  const [reviewResult, setReviewResult] = useState<'profit' | 'loss' | 'flat'>('profit');
  const [reviewPnl, setReviewPnl] = useState(0);
  const [reviewNote, setReviewNote] = useState('');

  useEffect(() => {
    if (currentPrice) setPrice(currentPrice);
  }, [currentPrice]);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const [logData, statsData] = await Promise.all([
        tradeLogApi.list({ stock_code: stockCode, limit: 20 }),
        tradeLogApi.stats(stockCode),
      ]);
      setLogs(logData);
      setStats(statsData);
    } catch { /* ignore */ }
    setLoading(false);
  }, [stockCode]);

  useEffect(() => {
    if (expanded) fetchData();
  }, [expanded, fetchData]);

  const handleSubmit = async () => {
    if (!stockCode) return;
    const data: TradeLogCreate = {
      stock_code: stockCode,
      stock_name: stockName || '',
      action,
      price,
      shares,
      amount: price * shares,
      reason,
      analysis_score: analysisScore,
      analysis_advice: analysisAdvice || '',
      query_id: queryId || '',
    };
    try {
      await tradeLogApi.create(data);
      setShowForm(false);
      setReason('');
      setShares(0);
      fetchData();
    } catch { /* ignore */ }
  };

  const handleReview = async (logId: string) => {
    try {
      await tradeLogApi.review(logId, {
        review_result: reviewResult,
        review_pnl: reviewPnl,
        review_pnl_pct: price > 0 ? Math.round(reviewPnl / price * 10000) / 100 : 0,
        review_note: reviewNote,
      });
      setReviewingId(null);
      setReviewNote('');
      setReviewPnl(0);
      fetchData();
    } catch { /* ignore */ }
  };

  const handleDelete = async (logId: string) => {
    try {
      await tradeLogApi.delete(logId);
      fetchData();
    } catch { /* ignore */ }
  };

  return (
    <Card variant="bordered" padding="sm">
      <button
        type="button"
        className="w-full flex items-center justify-between text-left"
        onClick={() => setExpanded(!expanded)}
      >
        <h4 className="text-xs font-medium text-cyan">
          📝 交易日志 {stats ? `(${stats.totalTrades}条)` : ''}
        </h4>
        <span className="text-[10px] text-muted">{expanded ? '▲' : '▼'}</span>
      </button>

      {expanded && (
        <div className="mt-2 space-y-2">
          {/* 统计卡片 */}
          {stats && stats.reviewedCount > 0 && (
            <div className="grid grid-cols-4 gap-1 text-[10px] text-center">
              <div className="bg-elevated rounded p-1">
                <div className="text-muted">胜率</div>
                <div className={stats.winRate >= 50 ? 'text-success font-bold' : 'text-danger font-bold'}>
                  {stats.winRate}%
                </div>
              </div>
              <div className="bg-elevated rounded p-1">
                <div className="text-muted">盈亏</div>
                <div className={stats.totalPnl >= 0 ? 'text-success' : 'text-danger'}>
                  {stats.totalPnl >= 0 ? '+' : ''}{stats.totalPnl.toFixed(0)}
                </div>
              </div>
              <div className="bg-elevated rounded p-1">
                <div className="text-muted">已复盘</div>
                <div>{stats.reviewedCount}/{stats.totalTrades}</div>
              </div>
              <div className="bg-elevated rounded p-1">
                <div className="text-muted">跟随建议</div>
                <div>{stats.followedAdviceCount}</div>
              </div>
            </div>
          )}

          {/* 新增记录按钮 */}
          {!showForm ? (
            <button
              type="button"
              className="w-full text-[11px] py-1 rounded bg-cyan/10 text-cyan hover:bg-cyan/20 transition"
              onClick={() => setShowForm(true)}
            >
              + 记录操作
            </button>
          ) : (
            <div className="space-y-1.5 p-2 bg-elevated rounded text-[11px]">
              {/* 操作类型 */}
              <div className="flex gap-1">
                {(['buy', 'sell', 'hold', 'watch'] as const).map(a => (
                  <button
                    key={a}
                    type="button"
                    className={`flex-1 py-0.5 rounded text-[10px] transition ${
                      action === a ? 'bg-cyan text-white font-bold' : 'bg-elevated text-muted hover:text-primary'
                    }`}
                    onClick={() => setAction(a)}
                  >
                    {ACTION_LABELS[a].emoji} {ACTION_LABELS[a].label}
                  </button>
                ))}
              </div>
              {/* 价格和股数 */}
              {(action === 'buy' || action === 'sell') && (
                <div className="flex gap-1">
                  <input
                    type="number"
                    placeholder="价格"
                    value={price || ''}
                    onChange={e => setPrice(Number(e.target.value))}
                    className="flex-1 bg-elevated rounded px-1.5 py-0.5 text-[11px]"
                  />
                  <input
                    type="number"
                    placeholder="股数"
                    value={shares || ''}
                    onChange={e => setShares(Number(e.target.value))}
                    className="flex-1 bg-elevated rounded px-1.5 py-0.5 text-[11px]"
                    step={100}
                  />
                </div>
              )}
              {/* 理由 */}
              <input
                type="text"
                placeholder="操作理由（可选）"
                value={reason}
                onChange={e => setReason(e.target.value)}
                className="w-full bg-elevated rounded px-1.5 py-0.5 text-[11px]"
              />
              {/* 按钮 */}
              <div className="flex gap-1">
                <button
                  type="button"
                  className="flex-1 py-0.5 rounded bg-cyan text-white text-[10px] font-bold"
                  onClick={handleSubmit}
                >
                  保存
                </button>
                <button
                  type="button"
                  className="flex-1 py-0.5 rounded bg-elevated text-muted text-[10px]"
                  onClick={() => setShowForm(false)}
                >
                  取消
                </button>
              </div>
            </div>
          )}

          {/* 记录列表 */}
          {loading ? (
            <div className="text-[10px] text-muted text-center py-2">加载中...</div>
          ) : logs.length === 0 ? (
            <div className="text-[10px] text-muted text-center py-2">暂无记录</div>
          ) : (
            <div className="space-y-1 max-h-48 overflow-y-auto">
              {logs.map(log => {
                const al = ACTION_LABELS[log.action] || ACTION_LABELS.watch;
                return (
                  <div key={log.id} className="bg-elevated rounded p-1.5 text-[10px]">
                    <div className="flex items-center justify-between">
                      <span>
                        <span className={al.color}>{al.emoji} {al.label}</span>
                        {log.price > 0 && <span className="text-muted ml-1">@{log.price}</span>}
                        {log.shares > 0 && <span className="text-muted ml-1">{log.shares}股</span>}
                      </span>
                      <span className="text-muted">{log.createdAt?.slice(5, 16)}</span>
                    </div>
                    {log.reason && <div className="text-muted mt-0.5">{log.reason}</div>}
                    {log.analysisScore != null && (
                      <div className="text-muted mt-0.5">
                        分析评分: {log.analysisScore} | {log.analysisAdvice}
                      </div>
                    )}
                    {/* 复盘结果 */}
                    {log.reviewResult ? (
                      <div className={`mt-0.5 ${log.reviewResult === 'profit' ? 'text-success' : log.reviewResult === 'loss' ? 'text-danger' : 'text-muted'}`}>
                        复盘: {log.reviewResult === 'profit' ? '盈利' : log.reviewResult === 'loss' ? '亏损' : '持平'}
                        {log.reviewPnl !== 0 && ` ${log.reviewPnl > 0 ? '+' : ''}${log.reviewPnl.toFixed(0)}`}
                        {log.reviewNote && ` | ${log.reviewNote}`}
                      </div>
                    ) : (
                      <div className="mt-0.5 flex gap-1">
                        {reviewingId === log.id ? (
                          <div className="flex-1 space-y-1">
                            <div className="flex gap-1">
                              {(['profit', 'loss', 'flat'] as const).map(r => (
                                <button
                                  key={r}
                                  type="button"
                                  className={`flex-1 py-0.5 rounded text-[9px] ${
                                    reviewResult === r ? 'bg-cyan text-white' : 'bg-elevated'
                                  }`}
                                  onClick={() => setReviewResult(r)}
                                >
                                  {r === 'profit' ? '盈利' : r === 'loss' ? '亏损' : '持平'}
                                </button>
                              ))}
                            </div>
                            <div className="flex gap-1">
                              <input
                                type="number"
                                placeholder="盈亏金额"
                                value={reviewPnl || ''}
                                onChange={e => setReviewPnl(Number(e.target.value))}
                                className="flex-1 bg-elevated rounded px-1 py-0.5 text-[9px]"
                              />
                              <input
                                type="text"
                                placeholder="复盘备注"
                                value={reviewNote}
                                onChange={e => setReviewNote(e.target.value)}
                                className="flex-1 bg-elevated rounded px-1 py-0.5 text-[9px]"
                              />
                            </div>
                            <div className="flex gap-1">
                              <button
                                type="button"
                                className="flex-1 py-0.5 rounded bg-cyan text-white text-[9px]"
                                onClick={() => handleReview(log.id)}
                              >
                                保存
                              </button>
                              <button
                                type="button"
                                className="py-0.5 px-1 rounded bg-elevated text-[9px]"
                                onClick={() => setReviewingId(null)}
                              >
                                取消
                              </button>
                            </div>
                          </div>
                        ) : (
                          <>
                            <button
                              type="button"
                              className="text-[9px] text-cyan hover:underline"
                              onClick={() => setReviewingId(log.id)}
                            >
                              复盘
                            </button>
                            <button
                              type="button"
                              className="text-[9px] text-danger/50 hover:text-danger"
                              onClick={() => handleDelete(log.id)}
                            >
                              删除
                            </button>
                          </>
                        )}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}
    </Card>
  );
};
