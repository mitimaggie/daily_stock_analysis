import { useState, useRef, useEffect, useCallback } from 'react';
import type { ChatMessage } from '../../api/chat';
import { sendChatMessage } from '../../api/chat';

interface ChatPanelProps {
  queryId: string;
  onClose: () => void;
}

export const ChatPanel: React.FC<ChatPanelProps> = ({ queryId, onClose }) => {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  // 自动滚动到底部
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, loading]);

  // 聚焦输入框
  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  const handleSend = useCallback(async () => {
    const text = input.trim();
    if (!text || loading) return;

    const userMsg: ChatMessage = { role: 'user', content: text };
    const newMessages = [...messages, userMsg];
    setMessages(newMessages);
    setInput('');
    setError(null);
    setLoading(true);

    try {
      const res = await sendChatMessage({
        query_id: queryId,
        messages: newMessages,
      });
      setMessages(prev => [...prev, { role: 'assistant', content: res.reply }]);
    } catch (e) {
      setError(e instanceof Error ? e.message : '请求失败');
    } finally {
      setLoading(false);
    }
  }, [input, loading, messages, queryId]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div className="flex flex-col h-full bg-surface-1 border-l border-white/5">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-white/5">
        <div className="flex items-center gap-2">
          <span className="text-base">💬</span>
          <h3 className="text-sm font-semibold text-white">AI 深度探讨</h3>
        </div>
        <button
          onClick={onClose}
          className="w-7 h-7 flex items-center justify-center rounded-md text-muted hover:text-white hover:bg-white/5 transition-colors"
        >
          ✕
        </button>
      </div>

      {/* Welcome hint */}
      {messages.length === 0 && (
        <div className="px-4 py-6 text-center">
          <div className="text-2xl mb-2">🤖</div>
          <p className="text-sm text-muted mb-3">基于当前分析报告，向 AI 提问任何问题</p>
          <div className="flex flex-wrap gap-2 justify-center">
            {[
              '这个评分意味着什么？',
              '为什么推荐这个止损位？',
              '如果明天跳空高开怎么办？',
              '帮我制定一个操作计划',
            ].map(q => (
              <button
                key={q}
                onClick={() => { setInput(q); inputRef.current?.focus(); }}
                className="text-[11px] px-2.5 py-1.5 rounded-full border border-white/10 text-white/50 hover:text-white hover:border-cyan/30 hover:bg-cyan/5 transition-all"
              >
                {q}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Messages */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto px-4 py-3 space-y-3">
        {messages.map((msg, i) => (
          <div key={i} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
            <div
              className={`max-w-[85%] rounded-xl px-3.5 py-2.5 text-[13px] leading-relaxed whitespace-pre-wrap ${
                msg.role === 'user'
                  ? 'bg-cyan/15 text-white border border-cyan/20'
                  : 'bg-surface-2 text-white/80 border border-white/5'
              }`}
            >
              {msg.content}
            </div>
          </div>
        ))}

        {/* Loading indicator */}
        {loading && (
          <div className="flex justify-start">
            <div className="bg-surface-2 border border-white/5 rounded-xl px-3.5 py-2.5 text-[13px] text-muted">
              <span className="inline-flex gap-1">
                <span className="animate-pulse">●</span>
                <span className="animate-pulse" style={{ animationDelay: '0.2s' }}>●</span>
                <span className="animate-pulse" style={{ animationDelay: '0.4s' }}>●</span>
              </span>
            </div>
          </div>
        )}

        {/* Error */}
        {error && (
          <div className="text-[11px] text-danger bg-danger/10 border border-danger/20 rounded-lg px-3 py-2">
            {error}
          </div>
        )}
      </div>

      {/* Input */}
      <div className="px-3 py-3 border-t border-white/5">
        <div className="flex gap-2 items-end">
          <textarea
            ref={inputRef}
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="输入问题...（Enter 发送，Shift+Enter 换行）"
            rows={1}
            className="flex-1 bg-surface-2 border border-white/10 rounded-lg px-3 py-2 text-[13px] text-white placeholder-white/30 resize-none focus:outline-none focus:border-cyan/30 transition-colors"
            style={{ maxHeight: '120px' }}
            disabled={loading}
          />
          <button
            onClick={handleSend}
            disabled={!input.trim() || loading}
            className="shrink-0 w-9 h-9 flex items-center justify-center rounded-lg bg-cyan/20 text-cyan hover:bg-cyan/30 disabled:opacity-30 disabled:cursor-not-allowed transition-all"
          >
            ↑
          </button>
        </div>
        <div className="text-[10px] text-muted/50 mt-1.5 text-center">
          AI 分析仅供参考，不构成投资建议
        </div>
      </div>
    </div>
  );
};
