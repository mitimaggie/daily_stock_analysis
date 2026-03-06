import React, { useState, useEffect, useCallback } from 'react';
import { Card } from '../common';

const STORAGE_KEY = 'dsa_watchlist';

export interface WatchlistItem {
  code: string;
  name?: string;
  addedAt: string;
}

interface WatchlistProps {
  /** 当前输入框中的股票代码 */
  currentCode?: string;
  /** 点击自选股触发分析 */
  onAnalyze: (code: string) => void;
  /** 批量分析 */
  onBatchAnalyze: (codes: string[]) => void;
  /** 是否正在分析 */
  isAnalyzing?: boolean;
  /** 最近一次分析结果摘要（代码 → 评分/建议） */
  scoreMap?: Record<string, { score?: number | null; advice?: string | null }>;
}

/** 从 localStorage 读取自选股列表 */
function loadWatchlist(): WatchlistItem[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? JSON.parse(raw) : [];
  } catch {
    return [];
  }
}

/** 保存自选股列表到 localStorage */
function saveWatchlist(items: WatchlistItem[]) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(items));
}

/**
 * 自选股列表组件
 * 支持添加/删除/一键批量分析
 */
export const Watchlist: React.FC<WatchlistProps> = ({
  currentCode,
  onAnalyze,
  onBatchAnalyze,
  isAnalyzing = false,
  scoreMap = {},
}) => {
  const [items, setItems] = useState<WatchlistItem[]>(loadWatchlist);
  const [addCode, setAddCode] = useState('');
  const [expanded, setExpanded] = useState(true);

  // 持久化
  useEffect(() => {
    saveWatchlist(items);
  }, [items]);

  const handleAdd = useCallback(() => {
    const code = (addCode || currentCode || '').trim().toUpperCase();
    if (!code) return;
    if (items.some(i => i.code === code)) {
      setAddCode('');
      return;
    }
    setItems(prev => [...prev, { code, addedAt: new Date().toISOString() }]);
    setAddCode('');
  }, [addCode, currentCode, items]);

  const handleRemove = useCallback((code: string) => {
    setItems(prev => prev.filter(i => i.code !== code));
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

          {/* 列表 */}
          {items.length === 0 ? (
            <div className="text-[10px] text-muted py-2 text-center">
              暂无自选股，输入代码添加
            </div>
          ) : (
            <div className="space-y-0.5 max-h-[200px] overflow-y-auto">
              {items.map(item => (
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
                    {scoreMap[item.code] && (() => {
                      const s = scoreMap[item.code];
                      const sc = s.score;
                      const adv = s.advice;
                      if (sc == null && !adv) return null;
                      const scoreColor = sc == null ? '' : sc >= 70 ? 'text-emerald-400' : sc >= 50 ? 'text-amber-400' : 'text-red-400/70';
                      return (
                        <div className="flex items-center gap-1.5 mt-0.5">
                          {sc != null && <span className={`text-[10px] font-mono font-bold ${scoreColor}`}>{sc}</span>}
                          {adv && <span className="text-[9px] text-white/25 truncate max-w-[80px]">{adv}</span>}
                        </div>
                      );
                    })()}
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
              ))}
            </div>
          )}

          {/* 批量分析按钮 */}
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
