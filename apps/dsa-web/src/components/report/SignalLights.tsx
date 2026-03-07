import React from 'react';

interface SignalLightsProps {
  quantExtras: Record<string, any> | null;
  northboundHolding?: Record<string, any> | null;
}

type SignalColor = 'green' | 'yellow' | 'red' | 'gray';

function getTechSignal(qe: Record<string, any>): { color: SignalColor; label: string } {
  const ma = (qe.ma_alignment ?? qe.maAlignment ?? '').toLowerCase();
  const buySignal = qe.buy_signal ?? qe.buySignal ?? '';

  if (ma.includes('强势多头') || ma.includes('多头排列') || buySignal === '强烈买入' || buySignal === '激进买入') {
    return { color: 'green', label: '强势多头' };
  }
  if (ma.includes('多头') || ma.includes('偏多') || buySignal === '买入' || buySignal === '加仓') {
    return { color: 'green', label: '偏多' };
  }
  if (ma.includes('强势空头') || ma.includes('空头排列') || buySignal === '清仓') {
    return { color: 'red', label: '强势空头' };
  }
  if (ma.includes('空头') || ma.includes('偏空') || buySignal === '减仓') {
    return { color: 'red', label: '偏空' };
  }
  return { color: 'yellow', label: '震荡' };
}

function getFundamentalSignal(qe: Record<string, any>): { color: SignalColor; label: string } {
  const vv = (qe.valuation_verdict ?? qe.valuationVerdict ?? '').toLowerCase();
  const fs = (qe.fundamental_signal ?? qe.fundamentalSignal ?? '').toLowerCase();

  if (!vv && !fs) return { color: 'gray', label: '数据缺失' };

  if (vv.includes('低估') || vv.includes('合理偏低')) return { color: 'green', label: '估值低' };
  if (vv.includes('严重高估') || vv.includes('泡沫')) return { color: 'red', label: '严重高估' };
  if (vv.includes('高估')) return { color: 'red', label: '高估' };
  if (vv.includes('合理')) return { color: 'yellow', label: '估值合理' };

  if (fs.includes('较差') || fs.includes('极差') || fs.includes('差')) return { color: 'red', label: '基本面弱' };
  if (fs.includes('良好') || fs.includes('优秀') || fs.includes('强')) return { color: 'green', label: '基本面强' };

  return { color: 'yellow', label: '基本面中' };
}

function getCapitalSignal(qe: Record<string, any>): { color: SignalColor; label: string } {
  const cf = (qe.capital_flow_signal ?? qe.capitalFlowSignal ?? '').toLowerCase();

  if (!cf || cf === '资金面数据正常') return { color: 'yellow', label: '资金中性' };
  if (cf.includes('持续流入') || cf.includes('大额净流入') || cf.includes('大幅净流入')) {
    return { color: 'green', label: '主力大举流入' };
  }
  if (cf.includes('净流入') || cf.includes('流入')) return { color: 'green', label: '资金流入' };
  if (cf.includes('持续流出') || cf.includes('大额净流出')) return { color: 'red', label: '主力持续撤离' };
  if (cf.includes('净流出') || cf.includes('流出')) return { color: 'red', label: '资金流出' };
  return { color: 'yellow', label: '资金中性' };
}

const DOT_GLOW: Record<SignalColor, string> = {
  green:  'bg-emerald-400 shadow-[0_0_8px_2px_rgba(52,211,153,0.45)]',
  yellow: 'bg-yellow-400  shadow-[0_0_6px_1px_rgba(250,204,21,0.35)]',
  red:    'bg-red-400     shadow-[0_0_8px_2px_rgba(248,113,113,0.45)]',
  gray:   'bg-white/20',
};

const TEXT_COLOR: Record<SignalColor, string> = {
  green:  'text-emerald-400',
  yellow: 'text-yellow-400',
  red:    'text-red-400',
  gray:   'text-white/25',
};

function getNorthboundSignal(nb: Record<string, any> | null | undefined): { color: SignalColor; label: string } | null {
  if (!nb) return null;
  const pct = nb.holding_pct_a ?? nb.holdingPctA ?? 0;
  const chg = nb.shares_change ?? nb.sharesChange ?? 0;
  if (!pct && !chg) return null;
  if (chg > 0) {
    return pct >= 2 ? { color: 'green', label: '外资大幅增持' } : { color: 'green', label: '外资增持' };
  }
  if (chg < 0) {
    return { color: 'red', label: '外资减持' };
  }
  return pct >= 2 ? { color: 'yellow', label: `外资${pct.toFixed(1)}%持仓` } : { color: 'gray', label: '外资低配' };
}

export const SignalLights: React.FC<SignalLightsProps> = ({ quantExtras, northboundHolding }) => {
  if (!quantExtras) return null;

  const tech    = getTechSignal(quantExtras);
  const fund    = getFundamentalSignal(quantExtras);
  const capital = getCapitalSignal(quantExtras);
  const north   = getNorthboundSignal(northboundHolding);

  const signals = [
    { key: '技术面', ...tech },
    { key: '基本面', ...fund },
    { key: '资金面', ...capital },
    ...(north ? [{ key: '北向', ...north }] : []),
  ];

  return (
    <div className="rounded-xl bg-[var(--bg-card)] border border-white/[0.06] px-4 py-3">
      <div className="flex items-center justify-around">
        {signals.map(({ key, color, label }) => (
          <div key={key} className="flex flex-col items-center gap-1.5 flex-1">
            <div className={`w-2.5 h-2.5 rounded-full ${DOT_GLOW[color]}`} />
            <span className="text-[9px] text-white/25 uppercase tracking-wider">{key}</span>
            <span className={`text-[11px] font-semibold ${TEXT_COLOR[color]}`}>{label}</span>
          </div>
        ))}
      </div>
    </div>
  );
};
