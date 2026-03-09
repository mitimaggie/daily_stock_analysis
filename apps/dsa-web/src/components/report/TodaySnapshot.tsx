import type React from 'react';
import type { TodaySnapshot as TodaySnapshotType } from '../../types/analysis';

interface TodaySnapshotProps {
  data: TodaySnapshotType;
}

/** 格式化成交量（万手/亿） */
const fmtVolume = (v?: number): string => {
  if (v == null || v <= 0) return '—';
  if (v >= 1e8) return `${(v / 1e8).toFixed(2)}亿`;
  if (v >= 1e4) return `${(v / 1e4).toFixed(0)}万`;
  return v.toFixed(0);
};

/** 格式化成交额（亿/万） */
const fmtAmount = (a?: number): string => {
  if (a == null || a <= 0) return '—';
  if (a >= 1e8) return `${(a / 1e8).toFixed(2)}亿`;
  if (a >= 1e4) return `${(a / 1e4).toFixed(0)}万`;
  return a.toFixed(0);
};

/** 格式化百分比 */
const fmtPct = (p?: number | null): string => {
  if (p == null) return '—';
  return `${p >= 0 ? '+' : ''}${p.toFixed(2)}%`;
};

const fmtPrice = (p?: number): string => {
  if (p == null || p <= 0) return '—';
  return p.toFixed(2);
};

interface CellProps {
  label: string;
  value: string;
  color?: string;
  highlight?: boolean;
  tip?: string;
}

const Cell: React.FC<CellProps> = ({ label, value, color, highlight, tip }) => (
  <div className={`flex flex-col items-center rounded-lg px-1 py-1 ${highlight ? 'bg-amber-500/[0.06] border border-amber-500/15' : ''}`} title={tip}>
    <span className="text-[10px] text-white/35 mb-0.5">{label}</span>
    <span className={`text-xs font-mono font-medium ${color || 'text-white/80'}`}>{value}</span>
  </div>
);

/**
 * 当日行情快照组件
 */
export const TodaySnapshot: React.FC<TodaySnapshotProps> = ({ data }) => {
  const {
    open, high, low, close,
    volume, amount, pctChg,
    currentPrice, changePct,
    volumeRatio, turnoverRate,
  } = data;

  // 涨跌幅颜色
  const chg = changePct ?? pctChg;
  const chgColor = chg == null ? '' : chg > 0 ? 'text-red-400' : chg < 0 ? 'text-green-400' : '';

  // 振幅
  const amplitude = (high && low && close)
    ? ((high - low) / (close || 1) * 100)
    : null;

  // 量比预警
  const vrHigh = volumeRatio != null && volumeRatio >= 2.0;
  const vrColor = volumeRatio == null ? '' : volumeRatio >= 3.0 ? 'text-red-400' : volumeRatio >= 2.0 ? 'text-amber-400' : volumeRatio >= 1.5 ? 'text-white/70' : 'text-white/50';
  // 换手率预警
  const trHigh = turnoverRate != null && turnoverRate >= 5;
  const trColor = turnoverRate == null ? '' : turnoverRate >= 10 ? 'text-red-400' : turnoverRate >= 5 ? 'text-amber-400' : 'text-white/70';

  // 异常标记
  const anomalies: string[] = [];
  if (vrHigh) anomalies.push(`量比${(volumeRatio ?? 0).toFixed(1)}×，成交异常放大`);
  if (trHigh) anomalies.push(`换手率${(turnoverRate ?? 0).toFixed(1)}%，市场活跃`);

  return (
    <div className="rounded-xl bg-[var(--bg-card)] border border-white/[0.06] p-4">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold text-white/60 flex items-center gap-1.5">
          <span>📈</span> 当日行情
        </h3>
        {anomalies.length > 0 && (
          <span className="text-[10px] text-amber-400/80 font-mono">⚠ {anomalies[0]}</span>
        )}
      </div>

      {/* OHLCV 行 */}
      <div className="grid grid-cols-5 gap-2 mb-2">
        <Cell label="收盘" value={fmtPrice(close)} />
        <Cell label="开盘" value={fmtPrice(open)} />
        <Cell label="最高" value={fmtPrice(high)} />
        <Cell label="最低" value={fmtPrice(low)} />
        <Cell label="涨跌幅" value={fmtPct(chg)} color={chgColor} />
      </div>

      {/* 二行：量额+换手+量比 */}
      <div className="grid grid-cols-5 gap-2 pt-2 border-t border-white/[0.04]">
        <Cell label="成交量" value={fmtVolume(volume)} />
        <Cell label="成交额" value={fmtAmount(amount)} />
        <Cell label="振幅" value={amplitude != null ? `${amplitude.toFixed(2)}%` : '—'} />
        <Cell label="换手率" value={turnoverRate != null ? `${turnoverRate.toFixed(2)}%` : '—'}
          color={trColor} highlight={trHigh} tip="换手率>5%表示当日交易活跃" />
        <Cell label="量比" value={volumeRatio != null ? volumeRatio.toFixed(2) : '—'}
          color={vrColor} highlight={vrHigh} tip="量比>2表示有异常放量" />
      </div>

      {/* 当前价 */}
      {currentPrice != null && currentPrice > 0 && (
        <div className="mt-2 pt-2 border-t border-white/[0.04] flex items-center gap-3 text-xs">
          <span className="text-white/40">当前价</span>
          <span className={`font-mono font-bold text-sm ${chgColor}`}>
            {currentPrice.toFixed(2)}
          </span>
        </div>
      )}
    </div>
  );
};
