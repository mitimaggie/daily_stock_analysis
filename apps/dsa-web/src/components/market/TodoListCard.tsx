import type React from 'react';
import { useNavigate } from 'react-router-dom';
import type { TodoItem } from '../../types/market';

interface TodoListCardProps {
  todos: TodoItem[];
}

const priorityConfig: Record<TodoItem['priority'], { dot: string; border: string }> = {
  high: { dot: 'bg-red-500', border: 'border-l-red-500/60' },
  medium: { dot: 'bg-orange-400', border: 'border-l-orange-400/60' },
  low: { dot: 'bg-black/[0.12]', border: 'border-l-black/[0.08]' },
};

const TodoListCard: React.FC<TodoListCardProps> = ({ todos }) => {
  const navigate = useNavigate();

  const handleClick = (code: string) => {
    navigate(`/analysis?stock=${code}`);
  };

  return (
    <div className="terminal-card p-4">
      <h3 className="text-[14px] font-semibold text-primary mb-3 flex items-center gap-2">
        <svg className="w-4 h-4 text-cyan" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" />
        </svg>
        今日操作清单
      </h3>

      {todos.length === 0 ? (
        <div className="py-6 text-center">
          <p className="text-[13px] text-secondary">今日无需特别操作，保持观望</p>
          <p className="text-[11px] text-muted mt-1">关注市场变化，等待确定性机会</p>
        </div>
      ) : (
        <div className="space-y-2">
          {todos.map((item, idx) => {
            const cfg = priorityConfig[item.priority] ?? priorityConfig.low;
            return (
              <button
                key={`${item.code}-${idx}`}
                type="button"
                onClick={() => handleClick(item.code)}
                className={`w-full text-left p-3 rounded-lg bg-elevated/50 border border-border-dim border-l-2 ${cfg.border} hover:bg-hover transition-colors`}
              >
                <div className="flex items-center gap-2 mb-1">
                  <span className={`w-2 h-2 rounded-full ${cfg.dot} flex-shrink-0`} />
                  <span className="text-[13px] font-mono text-primary/80">{item.code}</span>
                  <span className="text-[12px] text-secondary">{item.name}</span>
                </div>
                <p className="text-[12px] text-primary/70 pl-4">{item.message}</p>
                {item.detail && (
                  <p className="text-[11px] text-muted pl-4 mt-0.5">{item.detail}</p>
                )}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
};

export default TodoListCard;
