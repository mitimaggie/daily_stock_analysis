/**
 * 全局快速查股命令面板
 * Cmd+K / Ctrl+K 唤起，输入股票代码或名称联想跳转分析页
 */

import type React from 'react';
import { useState, useEffect, useRef, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { historyApi } from '../api/history';
import type { HistoryItem } from '../types/analysis';
import { mapAdviceDisplay } from '../types/analysis';
import { getRecentStartDate, toDateInputValue } from '../utils/format';

interface CommandPaletteProps {
  open: boolean;
  onClose: () => void;
}

const CACHE_TTL_MS = 5 * 60 * 1000;
let _cachedItems: HistoryItem[] = [];
let _cachedAt = 0;

export const CommandPalette: React.FC<CommandPaletteProps> = ({ open, onClose }) => {
  const navigate = useNavigate();
  const [query, setQuery] = useState('');
  const [historyItems, setHistoryItems] = useState<HistoryItem[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [highlightIndex, setHighlightIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  const fetchHistory = useCallback(async () => {
    if (Date.now() - _cachedAt < CACHE_TTL_MS && _cachedItems.length > 0) {
      setHistoryItems(_cachedItems);
      return;
    }
    setIsLoading(true);
    try {
      const response = await historyApi.getList({
        startDate: getRecentStartDate(30),
        endDate: toDateInputValue(new Date()),
        page: 1,
        limit: 100,
      });
      const seen = new Set<string>();
      const deduped = response.items.filter((item) => {
        if (seen.has(item.stockCode)) return false;
        seen.add(item.stockCode);
        return true;
      });
      _cachedItems = deduped;
      _cachedAt = Date.now();
      setHistoryItems(deduped);
    } catch (err) {
      console.error('CommandPalette fetch history failed:', err);
      setHistoryItems([]);
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    if (open) {
      setQuery('');
      setHighlightIndex(0);
      fetchHistory();
      inputRef.current?.focus();
    }
  }, [open, fetchHistory]);

  const q = query.trim().toUpperCase();
  const filtered = historyItems.filter((item) => {
    const code = item.stockCode.toUpperCase();
    const name = (item.stockName || '').toUpperCase();
    return code.includes(q) || name.includes(q);
  }).slice(0, 8);

  const handleSelect = useCallback(
    (item: HistoryItem) => {
      navigate(`/analysis?stock=${item.stockCode}`);
      onClose();
    },
    [navigate, onClose]
  );

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Escape') {
      e.preventDefault();
      onClose();
      return;
    }
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setHighlightIndex((prev) => (prev < filtered.length - 1 ? prev + 1 : prev));
      return;
    }
    if (e.key === 'ArrowUp') {
      e.preventDefault();
      setHighlightIndex((prev) => (prev > 0 ? prev - 1 : prev));
      return;
    }
    if (e.key === 'Enter' && filtered.length > 0) {
      e.preventDefault();
      handleSelect(filtered[highlightIndex]);
      return;
    }
  };

  if (!open) return null;

  const isMac = typeof navigator !== 'undefined' && /Mac|iPod|iPhone|iPad/.test(navigator.platform);
  const shortcutHint = isMac ? '⌘K' : 'Ctrl+K';

  return (
    <div
      className="fixed inset-0 z-[100] flex items-start justify-center pt-[15vh] bg-black/60 backdrop-blur-sm animate-fade-in"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-label="快速查股"
    >
      <div
        className="w-full max-w-lg rounded-xl bg-card border border-black/[0.08] shadow-xl overflow-hidden animate-slide-up"
        onClick={(e) => e.stopPropagation()}
      >
        {/* 输入框 */}
        <div className="flex items-center gap-2 px-3 py-2 border-b border-black/[0.06]">
          <span className="text-[11px] text-muted px-2 py-1 rounded bg-black/[0.04] border border-black/[0.06] font-mono">
            {shortcutHint}
          </span>
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setHighlightIndex(0);
            }}
            onKeyDown={handleKeyDown}
            placeholder="输入股票代码或名称..."
            className="flex-1 text-[14px] text-primary placeholder-muted bg-transparent focus:outline-none py-1.5"
            autoComplete="off"
          />
        </div>

        {/* 结果列表 */}
        <div className="max-h-[320px] overflow-y-auto">
          {isLoading ? (
            <div className="flex items-center justify-center py-8 gap-2">
              <div className="w-4 h-4 border-2 border-cyan/20 border-t-cyan rounded-full animate-spin" />
              <span className="text-[12px] text-muted">加载历史记录...</span>
            </div>
          ) : filtered.length === 0 ? (
            <div className="py-8 text-center text-[12px] text-muted">
              {q ? '无匹配结果' : '输入股票代码或名称进行搜索'}
            </div>
          ) : (
            <ul className="py-1">
              {filtered.map((item, idx) => {
                const score = item.sentimentScore;
                const scoreColor =
                  score == null
                    ? 'text-muted'
                    : score >= 70
                      ? 'text-emerald-600'
                      : score >= 50
                        ? 'text-yellow-500'
                        : 'text-red-600';
                const isHighlight = idx === highlightIndex;
                return (
                  <li key={item.stockCode + item.queryId}>
                    <button
                      type="button"
                      onClick={() => handleSelect(item)}
                      onMouseEnter={() => setHighlightIndex(idx)}
                      className={`w-full flex items-center gap-3 px-3 py-2.5 text-left transition ${
                        isHighlight ? 'bg-cyan/10 border-l-2 border-cyan' : 'hover:bg-black/[0.03] border-l-2 border-transparent'
                      }`}
                    >
                      <span className="text-[13px] font-mono font-medium text-primary/90 w-16 flex-shrink-0">
                        {item.stockCode}
                      </span>
                      <span className="text-[12px] text-secondary flex-1 truncate">
                        {item.stockName || '—'}
                      </span>
                      {score != null && (
                        <span className={`text-[11px] font-mono font-semibold ${scoreColor}`}>
                          {score}分
                        </span>
                      )}
                      {item.operationAdvice && (
                        <span className="text-[11px] text-muted truncate max-w-[80px]">
                          {mapAdviceDisplay(item.operationAdvice)}
                        </span>
                      )}
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
};
