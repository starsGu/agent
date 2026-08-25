import { useEffect, useState } from 'react';

export default function ChatInput({
  disabled,
  sending,
  workingDirectory,
  selectingDirectory,
  onSend,
  onSelectWorkingDirectory,
  resetKey,
}) {
  const [text, setText] = useState('');

  useEffect(() => {
    setText('');
  }, [resetKey]);

  async function submit() {
    if (!text.trim() || disabled || sending) return;
    const pendingText = text;
    setText('');
    await onSend(pendingText);
  }

  function handleKeyDown(event) {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      submit();
    }
  }

  return (
    <div className="composer-wrap">
      <div className="composer">
        <textarea
          aria-label="输入消息"
          value={text}
          onChange={(event) => setText(event.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={disabled ? '请先选择会话' : '输入你的问题…'}
          rows="1"
          disabled={disabled || sending}
        />
        <button
          className="send-button"
          type="button"
          onClick={submit}
          disabled={disabled || sending || !text.trim()}
          aria-label="发送消息"
        >
          {sending ? '发送中' : '发送'}
        </button>
      </div>
      <div className="composer-footer">
        <button
          className="working-directory-button"
          type="button"
          onClick={onSelectWorkingDirectory}
          disabled={disabled || sending || selectingDirectory}
          aria-label="选择当前对话的工作目录"
          title={workingDirectory
            ? `当前工作目录：${workingDirectory}`
            : '正在加载工作目录…'}
        >
          <svg
            viewBox="0 0 24 24"
            aria-hidden="true"
            focusable="false"
          >
            <path d="M3.75 6.75A1.75 1.75 0 0 1 5.5 5h4l2 2H18.5a1.75 1.75 0 0 1 1.75 1.75v7.75a1.75 1.75 0 0 1-1.75 1.75h-13a1.75 1.75 0 0 1-1.75-1.75V6.75Z" />
          </svg>
          <span className="visually-hidden">
            {selectingDirectory ? '正在选择目录' : '选择工作目录'}
          </span>
        </button>
        <p className="composer-hint">Enter 发送 · Shift + Enter 换行</p>
      </div>
    </div>
  );
}
