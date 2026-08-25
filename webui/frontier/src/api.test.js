import assert from 'node:assert/strict';
import test from 'node:test';

import {
  normalizeAssistantSegments,
  parseNdjsonStream,
  postChatMessageStream,
} from './api.js';

function bodyFromChunks(chunks) {
  const encoder = new TextEncoder();
  return new ReadableStream({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
      controller.close();
    },
  });
}

test('parses NDJSON when lines cross network chunk boundaries', async () => {
  const body = bodyFromChunks([
    '{"type":"start","session_id":"s1"}\n{"type":"chu',
    'nk","kind":"text","text":"你',
    '好"}\n',
  ]);
  const events = [];
  for await (const event of parseNdjsonStream(body)) events.push(event);

  assert.deepEqual(events, [
    { type: 'start', session_id: 's1' },
    { type: 'chunk', kind: 'text', text: '你好' },
  ]);
});

test('stream chat uses one POST and returns the current structured turn', async () => {
  const originalFetch = globalThis.fetch;
  const requests = [];
  const streamEvents = [
    { type: 'start', session_id: 'session-1' },
    { type: 'chunk', kind: 'text', text: '检查' },
    {
      type: 'chunk',
      kind: 'tool_call',
      call_key: 'generation-0:0',
      name_delta: 'run_python',
      arguments_delta: '{}',
    },
    {
      type: 'tool_call_done',
      call_key: 'generation-0:0',
      tool_call_id: 'call-1',
      name: 'run_python',
      status: 'complete',
    },
    {
      type: 'done',
      session_id: 'session-1',
      ai_message: [
        { type: 'text', text: '检查' },
        {
          type: 'tool_call',
          tool_call_id: 'call-1',
          name: 'run_python',
          status: 'complete',
        },
      ],
    },
  ];

  globalThis.fetch = async (url, options) => {
    requests.push({ url, options });
    return new Response(
      bodyFromChunks(streamEvents.map((event) => `${JSON.stringify(event)}\n`)),
      { status: 200, headers: { 'Content-Type': 'application/x-ndjson' } },
    );
  };

  try {
    const received = [];
    const done = await postChatMessageStream(
      'hello',
      'session-1',
      'D:\\workspace',
      { onEvent: (event) => received.push(event) },
    );

    assert.equal(requests.length, 1);
    assert.equal(requests[0].url, '/api/chat/stream');
    assert.equal(requests[0].options.method, 'POST');
    assert.deepEqual(received, streamEvents.slice(1, -1));
    assert.deepEqual(done, streamEvents.at(-1));
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('normalizes legacy strings and structured assistant segments', () => {
  assert.deepEqual(normalizeAssistantSegments('legacy'), [
    { type: 'text', text: 'legacy' },
  ]);
  assert.deepEqual(normalizeAssistantSegments([
    { type: 'text', text: 'a' },
    { type: 'text', text: 'b' },
    {
      type: 'tool_call',
      tool_call_id: 'call-1',
      name: 'pdfinfo',
      status: 'complete',
    },
  ]), [
    { type: 'text', text: 'ab' },
    {
      type: 'tool_call',
      tool_call_id: 'call-1',
      name: 'pdfinfo',
      status: 'complete',
    },
  ]);
});
