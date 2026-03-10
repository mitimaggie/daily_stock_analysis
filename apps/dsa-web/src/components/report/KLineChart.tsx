import React, { useEffect, useRef, useState, useCallback } from 'react';
import {
  createChart,
  ColorType,
  CrosshairMode,
  CandlestickSeries,
  LineSeries,
  HistogramSeries,
} from 'lightweight-charts';
import type { IChartApi, CandlestickData, HistogramData, Time } from 'lightweight-charts';
import { Card } from '../common';
import apiClient from '../../api';

interface KLineChartProps {
  stockCode: string;
  stockName?: string;
}

interface KLineDataItem {
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume?: number;
  change_percent?: number;
}

/** 计算均线 */
function calcMA(data: KLineDataItem[], period: number): { time: Time; value: number }[] {
  const result: { time: Time; value: number }[] = [];
  for (let i = period - 1; i < data.length; i++) {
    let sum = 0;
    for (let j = 0; j < period; j++) {
      sum += data[i - j].close;
    }
    result.push({ time: data[i].date as Time, value: sum / period });
  }
  return result;
}

/**
 * K线图表组件
 * 使用 Lightweight Charts v5 展示K线 + 均线 + 成交量
 */
export const KLineChart: React.FC<KLineChartProps> = ({ stockCode, stockName }) => {
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);

  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [days, setDays] = useState(120);
  const [expanded, setExpanded] = useState(true);

  const fetchAndRender = useCallback(async (signal?: AbortSignal) => {
    if (!stockCode || !chartContainerRef.current) return;

    setIsLoading(true);
    setError(null);

    try {
      const res = await apiClient.get(`/api/v1/stocks/${stockCode}/history`, {
        params: { period: 'daily', days },
        signal,
      });
      if (signal?.aborted) return;
      const items: KLineDataItem[] = res.data?.data ?? [];

      if (items.length === 0) {
        setError('暂无K线数据');
        setIsLoading(false);
        return;
      }

      // 销毁旧图表
      if (chartRef.current) {
        chartRef.current.remove();
        chartRef.current = null;
      }

      const container = chartContainerRef.current;
      const chart = createChart(container, {
        width: container.clientWidth,
        height: 400,
        layout: {
          background: { type: ColorType.Solid, color: 'transparent' },
          textColor: 'rgba(255,255,255,0.5)',
          fontSize: 11,
        },
        grid: {
          vertLines: { color: 'rgba(255,255,255,0.04)' },
          horzLines: { color: 'rgba(255,255,255,0.04)' },
        },
        crosshair: { mode: CrosshairMode.Normal },
        rightPriceScale: {
          borderColor: 'rgba(255,255,255,0.1)',
          scaleMargins: { top: 0.05, bottom: 0.25 },
        },
        timeScale: {
          borderColor: 'rgba(255,255,255,0.1)',
          timeVisible: false,
        },
      });

      chartRef.current = chart;

      // K线 (v5 API: chart.addSeries(CandlestickSeries, options))
      const candleSeries = chart.addSeries(CandlestickSeries, {
        upColor: '#ff4d4d',
        downColor: '#00d46a',
        borderUpColor: '#ff4d4d',
        borderDownColor: '#00d46a',
        wickUpColor: '#ff4d4d',
        wickDownColor: '#00d46a',
      });

      const candleData: CandlestickData[] = items.map(d => ({
        time: d.date as Time,
        open: d.open,
        high: d.high,
        low: d.low,
        close: d.close,
      }));
      candleSeries.setData(candleData);

      // 均线
      const ma5Data = calcMA(items, 5);
      const ma10Data = calcMA(items, 10);
      const ma20Data = calcMA(items, 20);
      const ma60Data = calcMA(items, 60);

      const ma5Series = chart.addSeries(LineSeries, { color: '#f59e0b', lineWidth: 1, priceLineVisible: false, lastValueVisible: false });
      const ma10Series = chart.addSeries(LineSeries, { color: '#3b82f6', lineWidth: 1, priceLineVisible: false, lastValueVisible: false });
      const ma20Series = chart.addSeries(LineSeries, { color: '#a855f7', lineWidth: 1, priceLineVisible: false, lastValueVisible: false });

      ma5Series.setData(ma5Data);
      ma10Series.setData(ma10Data);
      ma20Series.setData(ma20Data);
      if (ma60Data.length > 0) {
        const ma60Series = chart.addSeries(LineSeries, { color: '#6b7280', lineWidth: 1, priceLineVisible: false, lastValueVisible: false });
        ma60Series.setData(ma60Data);
      }

      // 成交量
      const volumeSeries = chart.addSeries(HistogramSeries, {
        priceFormat: { type: 'volume' },
        priceScaleId: 'volume',
      });

      chart.priceScale('volume').applyOptions({
        scaleMargins: { top: 0.8, bottom: 0 },
      });

      const volumeData: HistogramData[] = items.map(d => ({
        time: d.date as Time,
        value: d.volume ?? 0,
        color: d.close >= d.open ? 'rgba(255,77,77,0.35)' : 'rgba(0,212,106,0.35)',
      }));
      volumeSeries.setData(volumeData);

      // 自适应时间范围
      chart.timeScale().fitContent();

      // 响应式
      const resizeObserver = new ResizeObserver(entries => {
        for (const entry of entries) {
          const { width } = entry.contentRect;
          if (width > 0) chart.applyOptions({ width });
        }
      });
      resizeObserver.observe(container);

      // 清理
      const cleanup = () => {
        resizeObserver.disconnect();
      };
      (container as any).__chartCleanup = cleanup;

    } catch (err) {
      if (signal?.aborted) return;
      setError(err instanceof Error ? err.message : '加载K线数据失败');
    } finally {
      if (!signal?.aborted) {
        setIsLoading(false);
      }
    }
  }, [stockCode, days]);

  useEffect(() => {
    if (!expanded) return;
    const controller = new AbortController();
    fetchAndRender(controller.signal);
    return () => {
      controller.abort();
      if (chartRef.current) {
        chartRef.current.remove();
        chartRef.current = null;
      }
      if (chartContainerRef.current) {
        const cleanup = (chartContainerRef.current as any).__chartCleanup;
        if (cleanup) cleanup();
      }
    };
  }, [expanded, fetchAndRender]);

  return (
    <Card variant="bordered" padding="md">
      <button
        type="button"
        className="w-full flex items-center justify-between text-left mb-3"
        onClick={() => setExpanded(!expanded)}
      >
        <div className="flex items-baseline gap-2">
          <span className="label-uppercase">K-LINE CHART</span>
          <h3 className="text-base font-semibold text-white">
            {stockName || stockCode} K线图
          </h3>
        </div>
        <span className="text-xs text-muted">{expanded ? '▲' : '▼'}</span>
      </button>

      {expanded && (
        <div>
          {/* 周期选择 */}
          <div className="flex items-center gap-2 mb-3">
            {[
              { label: '30日', value: 30 },
              { label: '60日', value: 60 },
              { label: '120日', value: 120 },
              { label: '250日', value: 250 },
            ].map(opt => (
              <button
                key={opt.value}
                type="button"
                onClick={() => setDays(opt.value)}
                className={`text-xs px-2.5 py-1 rounded-md transition-colors ${
                  days === opt.value
                    ? 'bg-cyan/20 text-cyan border border-cyan/30'
                    : 'bg-surface-2 text-muted hover:text-white border border-transparent'
                }`}
              >
                {opt.label}
              </button>
            ))}

            {/* 均线图例 */}
            <div className="ml-auto flex items-center gap-3 text-[10px]">
              <span className="flex items-center gap-1"><span className="w-3 h-0.5 bg-[#f59e0b] inline-block" />MA5</span>
              <span className="flex items-center gap-1"><span className="w-3 h-0.5 bg-[#3b82f6] inline-block" />MA10</span>
              <span className="flex items-center gap-1"><span className="w-3 h-0.5 bg-[#a855f7] inline-block" />MA20</span>
              <span className="flex items-center gap-1"><span className="w-3 h-0.5 bg-[#6b7280] inline-block" />MA60</span>
            </div>
          </div>

          {/* 图表容器 */}
          {isLoading && (
            <div className="flex items-center justify-center h-[400px] text-xs text-muted">
              <div className="w-4 h-4 border-2 border-cyan/20 border-t-cyan rounded-full animate-spin mr-2" />
              加载K线数据...
            </div>
          )}

          {error && !isLoading && (
            <div className="flex items-center justify-center h-[400px] text-xs text-danger">
              {error}
              <button
                type="button"
                onClick={() => fetchAndRender()}
                className="ml-2 text-cyan hover:text-white"
              >
                重试
              </button>
            </div>
          )}

          <div
            ref={chartContainerRef}
            className="w-full"
            style={{ display: isLoading || error ? 'none' : 'block' }}
          />
        </div>
      )}
    </Card>
  );
};
