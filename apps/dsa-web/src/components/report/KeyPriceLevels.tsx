import React from 'react';
import type { KeyPriceLevel } from '../../types/analysis';

interface KeyPriceLevelsProps {
  levels: KeyPriceLevel[];
  currentPrice?: number;
  riskRewardRatio?: number;
  takeProfitPlan?: string;
  hasPositionInfo?: boolean;
  costPrice?: number;
  defenseMode?: boolean;
}

const TYPE_CONFIG: Record<string, { emoji: string; color: string; bg: string }> = {
  take_profit: { emoji: '🟡', color: '#ffaa00', bg: 'rgba(255,170,0,0.08)' },
  breakout:    { emoji: '🔵', color: '#00d4ff', bg: 'rgba(0,212,255,0.08)' },
  buy:         { emoji: '🟢', color: '#00ff88', bg: 'rgba(0,255,136,0.08)' },
  support:     { emoji: '🟠', color: '#ff8c00', bg: 'rgba(255,140,0,0.08)' },
  stop_loss:   { emoji: '🔴', color: '#ff4466', bg: 'rgba(255,68,102,0.08)' },
  resistance:  { emoji: '⚪', color: '#999',    bg: 'rgba(153,153,153,0.08)' },
};

/**
 * 盘中关键价位表 — 价格从高→低排列，当前价位高亮
 */
export const KeyPriceLevels: React.FC<KeyPriceLevelsProps> = ({
  levels,
  currentPrice,
  riskRewardRatio,
  takeProfitPlan,
  hasPositionInfo = false,
  costPrice,
  defenseMode = false,
}) => {
  if (!levels || levels.length === 0) return null;

  // 已按价格从高到低排序（后端已排），做防御性排序
  const sorted = [...levels].sort((a, b) => b.price - a.price);

  // 找到当前价应该插入的位置
  let insertIdx = sorted.length;
  if (currentPrice && currentPrice > 0) {
    insertIdx = sorted.findIndex((l) => l.price < currentPrice);
    if (insertIdx === -1) insertIdx = sorted.length;
  }

  // 找到成本价应该插入的位置
  let costIdx = -1;
  if (hasPositionInfo && costPrice && costPrice > 0) {
    costIdx = sorted.findIndex((l) => l.price < costPrice);
    if (costIdx === -1) costIdx = sorted.length;
  }

  return (
    <div className="rounded-xl bg-[var(--bg-card)] border border-white/[0.06] p-4">
      {/* 标题栏 */}
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold text-white/90 flex items-center gap-1.5">
          <span>📍</span> 盘中关键价位
        </h3>
        {riskRewardRatio != null && riskRewardRatio > 0 && (
          <span className={`text-xs font-mono px-2 py-0.5 rounded ${
            riskRewardRatio >= 2 ? 'bg-green-500/15 text-green-400' :
            riskRewardRatio >= 1.5 ? 'bg-yellow-500/15 text-yellow-400' :
            'bg-red-500/15 text-red-400'
          }`}>
            R:R {riskRewardRatio.toFixed(1)}:1
          </span>
        )}
      </div>

      {/* 价位表格 */}
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="text-white/40 border-b border-white/[0.06]">
              <th className="text-left py-1.5 pr-2 font-medium">价位</th>
              <th className="text-left py-1.5 px-2 font-medium">类型</th>
              <th className="text-left py-1.5 pl-2 font-medium">触发动作</th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((level, idx) => {
              const cfg = TYPE_CONFIG[level.type] || TYPE_CONFIG.resistance;
              const isAboveCurrent = idx < insertIdx;

              return (
                <React.Fragment key={`${level.price}-${level.type}`}>
                  {/* 成本价标记行 */}
                  {costIdx >= 0 && idx === costIdx && costPrice && costPrice > 0 && (
                    <tr>
                      <td colSpan={3} className="py-1">
                        <div className="flex items-center gap-2 text-[11px]">
                          <div className="flex-1 h-px bg-purple-400/40" />
                          <span className="text-purple-400 font-mono font-bold whitespace-nowrap">
                            💰 成本 {costPrice.toFixed(2)}
                          </span>
                          <div className="flex-1 h-px bg-purple-400/40" />
                        </div>
                      </td>
                    </tr>
                  )}
                  {/* 当前价标记行 */}
                  {idx === insertIdx && currentPrice && currentPrice > 0 && (
                    <tr>
                      <td colSpan={3} className="py-1">
                        <div className="flex items-center gap-2 text-[11px]">
                          <div className="flex-1 h-px bg-cyan-400/40" />
                          <span className="text-cyan-400 font-mono font-bold whitespace-nowrap">
                            ▶ 当前价 {currentPrice.toFixed(2)}
                          </span>
                          <div className="flex-1 h-px bg-cyan-400/40" />
                        </div>
                      </td>
                    </tr>
                  )}
                  <tr
                    className="border-b border-white/[0.03] hover:bg-white/[0.02] transition-colors"
                    style={{ opacity: isAboveCurrent ? 1 : 0.75 }}
                  >
                    <td className="py-1.5 pr-2">
                      <span className="font-mono font-bold text-sm" style={{ color: cfg.color }}>
                        {level.price.toFixed(2)}
                      </span>
                    </td>
                    <td className="py-1.5 px-2">
                      <span
                        className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[11px] font-medium"
                        style={{ background: cfg.bg, color: cfg.color }}
                      >
                        {cfg.emoji} {defenseMode && level.action === '理想买点' ? '反弹减仓' : hasPositionInfo && level.action === '理想买点' ? '加仓机会' : level.action}
                      </span>
                    </td>
                    <td className="py-1.5 pl-2 text-white/60">
                      {level.desc}
                    </td>
                  </tr>
                </React.Fragment>
              );
            })}
            {/* 如果当前价低于所有价位 */}
            {insertIdx === sorted.length && currentPrice && currentPrice > 0 && (
              <tr>
                <td colSpan={3} className="py-1">
                  <div className="flex items-center gap-2 text-[11px]">
                    <div className="flex-1 h-px bg-cyan-400/40" />
                    <span className="text-cyan-400 font-mono font-bold whitespace-nowrap">
                      ▶ 当前价 {currentPrice.toFixed(2)}
                    </span>
                    <div className="flex-1 h-px bg-cyan-400/40" />
                  </div>
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {/* 分批止盈计划 */}
      {takeProfitPlan && (
        <div className="mt-2 pt-2 border-t border-white/[0.06] text-[11px] text-white/50">
          📋 {takeProfitPlan}
        </div>
      )}
      {/* 说明：技术面客观价位，与持仓诊断的区别 */}
      <div className="mt-2 pt-2 border-t border-white/[0.04] text-[10px] text-white/25 leading-relaxed">
        💡 <span className="text-white/40 font-medium">如何选择止损线？</span> 回测数据（1590 样本）显示：「技术止损」综合收益 +0.49%，胜率 36%；「成本线止损」触发率高达 97%（股价几乎必然短暂跌破买入价），综合收益 -0.22%。<span className="text-yellow-400/60">建议以此处技术止损为执行线，成本线仅作心理参考。</span>
      </div>
    </div>
  );
};
