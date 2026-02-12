import type React from 'react';
import type { ReportStrategy as ReportStrategyType } from '../../types/analysis';

interface ReportStrategyProps {
  strategy?: ReportStrategyType;
}

interface StrategyItemProps {
  label: string;
  value?: string;
  color: string;
}

const StrategyItem: React.FC<StrategyItemProps> = ({
  label,
  value,
  color,
}) => (
  <div className="flex items-center justify-between py-1.5">
    <div className="flex items-center gap-2">
      <span className="w-1.5 h-1.5 rounded-full flex-shrink-0" style={{ background: color }} />
      <span className="text-xs text-white/50">{label}</span>
    </div>
    <span
      className="text-sm font-bold font-mono"
      style={{ color: value ? color : 'var(--text-muted)' }}
    >
      {value || '—'}
    </span>
  </div>
);

/**
 * 策略点位区组件 - 终端风格
 */
export const ReportStrategy: React.FC<ReportStrategyProps> = ({ strategy }) => {
  if (!strategy) {
    return null;
  }

  const strategyItems = [
    {
      label: '理想买入',
      value: strategy.idealBuy,
      color: '#00ff88', // success
    },
    {
      label: '二次买入',
      value: strategy.secondaryBuy,
      color: '#00d4ff', // cyan
    },
    {
      label: '止损价位',
      value: strategy.stopLoss,
      color: '#ff4466', // danger
    },
    {
      label: '止盈目标',
      value: strategy.takeProfit,
      color: '#ffaa00', // warning
    },
  ];

  return (
    <div className="rounded-xl bg-[var(--bg-card)] border border-white/[0.06] p-4">
      <div className="grid grid-cols-2 gap-x-6">
        {strategyItems.map((item) => (
          <StrategyItem key={item.label} {...item} />
        ))}
      </div>
    </div>
  );
};
