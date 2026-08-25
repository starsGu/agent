import { stripWorkingDirectoryContext } from './workingDirectory.js';

const API_BASE_URL = (
  import.meta.env?.VITE_API_BASE_URL || '/api'
).replace(/\/$/, '');

function normalizeSessions(data) {
  const source = Array.isArray(data) ? data : [];

  return source.map((session) =>
    typeof session === 'string'
      ? { session_id: session, title: session }
      : session,
  );
}

function normalizeMessages(data, sessionId) {
  if (!Array.isArray(data)) return [];

  return data.flatMap((turn, index) => {
    if (!turn) return [];

    const messages = [];

    if (typeof turn.human_message === 'string') {
      messages.push({
        id: `${sessionId}-${index}-user`,
        session_id: sessionId,
        role: 'user',
        text: stripWorkingDirectoryContext(turn.human_message),
      });
    }

    const assistantSegments = normalizeAssistantSegments(turn.ai_message);
    if (assistantSegments.length > 0) {
      messages.push({
        id: `${sessionId}-${index}-assistant`,
        session_id: sessionId,
        role: 'assistant',
        segments: assistantSegments,
      });
    }

    return messages;
  });
}

export function normalizeAssistantSegments(value) {
  if (typeof value === 'string') {
    return value ? [{ type: 'text', text: value }] : [];
  }
  if (!Array.isArray(value)) return [];

  const segments = [];
  for (const segment of value) {
    if (segment?.type === 'text' && typeof segment.text === 'string') {
      if (!segment.text) continue;
      if (segments.at(-1)?.type === 'text') {
        segments[segments.length - 1].text += segment.text;
      } else {
        segments.push({ type: 'text', text: segment.text });
      }
      continue;
    }

    if (
      segment?.type === 'tool_call'
      && typeof segment.tool_call_id === 'string'
      && typeof segment.name === 'string'
      && segment.status === 'complete'
    ) {
      segments.push({
        type: 'tool_call',
        tool_call_id: segment.tool_call_id,
        name: segment.name,
        status: 'complete',
      });
    }
  }
  return segments;
}

async function readJson(response, message) {
  if (!response.ok) {
    throw new Error(`${message}（${response.status}）`);
  }

  try {
    return await response.json();
  } catch {
    throw new Error(`${message}：返回内容不是有效的 JSON`);
  }
}

export async function getAgentState(signal) {
  const response = await fetch(`${API_BASE_URL}/agentState`, {
    headers: { Accept: 'application/json' },
    signal,
  });
  const data = await readJson(response, '检测 Agent 状态失败');

  if (typeof data !== 'boolean') {
    throw new Error('检测 Agent 状态失败：返回格式无效');
  }

  return data;
}

export async function getAgentSessions(signal) {
  const response = await fetch(`${API_BASE_URL}/agentSessions`, {
    headers: { Accept: 'application/json' },
    signal,
  });
  const data = await readJson(response, '加载会话失败');

  return normalizeSessions(data);
}

export async function getSessionMessages(sessionId, signal) {
  const response = await fetch(
    `${API_BASE_URL}/agent?session_id=${encodeURIComponent(sessionId)}`,
    {
      headers: { Accept: 'application/json' },
      signal,
    },
  );
  const data = await readJson(response, '加载消息失败');

  return normalizeMessages(data, String(sessionId));
}

export async function postChatMessage(text, sessionId, workingDirectory) {
  const response = await fetch(`${API_BASE_URL}/chat`, {
    method: 'POST',
    headers: {
      Accept: 'application/json',
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      human_message: text,
      session_id: sessionId,
      working_directory: workingDirectory,
    }),
  });

  if (!response.ok) {
    if (response.status === 422) {
      throw new Error('工作目录不可用，请重新选择后发送');
    }
    throw new Error(`发送失败（${response.status}）`);
  }
}

export class ChatStreamError extends Error {
  constructor(message, code = 'chat_stream_failed') {
    super(message);
    this.name = 'ChatStreamError';
    this.code = code;
  }
}

