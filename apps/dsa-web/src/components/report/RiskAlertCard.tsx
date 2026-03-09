import type React from 'react';

interface RiskAlertCardProps {
  upcomingUnlock?: any;
  insiderChanges?: any;
  conceptContext?: string;
}

interface AlertItem {
  key: string;
  level: 'red' | 'orange' | 'yellow';
  icon: string;
  text: string;
}

function parseAlerts(
  upcomingUnlock: any,
  insiderChanges: any,
  conceptContext?: string,
): AlertItem[] {
  const alerts: AlertItem[] = [];

  if (upcomingUnlock) {
    const u = typeof upcomingUnlock === 'string' ? upcomingUnlock : JSON.stringify(upcomingUnlock);
    const dateMatch = u.match(/\d{4}-\d{2}-\d{2}/);
    if (dateMatch) {
      const days = Math.round((new Date(dateMatch[0]).getTime() - Date.now()) / 86400000);
      if (days >= 0 && days <= 30) {
        alerts.push({ key: 'unlock', level: 'red', icon: '⚠️', text: `解禁压力：${days}天后解禁（${dateMatch[0]}）` });
      } else if (days > 30 && days <= 90) {
        alerts.push({ key: 'unlock', level: 'orange', icon: '📅', text: `近期解禁: ${dateMatch[0]}` });
      }
    }
  }

  if (insiderChanges) {
    const ic = typeof insiderChanges === 'string' ? insiderChanges : JSON.stringify(insiderChanges);
    if (/净减持|大幅减持|大量减持/.test(ic)) {
      alerts.push({ key: 'insider', level: 'orange', icon: '📉', text: '高管/大股东近期有减持行为' });
    }
  }

  if (conceptContext) {
    const lines = conceptContext.split('\n');
    for (const line of lines) {
      if (line.includes('退潮') || line.includes('降温') || line.includes('热度下降')) {
        alerts.push({ key: 'concept_fade', level: 'yellow', icon: '📉', text: '概念板块热度下降，注意退潮风险' });
        break;
      }
    }
  }

  return alerts;
}

const LEVEL_STYLE: Record<string, string> = {
  red: 'bg-red-500/10 border-red-500/25 text-red-300',
  orange: 'bg-orange-500/10 border-orange-500/25 text-orange-300',
  yellow: 'bg-yellow-500/10 border-yellow-500/25 text-yellow-300',
};

export const RiskAlertCard: React.FC<RiskAlertCardProps> = ({
  upcomingUnlock,
  insiderChanges,
  conceptContext,
}) => {
  const alerts = parseAlerts(upcomingUnlock, insiderChanges, conceptContext);
  if (alerts.length === 0) return null;

  return (
    <div className="rounded-xl bg-[var(--bg-card)] border border-red-500/15 p-4">
      <h3 className="text-sm font-semibold text-red-400/80 mb-2 flex items-center gap-1.5">
        <span>🚨</span> 风险预警
      </h3>
      <div className="space-y-1.5">
        {alerts.map(a => (
          <div
            key={a.key}
            className={`flex items-center gap-2 px-3 py-2 rounded-lg text-[12px] font-medium border ${LEVEL_STYLE[a.level]}`}
          >
            <span>{a.icon}</span>
            <span>{a.text}</span>
          </div>
        ))}
      </div>
    </div>
  );
};
