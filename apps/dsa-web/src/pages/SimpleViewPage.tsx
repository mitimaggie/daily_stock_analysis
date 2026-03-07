import type React from 'react';
import { useState, useEffect } from 'react';
import { portfolioApi, type SimpleViewData } from '../api/portfolio';

const SimpleViewPage: React.FC = () => {
  const code = window.location.pathname.split('/').filter(Boolean)[1] || '';
  const [data, setData] = useState<SimpleViewData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!code) { setError('无效股票代码'); setLoading(false); return; }
    portfolioApi.getSimpleView(code)
      .then(d => { setData(d as SimpleViewData); setLoading(false); })
      .catch(() => { setError('加载失败'); setLoading(false); });
  }, [code]);

  if (loading) return (
    <div className="min-h-screen bg-[#0a0a0f] flex items-center justify-center text-white/40 text-[16px]">
      加载中…
    </div>
  );
  if (error || !data) return (
    <div className="min-h-screen bg-[#0a0a0f] flex items-center justify-center text-red-400 text-[16px]">
      {error || '数据不可用'}
    </div>
  );

  const signal = data.signal;
  const pnlPct = data.pnl_pct;
  const bgMap: Record<string, string> = {
    stop_loss: 'bg-red-500/10 border-red-500/40',
    reduce: 'bg-amber-500/10 border-amber-500/40',
    add_watch: 'bg-emerald-500/10 border-emerald-500/40',
    hold: 'bg-white/5 border-white/15',
    unknown: 'bg-white/3 border-white/10',
  };
  const textMap: Record<string, string> = {
    stop_loss: 'text-red-400', reduce: 'text-amber-400',
    add_watch: 'text-emerald-400', hold: 'text-white/70', unknown: 'text-white/30',
  };

  const cardBg = bgMap[signal] || bgMap.unknown;
  const signalColor = textMap[signal] || textMap.unknown;
  const pnlColor = pnlPct == null ? 'text-white/40' : pnlPct >= 0 ? 'text-red-400' : 'text-emerald-400';

  return (
    <div className="min-h-screen bg-[#0a0a0f] text-white flex flex-col items-center justify-center px-4 py-8">
      <div className={`w-full max-w-sm rounded-2xl border ${cardBg} p-6 space-y-5`}>
        {/* 代码 + 名称 */}
        <div className="text-center">
          <div className="text-[13px] text-white/40">{data.name}</div>
          <div className="text-[28px] font-bold font-mono text-white/90 mt-0.5">{data.code}</div>
        </div>

        {/* 信号灯 */}
        <div className="text-center">
          <div className="text-[64px] leading-none">{data.signal_emoji}</div>
          <div className={`text-[20px] font-bold mt-2 ${signalColor}`}>
            {data.signal_text || signal.replace('_', ' ').toUpperCase()}
          </div>
        </div>

        {/* P&L 大字 */}
        <div className="text-center">
          <div className="text-[11px] text-white/30 mb-1">浮盈亏</div>
          <div className={`text-[36px] font-bold font-mono ${pnlColor}`}>
            {pnlPct == null ? '--' : `${pnlPct >= 0 ? '+' : ''}${pnlPct.toFixed(2)}%`}
          </div>
        </div>

        {/* 关键数字 */}
        <div className="grid grid-cols-2 gap-3">
          <div className="rounded-lg bg-white/5 p-3 text-center">
            <div className="text-[10px] text-white/30 mb-0.5">成本价</div>
            <div className="text-[18px] font-mono text-white/80">{data.cost_price?.toFixed(2) ?? '--'}</div>
          </div>
          <div className="rounded-lg bg-white/5 p-3 text-center">
            <div className="text-[10px] text-white/30 mb-0.5">当前价</div>
            <div className="text-[18px] font-mono text-white/80">{data.current_price?.toFixed(2) ?? '--'}</div>
          </div>
          <div className="rounded-lg bg-amber-500/10 border border-amber-500/20 p-3 text-center">
            <div className="text-[10px] text-amber-400/60 mb-0.5">ATR止损</div>
            <div className="text-[18px] font-mono text-amber-400">{data.atr_stop?.toFixed(2) ?? '--'}</div>
          </div>
          <div className="rounded-lg bg-white/5 p-3 text-center">
            <div className="text-[10px] text-white/30 mb-0.5">AI评分</div>
            <div className="text-[18px] font-mono text-white/80">{data.score ?? '--'}</div>
          </div>
        </div>

        {/* AI一句话建议 */}
        {data.advice_short && (
          <div className="rounded-lg bg-white/5 p-3 text-center">
            <div className="text-[10px] text-white/30 mb-1">AI建议</div>
            <div className="text-[16px] font-bold text-white/90">{data.advice_short}</div>
          </div>
        )}

        {/* 一句话摘要 */}
        {data.analysis_summary && (
          <div className="text-[12px] text-white/50 text-center leading-relaxed">
            {data.analysis_summary}
          </div>
        )}

        {/* 持仓周期 + 再分析日期 */}
        <div className="flex items-center justify-between text-[11px] text-white/30">
          {data.holding_horizon_label && (
            <span className="px-2 py-0.5 rounded border border-sky-500/20 text-sky-400/70">{data.holding_horizon_label}</span>
          )}
          {data.next_review_at && (
            <span>📅 复盘: {data.next_review_at}</span>
          )}
        </div>

        {/* 分析时间 */}
        {data.analyzed_at && (
          <div className="text-center text-[10px] text-white/20">
            分析时间: {new Date(data.analyzed_at!).toLocaleString('zh-CN')}
          </div>
        )}

        {/* 返回按钮 */}
        <a href="/portfolio" className="block text-center text-[12px] text-white/30 hover:text-white/60 transition py-2">
          ← 返回持仓管理
        </a>
      </div>
    </div>
  );
};

export default SimpleViewPage;
