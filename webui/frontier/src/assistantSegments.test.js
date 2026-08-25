import assert from 'node:assert/strict';
import test from 'node:test';

import { applyAssistantStreamEvent } from './assistantSegments.js';

test('merges text chunks and completes a provisional tool call', () => {
  let segments = [];
  segments = applyAssistantStreamEvent(segments, {
    type: 'chunk',
    kind: 'text',
    text: '我来',
  });
  segments = applyAssistantStreamEvent(segments, {
    type: 'chunk',
    kind: 'text',
    text: '检查',
  });
  segments = applyAssistantStreamEvent(segments, {
    type: 'chunk',
    kind: 'tool_call',
    call_key: 'generation-0:0',
    name_delta: 'run_',
    arguments_delta: '{"path":',
  });
  segments = applyAssistantStreamEvent(segments, {
    type: 'chunk',
    kind: 'tool_call',
    call_key: 'generation-0:0',
    name_delta: 'python',
    arguments_delta: '"a.pdf"}',
  });

  assert.deepEqual(segments, [
    { type: 'text', text: '我来检查' },
    {
      type: 'tool_call',
      call_key: 'generation-0:0',
      name: 'run_python',
      arguments: '{"path":"a.pdf"}',
      status: 'streaming',
    },
  ]);

  segments = applyAssistantStreamEvent(segments, {
    type: 'tool_call_done',
    call_key: 'generation-0:0',
    tool_call_id: 'call-1',
    name: 'run_python',
    status: 'complete',
  });

  assert.deepEqual(segments, [
    { type: 'text', text: '我来检查' },
    {
      type: 'tool_call',
      call_key: 'generation-0:0',
      tool_call_id: 'call-1',
      name: 'run_python',
      status: 'complete',
    },
  ]);
});

test('keeps parallel tool calls separate and ordered', () => {
  let segments = [];
  for (const [callKey, name] of [
    ['generation-0:0', 'pdfinfo'],
    ['generation-0:1', 'pdftotext'],
  ]) {
    segments = applyAssistantStreamEvent(segments, {
      type: 'chunk',
      kind: 'tool_call',
      call_key: callKey,
      name_delta: name,
      arguments_delta: '',
    });
  }

  assert.deepEqual(segments.map((segment) => segment.name), [
    'pdfinfo',
    'pdftotext',
  ]);
});
