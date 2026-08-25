function appendTextSegment(segments, text) {
  if (!text) return segments;
  const next = segments.map((segment) => ({ ...segment }));
  if (next.at(-1)?.type === 'text') {
    next[next.length - 1].text += text;
  } else {
    next.push({ type: 'text', text });
  }
  return next;
}

export function applyAssistantStreamEvent(currentSegments, event) {
  const segments = Array.isArray(currentSegments) ? currentSegments : [];

  if (event?.type === 'chunk' && event.kind === 'text') {
    return appendTextSegment(segments, event.text);
  }

  if (event?.type === 'chunk' && event.kind === 'tool_call') {
    const next = segments.map((segment) => ({ ...segment }));
    const segmentIndex = next.findIndex(
      (segment) => segment.type === 'tool_call'
        && segment.call_key === event.call_key,
    );
    const toolSegment = segmentIndex === -1
      ? {
          type: 'tool_call',
          call_key: event.call_key,
          name: '',
          arguments: '',
          status: 'streaming',
        }
      : next[segmentIndex];

    toolSegment.name += event.name_delta;
    toolSegment.arguments += event.arguments_delta;
    if (segmentIndex === -1) next.push(toolSegment);
    return next;
  }

  if (event?.type === 'tool_call_done') {
    const next = segments.map((segment) => ({ ...segment }));
    const segmentIndex = next.findIndex(
      (segment) => segment.type === 'tool_call'
        && segment.call_key === event.call_key,
    );
    const completedSegment = {
      type: 'tool_call',
      call_key: event.call_key,
      tool_call_id: event.tool_call_id,
      name: event.name,
      status: 'complete',
    };

    if (segmentIndex === -1) next.push(completedSegment);
    else next[segmentIndex] = completedSegment;
    return next;
  }

  return segments;
}
