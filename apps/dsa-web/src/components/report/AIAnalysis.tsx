import type React from 'react';
import { useState } from 'react';

interface AIAnalysisProps {
  intelligence: Record<string, any>;
  counterArguments?: string[];
}

/**
 * AI 分析视角组件
 * 展示风险提示、正面催化剂、情绪总结、盈利展望、反面论据
 */
export const AIAnalysis: React.FC<AIAnalysisProps> = ({ intelligence, counterArguments }) => {
  const [expanded, setExpanded] = useState(true);

  if (!intelligence || Object.keys(intelligence).length === 0) return null;

  const riskAlerts = intelligence.risk_alerts ?? intelligence.riskAlerts ?? [];
  const positiveCatalysts = intelligence.positive_catalysts ?? intelligence.positiveCatalysts ?? [];
  const sentimentSummary = intelligence.sentiment_summary ?? intelligence.sentimentSummary ?? '';
  const earningsOutlook = intelligence.earnings_outlook ?? intelligence.earningsOutlook ?? '';

  return (
    <div className="rounded-xl bg-[var(--bg-card)] border border-white/[0.06] p-4">
      <button
        type="button"
        className="w-full flex items-center justify-between text-left mb-3"
        onClick={() => setExpanded(!expanded)}
      >
        <h3 className="text-sm font-semibold text-white/70">AI 分析视角</h3>
        <span className="text-xs text-white/30">{expanded ? '▲' : '▼'}</span>
      </button>

      {expanded && (
        <div className="space-y-4">
          {/* 情绪总结 */}
          {sentimentSummary && (
            <div className="p-3 rounded-lg bg-elevated border border-white/5">
              <h4 className="text-[10px] text-cyan font-medium mb-1.5">📊 市场情绪</h4>
              <p className="text-sm text-white/90 leading-relaxed">{sentimentSummary}</p>
            </div>
          )}

          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {/* 正面催化剂 */}
            {positiveCatalysts.length > 0 && (
              <div className="bg-success/5 rounded-lg p-3 border border-success/10">
                <h4 className="text-[10px] text-success font-medium mb-2">🟢 正面催化剂</h4>
                <div className="space-y-1.5">
                  {positiveCatalysts.map((item: string, i: number) => (
                    <div key={i} className="text-[11px] text-white/80 flex items-start gap-1.5">
                      <span className="text-success mt-0.5 flex-shrink-0">+</span>
                      <span>{item}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* 风险提示 */}
            {riskAlerts.length > 0 && (
              <div className="bg-danger/5 rounded-lg p-3 border border-danger/10">
                <h4 className="text-[10px] text-danger font-medium mb-2">🔴 风险提示</h4>
                <div className="space-y-1.5">
                  {riskAlerts.map((item: string, i: number) => (
                    <div key={i} className="text-[11px] text-white/80 flex items-start gap-1.5">
                      <span className="text-danger mt-0.5 flex-shrink-0">−</span>
                      <span>{item}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>

          {/* 盈利展望 */}
          {earningsOutlook && (
            <div className="p-3 rounded-lg bg-elevated border border-white/5">
              <h4 className="text-[10px] text-cyan font-medium mb-1.5">💰 盈利展望</h4>
              <p className="text-sm text-white/90 leading-relaxed">{earningsOutlook}</p>
            </div>
          )}

          {/* 反面论据 */}
          {counterArguments && counterArguments.length > 0 && (
            <div className="p-3 rounded-lg bg-warning/5 border border-warning/10">
              <h4 className="text-[10px] text-warning font-medium mb-2">⚖️ 反面论证（当前判断的潜在漏洞）</h4>
              <div className="space-y-1.5">
                {counterArguments.map((item: string, i: number) => (
                  <div key={i} className="text-[11px] text-white/80 flex items-start gap-1.5">
                    <span className="text-warning mt-0.5 flex-shrink-0">•</span>
                    <span>{item}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
};
