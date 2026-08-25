import { useEffect, useState } from 'react';
import { getAgentState } from './api.js';
import TopBar from './components/TopBar.jsx';
import Content from './components/Content.jsx';
import PluginDialog from './components/PluginDialog.jsx';
import SystemPromptDialog from './components/SystemPromptDialog.jsx';

export default function App() {
  const [agentState, setAgentState] = useState(false);
  const [checkingAgent, setCheckingAgent] = useState(true);
  const [refreshTime, setRefreshTime] = useState(0);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [pluginsOpen, setPluginsOpen] = useState(false);

  useEffect(() => {
    const controller = new AbortController();

    async function checkAgent() {
      setCheckingAgent(true);

      try {
        setAgentState(await getAgentState(controller.signal));
      } catch (requestError) {
        if (requestError.name !== 'AbortError') setAgentState(false);
      } finally {
        if (!controller.signal.aborted) setCheckingAgent(false);
      }
    }

    checkAgent();
    return () => controller.abort();
  }, [refreshTime]);

  return (
    <div className="app-shell">
      <TopBar
        agentState={agentState}
        checkingAgent={checkingAgent}
        settingsOpen={settingsOpen}
        pluginsOpen={pluginsOpen}
        onOpenSettings={() => {
          setPluginsOpen(false);
          setSettingsOpen(true);
        }}
        onOpenPlugins={() => {
          setSettingsOpen(false);
          setPluginsOpen(true);
        }}
        onReconnect={() => setRefreshTime((value) => value + 1)}
      />
      {agentState ? <Content /> : <main className="workspace" />}
      <SystemPromptDialog
        open={settingsOpen}
        onClose={() => setSettingsOpen(false)}
      />
      <PluginDialog
        open={pluginsOpen}
        onClose={() => setPluginsOpen(false)}
      />
    </div>
  );
}
