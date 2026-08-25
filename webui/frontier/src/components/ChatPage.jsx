import ChatInput from './ChatInput.jsx';
import MessageList from './MessageList.jsx';

export default function ChatPage({
  messages,
  currentSession,
  loading,
  sending,
  workingDirectory,
  selectingDirectory,
  error,
  onSend,
  onSelectWorkingDirectory,
  onRetry,
}) {
  return (
    <section className="chat-page">
      <div className="chat-heading">
        <div>
          <p className="eyebrow">CURRENT SESSION</p>
          <h1>
            {currentSession === null ? '新会话' : '对话'}
          </h1>
        </div>
        <span className={`connection-dot ${error ? 'error' : ''}`}>
          {error ? '连接异常' : '本地服务'}
        </span>
      </div>

      {error ? (
        <div className="error-banner" role="alert">
          <span>{error}</span>
          <button type="button" onClick={onRetry}>
            重试
          </button>
        </div>
      ) : null}

      <MessageList
        messages={messages}
        loading={loading}
        currentSession={currentSession}
      />

      <ChatInput
        disabled={loading || !workingDirectory}
        sending={sending}
        workingDirectory={workingDirectory}
        selectingDirectory={selectingDirectory}
        onSend={onSend}
        onSelectWorkingDirectory={onSelectWorkingDirectory}
        resetKey={currentSession ?? 'new-session'}
      />
    </section>
  );
}
