import { useEffect, useRef, useState } from 'react';
import { getPlugins, setPluginEnabled } from '../api.js';

export default function PluginDialog({ open, onClose }) {
  const dialogRef = useRef(null);
  const [plugins, setPlugins] = useState([]);
  const [usePlugins, setUsePlugins] = useState({});
  const [loading, setLoading] = useState(false);
  const [updatingName, setUpdatingName] = useState('');
  const [error, setError] = useState('');

  async function loadPluginList(signal) {
    const data = await getPlugins(signal);
    setPlugins(data.plugins);
    setUsePlugins(data.usePlugins);
  }

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return undefined;

    if (!open) {
      if (dialog.open) dialog.close();
      return undefined;
    }

    dialog.showModal();
    const controller = new AbortController();
    setLoading(true);
    setError('');

    loadPluginList(controller.signal)
      .catch((requestError) => {
        if (requestError.name !== 'AbortError') setError(requestError.message);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });

    return () => controller.abort();
  }, [open]);

  async function togglePlugin(name) {
    const enabled = Boolean(usePlugins[name]);
    setUpdatingName(name);
    setError('');

    try {
      await setPluginEnabled(name, !enabled);
      await loadPluginList();
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setUpdatingName('');
    }
  }

  function handleCancel(event) {
    event.preventDefault();
    if (!updatingName) onClose();
  }

  function handleBackdropClick(event) {
    if (event.target === dialogRef.current && !updatingName) onClose();
  }

  return (
    <dialog
      ref={dialogRef}
      className="settings-dialog plugins-dialog"
      aria-labelledby="plugins-title"
      onCancel={handleCancel}
      onClick={handleBackdropClick}
    >
      <div className="settings-panel">
        <div className="settings-heading">
          <div>
            <p className="eyebrow">PLUGINS</p>
            <h2 id="plugins-title">插件</h2>
          </div>
          <button
            className="dialog-close"
            type="button"
            aria-label="关闭插件列表"
            disabled={Boolean(updatingName)}
            onClick={onClose}
          >
            ×
          </button>
        </div>

        {loading ? <p className="plugin-empty">正在加载插件…</p> : null}

        {!loading && plugins.length === 0 && !error ? (
          <p className="plugin-empty">没有发现可用插件</p>
        ) : null}

        {!loading && plugins.length > 0 ? (
          <div className="plugin-list">
            {plugins.map((currentPlugin, index) => {
              const enabled = Boolean(usePlugins[currentPlugin.name]);
              const updating = updatingName === currentPlugin.name;

              return (
                <div
                  className="plugin-item"
                  key={`${currentPlugin.name}-${currentPlugin.version}-${index}`}
                >
                  <div className="plugin-info">
                    <div className="plugin-name-row">
                      <strong>{currentPlugin.name}</strong>
                      <span className={`plugin-status ${enabled ? 'enabled' : ''}`}>
                        {enabled ? '已启用' : '已禁用'}
                      </span>
                    </div>
                    <span className="plugin-version">版本 {currentPlugin.version}</span>
                  </div>
                  <button
                    className={`plugin-toggle ${enabled ? 'disable' : ''}`}
                    type="button"
                    disabled={Boolean(updatingName)}
                    onClick={() => togglePlugin(currentPlugin.name)}
                  >
                    {updating ? '处理中…' : enabled ? '禁用' : '启用'}
                  </button>
                </div>
              );
            })}
          </div>
        ) : null}

        {error ? (
          <p className="settings-error" role="alert">
            {error}
          </p>
        ) : null}
      </div>
    </dialog>
  );
}
