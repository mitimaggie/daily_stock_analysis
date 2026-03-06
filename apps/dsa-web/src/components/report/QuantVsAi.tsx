import type React from 'react';
import { useState } from 'react';
import type { QuantVsAi as QuantVsAiType } from '../../types/analysis';

interface QuantVsAiProps {
  data: QuantVsAiType;
  skillUsed?: string;
}

const SKILL_LABEL: Record<string, string> = {
  druckenmiller: 'Druckenmiller',
  lynch: 'Lynch',
  buffett: 'Buffett',
  soros: 'Soros',
  default: '通用',
};

const SKILL_DESC: Record<string, string> = {
  druckenmiller: '宏观流动性',
  soros: '反身性情绪',
  lynch: '成长股侦察',
  buffett: '价值投资',
  default: '综合',
};

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
export const QuantVsAi: React.FC<QuantVsAiProps> = ({ data, skillUsed }) => {
  const { quantScore, quantAdvice, aiScore, aiAdvice, divergenceReason, divergenceAlert } = data;

  // 分歧度（优先用后端计算值）
  const divergence = data.divergence ?? (aiScore != null ? Math.abs(quantScore - aiScore) : 0);
  const hasSevereDivergence = divergence >= 20;
  const hasMildDivergence = divergence >= 10 && divergence < 20;

  // 严重分歧时默认展开（用户需要知道），否则默认折叠
  const [expanded, setExpanded] = useState(hasSevereDivergence);

  return (
    <div className="rounded-xl bg-[var(--bg-card)] border border-white/[0.06] p-4">
      <button
        type="button"
        className="w-full flex items-center justify-between text-left"
        onClick={() => setExpanded(!expanded)}
      >
        <h3 className="text-sm font-semibold text-white/70 flex items-center gap-1.5">
          <span>⚖️</span> 技术面 vs AI研判
          {skillUsed && (
            <span className="text-[10px] px-1.5 py-0.5 rounded border border-violet-500/20 bg-violet-500/5 text-violet-400/80 font-mono font-normal">
              {SKILL_LABEL[skillUsed] ?? skillUsed} · {SKILL_DESC[skillUsed] ?? 'AI'}
            </span>
          )}
          {hasSevereDivergence && (
            <span className="text-[11px] px-2 py-0.5 rounded bg-red-500/20 text-red-400 font-semibold animate-pulse">
              ⚠️ 严重分歧 {divergence}分
            </span>
          )}
          {hasMildDivergence && (
            <span className="text-[11px] px-2 py-0.5 rounded bg-orange-500/15 text-orange-400">
              分歧 {divergence}分
            </span>
          )}
        </h3>
        <span className="text-xs text-white/30 ml-2">{expanded ? '▲' : '▼'}</span>
      </button>
      {!expanded && (
        <div className="mt-2 text-[11px] text-white/35">
          技术信号 <span className={`font-mono font-semibold ${scoreColor(quantScore)}`}>{quantScore}</span>
          {aiScore != null && <> · AI <span className={`font-mono font-semibold ${scoreColor(aiScore)}`}>{aiScore}</span></>}
          {hasSevereDivergence && <span className="ml-1 text-red-400">分歧</span>}
        </div>
      )}

      {expanded && (<>
      {/* 严重分歧告警横幅 */}
      {hasSevereDivergence && (
        <div className="mb-3 px-3 py-2 rounded-lg bg-red-500/10 border border-red-500/25 text-[11px] text-red-300 leading-relaxed">
          {divergenceAlert || `技术信号(${quantScore}分) 与 AI研判(${aiScore}分) 方向不一致，请结合基本面和市场情绪综合判断`}
        </div>
      )}

      {/* 对比表格 */}
      <table className="w-full text-xs">
        <thead>
          <tr className="text-white/40 border-b border-white/[0.06]">
            <th className="text-left py-1.5 font-medium w-16"></th>
            <th className="text-center py-1.5 font-medium">技术信号</th>
            <th className="text-center py-1.5 font-medium">
              AI 研判
              {skillUsed && <span className="text-[10px] text-violet-400/60 font-mono font-normal ml-1">({SKILL_LABEL[skillUsed] ?? skillUsed})</span>}
            </th>
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

      {/* 综合研判叙述 */}
      <div className="mt-2.5 pt-2.5 border-t border-white/[0.06] text-[12px] text-white/60 leading-relaxed">
        <span className="text-white/40 text-[11px]">综合研判：</span>
        {(() => {
          const qDir = scoreDirection(quantScore);
          const aDir = aiScore != null ? scoreDirection(aiScore) : null;
          const qLabel = `技术信号${quantScore}分(${qDir})`;
          const aLabel = aiScore != null ? `AI研判${aiScore}分(${aDir})` : 'AI 未出分';
          const aligned = aiScore != null && Math.abs(quantScore - aiScore) < 15;
          const prefix = aligned
            ? `${qLabel} vs ${aLabel}，技术信号与AI研判方向一致。`
            : aiScore != null
              ? `${qLabel} vs ${aLabel}，存在差异(${divergence}分)。`
              : `${qLabel}，${aLabel}。`;
          const reason = divergenceReason && divergenceReason !== '与量化结论一致'
            ? ` ${divergenceReason}`
            : '';
          return prefix + reason;
        })()}
      </div>
      </>)}
    </div>
  );
};
