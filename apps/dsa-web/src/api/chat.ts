import { API_BASE_URL } from '../utils/constants';

export interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
}

export interface ChatRequest {
  query_id: string;
  messages: ChatMessage[];
}

export interface ChatResponse {
  reply: string;
}

export async function sendChatMessage(req: ChatRequest): Promise<ChatResponse> {
  const res = await fetch(`${API_BASE_URL}/api/v1/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || `Chat failed: ${res.status}`);
  }
  return res.json();
}

export interface AgentEvent {
  type: 'thinking' | 'tool_start' | 'tool_done' | 'chunk' | 'done' | 'error';
  tool?: string;
  display_name?: string;
  text?: string;
  message?: string;
  // legacy compat
  chunk?: string;
  done?: boolean;
  error?: string;
}

/**
 * 流式对话 — SSE 事件回调（支持 Agent 工具调用进度）
 */
export async function sendChatMessageStream(
  req: ChatRequest,
  onChunk: (text: string) => void,
  onDone: () => void,
  onError: (err: string) => void,
  onAgentEvent?: (event: AgentEvent) => void,
): Promise<void> {
  const res = await fetch(`${API_BASE_URL}/api/v1/chat/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    onError(err.detail || `Chat failed: ${res.status}`);
    return;
  }

  const reader = res.body?.getReader();
  if (!reader) {
    onError('No readable stream');
    return;
  }

  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = lines.pop() || '';

    for (const line of lines) {
      if (!line.startsWith('data: ')) continue;
      try {
        const payload = JSON.parse(line.slice(6)) as AgentEvent;

        // 新格式：通过 type 字段路由
        if (payload.type === 'done' || payload.done) {
          onDone();
          return;
        }
        if (payload.type === 'error' || payload.error) {
          onError(payload.message || payload.error || 'Unknown error');
          return;
        }
        if (payload.type === 'chunk') {
          const text = payload.text || payload.chunk || '';
          if (text) onChunk(text);
          continue;
        }
        // Agent 进度事件（thinking / tool_start / tool_done）
        if (payload.type && onAgentEvent) {
          onAgentEvent(payload);
          continue;
        }
        // 旧格式兼容
        if (payload.chunk) {
          onChunk(payload.chunk);
        }
      } catch { /* skip malformed lines */ }
    }
  }
  onDone();
}
