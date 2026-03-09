import type React from 'react';
import type { SentimentData } from '../../types/market';

interface LimitPoolStatsProps {
  data: SentimentData;
}

const LimitPoolStats: React.FC<LimitPoolStatsProps> = ({ data }) => {
  return (
    <div className="terminal-card p-4">
      <h3 className="text-[14px] font-semibold text-white mb-3 flex items-center gap-2">
        <svg className="w-4 h-4 text-cyan" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
        </svg>
        涨跌停统计
      </h3>

      {/* 核心三指标 */}
      <div className="grid grid-cols-3 gap-3 mb-4">
        <div className="text-center p-3 rounded-xl bg-success/5 border border-success/10">
          <p className="text-2xl font-bold text-success">{data.limitUp}</p>
          <p className="text-[11px] text-success/70 mt-0.5">涨停</p>
        </div>
        <div className="text-center p-3 rounded-xl bg-danger/5 border border-danger/10">
          <p className="text-2xl font-bold text-danger">{data.limitDown}</p>
          <p className="text-[11px] text-danger/70 mt-0.5">跌停</p>
        </div>
        <div className="text-center p-3 rounded-xl bg-warning/5 border border-warning/10">
          <p className="text-2xl font-bold text-warning">{data.broken}</p>
          <p className="text-[11px] text-warning/70 mt-0.5">炸板</p>
        </div>
      </div>

      {/* 辅助指标 */}
      <div className="grid grid-cols-2 gap-x-4 gap-y-2 px-1">
        <div className="flex justify-between items-center">
          <span className="text-[12px] text-muted">炸板率</span>
          <span className="text-[12px] font-mono text-warning">{data.brokenRate.toFixed(1)}%</span>
        </div>
        <div className="flex justify-between items-center">
          <span className="text-[12px] text-muted">情绪温度</span>
          <span className="text-[12px] font-mono text-cyan">{data.emotionTemp}</span>
        </div>
        <div className="flex justify-between items-center">
          <span className="text-[12px] text-muted">上涨</span>
          <span className="text-[12px] font-mono text-success">{data.advanceCount}</span>
        </div>
        <div className="flex justify-between items-center">
          <span className="text-[12px] text-muted">下跌</span>
          <span className="text-[12px] font-mono text-danger">{data.declineCount}</span>
        </div>
        {data.flatCount > 0 && (
          <div className="flex justify-between items-center col-span-2">
            <span className="text-[12px] text-muted">平盘</span>
            <span className="text-[12px] font-mono text-secondary">{data.flatCount}</span>
          </div>
        )}
      </div>
    </div>
  );
};

export default LimitPoolStats;
