import React, { useState, useEffect, useMemo } from 'react';
import { marketApi } from '../../api/market';
import type { ConceptItem } from '../../types/market';
import { safeFixed } from '../../utils/format';

interface PortfolioHeatScanProps {
  portfolioItems: { code: string; name: string }[];
}

const PortfolioHeatScan: React.FC<PortfolioHeatScanProps> = ({ portfolioItems }) => {
  const [concepts, setConcepts] = useState<ConceptItem[]>([]);
  const [holdingMap, setHoldingMap] = useState<Record<string, string[]>>({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const [loaded, setLoaded] = useState(false);

  const holdingCodes = portfolioItems.map(p => p.code);
  const holdingCodesKey = useMemo(() => portfolioItems.map(p => p.code).join(','), [portfolioItems]);
  const holdingNameMap = Object.fromEntries(portfolioItems.map(p => [p.code, p.name]));

  useEffect(() => {
    if (loaded) setLoaded(false);
  }, [holdingCodesKey]);

  useEffect(() => {
    if (!expanded || loaded) return;
    let cancelled = false;
    const load = async () => {
      setLoading(true);
      setError(false);
      try {
        const [overview, mapping] = await Promise.all([
          marketApi.getOverview(),
          holdingCodes.length > 0 ? marketApi.getConceptHoldings(holdingCodes) : Promise.resolve({}),
        ]);
        if (!cancelled) {
          if (overview.concepts) setConcepts(overview.concepts);
          setHoldingMap(mapping);
          setLoaded(true);
        }
      } catch {
        if (!cancelled) setError(true);
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    load();
    return () => { cancelled = true; };
  }, [expanded, loaded]);

  const topConcepts = concepts.slice(0, 20);

  const getHoldingStocks = (conceptName: string): string[] => {
    return holdingMap[conceptName] || [];
  };

  const hasAnyIntersection = topConcepts.slice(0, 10).some(c => getHoldingStocks(c.name).length > 0);

  return (
    <div className="rounded-xl border border-black/[0.07] bg-card overflow-hidden">
      <button
        type="button"
        onClick={() => setExpanded(v => !v)}
        className="w-full flex items-center justify-between p-4 hover:bg-black/[0.02] transition"
      >
        <div className="flex items-center gap-2">
          <span className="text-[13px]">🔍</span>
          <span className="text-[13px] font-medium text-primary/70">市场概念热度</span>
          {topConcepts.length > 0 && <span className="text-[10px] text-muted">Top {Math.min(topConcepts.length, 10)}</span>}
          {!expanded && hasAnyIntersection && (
            <span className="text-[10px] px-1.5 py-0.5 rounded bg-cyan-500/10 border border-cyan-500/20 text-cyan-500">有持仓关联</span>
          )}
        </div>
        <span className="text-[10px] text-muted">{expanded ? '▲ 收起' : '▼ 展开'}</span>
      </button>

      {expanded && (
        <div className="px-4 pb-4 space-y-3">
          {loading && (
            <div className="text-[11px] text-muted py-3">概念热度加载中…</div>
          )}
          {!loading && error && (
            <div className="text-[11px] text-muted/70 py-3">加载失败</div>
          )}
          {!loading && !error && concepts.length === 0 && loaded && (
            <div className="text-[11px] text-muted/70 py-3">暂无概念数据</div>
          )}
          {!loading && !error && holdingCodes.length > 0 && !hasAnyIntersection && concepts.length > 0 && (
            <p className="text-[11px] text-muted bg-black/[0.02] border border-black/[0.05] rounded px-3 py-2">
              你的持仓未涉及当前热门概念
            </p>
          )}

          {!loading && !error && holdingCodes.length > 0 && hasAnyIntersection && concepts.length > 0 && (
            <p className="text-[11px] text-muted">
              对照你的 {portfolioItems.length} 只持仓，看看哪些概念正在发力
            </p>
          )}

          {!loading && !error && concepts.length > 0 && (<>
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

                const matchedStocks = getHoldingStocks(c.name);

                return (
                  <div key={c.code} className={`rounded-lg border px-3 py-2 ${borderColor}`}>
                    <div className="flex items-center gap-2">
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
                    {matchedStocks.length > 0 && (
                      <div className="mt-1 flex items-center gap-1.5 flex-wrap">
                        {matchedStocks.map(code => (
                          <span key={code} className="text-[10px] px-1.5 py-0.5 rounded bg-cyan-500/10 border border-cyan-500/20 text-cyan-500 font-medium">
                            你的 {holdingNameMap[code] || code}
                          </span>
                        ))}
                      </div>
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
                    const matchedStocks = getHoldingStocks(c.name);
                    return (
                      <div key={c.code} className="px-3 py-1">
                        <div className="flex items-center gap-2 text-[11px]">
                          <span className="text-muted truncate flex-1">{c.name}</span>
                          <span className={`font-mono ${pctColor}`}>
                            {c.pctChg >= 0 ? '+' : ''}{safeFixed(c.pctChg, 1, '0.0')}%
                          </span>
                          <span className="text-muted/70">Top {c.rank}</span>
                        </div>
                        {matchedStocks.length > 0 && (
                          <div className="mt-0.5 flex items-center gap-1 flex-wrap">
                            {matchedStocks.map(code => (
                              <span key={code} className="text-[9px] px-1 py-px rounded bg-cyan-500/10 border border-cyan-500/20 text-cyan-500">
                                你的 {holdingNameMap[code] || code}
                              </span>
                            ))}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              </details>
            )}
          </>)}
        </div>
      )}
    </div>
  );
};

export default PortfolioHeatScan;