export async function* parseNdjsonStream(body) {
  if (!body || typeof body.getReader !== 'function') {
    throw new ChatStreamError('发送失败：浏览器没有收到响应流');
  }

  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  try {
    while (true) {
      const { done, value } = await reader.read();
      buffer += decoder.decode(value, { stream: !done });

      let newlineIndex = buffer.indexOf('\n');
      while (newlineIndex !== -1) {
        const line = buffer.slice(0, newlineIndex).trim();
        buffer = buffer.slice(newlineIndex + 1);

        if (line) {
          try {
            yield JSON.parse(line);
          } catch {
            throw new ChatStreamError(
              '发送失败：流式响应格式无效',
              'invalid_stream_json',
            );
          }
        }
        newlineIndex = buffer.indexOf('\n');
      }

      if (done) break;
    }

    const finalLine = buffer.trim();
    if (finalLine) {
      try {
        yield JSON.parse(finalLine);
      } catch {
        throw new ChatStreamError(
          '发送失败：流式响应格式无效',
          'invalid_stream_json',
        );
      }
    }
  } finally {
    reader.releaseLock();
  }
}

function requireStreamEvent(event, sessionId) {
  if (!event || typeof event !== 'object' || typeof event.type !== 'string') {
    throw new ChatStreamError(
      '发送失败：流式响应格式无效',
      'invalid_stream_event',
    );
  }

  if (event.type === 'start' || event.type === 'done') {
    if (event.session_id !== sessionId) {
      throw new ChatStreamError(
        '发送失败：会话标识不匹配',
        'stream_session_mismatch',
      );
    }
  }

  if (event.type === 'chunk') {
    const validTextChunk = (
      event.kind === 'text'
      && typeof event.text === 'string'
    );
    const validToolChunk = (
      event.kind === 'tool_call'
      && typeof event.call_key === 'string'
      && typeof event.name_delta === 'string'
      && typeof event.arguments_delta === 'string'
    );
    if (!validTextChunk && !validToolChunk) {
      throw new ChatStreamError(
        '发送失败：增量消息格式无效',
        'invalid_stream_event',
      );
    }
  }

  if (
    event.type === 'tool_call_done'
    && (
      typeof event.call_key !== 'string'
      || typeof event.tool_call_id !== 'string'
      || typeof event.name !== 'string'
      || event.status !== 'complete'
    )
  ) {
    throw new ChatStreamError(
      '发送失败：工具调用消息格式无效',
      'invalid_stream_event',
    );
  }

  if (
    event.type === 'done'
    && (
      !Array.isArray(event.ai_message)
      || normalizeAssistantSegments(event.ai_message).length
        !== event.ai_message.length
    )
  ) {
    throw new ChatStreamError(
      '发送失败：完整消息格式无效',
      'invalid_stream_event',
    );
  }

  if (
    event.type === 'error'
    && (typeof event.code !== 'string' || typeof event.message !== 'string')
  ) {
    throw new ChatStreamError(
      '发送失败：错误消息格式无效',
      'invalid_stream_event',
    );
  }

  if (
    !['start', 'chunk', 'tool_call_done', 'done', 'error'].includes(event.type)
  ) {
    throw new ChatStreamError(
      '发送失败：未知的流式事件',
      'invalid_stream_event',
    );
  }

  return event;
}

export async function postChatMessageStream(
  text,
  sessionId,
  workingDirectory,
  handlers = {},
) {
  const response = await fetch(`${API_BASE_URL}/chat/stream`, {
    method: 'POST',
    headers: {
      Accept: 'application/x-ndjson',
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      human_message: text,
      session_id: sessionId,
      working_directory: workingDirectory,
    }),
    signal: handlers.signal,
  });

  if (!response.ok) {
    if (response.status === 422) {
      throw new ChatStreamError(
        '工作目录不可用，请重新选择后发送',
        'invalid_request',
      );
    }
    throw new ChatStreamError(`发送失败（${response.status}）`);
  }

  let started = false;
  let terminalEvent = null;

  for await (const rawEvent of parseNdjsonStream(response.body)) {
    const event = requireStreamEvent(rawEvent, sessionId);

    if (terminalEvent !== null) {
      throw new ChatStreamError(
        '发送失败：结束事件之后仍有数据',
        'invalid_stream_event',
      );
    }

    if (event.type === 'start') {
      if (started) {
        throw new ChatStreamError(
          '发送失败：收到重复的开始事件',
          'invalid_stream_event',
        );
      }
      started = true;
      handlers.onStart?.(event);
      continue;
    }

    if (!started) {
      throw new ChatStreamError(
        '发送失败：响应流缺少开始事件',
        'invalid_stream_event',
      );
    }

    if (event.type === 'chunk' || event.type === 'tool_call_done') {
      handlers.onEvent?.(event);
      if (event.type === 'chunk' && event.kind === 'text') {
        handlers.onChunk?.(event.text, event);
      }
      continue;
    }

    terminalEvent = event;
    if (event.type === 'error') {
      throw new ChatStreamError(event.message, event.code);
    }
  }

  if (terminalEvent?.type !== 'done') {
    throw new ChatStreamError(
      '发送失败：响应流提前结束',
      'incomplete_stream',
    );
  }

  handlers.onDone?.(terminalEvent);
  return terminalEvent;
}

