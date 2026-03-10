import type React from 'react';

interface HotMatch {
  name: string;
  pct: string;
  rank: string;
  type: string;
}

interface ParsedConcept {
  concepts: string[];
  hotMatches: HotMatch[];
}

function parseConceptContext(text: string): ParsedConcept {
  const concepts: string[] = [];
  const hotMatches: HotMatch[] = [];

  const lines = text.split('\n');
  for (const line of lines) {
    if (line.startsWith('概念:') || line.startsWith('概念：')) {
      concepts.push(
        ...line.replace(/概念[:：]/, '').trim().split(/[,，]/).map(s => s.trim()).filter(Boolean),
      );
    }
    if (line.startsWith('热门概念命中:') || line.startsWith('热门概念命中：')) {
      const matches = line.replace(/热门概念命中[:：]/, '').trim().split('|');
      for (const m of matches) {
        const match = m.match(/(.+?)\(今日([+\-\d.]+%),排名第(\d+)(?:,(.+?))?\)/);
        if (match) {
          hotMatches.push({
            name: match[1].trim(),
            pct: match[2],
            rank: match[3],
            type: match[4]?.trim() || '',
          });
        }
      }
    }
  }
  return { concepts, hotMatches };
}

interface ConceptBadgeProps {
  conceptContext?: string;
}

export const ConceptBadge: React.FC<ConceptBadgeProps> = ({ conceptContext }) => {
  if (!conceptContext) return null;

  const { concepts, hotMatches } = parseConceptContext(conceptContext);
  if (concepts.length === 0 && hotMatches.length === 0) return null;

  const hotNames = new Set(hotMatches.map(h => h.name));

  return (
    <div className="flex items-center gap-1.5 overflow-x-auto pb-1 scrollbar-hide">
      {hotMatches.map(h => (
        <span
          key={h.name}
          className="flex-shrink-0 text-[11px] px-2 py-0.5 rounded-full bg-orange-500/15 border border-orange-500/25 text-orange-300 font-medium whitespace-nowrap"
        >
          {h.name}
          <span className="ml-1 text-[10px] text-orange-400/70">{h.pct}</span>
          {h.type && (
            <span className="ml-1 text-[9px] text-orange-400/50">
              {h.type.includes('持续') ? '🔥' : '⚡'}
            </span>
          )}
        </span>
      ))}
      {concepts.filter(c => !hotNames.has(c)).map(c => (
        <span
          key={c}
          className="flex-shrink-0 text-[11px] px-2 py-0.5 rounded-full bg-black/[0.04] border border-black/[0.06] text-muted whitespace-nowrap"
        >
          {c}
        </span>
      ))}
    </div>
  );
};
