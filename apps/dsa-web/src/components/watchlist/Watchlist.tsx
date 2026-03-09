import React, { useState, useEffect, useCallback } from 'react';
import { Card } from '../common';
import { portfolioApi, type WatchlistItem as ApiWatchlistItem } from '../../api/portfolio';

export interface WatchlistItem {
  code: string;
  name?: string;
  addedAt: string;
  lastScore?: number | null;
  lastAdvice?: string | null;
}

interface WatchlistProps {
  currentCode?: string;
  onAnalyze: (code: string) => void;
  onBatchAnalyze: (codes: string[]) => void;
  isAnalyzing?: boolean;
  scoreMap?: Record<string, { score?: number | null; advice?: string | null }>;
}

function apiItemToLocal(item: ApiWatchlistItem): WatchlistItem {
  return {
    code: item.code,
    name: item.name || undefined,
    addedAt: item.createdAt || new Date().toISOString(),
    lastScore: item.lastScore,
    lastAdvice: item.lastAdvice || null,
  };
}

export const Watchlist: React.FC<WatchlistProps> = ({
  currentCode,
  onAnalyze,
  onBatchAnalyze,
  isAnalyzing = false,
  scoreMap = {},
}) => {
  const [items, setItems] = useState<WatchlistItem[]>([]);
  const [addCode, setAddCode] = useState('');
  const [expanded, setExpanded] = useState(true);
  const [loading, setLoading] = useState(false);

  const fetchItems = useCallback(async () => {
    setLoading(true);
    try {
      const data = await portfolioApi.watchlistList('score');
      setItems(data.map(apiItemToLocal));
    } catch (e) {
      console.error('自选股加载失败', e);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchItems();
  }, [fetchItems]);

  const handleAdd = useCallback(async () => {
    const code = (addCode || currentCode || '').trim().toUpperCase();
    if (!code) return;
    if (items.some(i => i.code === code)) {
      setAddCode('');
      return;
    }
    try {
      await portfolioApi.watchlistAdd({ code });
      setAddCode('');
      fetchItems();
    } catch (e) {
      console.error('添加自选股失败', e);
    }
  }, [addCode, currentCode, items, fetchItems]);

  const handleRemove = useCallback(async (code: string) => {
    try {
      await portfolioApi.watchlistRemove(code);
      setItems(prev => prev.filter(i => i.code !== code));
    } catch (e) {
      console.error('移除自选股失败', e);
    }
  }, []);

  const handleBatchAnalyze = useCallback(() => {
    if (items.length === 0) return;
    onBatchAnalyze(items.map(i => i.code));
  }, [items, onBatchAnalyze]);

  return (
    <Card variant="bordered" padding="sm" className="text-left">
      <button
        type="button"
        className="w-full flex items-center justify-between text-left px-1 py-0.5"
        onClick={() => setExpanded(!expanded)}
      >
        <div className="flex items-center gap-1.5">
          <span className="text-xs font-medium text-cyan">⭐</span>
          <span className="text-xs font-medium text-white">自选股</span>
          <span className="text-[10px] text-muted">({items.length})</span>
        </div>
        <span className="text-[10px] text-muted">{expanded ? '▲' : '▼'}</span>
      </button>

      {expanded && (
        <div className="mt-2 space-y-2">
          {/* 添加输入 */}
          <div className="flex gap-1">
            <input
              type="text"
              value={addCode}
              onChange={e => setAddCode(e.target.value.toUpperCase())}
              onKeyDown={e => { if (e.key === 'Enter') handleAdd(); }}
              placeholder="代码"
              className="input-terminal flex-1 text-xs py-1 px-2"
            />
            <button
              type="button"
              onClick={handleAdd}
              className="text-[10px] px-2 py-1 rounded bg-cyan/10 text-cyan border border-cyan/20 hover:bg-cyan/20 transition-colors"
            >
              +
            </button>
          </div>

          {loading ? (
            <div className="text-[10px] text-muted py-2 text-center">加载中…</div>
          ) : items.length === 0 ? (
            <div className="text-[10px] text-muted py-2 text-center">
              暂无自选股，输入代码添加
            </div>
          ) : (
            <div className="space-y-0.5 max-h-[200px] overflow-y-auto">
              {items.map(item => {
                const apiScore = item.lastScore;
                const apiAdvice = item.lastAdvice;
                const mapEntry = scoreMap[item.code];
                const sc = apiScore ?? mapEntry?.score ?? null;
                const adv = apiAdvice ?? mapEntry?.advice ?? null;
                const scoreColor = sc == null ? '' : sc >= 70 ? 'text-emerald-400' : sc >= 50 ? 'text-amber-400' : 'text-red-400/70';
                return (
                  <div
                    key={item.code}
                    className="group flex items-center justify-between px-2 py-1.5 rounded hover:bg-hover transition-colors cursor-pointer"
                  >
                    <button
                      type="button"
                      onClick={() => onAnalyze(item.code)}
                      disabled={isAnalyzing}
                      className="flex-1 text-left min-w-0"
                    >
                      <div className="flex items-center gap-1.5">
                        <span className="text-xs font-mono text-white hover:text-cyan transition-colors disabled:opacity-50 flex-shrink-0">{item.code}</span>
                        {item.name && <span className="text-muted text-[10px] truncate">{item.name}</span>}
                      </div>
                      {(sc != null || adv) && (
                        <div className="flex items-center gap-1.5 mt-0.5">
                          {sc != null && <span className={`text-[10px] font-mono font-bold ${scoreColor}`}>{sc}</span>}
                          {adv && <span className="text-[9px] text-white/25 truncate max-w-[80px]">{adv}</span>}
                        </div>
                      )}
                    </button>
                    <button
                      type="button"
                      onClick={(e) => { e.stopPropagation(); handleRemove(item.code); }}
                      className="text-[10px] text-muted hover:text-danger opacity-0 group-hover:opacity-100 transition-all px-1"
                      title="移除"
                    >
                      ✕
                    </button>
                  </div>
                );
              })}
            </div>
          )}

          {items.length > 0 && (
            <button
              type="button"
              onClick={handleBatchAnalyze}
              disabled={isAnalyzing}
              className="w-full text-[10px] py-1.5 rounded bg-cyan/10 text-cyan border border-cyan/20 hover:bg-cyan/20 transition-colors disabled:opacity-50"
            >
              {isAnalyzing ? '分析中...' : `一键分析全部 (${items.length})`}
            </button>
          )}
        </div>
      )}
    </Card>
  );
};
