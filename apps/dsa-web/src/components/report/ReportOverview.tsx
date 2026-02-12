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
}

/**
 * 报告概览区组件 - 终端风格
 */
export const ReportOverview: React.FC<ReportOverviewProps> = ({
  meta,
  summary,
  hasPositionInfo = false,
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
    <div className="space-y-3">
      {/* Hero: 股票名 + 价格 + 评分（紧凑一行） */}
      <div className="rounded-xl bg-[var(--bg-card)] border border-white/[0.06] px-4 py-3">
        <div className="flex items-center justify-between gap-3">
          <div className="flex-1 min-w-0">
            <div className="flex items-baseline gap-2">
              <span className="text-base font-bold text-white">{meta.stockName || meta.stockCode}</span>
              <span className="font-mono text-[11px] text-white/30">{meta.stockCode}</span>
              <span className="text-[11px] text-white/20">{formatDateTime(meta.createdAt)}</span>
            </div>
            {displayPrice != null && (
              <div className="flex items-baseline gap-2 mt-0.5">
                <span className={`text-lg font-bold font-mono ${getPriceChangeColor(displayChangePct)}`}>
                  {displayPrice.toFixed(2)}
                </span>
                <span className={`text-[13px] font-semibold font-mono ${getPriceChangeColor(displayChangePct)}`}>
                  {formatChangePct(displayChangePct)}
                </span>
                {lastUpdate && (
                  <span className="text-[10px] text-white/20 font-mono">{lastUpdate}</span>
                )}
              </div>
            )}
          </div>
          <ScoreGauge score={summary.sentimentScore} size="xs" showLabel={true} />
        </div>
      </div>

      {/* 操作建议 + 趋势预测 */}
      <div className="grid grid-cols-2 gap-2">
        <div className="rounded-xl bg-[var(--bg-card)] border border-white/[0.06] p-3">
          <div className="text-[11px] text-white/30 mb-1">操作建议</div>
          <p className="text-[13px] text-white/90 leading-snug">
            {summary.operationAdvice || '暂无建议'}
          </p>
        </div>
        <div className="rounded-xl bg-[var(--bg-card)] border border-white/[0.06] p-3">
          <div className="text-[11px] text-white/30 mb-1">趋势预测</div>
          <p className="text-[13px] text-white/90 leading-snug">
            {summary.trendPrediction || '暂无预测'}
          </p>
        </div>
      </div>

      {/* 关键结论 */}
      <div className="rounded-xl bg-[var(--bg-card)] border border-white/[0.06] p-4">
        <p className="text-sm text-white/85 leading-relaxed whitespace-pre-wrap text-left">
          {summary.analysisSummary || '暂无分析结论'}
        </p>
      </div>

      {/* 持仓建议：空仓者建议始终显示，持仓者建议仅在用户填写持仓信息时显示 */}
      {(summary.positionAdvice?.noPosition || (hasPositionInfo && summary.positionAdvice?.hasPosition)) && (
        <div className="rounded-xl bg-[var(--bg-card)] border border-white/[0.06] p-4 space-y-2.5">
          {summary.positionAdvice?.noPosition && (
            <div className="flex gap-2 items-start">
              <span className="text-[11px] text-cyan bg-cyan/10 px-1.5 py-0.5 rounded flex-shrink-0">空仓</span>
              <p className="text-sm text-white/80 leading-relaxed">{summary.positionAdvice.noPosition}</p>
            </div>
          )}
          {hasPositionInfo && summary.positionAdvice?.hasPosition && (
            <div className="flex gap-2 items-start">
              <span className="text-[11px] text-warning bg-warning/10 px-1.5 py-0.5 rounded flex-shrink-0">持仓</span>
              <p className="text-sm text-white/80 leading-relaxed">{summary.positionAdvice.hasPosition}</p>
            </div>
          )}
        </div>
      )}
    </div>
  );
};
