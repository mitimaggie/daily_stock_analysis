import type React from 'react';
import { useState, useEffect, useRef } from 'react';
import type { ReportMeta, ReportSummary as ReportSummaryType } from '../../types/analysis';
import { ScoreGauge } from '../common';
import { formatDateTime } from '../../utils/format';
import apiClient from '../../api';

interface ReportOverviewProps {
  meta: ReportMeta;
  summary: ReportSummaryType;
  isHistory?: boolean;
  hasPositionInfo?: boolean;
  oneSentence?: string;
  costPrice?: number;
  positionAmount?: number;
  onRefresh?: () => void;
  isRefreshing?: boolean;
}

/**
 * 报告概览区组件 - 终端风格
 */
export const ReportOverview: React.FC<ReportOverviewProps> = ({
  meta,
  summary,
  hasPositionInfo = false,
  oneSentence,
  costPrice,
  positionAmount,
  onRefresh,
  isRefreshing = false,
}) => {
  // 盘中自动刷新价格
  const [livePrice, setLivePrice] = useState<number | undefined>(meta.currentPrice ?? undefined);
  const [liveChangePct, setLiveChangePct] = useState<number | undefined>(meta.changePct ?? undefined);
  const [lastUpdate, setLastUpdate] = useState<string>('');
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    setLivePrice(meta.currentPrice ?? undefined);
    setLiveChangePct(meta.changePct ?? undefined);
    setLastUpdate('');
  }, [meta.stockCode, meta.currentPrice, meta.changePct]);

  useEffect(() => {
    const isTrading = () => {
      const now = new Date();
      const day = now.getDay();
      if (day === 0 || day === 6) return false;
      const h = now.getHours(), m = now.getMinutes();
      const t = h * 60 + m;
      return t >= 9 * 60 + 15 && t <= 15 * 60;
    };

    const fetchQuote = async () => {
      if (!isTrading() || !meta.stockCode) return;
      try {
        const res = await apiClient.get(`/api/v1/stocks/${meta.stockCode}/quote`);
        const d = res.data;
        if (d.current_price) {
          setLivePrice(d.current_price);
          setLiveChangePct(d.change_percent ?? undefined);
          setLastUpdate(new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' }));
        }
      } catch { /* 静默失败 */ }
    };

    if (isTrading() && meta.stockCode) {
      fetchQuote();
      timerRef.current = setInterval(fetchQuote, 30000);
    }
    return () => { if (timerRef.current) clearInterval(timerRef.current); };
  }, [meta.stockCode]);

  const displayPrice = livePrice ?? meta.currentPrice;
  const displayChangePct = liveChangePct ?? meta.changePct;
  // 根据涨跌幅获取颜色
  const getPriceChangeColor = (changePct: number | undefined): string => {
    if (changePct === undefined || changePct === null) return 'text-muted';
    if (changePct > 0) return 'text-[#ff4d4d]'; // 红涨
    if (changePct < 0) return 'text-[#00d46a]'; // 绿跌
    return 'text-muted';
  };

  // 格式化涨跌幅
  const formatChangePct = (changePct: number | undefined): string => {
    if (changePct === undefined || changePct === null) return '--';
    const sign = changePct > 0 ? '+' : '';
    return `${sign}${changePct.toFixed(2)}%`;
  };

  return (
    <div className="rounded-xl bg-[var(--bg-card)] border border-white/[0.06] p-4 space-y-3">
      {/* 第一行：股票名 + 价格 + 评分 */}
      <div className="flex items-center justify-between">
        <div className="flex items-baseline gap-2 flex-wrap">
          <span className="text-[15px] font-bold text-white">{meta.stockName || meta.stockCode}</span>
          {displayPrice != null && (
            <>
              <span className={`text-[15px] font-bold font-mono ${getPriceChangeColor(displayChangePct)}`}>
                {displayPrice.toFixed(2)}
              </span>
              <span className={`text-[12px] font-mono ${getPriceChangeColor(displayChangePct)}`}>
                {formatChangePct(displayChangePct)}
              </span>
            </>
          )}
          <span className="text-[11px] text-white/20">{meta.stockCode} · {formatDateTime(meta.createdAt)}</span>
          {lastUpdate && <span className="text-[10px] text-white/20 font-mono">{lastUpdate}</span>}
        </div>
        <div className="flex items-center gap-2">
          {onRefresh && (
            <button
              type="button"
              onClick={onRefresh}
              disabled={isRefreshing}
              className="p-1.5 rounded-lg hover:bg-white/[0.06] text-white/30 hover:text-white/60 transition-colors disabled:opacity-40"
              title="刷新分析"
            >
              <svg
                className={`w-4 h-4 ${isRefreshing ? 'animate-spin' : ''}`}
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
              </svg>
            </button>
          )}
          <div className="flex items-center gap-1">
            <ScoreGauge score={summary.sentimentScore} size="xs" showLabel={false} />
            {meta.scoreChange != null && meta.scoreChange !== 0 && (
              <span className={`text-[11px] font-mono font-semibold ${meta.scoreChange > 0 ? 'text-[#ff4d4d]' : 'text-[#00d46a]'}`}>
                {meta.scoreChange > 0 ? '▲' : '▼'}{Math.abs(meta.scoreChange)}
              </span>
            )}
          </div>
        </div>
      </div>

      {/* 持仓成本 & 浮盈亏（有持仓时显示） */}
      {hasPositionInfo && costPrice != null && costPrice > 0 && (() => {
        const price = displayPrice ?? meta.currentPrice;
        const pnlPct = price && price > 0 ? ((price - costPrice) / costPrice * 100) : null;
        const pnlAmt = price && positionAmount ? ((price - costPrice) * positionAmount) : null;
        return (
          <div className="flex items-center gap-4 text-[12px] text-white/50">
            <span>成本 <span className="font-mono text-white/70">{costPrice.toFixed(2)}</span></span>
            {pnlPct != null && (
              <span className={`font-mono font-semibold ${pnlPct >= 0 ? 'text-[#ff4d4d]' : 'text-[#00d46a]'}`}>
                {pnlPct >= 0 ? '+' : ''}{pnlPct.toFixed(2)}%
              </span>
            )}
            {pnlAmt != null && (
              <span className={`font-mono text-[11px] ${pnlAmt >= 0 ? 'text-[#ff4d4d]/70' : 'text-[#00d46a]/70'}`}>
                {pnlAmt >= 0 ? '+' : ''}{(pnlAmt / 10000).toFixed(2)}万
              </span>
            )}
          </div>
        );
      })()}

      {/* 操作建议 + 趋势预测（紧凑两行） */}
      <div className="grid grid-cols-2 gap-x-4 text-[13px]">
        <div>
          <span className="text-white/30 text-[11px]">操作建议</span>
          <p className="text-white/90 leading-snug mt-0.5">{summary.operationAdvice || '暂无'}</p>
        </div>
        <div>
          <span className="text-white/30 text-[11px]">趋势预测</span>
          <p className="text-white/90 leading-snug mt-0.5">{summary.trendPrediction || '暂无'}</p>
        </div>
      </div>

      {/* 分割线 */}
      <div className="border-t border-white/5" />

      {/* 一句话核心结论 */}
      <p className="text-[13px] text-white/70 leading-relaxed whitespace-pre-wrap text-left">
        {oneSentence || summary.analysisSummary || '暂无分析结论'}
      </p>

      {/* 持仓建议 */}
      {(summary.positionAdvice?.noPosition || summary.positionAdvice?.hasPosition) && (
        <div className="border-t border-white/5 pt-3 space-y-2">
          {/* 有持仓数据时只显示持仓建议，无持仓数据时显示空仓建议 */}
          {!hasPositionInfo && summary.positionAdvice?.noPosition && (
            <div className="flex gap-2 items-start text-[13px]">
              <span className="text-[10px] text-white/40 bg-white/5 px-1.5 py-0.5 rounded flex-shrink-0">空仓</span>
              <p className="text-white/70 leading-relaxed">{summary.positionAdvice.noPosition}</p>
            </div>
          )}
          {summary.positionAdvice?.hasPosition && (
            <div className="flex gap-2 items-start text-[13px]">
              <span className="text-[10px] text-white/40 bg-white/5 px-1.5 py-0.5 rounded flex-shrink-0">{hasPositionInfo ? '策略' : '持仓'}</span>
              <p className="text-white/70 leading-relaxed">{summary.positionAdvice.hasPosition}</p>
            </div>
          )}
        </div>
      )}
    </div>
  );
};
