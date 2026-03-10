import type React from 'react';
import type { ConceptItem } from '../../types/market';

interface ConceptHeatMapProps {
  concepts: ConceptItem[] | null;
}

const ConceptHeatMap: React.FC<ConceptHeatMapProps> = ({ concepts }) => {
  if (!concepts || concepts.length === 0) {
    return (
      <div className="terminal-card p-4">
        <h3 className="text-[14px] font-semibold text-primary mb-3 flex items-center gap-2">
          <svg className="w-4 h-4 text-orange-400" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" d="M17.657 18.657A8 8 0 016.343 7.343S7 9 9 10c0-2 .5-5 2.986-7C14 5 16.09 5.777 17.656 7.343A7.975 7.975 0 0120 13a7.975 7.975 0 01-2.343 5.657z" />
          </svg>
          概念热度 Top 10
        </h3>
        <p className="text-[13px] text-muted text-center py-4">暂无概念数据</p>
      </div>
    );
  }

  return (
    <div className="terminal-card p-4">
      <h3 className="text-[14px] font-semibold text-primary mb-3 flex items-center gap-2">
        <svg className="w-4 h-4 text-orange-400" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" d="M17.657 18.657A8 8 0 016.343 7.343S7 9 9 10c0-2 .5-5 2.986-7C14 5 16.09 5.777 17.656 7.343A7.975 7.975 0 0120 13a7.975 7.975 0 01-2.343 5.657z" />
        </svg>
        概念热度 Top 10
      </h3>

      <div className="space-y-2">
        {concepts.slice(0, 10).map((item) => {
          const isUp = item.pctChg >= 0;
          const isHot = item.heatType === '持续热点';

          return (
            <div key={item.code || item.name} className="flex items-start gap-3 p-2.5 rounded-lg bg-elevated/30 hover:bg-elevated/60 transition-colors">
              <span className="text-[13px] font-mono text-muted w-5 text-right flex-shrink-0 pt-0.5">
                {item.rank}
              </span>

              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 mb-0.5">
                  <span className="text-[13px] font-medium text-primary truncate">{item.name}</span>
                  <span className={`text-[12px] font-mono font-semibold ${isUp ? 'text-success' : 'text-danger'}`}>
                    {isUp ? '+' : ''}{item.pctChg.toFixed(1)}%
                  </span>
                  <span className={`text-[10px] px-1.5 py-0.5 rounded-full font-medium flex-shrink-0 ${
                    isHot
                      ? 'bg-orange-500/15 text-orange-400 border border-orange-500/20'
                      : 'bg-cyan/10 text-cyan border border-cyan/20'
                  }`}>
                    {isHot ? '🔥 持续热点' : '⚡ 短线脉冲'}
                  </span>
                </div>
                <p className="text-[11px] text-muted">
                  领涨：{item.leadingStock}
                  {item.amount > 0 && (
                    <span className="ml-2">成交 {(item.amount / 100000000).toFixed(1)}亿</span>
                  )}
                </p>
              </div>
            </div>
          );
        })}
      </div>

      <p className="text-[10px] text-muted mt-3 text-center">
        概念热度仅供参考市场方向，不构成买入建议
      </p>
    </div>
  );
};

export default ConceptHeatMap;
