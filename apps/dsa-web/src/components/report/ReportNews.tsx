import type React from 'react';
import { useState, useEffect, useCallback } from 'react';
import { Card } from '../common';
import { historyApi } from '../../api/history';
import type { NewsIntelItem } from '../../types/analysis';

interface ReportNewsProps {
  queryId?: string;
  limit?: number;
  /** 当结构化新闻API返回空时，回退显示原始新闻文本 */
  newsContentFallback?: string | null;
}

/**
 * 资讯区组件 - 终端风格
 */
/** 检测是否为原始数据表格（股票代码+数字堆砌） */
function isRawDataTable(text: string): boolean {
  if (!text) return false;
  // 多个6位数字（股票代码）+ 大量浮点数 = 原始数据表
  const codeCount = (text.match(/\b\d{6}\b/g) || []).length;
  const numCount = (text.match(/\b\d+\.\d+\b/g) || []).length;
  return codeCount >= 2 && numCount >= 4;
}

/** 解析原始新闻文本为结构化条目 */
function parseNewsText(text: string): { title: string; time?: string }[] {
  const lines = text.split('\n').filter(l => l.trim());
  const results: { title: string; time?: string }[] = [];
  for (const line of lines) {
    // 跳过原始数据表格行
    if (isRawDataTable(line)) continue;
    // 匹配格式: "1. 【来源】标题 (时间)" 或 "数字. 标题"
    const match = line.match(/^\d+\.\s*(.+?)(?:\s*\((\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})\))?$/);
    if (match) {
      results.push({ title: match[1].trim(), time: match[2] });
    }
  }
  return results;
}

export const ReportNews: React.FC<ReportNewsProps> = ({ queryId, limit = 20, newsContentFallback }) => {
  const [isLoading, setIsLoading] = useState(false);
  const [items, setItems] = useState<NewsIntelItem[]>([]);
  const [fallbackItems, setFallbackItems] = useState<{ title: string; time?: string }[]>([]);
  const [error, setError] = useState<string | null>(null);

  const fetchNews = useCallback(async () => {
    if (!queryId) return;
    setIsLoading(true);
    setError(null);

    try {
      const response = await historyApi.getNews(queryId, limit);
      setItems(response.items || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载资讯失败');
    } finally {
      setIsLoading(false);
    }
  }, [queryId, limit]);

  useEffect(() => {
    setItems([]);
    setFallbackItems([]);
    setError(null);

    if (queryId) {
      fetchNews();
    }
  }, [queryId, fetchNews]);

  // 当结构化新闻为空时，解析原始新闻文本作为回退
  useEffect(() => {
    if (!isLoading && items.length === 0 && newsContentFallback) {
      setFallbackItems(parseNewsText(newsContentFallback));
    }
  }, [isLoading, items.length, newsContentFallback]);

  if (!queryId) {
    return null;
  }

  const hasContent = items.length > 0 || fallbackItems.length > 0;

  return (
    <Card variant="bordered" padding="md">
      <div className="flex items-center justify-between mb-3">
        <div className="mb-3 flex items-baseline gap-2">
          <span className="label-uppercase">F10 DISCLOSURE</span>
          <h3 className="text-base font-semibold text-white">公告与披露</h3>
        </div>
        <div className="flex items-center gap-2">
          {isLoading && (
            <div className="w-3.5 h-3.5 border-2 border-cyan/20 border-t-cyan rounded-full animate-spin" />
          )}
          <button
            type="button"
            onClick={fetchNews}
            className="text-xs text-cyan hover:text-white transition-colors"
          >
            刷新
          </button>
        </div>
      </div>

      {error && !isLoading && (
        <div className="flex items-center justify-between gap-3 p-3 rounded-lg bg-danger/10 border border-danger/20 text-xs text-danger">
          <span>{error}</span>
          <button
            type="button"
            onClick={fetchNews}
            className="text-xs text-cyan hover:text-white transition-colors"
          >
            重试
          </button>
        </div>
      )}

      {isLoading && !error && (
        <div className="flex items-center gap-2 text-xs text-secondary">
          <div className="w-4 h-4 border-2 border-cyan/20 border-t-cyan rounded-full animate-spin" />
          加载资讯中...
        </div>
      )}

      {!isLoading && !error && !hasContent && (
        <div className="text-xs text-muted">暂无近期公告与披露</div>
      )}

      {!isLoading && !error && items.length > 0 && (
        <div className="space-y-2 text-left">
          {items.map((item, index) => (
            <div
              key={`${item.title}-${index}`}
              className="group p-3 rounded-lg bg-elevated/80 border border-white/5 hover:border-cyan/30 hover:bg-hover transition-colors"
            >
              <div className="flex items-start justify-between gap-3">
                <div className="flex-1 min-w-0 text-left">
                  <p className="text-sm text-white font-medium leading-snug text-left">
                    {item.title}
                  </p>
                  {item.snippet && !isRawDataTable(item.snippet) && (
                    <p className="text-xs text-secondary mt-1 text-left">
                      {item.snippet}
                    </p>
                  )}
                </div>
                {item.url && (
                  <a
                    href={item.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-xs text-cyan hover:text-white transition-colors inline-flex items-center gap-1 whitespace-nowrap"
                  >
                    跳转
                    <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        strokeWidth={2}
                        d="M14 3h7m0 0v7m0-7L10 14"
                      />
                    </svg>
                  </a>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* 回退：从原始新闻文本解析的条目 */}
      {!isLoading && !error && items.length === 0 && fallbackItems.length > 0 && (
        <div className="space-y-2 text-left">
          <div className="text-[10px] text-muted mb-1">来源：Akshare 免费新闻源（可能非最新）</div>
          {fallbackItems.map((item, index) => (
            <div
              key={`fb-${index}`}
              className="p-2.5 rounded-lg bg-elevated/80 border border-white/5"
            >
              <p className="text-sm text-white/90 leading-snug">{item.title}</p>
              {item.time && (
                <p className="text-[10px] text-muted mt-1">{item.time}</p>
              )}
            </div>
          ))}
        </div>
      )}
    </Card>
  );
};
