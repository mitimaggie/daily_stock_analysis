import type React from 'react';

interface KeyInsightsProps {
  intelligence?: Record<string, any>;
  counterArguments?: string[];
  quantExtras?: Record<string, any>;
}

interface InsightItem {
  emoji: string;
  text: string;
  category: 'risk' | 'positive' | 'data' | 'signal';
}

const CATEGORY_STYLE: Record<string, { bg: string; border: string; text: string }> = {
  risk:     { bg: 'bg-red-500/5',    border: 'border-red-500/10',    text: 'text-red-400' },
  positive: { bg: 'bg-green-500/5',  border: 'border-green-500/10',  text: 'text-green-400' },
  data:     { bg: 'bg-cyan-500/5',   border: 'border-cyan-500/10',   text: 'text-cyan-400' },
  signal:   { bg: 'bg-yellow-500/5', border: 'border-yellow-500/10', text: 'text-yellow-400' },
};

/**
 * 重要信息汇总 — 合并 AI 分析 + 量化风险因子
 * PushPlus 风格：emoji 分类的结构化 bullet list
 */
export const KeyInsights: React.FC<KeyInsightsProps> = ({
  intelligence,
  counterArguments,
  quantExtras,
}) => {
  const items: InsightItem[] = [];
  const qe = quantExtras as Record<string, any> | undefined;

  // === AI 分析部分 ===
  if (intelligence) {
    // 盈利展望
    const earnings = intelligence.earnings_outlook ?? intelligence.earningsOutlook;
    if (earnings) {
      items.push({ emoji: '📊', text: `业绩预期: ${earnings}`, category: 'data' });
    }

    // 市场情绪
    const sentiment = intelligence.sentiment_summary ?? intelligence.sentimentSummary;
    if (sentiment) {
      items.push({ emoji: '🫧', text: `舆情情绪: ${sentiment}`, category: 'data' });
    }

    // 正面催化剂
    const catalysts = intelligence.positive_catalysts ?? intelligence.positiveCatalysts ?? [];
    for (const c of catalysts) {
      items.push({ emoji: '✨', text: c, category: 'positive' });
    }

    // 风险提示
    const risks = intelligence.risk_alerts ?? intelligence.riskAlerts ?? [];
    for (const r of risks) {
      items.push({ emoji: '⚠️', text: r, category: 'risk' });
    }
  }

  // === 量化风险因子 ===
  if (qe) {
    const riskFactors = qe.risk_factors ?? qe.riskFactors ?? [];
    for (const r of riskFactors) {
      // 避免和 AI risk_alerts 重复
      if (!items.some((i) => i.text === r)) {
        items.push({ emoji: '🔴', text: r, category: 'risk' });
      }
    }

    // PE 分位
    const pePct = qe.pe_percentile ?? qe.pePercentile;
    if (pePct != null && pePct >= 0) {
      if (pePct >= 90) {
        items.push({ emoji: '💎', text: `PE历史分位${pePct.toFixed(0)}%，估值极度高企`, category: 'risk' });
      } else if (pePct <= 10) {
        items.push({ emoji: '💎', text: `PE历史分位${pePct.toFixed(0)}%，估值极低`, category: 'positive' });
      }
    }

    // 信号共振
    const resonance = qe.resonance_signals ?? qe.resonanceSignals ?? [];
    if (resonance.length >= 2) {
      items.push({ emoji: '🔥', text: `多指标共振: ${resonance.join(', ')}`, category: 'signal' });
    }

    // 情绪极端
    const sentimentExtreme = qe.sentiment_extreme ?? qe.sentimentExtreme;
    if (sentimentExtreme) {
      const detail = qe.sentiment_extreme_detail ?? qe.sentimentExtremeDetail ?? '';
      items.push({
        emoji: sentimentExtreme === '极度贪婪' ? '🔴' : '🟢',
        text: `${sentimentExtreme}${detail ? `: ${detail}` : ''}`,
        category: sentimentExtreme === '极度贪婪' ? 'risk' : 'positive',
      });
    }

    // 量能异动
    const volTrend = qe.volume_trend_3d ?? qe.volumeTrend3d;
    if (volTrend) {
      items.push({ emoji: '📊', text: `量能: ${volTrend}`, category: 'data' });
    }
  }

  // === 反面论据 ===
  if (counterArguments && counterArguments.length > 0) {
    for (const ca of counterArguments) {
      items.push({ emoji: '⚖️', text: ca, category: 'positive' });
    }
  }

  if (items.length === 0) return null;

  // 按分类排序：signal > risk > data > positive
  const order = { signal: 0, risk: 1, data: 2, positive: 3 };
  items.sort((a, b) => order[a.category] - order[b.category]);

  return (
    <div className="rounded-xl bg-[var(--bg-card)] border border-black/[0.06] p-4">
      <h3 className="text-sm font-semibold text-secondary flex items-center gap-1.5 mb-3">
        <span>📋</span> 重要信息
      </h3>

      <div className="space-y-1.5">
        {items.map((item, idx) => {
          const style = CATEGORY_STYLE[item.category];
          return (
            <div
              key={idx}
              className={`flex items-start gap-2 text-[12px] leading-relaxed px-2 py-1 rounded ${style.bg} ${style.border} border`}
            >
              <span className="flex-shrink-0 mt-0.5">{item.emoji}</span>
              <span className={`${style.text}`}>{item.text}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
};
