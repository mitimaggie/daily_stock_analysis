import type React from 'react';
import type { TrafficLightData, SentimentData } from '../../types/market';

interface TrafficLightProps {
  data: TrafficLightData;
  sentiment?: SentimentData;
}

const signalConfig: Record<TrafficLightData['signal'], { bg: string; glow: string; ring: string }> = {
  active: {
    bg: 'bg-emerald-500',
    glow: 'shadow-[0_0_40px_rgba(16,185,129,0.5)]',
    ring: 'ring-emerald-500/30',
  },
  cautious: {
    bg: 'bg-yellow-400',
    glow: 'shadow-[0_0_40px_rgba(250,204,21,0.5)]',
    ring: 'ring-yellow-400/30',
  },
  wait: {
    bg: 'bg-orange-500',
    glow: 'shadow-[0_0_40px_rgba(249,115,22,0.5)]',
    ring: 'ring-orange-500/30',
  },
  cash: {
    bg: 'bg-red-500',
    glow: 'shadow-[0_0_40px_rgba(239,68,68,0.5)]',
    ring: 'ring-red-500/30',
  },
};

const TrafficLight: React.FC<TrafficLightProps> = ({ data, sentiment }) => {
  const config = signalConfig[data.signal] ?? signalConfig.wait;

  const summaryParts: string[] = [];
  if (sentiment) {
    if (sentiment.limitUp > 0) summaryParts.push(`涨停${sentiment.limitUp}家`);
    if (sentiment.limitDown > 0) summaryParts.push(`跌停${sentiment.limitDown}家`);
    if (sentiment.emotionLabel) summaryParts.push(`情绪${sentiment.emotionLabel}`);
  }

  return (
    <div className="terminal-card p-5">
      <div className="text-center">
        <p className="text-[13px] text-secondary mb-4 font-medium tracking-wide">今日市场判断</p>

        <div className="flex justify-center mb-4">
          <div className={`w-20 h-20 rounded-full ${config.bg} ${config.glow} ring-4 ${config.ring} flex items-center justify-center transition-all duration-500`}>
            <span className="text-2xl font-bold text-white drop-shadow-md">
              {data.signalLabel}
            </span>
          </div>
        </div>

        {summaryParts.length > 0 && (
          <p className="text-[13px] text-secondary mb-3">
            {summaryParts.join(' · ')}
          </p>
        )}

        <p className="text-[13px] text-white/80 leading-relaxed max-w-sm mx-auto">
          {data.reason}
        </p>

        <p className="text-[10px] text-muted mt-4">
          信号基于统计规律，极端行情可能滞后。不构成投资建议。
        </p>
      </div>
    </div>
  );
};

export default TrafficLight;
