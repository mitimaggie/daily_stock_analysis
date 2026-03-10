import React, { useState, useEffect } from 'react';
import { marketApi } from '../../api/market';
import type { ConceptItem } from '../../types/market';
import { safeFixed } from '../../utils/format';

interface PortfolioHeatScanProps {
  portfolioItems: { code: string; name: string }[];
}

const PortfolioHeatScan: React.FC<PortfolioHeatScanProps> = ({ portfolioItems }) => {
  const [concepts, setConcepts] = useState<ConceptItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      setLoading(true);
      setError(false);
      try {
        const overview = await marketApi.getOverview();
        if (!cancelled && overview.concepts) {
          setConcepts(overview.concepts);
        }
      } catch {
        if (!cancelled) setError(true);
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    load();
    return () => { cancelled = true; };
  }, []);

  if (loading) {
    return (
      <div className="rounded-lg border border-black/[0.07] bg-black/[0.02] p-4">
        <div className="text-[11px] text-muted">概念热度加载中…</div>
      </div>
    );
  }

  if (error || concepts.length === 0) return null;

  const topConcepts = concepts.slice(0, 20);
  const holdingCodes = new Set(portfolioItems.map(p => p.code));
  const hasHoldings = holdingCodes.size > 0;

  return (
    <div className="rounded-xl border border-black/[0.07] bg-card p-4 space-y-3">
      <div className="flex items-center gap-2">
        <span className="text-[13px]">🔍</span>
        <span className="text-[13px] font-medium text-primary/70">市场概念热度</span>
        <span className="text-[10px] text-muted">Top {topConcepts.length}</span>
      </div>

      {hasHoldings && (
        <p className="text-[11px] text-muted">
          对照你的 {portfolioItems.length} 只持仓，看看哪些概念正在发力
        </p>
      )}

      <div className="space-y-1.5">
        {topConcepts.slice(0, 10).map((c) => {
          const isHot = c.rank <= 5;
          const isWarm = c.rank <= 10;
          const pctColor = c.pctChg >= 0 ? 'text-red-600' : 'text-emerald-600';
          const icon = isHot ? '🔥' : isWarm ? '⚡' : '😐';
          const borderColor = isHot
            ? 'border-red-500/15 bg-red-500/[0.04]'
            : isWarm
              ? 'border-amber-500/15 bg-amber-500/[0.04]'
              : 'border-black/[0.06] bg-black/[0.02]';

          return (
            <div key={c.code} className={`flex items-center gap-2 rounded-lg border px-3 py-2 ${borderColor}`}>
              <span className="text-[12px] flex-shrink-0">{icon}</span>
              <span className="text-[12px] text-primary/70 font-medium truncate flex-1">{c.name}</span>
              <span className={`text-[12px] font-mono font-medium ${pctColor}`}>
                {c.pctChg >= 0 ? '+' : ''}{safeFixed(c.pctChg, 1, '0.0')}%
              </span>
              <span className="text-[10px] text-muted flex-shrink-0">Top {c.rank}</span>
              {c.leadingStock && (
                <span className="text-[10px] text-muted truncate max-w-[60px]">{c.leadingStock}</span>
              )}
            </div>
          );
        })}
      </div>

      {topConcepts.length > 10 && (
        <details className="group">
          <summary className="text-[11px] text-muted cursor-pointer hover:text-muted transition">
            展开更多 ({topConcepts.length - 10})
          </summary>
          <div className="mt-1.5 space-y-1">
            {topConcepts.slice(10).map((c) => {
              const pctColor = c.pctChg >= 0 ? 'text-red-600/70' : 'text-emerald-600/70';
              return (
                <div key={c.code} className="flex items-center gap-2 px-3 py-1 text-[11px]">
                  <span className="text-muted truncate flex-1">{c.name}</span>
                  <span className={`font-mono ${pctColor}`}>
                    {c.pctChg >= 0 ? '+' : ''}{safeFixed(c.pctChg, 1, '0.0')}%
                  </span>
                  <span className="text-muted/70">Top {c.rank}</span>
                </div>
              );
            })}
          </div>
        </details>
      )}
    </div>
  );
};

export default PortfolioHeatScan;
