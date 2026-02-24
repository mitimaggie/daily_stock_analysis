import { useState, useRef, useEffect, useCallback } from 'react';
import ReactMarkdown from 'react-markdown';
import type { ChatMessage, AgentEvent } from '../../api/chat';
import { sendChatMessageStream } from '../../api/chat';

// ============ 常量 ============

const MAX_HISTORY_MESSAGES = 20;
const STORAGE_KEY_PREFIX = 'dsa_chat_';

const QUICK_QUESTIONS = [
  '这个评分意味着什么？',
  '为什么推荐这个止损位？',
  '如果明天跳空高开怎么办？',
  '帮我制定一个操作计划',
];

// ============ Agent 进度状态 ============

interface AgentStep {
  type: 'thinking' | 'tool_start' | 'tool_done';
  display_name?: string;
  tool?: string;
}

function AgentProgressBubble({ steps }: { steps: AgentStep[] }) {
  if (steps.length === 0) return null;
  const last = steps[steps.length - 1];
  const isThinking = last.type === 'thinking';
  const toolName = last.display_name || last.tool || '';

  return (
    <div className="flex justify-start">
      <div className="max-w-[85%] rounded-xl px-3.5 py-2.5 text-[12px] bg-surface-2 border border-white/5 text-white/50">
        <div className="flex items-center gap-2">
          {isThinking ? (
            <>
              <span className="inline-flex gap-0.5">
                <span className="w-1 h-1 rounded-full bg-cyan/60 animate-bounce" style={{ animationDelay: '0ms' }} />
                <span className="w-1 h-1 rounded-full bg-cyan/60 animate-bounce" style={{ animationDelay: '150ms' }} />
                <span className="w-1 h-1 rounded-full bg-cyan/60 animate-bounce" style={{ animationDelay: '300ms' }} />
              </span>
              <span>AI 正在思考...</span>
            </>
          ) : (
            <>
              <span className="text-cyan/70">⚙</span>
              <span>
                {last.type === 'tool_start' ? `正在${toolName}` : `${toolName}完成`}
              </span>
              {last.type === 'tool_start' && (
                <span className="inline-flex gap-0.5 ml-1">
                  <span className="w-1 h-1 rounded-full bg-cyan/40 animate-pulse" />
                </span>
              )}
            </>
          )}
        </div>
        {steps.length > 1 && (
          <div className="mt-1.5 flex flex-wrap gap-1">
            {steps.filter(s => s.type === 'tool_done').map((s, i) => (
              <span key={i} className="text-[10px] px-1.5 py-0.5 rounded bg-white/5 text-white/30">
                ✓ {s.display_name || s.tool}
              </span>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

// ============ 持久化 ============

function loadMessages(queryId: string): ChatMessage[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY_PREFIX + queryId);
    return raw ? JSON.parse(raw) : [];
  } catch { return []; }
}

function saveMessages(queryId: string, msgs: ChatMessage[]) {
  try {
    localStorage.setItem(STORAGE_KEY_PREFIX + queryId, JSON.stringify(msgs.slice(-50)));
  } catch { /* ignore quota errors */ }
}

// ============ 多轮截断 ============

function truncateForApi(msgs: ChatMessage[], max = MAX_HISTORY_MESSAGES): ChatMessage[] {
  if (msgs.length <= max) return msgs;
  return msgs.slice(-max);
}

// ============ 组件 ============

interface ChatPanelProps {
  queryId: string;
  onClose: () => void;
}

export const ChatPanel: React.FC<ChatPanelProps> = ({ queryId, onClose }) => {
  const [messages, setMessages] = useState<ChatMessage[]>(() => loadMessages(queryId));
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [streamingText, setStreamingText] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [agentSteps, setAgentSteps] = useState<AgentStep[]>([]);
  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  // queryId 切换时重新加载历史
  useEffect(() => {
    setMessages(loadMessages(queryId));
    setStreamingText('');
    setError(null);
    setAgentSteps([]);
  }, [queryId]);

  // 持久化消息
  useEffect(() => {
    if (messages.length > 0) {
      saveMessages(queryId, messages);
    }
  }, [messages, queryId]);

  // 自动滚动到底部
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, loading, streamingText]);

  // 聚焦输入框
  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  const handleSend = useCallback(async (overrideText?: string) => {
    const text = (overrideText ?? input).trim();
    if (!text || loading) return;

    const userMsg: ChatMessage = { role: 'user', content: text };
    const newMessages = [...messages, userMsg];
    setMessages(newMessages);
    setInput('');
    setError(null);
    setLoading(true);
    setStreamingText('');
    setAgentSteps([]);

    let accumulated = '';

    try {
      await sendChatMessageStream(
        { query_id: queryId, messages: truncateForApi(newMessages) },
        (chunk) => {
          accumulated += chunk;
          setStreamingText(accumulated);
        },
        () => {
          setMessages(prev => [...prev, { role: 'assistant', content: accumulated }]);
          setStreamingText('');
          setAgentSteps([]);
          setLoading(false);
        },
        (errMsg) => {
          setError(errMsg);
          setLoading(false);
          setStreamingText('');
          setAgentSteps([]);
        },
        (event: AgentEvent) => {
          if (event.type === 'thinking' || event.type === 'tool_start' || event.type === 'tool_done') {
            setAgentSteps(prev => [...prev, {
              type: event.type as AgentStep['type'],
              display_name: event.display_name,
              tool: event.tool,
            }]);
          }
        },
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : '请求失败');
      setLoading(false);
      setStreamingText('');
      setAgentSteps([]);
    }
  }, [input, loading, messages, queryId]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleClear = useCallback(() => {
    setMessages([]);
    localStorage.removeItem(STORAGE_KEY_PREFIX + queryId);
  }, [queryId]);

  return (
    <div className="flex flex-col h-full bg-surface-1 border-l border-white/5">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-white/5">
        <div className="flex items-center gap-2">
          <span className="text-base">💬</span>
          <h3 className="text-sm font-semibold text-white">AI 深度探讨</h3>
        </div>
        <div className="flex items-center gap-1">
          {messages.length > 0 && (
            <button
              onClick={handleClear}
              className="w-7 h-7 flex items-center justify-center rounded-md text-muted hover:text-white hover:bg-white/5 transition-colors"
              title="清空对话"
            >
              🗑
            </button>
          )}
          <button
            onClick={onClose}
            className="w-7 h-7 flex items-center justify-center rounded-md text-muted hover:text-white hover:bg-white/5 transition-colors"
          >
            ✕
          </button>
        </div>
      </div>

      {/* Welcome hint */}
      {messages.length === 0 && !loading && (
        <div className="px-4 py-6 text-center">
          <div className="text-2xl mb-2">🤖</div>
          <p className="text-sm text-muted mb-3">基于当前分析报告，向 AI 提问任何问题</p>
          <div className="flex flex-wrap gap-2 justify-center">
            {QUICK_QUESTIONS.map(q => (
              <button
                key={q}
                onClick={() => handleSend(q)}
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
              className={`max-w-[85%] rounded-xl px-3.5 py-2.5 text-[13px] leading-relaxed ${
                msg.role === 'user'
                  ? 'bg-cyan/15 text-white border border-cyan/20 whitespace-pre-wrap'
                  : 'bg-surface-2 text-white/80 border border-white/5 chat-markdown'
              }`}
            >
              {msg.role === 'assistant' ? (
                <ReactMarkdown>{msg.content}</ReactMarkdown>
              ) : (
                msg.content
              )}
            </div>
          </div>
        ))}

        {/* Agent 工具调用进度（loading 且有进度事件时显示） */}
        {loading && agentSteps.length > 0 && !streamingText && (
          <AgentProgressBubble steps={agentSteps} />
        )}

        {/* Streaming response */}
        {loading && streamingText && (
          <div className="flex justify-start">
            <div className="max-w-[85%] rounded-xl px-3.5 py-2.5 text-[13px] leading-relaxed bg-surface-2 text-white/80 border border-white/5 chat-markdown">
              <ReactMarkdown>{streamingText}</ReactMarkdown>
              <span className="inline-block w-1.5 h-4 bg-cyan/60 animate-pulse ml-0.5 align-text-bottom" />
            </div>
          </div>
        )}

        {/* Loading indicator (before first chunk, no agent steps) */}
        {loading && !streamingText && agentSteps.length === 0 && (
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

        {/* Quick follow-up suggestions (after AI responds) */}
        {!loading && messages.length > 0 && messages[messages.length - 1].role === 'assistant' && (
          <div className="flex flex-wrap gap-1.5 pt-1">
            {['继续分析风险', '给我一个操作计划', '还有什么要注意的？'].map(q => (
              <button
                key={q}
                onClick={() => handleSend(q)}
                className="text-[10px] px-2 py-1 rounded-full border border-white/8 text-white/35 hover:text-white/60 hover:border-cyan/25 hover:bg-cyan/5 transition-all"
              >
                {q}
              </button>
            ))}
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
            onClick={() => handleSend()}
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