export async function getDefaultWorkingDirectory(signal) {
  const response = await fetch(`${API_BASE_URL}/working-directory/default`, {
    headers: { Accept: 'application/json' },
    signal,
  });
  const data = await readJson(response, '加载默认工作目录失败');

  if (typeof data?.working_directory !== 'string' || !data.working_directory) {
    throw new Error('加载默认工作目录失败：返回格式无效');
  }

  return data.working_directory;
}

export async function openWorkingDirectoryPicker(initialDirectory) {
  const response = await fetch(`${API_BASE_URL}/working-directory/select`, {
    method: 'POST',
    headers: {
      Accept: 'application/json',
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ initial_directory: initialDirectory || null }),
  });
  const data = await readJson(response, '打开目录选择器失败');

  if (
    typeof data?.cancelled !== 'boolean'
    || typeof data?.working_directory !== 'string'
    || !data.working_directory
  ) {
    throw new Error('打开目录选择器失败：返回格式无效');
  }

  return {
    cancelled: data.cancelled,
    workingDirectory: data.working_directory,
  };
}

export async function deleteChatSession(sessionId) {
  const response = await fetch(
    `${API_BASE_URL}/sessions?session_id=${encodeURIComponent(sessionId)}`,
    { method: 'DELETE' },
  );

  if (!response.ok) {
    throw new Error(`删除会话失败（${response.status}）`);
  }
}

export async function getSystemPrompt(signal) {
  const response = await fetch(`${API_BASE_URL}/system-prompt`, {
    headers: { Accept: 'application/json' },
    signal,
  });
  const data = await readJson(response, '加载系统提示词失败');

  if (typeof data?.system_prompt !== 'string') {
    throw new Error('加载系统提示词失败：返回格式无效');
  }

  return data.system_prompt;
}

export async function updateSystemPrompt(systemPrompt) {
  const response = await fetch(`${API_BASE_URL}/system-prompt`, {
    method: 'POST',
    headers: {
      Accept: 'application/json',
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ system_prompt: systemPrompt }),
  });
  const data = await readJson(response, '保存系统提示词失败');

  if (typeof data?.system_prompt !== 'string') {
    throw new Error('保存系统提示词失败：返回格式无效');
  }

  return data.system_prompt;
}

export async function getPlugins(signal) {
  const response = await fetch(`${API_BASE_URL}/plugins`, {
    headers: { Accept: 'application/json' },
    signal,
  });
  const data = await readJson(response, '加载插件失败');

  if (!Array.isArray(data?.plugins) || !data?.use_plugins || typeof data.use_plugins !== 'object') {
    throw new Error('加载插件失败：返回格式无效');
  }

  return {
    plugins: data.plugins,
    usePlugins: data.use_plugins,
  };
}

export async function setPluginEnabled(name, enabled) {
  const action = enabled ? 'enable' : 'disable';
  const response = await fetch(`${API_BASE_URL}/plugins/${action}`, {
    method: 'POST',
    headers: {
      Accept: 'application/json',
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ name }),
  });
  const data = await readJson(response, enabled ? '启用插件失败' : '禁用插件失败');

  if (data?.name !== name || data?.enabled !== enabled) {
    throw new Error(`${enabled ? '启用' : '禁用'}插件失败：返回格式无效`);
  }

  return data;
}
