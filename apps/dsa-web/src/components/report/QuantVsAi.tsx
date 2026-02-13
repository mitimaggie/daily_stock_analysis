import type React from 'react';
import type { QuantVsAi as QuantVsAiType } from '../../types/analysis';

interface QuantVsAiProps {
  data: QuantVsAiType;
}

/** 评分→颜色 */
const scoreColor = (s: number | null | undefined): string => {
  if (s == null) return 'text-white/40';
  if (s >= 70) return 'text-green-400';
  if (s >= 50) return 'text-yellow-400';
  if (s >= 35) return 'text-orange-400';
  return 'text-red-400';
};

/** 评分→方向标签 */
const scoreDirection = (s: number | null | undefined): string => {
  if (s == null) return '—';
  if (s >= 60) return '看多';
  if (s <= 40) return '看空';
  return '中性';
};

/**
 * 量化 vs AI 对比卡片
 */
export const QuantVsAi: React.FC<QuantVsAiProps> = ({ data }) => {
  const { quantScore, quantAdvice, aiScore, aiAdvice, divergenceReason } = data;

  // 分歧度
  const divergence = aiScore != null ? Math.abs(quantScore - aiScore) : 0;
  const hasDivergence = divergence >= 15;

  return (
    <div className="rounded-xl bg-[var(--bg-card)] border border-white/[0.06] p-4">
      <h3 className="text-sm font-semibold text-white/90 flex items-center gap-1.5 mb-3">
        <span>⚖️</span> 量化 vs AI
        {hasDivergence && (
          <span className="ml-auto text-[11px] px-2 py-0.5 rounded bg-orange-500/15 text-orange-400">
            分歧 {divergence}分
          </span>
        )}
      </h3>

      {/* 对比表格 */}
      <table className="w-full text-xs">
        <thead>
          <tr className="text-white/40 border-b border-white/[0.06]">
            <th className="text-left py-1.5 font-medium w-16"></th>
            <th className="text-center py-1.5 font-medium">量化模型</th>
            <th className="text-center py-1.5 font-medium">AI 研判</th>
          </tr>
        </thead>
        <tbody>
          {/* 评分行 */}
          <tr className="border-b border-white/[0.03]">
            <td className="py-2 text-white/50 font-medium">评分</td>
            <td className="py-2 text-center">
              <span className={`font-mono font-bold text-lg ${scoreColor(quantScore)}`}>
                {quantScore}
              </span>
              <span className="text-white/30 text-[11px] ml-1">
                ({scoreDirection(quantScore)})
              </span>
            </td>
            <td className="py-2 text-center">
              <span className={`font-mono font-bold text-lg ${scoreColor(aiScore)}`}>
                {aiScore ?? '—'}
              </span>
              {aiScore != null && (
                <span className="text-white/30 text-[11px] ml-1">
                  ({scoreDirection(aiScore)})
                </span>
              )}
            </td>
          </tr>
          {/* 建议行 */}
          <tr className="border-b border-white/[0.03]">
            <td className="py-2 text-white/50 font-medium">建议</td>
            <td className="py-2 text-center text-white/80 font-medium">{quantAdvice || '—'}</td>
            <td className="py-2 text-center text-white/80 font-medium">{aiAdvice || '—'}</td>
          </tr>
        </tbody>
      </table>

      {/* 分歧原因 */}
      {divergenceReason && (
        <div className="mt-2 pt-2 border-t border-white/[0.06] text-[11px] text-white/50 leading-relaxed">
          <span className="text-white/30">逻辑：</span>{divergenceReason}
        </div>
      )}
    </div>
  );
};
