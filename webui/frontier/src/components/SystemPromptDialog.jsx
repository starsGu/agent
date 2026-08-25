import { useEffect, useRef, useState } from 'react';
import { getSystemPrompt, updateSystemPrompt } from '../api.js';

export default function SystemPromptDialog({ open, onClose }) {
  const dialogRef = useRef(null);
  const [systemPrompt, setSystemPrompt] = useState('');
  const [initialPrompt, setInitialPrompt] = useState('');
  const [loaded, setLoaded] = useState(false);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return undefined;

    if (!open) {
      if (dialog.open) dialog.close();
      return undefined;
    }

    dialog.showModal();
    const controller = new AbortController();
    setSystemPrompt('');
    setInitialPrompt('');
    setLoaded(false);

    async function loadSystemPrompt() {
      setLoading(true);
      setError('');

      try {
        const prompt = await getSystemPrompt(controller.signal);
        setSystemPrompt(prompt);
        setInitialPrompt(prompt);
        setLoaded(true);
      } catch (requestError) {
        if (requestError.name !== 'AbortError') {
          setError(requestError.message);
        }
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    }

    loadSystemPrompt();
    return () => controller.abort();
  }, [open]);

  async function closeAndSave() {
    if (loading || saving) return;

    if (!loaded) {
      onClose();
      return;
    }

    if (systemPrompt === initialPrompt) {
      onClose();
      return;
    }

    setSaving(true);
    setError('');

    try {
      const savedPrompt = await updateSystemPrompt(systemPrompt);
      setInitialPrompt(savedPrompt);
      onClose();
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setSaving(false);
    }
  }

  function handleCancel(event) {
    event.preventDefault();
    closeAndSave();
  }

  function handleBackdropClick(event) {
    if (event.target === dialogRef.current) closeAndSave();
  }

  return (
    <dialog
      ref={dialogRef}
      className="settings-dialog"
      aria-labelledby="settings-title"
      onCancel={handleCancel}
      onClick={handleBackdropClick}
    >
      <div className="settings-panel">
        <div className="settings-heading">
          <div>
            <p className="eyebrow">SETTINGS</p>
            <h2 id="settings-title">设置</h2>
          </div>
          <button
            className="dialog-close"
            type="button"
            aria-label="关闭并保存"
            disabled={loading || saving}
            onClick={closeAndSave}
          >
            ×
          </button>
        </div>

        <label className="prompt-field">
          <span>System prompt</span>
          <textarea
            value={systemPrompt}
            rows={10}
            placeholder={loading ? '正在加载…' : '输入系统提示词'}
            disabled={loading || saving || !loaded}
            onChange={(event) => setSystemPrompt(event.target.value)}
          />
        </label>

        {error ? (
          <p className="settings-error" role="alert">
            {error}
          </p>
        ) : null}

        <p className="settings-hint">
          {loading
            ? '正在加载…'
            : saving
              ? '正在保存…'
              : error && !loaded
                ? '加载失败，请关闭后重试'
                : '关闭对话框时自动保存'}
        </p>
      </div>
    </dialog>
  );
}
