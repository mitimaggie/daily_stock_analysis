import type React from 'react';
import { useState, useEffect, useCallback } from 'react';
import { Card } from '../common';
import { disclosuresApi } from '../../api/disclosures';
import type { DisclosureItem } from '../../api/disclosures';

interface ReportNewsProps {
  queryId?: string;
  stockCode?: string;
  limit?: number;
  /** 当结构化新闻API返回空时，回退显示原始新闻文本 */
  newsContentFallback?: string | null;
}


export const ReportNews: React.FC<ReportNewsProps> = ({ stockCode, limit = 20 }) => {
  const [isLoading, setIsLoading] = useState(false);
  const [items, setItems] = useState<DisclosureItem[]>([]);
  const [error, setError] = useState<string | null>(null);

  const fetchDisclosures = useCallback(async () => {
    if (!stockCode) return;
    setIsLoading(true);
    setError(null);

    try {
      const response = await disclosuresApi.getDisclosures(stockCode, 90, limit);
      setItems(response.items || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载公告失败');
    } finally {
      setIsLoading(false);
    }
  }, [stockCode, limit]);

  useEffect(() => {
    setItems([]);
    setError(null);

    if (stockCode) {
      fetchDisclosures();
    }
  }, [stockCode, fetchDisclosures]);

  if (!stockCode) {
    return null;
  }

  const hasContent = items.length > 0;

  return (
    <Card variant="bordered" padding="md">
      <div className="flex items-center justify-between mb-3">
        <div className="mb-3 flex items-baseline gap-2">
          <span className="label-uppercase">F10 DISCLOSURE</span>
          <h3 className="text-base font-semibold text-primary">公告与披露</h3>
        </div>
        <div className="flex items-center gap-2">
          {isLoading && (
            <div className="w-3.5 h-3.5 border-2 border-cyan/20 border-t-cyan rounded-full animate-spin" />
          )}
          <button
            type="button"
            onClick={fetchDisclosures}
            className="text-xs text-cyan hover:text-primary transition-colors"
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
            onClick={fetchDisclosures}
            className="text-xs text-cyan hover:text-primary transition-colors"
          >
            重试
          </button>
        </div>
      )}

      {isLoading && !error && (
        <div className="flex items-center gap-2 text-xs text-secondary">
          <div className="w-4 h-4 border-2 border-cyan/20 border-t-cyan rounded-full animate-spin" />
          加载公告中...
        </div>
      )}

      {!isLoading && !error && !hasContent && (
        <div className="text-xs text-muted">暂无近期公告与披露</div>
      )}

      {!isLoading && !error && items.length > 0 && (
        <div className="space-y-2 text-left">
          {items.map((item: DisclosureItem, index: number) => (
            <div
              key={`${item.title}-${index}`}
              className="group p-3 rounded-lg bg-elevated/80 border border-black/[0.03] hover:border-cyan/30 hover:bg-hover transition-colors"
            >
              <div className="flex items-start justify-between gap-3">
                <div className="flex-1 min-w-0 text-left">
                  <p className="text-sm text-primary font-medium leading-snug">
                    {item.title}
                  </p>
                  {item.pub_date && (
                    <p className="text-[10px] text-muted mt-1 font-mono">{item.pub_date}</p>
                  )}
                </div>
                {item.url && (
                  <a
                    href={item.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-xs text-cyan hover:text-primary transition-colors inline-flex items-center gap-1 whitespace-nowrap"
                  >
                    查看
                    <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M14 3h7m0 0v7m0-7L10 14" />
                    </svg>
                  </a>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
};
