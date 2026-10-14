/**
 * A Server-Sent Events parser for `fetch` response bodies.
 *
 * The browser's `EventSource` can only make GET requests, and the chat
 * stream is a POST with a JSON body and an optional `X-API-Key` header, so
 * the stream is read with `fetch` and parsed here instead. This follows the
 * SSE spec's line rules (https://html.spec.whatwg.org/multipage/server-sent-events.html):
 * events end at a blank line, `data:` lines join with newlines, lines
 * starting with `:` are comments, and LF, CR and CRLF all end a line. Chunk
 * boundaries can fall anywhere, even inside a CRLF pair, so the parser
 * buffers partial lines between chunks.
 */

export interface SseMessage {
  /** The `event:` field; `"message"` when the server didn't name one. */
  event: string;
  /** Every `data:` line of the event, joined with `\n`. */
  data: string;
}

/** Incremental parser: feed it text as it arrives and collect complete messages. */
export class SseParser {
  private buffer = '';
  private eventName = '';
  private dataLines: string[] = [];
  private pendingCr = false;

  /** Consume a chunk of the stream, returning every message it completed. */
  push(chunk: string): SseMessage[] {
    let text = chunk;
    // A CR at the end of the previous chunk may be the first half of CRLF.
    if (this.pendingCr && text.startsWith('\n')) text = text.slice(1);
    this.pendingCr = text.endsWith('\r');

    this.buffer += text;
    const lines = this.buffer.split(/\r\n|\r|\n/);
    this.buffer = lines.pop() ?? '';

    const messages: SseMessage[] = [];
    for (const line of lines) {
      const message = this.processLine(line);
      if (message) messages.push(message);
    }
    return messages;
  }

  /** Flush at end of stream: a final event without its trailing blank line still counts. */
  end(): SseMessage[] {
    const messages: SseMessage[] = [];
    if (this.buffer) {
      const message = this.processLine(this.buffer);
      if (message) messages.push(message);
      this.buffer = '';
    }
    const last = this.dispatch();
    if (last) messages.push(last);
    return messages;
  }

  private processLine(line: string): SseMessage | null {
    if (line === '') return this.dispatch();
    if (line.startsWith(':')) return null; // Comment / keep-alive ping.

    const colon = line.indexOf(':');
    const field = colon === -1 ? line : line.slice(0, colon);
    let value = colon === -1 ? '' : line.slice(colon + 1);
    if (value.startsWith(' ')) value = value.slice(1);

    if (field === 'event') this.eventName = value;
    else if (field === 'data') this.dataLines.push(value);
    // `id` and `retry` only matter for EventSource reconnection; ignored.
    return null;
  }

  private dispatch(): SseMessage | null {
    if (this.dataLines.length === 0) {
      this.eventName = '';
      return null;
    }
    const message = { event: this.eventName || 'message', data: this.dataLines.join('\n') };
    this.eventName = '';
    this.dataLines = [];
    return message;
  }
}

/** Yield each SSE message from a response body until the stream ends. */
export async function* readSse(body: ReadableStream<Uint8Array>): AsyncGenerator<SseMessage> {
  const reader = body.getReader();
  // `stream: true` holds back a multi-byte UTF-8 character split across chunks.
  const decoder = new TextDecoder();
  const parser = new SseParser();
  try {
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      yield* parser.push(decoder.decode(value, { stream: true }));
    }
    yield* parser.push(decoder.decode());
    yield* parser.end();
  } finally {
    reader.releaseLock();
  }
}
