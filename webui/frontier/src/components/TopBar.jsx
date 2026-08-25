export default function TopBar({
  agentState,
  checkingAgent,
  settingsOpen,
  pluginsOpen,
  onOpenSettings,
  onOpenPlugins,
  onReconnect,
}) {
  return (
    <header className="topbar">
      <div className="brand" aria-label="Frontier Chat">
        <span className="brand-mark">F</span>
        <span>Frontier</span>
      </div>
      <nav className="topnav" aria-label="顶部菜单">
        <button
          className={`topnav-button ${settingsOpen || pluginsOpen ? '' : 'active'}`}
          type="button"
        >
          会话
        </button>
        <button
          className={`topnav-button ${settingsOpen ? 'active' : ''}`}
          type="button"
          aria-haspopup="dialog"
          aria-expanded={settingsOpen}
          onClick={onOpenSettings}
        >
          设置
        </button>
        <button
          className={`topnav-button ${pluginsOpen ? 'active' : ''}`}
          type="button"
          aria-haspopup="dialog"
          aria-expanded={pluginsOpen}
          onClick={onOpenPlugins}
        >
          插件
        </button>
        <span className={`connection-dot ${agentState ? '' : 'error'}`}>
          {checkingAgent ? '检测中' : agentState ? '已连接' : '未连接'}
        </span>
        {!agentState && !checkingAgent ? (
          <button className="topnav-button" type="button" onClick={onReconnect}>
            重新检测
          </button>
        ) : null}
      </nav>
    </header>
  );
}
