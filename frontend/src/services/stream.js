/**
 * Server-sent-event reader for streaming chat.
 *
 * EventSource cannot be used here: it only issues GET requests and cannot
 * set the identity header, so we read the response body ourselves.
 */

import { API_BASE_URL, ApiError, getActiveToken } from './http';

/**
 * POSTs to an SSE endpoint and invokes handlers as events arrive.
 *
 * @param {string} path
 * @param {object} body
 * @param {object} handlers  { onStart, onTool, onSources, onDelta, onDone, onError }
 * @param {AbortSignal} [signal]
 */
export async function streamEvents(path, body, handlers = {}, signal) {
  const token = getActiveToken();

  const headers = { 'Content-Type': 'application/json', Accept: 'text/event-stream' };
  if (token) headers.Authorization = `Bearer ${token}`;

  let response;
  try {
    response = await fetch(`${API_BASE_URL.replace(/\/$/, '')}${path}`, {
      method: 'POST',
      headers,
      body: JSON.stringify(body),
      signal,
    });
  } catch (cause) {
    if (cause?.name === 'AbortError') throw cause;
    throw new ApiError(
      `Cannot reach the workbench backend at ${API_BASE_URL}.`,
      { status: 0 },
    );
  }

  if (!response.ok || !response.body) {
    let message = `Request failed (${response.status})`;
    try {
      const data = await response.json();
      message = data?.detail?.message || data?.detail || message;
    } catch {
      /* keep the default */
    }
    throw new ApiError(message, { status: response.status });
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  // SSE frames are separated by a blank line.
  const dispatch = (frame) => {
    let event = 'message';
    const dataLines = [];

    for (const line of frame.split('\n')) {
      if (line.startsWith('event:')) event = line.slice(6).trim();
      else if (line.startsWith('data:')) dataLines.push(line.slice(5).trim());
    }

    if (dataLines.length === 0) return;

    let payload;
    try {
      payload = JSON.parse(dataLines.join('\n'));
    } catch {
      return; // ignore a malformed frame rather than killing the stream
    }

    if (event === 'start') handlers.onStart?.(payload);
    // One per executed tool call, before the answer streams. Tool calling
    // cannot be streamed - the request arrives as a structured field, not
    // as prose - so these all land up front.
    else if (event === 'tool') handlers.onTool?.(payload);
    // Retrieval finishes before the first token, so citations can be shown
    // while the answer is still arriving. Omitted entirely when nothing was
    // retrieved - an absent event means no sources, never unknown sources.
    else if (event === 'sources') handlers.onSources?.(payload.sources ?? []);
    else if (event === 'delta') handlers.onDelta?.(payload.text ?? '');
    else if (event === 'done') handlers.onDone?.(payload);
    else if (event === 'error') handlers.onError?.(payload);
  };

  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });

    let split;
    while ((split = buffer.indexOf('\n\n')) !== -1) {
      const frame = buffer.slice(0, split);
      buffer = buffer.slice(split + 2);
      if (frame.trim()) dispatch(frame);
    }
  }

  if (buffer.trim()) dispatch(buffer);
}
