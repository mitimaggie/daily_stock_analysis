import type React from 'react';
import { useState } from 'react';

interface AiDiagnosisProps {
  analysisSummary?: string;
  intelligence?: Record<string, any>;
  counterArguments?: string[];
  positionAdvice?: { has_position?: string; no_position?: string };
}

/**
 * AI 诊断组件
 * 整合 AI 综合分析 + 信息依据（业绩、舆情、催化剂、风险、反面论据）
 */
export const AiDiagnosis: React.FC<AiDiagnosisProps> = ({
  analysisSummary,
  intelligence,
  counterArguments,
  positionAdvice,
}) => {
  const [expanded, setExpanded] = useState(false);
  const adviceText = positionAdvice?.has_position ?? positionAdvice?.no_position;

  const earningsOutlook = intelligence?.earnings_outlook ?? intelligence?.earningsOutlook;
  const sentimentSummary = intelligence?.sentiment_summary ?? intelligence?.sentimentSummary;
  const positiveCatalysts: string[] = intelligence?.positive_catalysts ?? intelligence?.positiveCatalysts ?? [];
  const riskAlerts: string[] = intelligence?.risk_alerts ?? intelligence?.riskAlerts ?? [];
  const hasDetails = earningsOutlook || sentimentSummary || positiveCatalysts.length > 0 || riskAlerts.length > 0 || (counterArguments && counterArguments.length > 0);

  if (!analysisSummary && !hasDetails) return null;

  return (
    <div className="rounded-xl bg-[var(--bg-card)] border border-white/[0.06] p-4">
      <button
        type="button"
        className="w-full flex items-center justify-between"
        onClick={() => setExpanded(!expanded)}
      >
        <h3 className="text-sm font-semibold text-white/90 flex items-center gap-1.5">
          <span>🧠</span> AI 诊断
        </h3>
        <span className="text-xs text-white/30">{expanded ? '▲' : '▼'}</span>
      </button>

      {/* 操作建议（有仓/无仓分别展示） */}
      {adviceText && (
        <div className="mt-2 p-2.5 rounded-lg bg-cyan/[0.06] border border-cyan/20">
          <div className="text-[10px] text-cyan/50 mb-1 font-medium tracking-wide uppercase">
            {positionAdvice?.has_position ? '持仓建议' : '入场建议'}
          </div>
          <p className="text-[13px] text-cyan/90 leading-snug">{adviceText}</p>
        </div>
      )}

      {/* AI 综合分析（始终可见） */}
      {analysisSummary && (
        <p className="mt-3 text-[13px] text-white/70 leading-relaxed whitespace-pre-wrap">
          {analysisSummary}
        </p>
      )}

      {/* 信息依据（折叠） */}
      {expanded && hasDetails && (
        <div className="mt-3 pt-3 border-t border-white/5 space-y-2.5">
          {earningsOutlook && (
            <div className="flex items-start gap-2 text-[12px]">
              <span className="flex-shrink-0 text-cyan-400/70">📊</span>
              <div>
                <span className="text-white/40 text-[11px]">业绩预期</span>
                <p className="text-white/60 leading-relaxed">{earningsOutlook}</p>
              </div>
            </div>
          )}

          {sentimentSummary && (
            <div className="flex items-start gap-2 text-[12px]">
              <span className="flex-shrink-0 text-cyan-400/70">🫧</span>
              <div>
                <span className="text-white/40 text-[11px]">舆情情绪</span>
                <p className="text-white/60 leading-relaxed">{sentimentSummary}</p>
              </div>
            </div>
          )}

          {positiveCatalysts.length > 0 && (
            <div className="flex items-start gap-2 text-[12px]">
              <span className="flex-shrink-0 text-green-400/70">✨</span>
              <div>
                <span className="text-white/40 text-[11px]">正面催化</span>
                {positiveCatalysts.map((c, i) => (
                  <p key={i} className="text-white/60 leading-relaxed">· {c}</p>
                ))}
              </div>
            </div>
          )}

          {riskAlerts.length > 0 && (
            <div className="flex items-start gap-2 text-[12px]">
              <span className="flex-shrink-0 text-red-400/70">⚠️</span>
              <div>
                <span className="text-white/40 text-[11px]">风险提示</span>
                {riskAlerts.map((r, i) => (
                  <p key={i} className="text-white/60 leading-relaxed">· {r}</p>
                ))}
              </div>
            </div>
          )}

          {counterArguments && counterArguments.length > 0 && (
            <div className="flex items-start gap-2 text-[12px]">
              <span className="flex-shrink-0 text-yellow-400/70">⚖️</span>
              <div>
                <span className="text-white/40 text-[11px]">反面论据</span>
                {counterArguments.map((ca, i) => (
                  <p key={i} className="text-white/60 leading-relaxed">· {ca}</p>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
};
