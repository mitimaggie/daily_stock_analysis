import type React from 'react';
import { useState } from 'react';

interface AiDigestCardProps {
  analysisSummary?: string;
}

const MAX_CHARS = 300;

export const AiDigestCard: React.FC<AiDigestCardProps> = ({ analysisSummary }) => {
  const [expanded, setExpanded] = useState(false);

  if (!analysisSummary) return null;

  const paragraphs = analysisSummary.split(/\n+/).filter(Boolean);
  const shortParagraphs = paragraphs.slice(0, 3);
  const shortText = shortParagraphs.join('\n');
  const isLong = analysisSummary.length > MAX_CHARS || paragraphs.length > 3;
  const displayText = expanded ? analysisSummary : shortText.slice(0, MAX_CHARS);

  return (
    <div className="rounded-xl bg-[var(--bg-card)] border border-black/[0.06] p-4">
      <h3 className="text-sm font-semibold text-primary/80 mb-2 flex items-center gap-1.5">
        <span>🧠</span> AI 诊断摘要
      </h3>
      <p className="text-[13px] text-secondary leading-relaxed whitespace-pre-wrap">
        {displayText}
        {!expanded && isLong && '…'}
      </p>
      {isLong && (
        <button
          type="button"
          onClick={() => setExpanded(v => !v)}
          className="mt-2 text-[11px] text-cyan-400/70 hover:text-cyan-400 transition-colors"
        >
          {expanded ? '收起 ▲' : '展开更多 ▼'}
        </button>
      )}
    </div>
  );
};
