function titleOf(session, index) {
  const title = session?.title ?? session?.name;
  return typeof title === 'string' && title.trim()
    ? title.trim()
    : `会话 ${index + 1}`;
}

export default function SessionSidebar({
  sessions,
  currentSession,
  onSelectSession,
  onNewSession,
  onDeleteSession,
  getSessionId,
  loading,
  deletingSessionId,
  disabled,
}) {
  return (
    <aside className="sidebar" aria-label="会话列表">
      <div className="sidebar-heading">
        <span>会话</span>
        <span className="session-count">{sessions.length}</span>
      </div>

      <div className="session-list">
        {loading && sessions.length === 0 ? (
          <p className="sidebar-status">正在加载…</p>
        ) : null}

        {!loading && sessions.length === 0 ? (
          <p className="sidebar-status">暂无会话</p>
        ) : null}

        {sessions.map((session, index) => {
          const sessionId = getSessionId(session);
          const sessionTitle = titleOf(session, index);
          return (
            <div
              className={`session-item ${
                sessionId === currentSession ? 'selected' : ''
              }`}
              key={sessionId ?? index}
            >
              <button
                className="session-select"
                type="button"
                onClick={() => onSelectSession(sessionId)}
                disabled={disabled || sessionId === null}
              >
                <span className="session-icon" aria-hidden="true">
                  {index + 1}
                </span>
                <span className="session-title">{sessionTitle}</span>
              </button>
              <button
                className="session-delete"
                type="button"
                aria-label={`删除会话 ${sessionTitle}`}
                title="删除会话"
                disabled={
                  disabled
                  || sessionId === null
                  || deletingSessionId !== null
                }
                onClick={(event) => {
                  event.stopPropagation();
                  onDeleteSession(sessionId);
                }}
              >
                {deletingSessionId === sessionId ? '…' : '×'}
              </button>
            </div>
          );
        })}
        <div className={`session-item ${currentSession === null ? 'selected' : ''}`}>
          <button
            className="session-select"
            type="button"
            onClick={onNewSession}
            disabled={disabled}
          >
            <span className="session-icon" aria-hidden="true">+</span>
            <span className="session-title">新建会话</span>
          </button>
        </div>
      </div>
    </aside>
  );
}
