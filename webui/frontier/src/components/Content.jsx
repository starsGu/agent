import { useEffect, useRef, useState } from 'react';
import {
  deleteChatSession,
  getAgentSessions,
  getDefaultWorkingDirectory,
  getSessionMessages,
  openWorkingDirectoryPicker,
  postChatMessageStream,
} from '../api.js';
import { applyAssistantStreamEvent } from '../assistantSegments.js';
import {
  loadWorkingDirectories,
  saveWorkingDirectories,
} from '../workingDirectory.js';
import SessionSidebar from './SessionSidebar.jsx';
import ChatPage from './ChatPage.jsx';

function sessionIdOf(session) {
  const value = session?.session_id ?? session?.id;
  return value == null ? null : String(value);
}

function createSessionId(text) {
  const title = Array.from(text).slice(0, 4).join('');
  const randomNumber = crypto.getRandomValues(new Uint32Array(1))[0];
  return `${title}-${randomNumber}`;
}

function createMessageId(sessionId, role) {
  const uniqueId = typeof crypto.randomUUID === 'function'
    ? crypto.randomUUID()
    : crypto.getRandomValues(new Uint32Array(1))[0];
  return `${sessionId}-${role}-${uniqueId}`;
}

export default function Content() {
  const [chatMessages, setChatMessages] = useState([]);
  const [sessions, setSessions] = useState([]);
  const [currentSession, setCurrentSession] = useState(null);
  const [sessionsRefreshKey, setSessionsRefreshKey] = useState(0);
  const [messagesRefreshKey, setMessagesRefreshKey] = useState(0);
  const [loadingSessions, setLoadingSessions] = useState(true);
  const [loadingMessages, setLoadingMessages] = useState(false);
  const [sending, setSending] = useState(false);
  const [deletingSessionId, setDeletingSessionId] = useState(null);
  const [defaultWorkingDirectory, setDefaultWorkingDirectory] = useState('');
  const [workingDirectory, setWorkingDirectory] = useState('');
  const [workingDirectories, setWorkingDirectories] = useState(
    loadWorkingDirectories,
  );
  const [selectingDirectory, setSelectingDirectory] = useState(false);
  const [error, setError] = useState('');
  const skipNextMessageLoadRef = useRef(null);
  const activeStreamControllerRef = useRef(null);
  const loading = loadingSessions || loadingMessages;

  useEffect(() => () => activeStreamControllerRef.current?.abort(), []);

  useEffect(() => {
    const controller = new AbortController();

    async function loadDefaultDirectory() {
      try {
        const directory = await getDefaultWorkingDirectory(controller.signal);
        setDefaultWorkingDirectory(directory);
      } catch (requestError) {
        if (requestError.name !== 'AbortError') {
          setError(requestError.message || '加载默认工作目录失败');
        }
      }
    }

    loadDefaultDirectory();
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (!defaultWorkingDirectory) return;

    setWorkingDirectory(
      currentSession === null
        ? defaultWorkingDirectory
        : workingDirectories[currentSession] ?? defaultWorkingDirectory,
    );
  }, [currentSession, defaultWorkingDirectory, workingDirectories]);

  useEffect(() => {
    const controller = new AbortController();

    async function loadSessions() {
      setLoadingSessions(true);
      try {
        setSessions(await getAgentSessions(controller.signal));
      } catch (requestError) {
        if (requestError.name !== 'AbortError') {
          setError(requestError.message || '加载会话失败');
        }
      } finally {
        if (!controller.signal.aborted) setLoadingSessions(false);
      }
    }

    loadSessions();
    return () => controller.abort();
  }, [sessionsRefreshKey]);

  useEffect(() => {
    if (currentSession === null) {
      setChatMessages([]);
      setLoadingMessages(false);
      return undefined;
    }

    if (skipNextMessageLoadRef.current === currentSession) {
      skipNextMessageLoadRef.current = null;
      setLoadingMessages(false);
      return undefined;
    }

    const controller = new AbortController();

    async function loadMessages() {
      setLoadingMessages(true);
      setError('');
      try {
        setChatMessages(
          await getSessionMessages(currentSession, controller.signal),
        );
      } catch (requestError) {
        if (requestError.name !== 'AbortError') {
          setError(requestError.message || '加载消息失败');
        }
      } finally {
        if (!controller.signal.aborted) setLoadingMessages(false);
      }
    }

    loadMessages();
    return () => controller.abort();
  }, [currentSession, messagesRefreshKey]);

  function handleSelectSession(sessionId) {
    if (sending || sessionId === currentSession) return;
    setChatMessages([]);
    setCurrentSession(sessionId);
    setError('');
  }

  function handleNewSession() {
    if (sending) return;
    setCurrentSession(null);
    setChatMessages([]);
    setWorkingDirectory(defaultWorkingDirectory);
    setError('');
  }

  function rememberWorkingDirectory(sessionId, directory) {
    if (sessionId === null || !directory) return;

    setWorkingDirectories((currentDirectories) => {
      const nextDirectories = {
        ...currentDirectories,
        [sessionId]: directory,
      };
      saveWorkingDirectories(nextDirectories);
      return nextDirectories;
    });
  }

  function forgetWorkingDirectory(sessionId) {
    setWorkingDirectories((currentDirectories) => {
      if (!(sessionId in currentDirectories)) return currentDirectories;

      const nextDirectories = { ...currentDirectories };
      delete nextDirectories[sessionId];
      saveWorkingDirectories(nextDirectories);
      return nextDirectories;
    });
  }

  async function handleDeleteSession(sessionId) {
    if (sessionId === null || deletingSessionId !== null || sending) return;

    setDeletingSessionId(sessionId);
    setError('');

    try {
      await deleteChatSession(sessionId);
      forgetWorkingDirectory(sessionId);
      setSessions((currentSessions) => currentSessions.filter(
        (session) => sessionIdOf(session) !== sessionId,
      ));

      if (sessionId === currentSession) {
        setCurrentSession(null);
        setChatMessages([]);
        setWorkingDirectory(defaultWorkingDirectory);
      }
    } catch (requestError) {
      setError(requestError.message || '删除会话失败');
    } finally {
      setDeletingSessionId(null);
    }
  }

  async function handleSend(text) {
    const content = text.trim();
    if (!content || !workingDirectory || sending) return false;

    const targetSession = currentSession ?? createSessionId(content);
    const userMessageId = createMessageId(targetSession, 'user');
    const assistantMessageId = createMessageId(targetSession, 'assistant');
    const streamController = new AbortController();

    setSending(true);
    setError('');
    activeStreamControllerRef.current = streamController;
    setChatMessages((currentMessages) => [
      ...currentMessages,
      {
        id: userMessageId,
        session_id: targetSession,
        role: 'user',
        text: content,
      },
      {
        id: assistantMessageId,
        session_id: targetSession,
        role: 'assistant',
        segments: [],
        streaming: true,
      },
    ]);

    try {
      const doneEvent = await postChatMessageStream(
        content,
        targetSession,
        workingDirectory,
        {
          signal: streamController.signal,
          onEvent: (event) => {
            setChatMessages((currentMessages) => currentMessages.map(
              (message) => message.id === assistantMessageId
                ? {
                    ...message,
                    segments: applyAssistantStreamEvent(
                      message.segments,
                      event,
                    ),
                  }
                : message,
            ));
          },
        },
      );
      setChatMessages((currentMessages) => currentMessages.map(
        (message) => message.id === assistantMessageId
          ? {
              ...message,
              segments: doneEvent.ai_message,
              streaming: false,
            }
          : message,
      ));
      rememberWorkingDirectory(targetSession, workingDirectory);
      setSessions((currentSessions) => (
        currentSessions.some(
          (session) => sessionIdOf(session) === targetSession,
        )
          ? currentSessions
          : [
              ...currentSessions,
              { session_id: targetSession, title: targetSession },
            ]
      ));
      if (currentSession === null) {
        skipNextMessageLoadRef.current = targetSession;
        setCurrentSession(targetSession);
      }
      return true;
    } catch (requestError) {
      setChatMessages((currentMessages) => currentMessages.filter(
        (message) => message.id !== assistantMessageId,
      ));
      if (requestError.name !== 'AbortError') {
        setError(requestError.message || '发送失败');
      }
      return false;
    } finally {
      if (activeStreamControllerRef.current === streamController) {
        activeStreamControllerRef.current = null;
      }
      setSending(false);
    }
  }

  function handleRetry() {
    setError('');
    if (currentSession === null) {
      setSessionsRefreshKey((value) => value + 1);
    } else {
      setMessagesRefreshKey((value) => value + 1);
    }
  }

  async function handleSelectWorkingDirectory() {
    if (!workingDirectory || selectingDirectory) return;

    setSelectingDirectory(true);
    setError('');

    try {
      const selection = await openWorkingDirectoryPicker(workingDirectory);
      if (!selection.cancelled) {
        setWorkingDirectory(selection.workingDirectory);
        rememberWorkingDirectory(
          currentSession,
          selection.workingDirectory,
        );
      }
    } catch (requestError) {
      setError(requestError.message || '打开目录选择器失败');
    } finally {
      setSelectingDirectory(false);
    }
  }

  return (
    <main className="workspace">
      <SessionSidebar
        sessions={sessions}
        currentSession={currentSession}
        onSelectSession={handleSelectSession}
        onNewSession={handleNewSession}
        onDeleteSession={handleDeleteSession}
        getSessionId={sessionIdOf}
        loading={loading}
        deletingSessionId={deletingSessionId}
        disabled={sending}
      />
      <ChatPage
        messages={chatMessages}
        currentSession={currentSession}
        loading={loading}
        sending={sending}
        workingDirectory={workingDirectory}
        selectingDirectory={selectingDirectory}
        error={error}
        onSend={handleSend}
        onSelectWorkingDirectory={handleSelectWorkingDirectory}
        onRetry={handleRetry}
      />
    </main>
  );
}
