import { useEffect, useRef } from 'react';

function textOf(message) {
  const value = message?.text ?? message?.content ?? '';
  return String(value);
}

export function renderAssistantSegment(segment, index) {
  if (segment?.type === 'tool_call' && segment.status === 'complete') {
    return (
      <p
        className="assistant-tool-call complete"
        key={segment.tool_call_id || segment.call_key || `tool-${index}`}
      >
        <span aria-hidden="true">✓</span>
        <span>{segment.name || 'unknown_tool'}</span>
        <span className="tool-call-status">· 调用完成</span>
      </p>
    );
  }

  if (segment?.type === 'tool_call') {
    const provisionalText = `${segment.name || ''}${segment.arguments || ''}`;
    return (
      <p
        className="assistant-tool-call streaming"
        key={segment.call_key || `tool-${index}`}
      >
        {provisionalText || '正在生成工具调用…'}
      </p>
    );
  }

  if (segment?.type === 'text') {
    return <p key={`text-${index}`}>{segment.text}</p>;
  }

  return null;
}

export default function MessageList({
  messages,
  loading,
  currentSession,
}) {
  const listRef = useRef(null);

  useEffect(() => {
    const list = listRef.current;
    if (list) list.scrollTop = list.scrollHeight;
  }, [messages]);

  if (loading && messages.length === 0) {
    return <div className="empty-state">正在读取消息…</div>;
  }

  if (currentSession === null && messages.length === 0) {
    return <div className="empty-state" aria-label="新会话" />;
  }

  if (messages.length === 0) {
    return <div className="empty-state">这个会话还没有消息</div>;
  }

  return (
    <div className="message-list" aria-live="polite" ref={listRef}>
      {messages.map((message, index) => {
        const role = message?.role === 'assistant' ? 'assistant' : 'user';
        return (
          <article
            className={`message-row ${role}`}
            key={message?.id ?? `${role}-${index}`}
          >
            <div className="message-avatar" aria-hidden="true">
              {role === 'assistant' ? 'AI' : '你'}
            </div>
            <div className="message-content">
              <span className="message-author">
                {role === 'assistant' ? 'Frontier' : '你'}
              </span>
              {role === 'assistant' ? (
                <div className="assistant-body">
                  {Array.isArray(message?.segments)
                    ? message.segments.map(renderAssistantSegment)
                    : <p>{textOf(message)}</p>}
                  {message?.streaming ? (
                    <span className="streaming-caret" aria-label="正在生成" />
                  ) : null}
                </div>
              ) : <p>{textOf(message)}</p>}
            </div>
          </article>
        );
      })}
    </div>
  );
}
