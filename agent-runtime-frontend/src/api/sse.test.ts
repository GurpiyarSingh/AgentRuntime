import { readSse, SseParser, type SseMessage } from './sse';

function parseAll(chunks: string[]): SseMessage[] {
  const parser = new SseParser();
  return [...chunks.flatMap((chunk) => parser.push(chunk)), ...parser.end()];
}

describe('SseParser', () => {
  it('parses named events with JSON data', () => {
    expect(parseAll(['event: final_answer\ndata: {"content":"hi"}\n\n'])).toEqual([
      { event: 'final_answer', data: '{"content":"hi"}' },
    ]);
  });

  it('defaults the event name to "message"', () => {
    expect(parseAll(['data: x\n\n'])).toEqual([{ event: 'message', data: 'x' }]);
  });

  it('joins multi-line data with newlines', () => {
    expect(parseAll(['data: one\ndata: two\n\n'])).toEqual([
      { event: 'message', data: 'one\ntwo' },
    ]);
  });

  it('handles events split at any point across chunks', () => {
    const stream = 'event: a\ndata: 1\n\nevent: b\ndata: 2\n\n';
    for (let cut = 1; cut < stream.length; cut += 1) {
      expect(parseAll([stream.slice(0, cut), stream.slice(cut)])).toEqual([
        { event: 'a', data: '1' },
        { event: 'b', data: '2' },
      ]);
    }
  });

  it('accepts CRLF and CR line endings, even with CRLF split across chunks', () => {
    expect(parseAll(['event: a\r\ndata: 1\r', '\n\r\n'])).toEqual([{ event: 'a', data: '1' }]);
    expect(parseAll(['data: 1\r\r'])).toEqual([{ event: 'message', data: '1' }]);
  });

  it('ignores comments and unknown fields', () => {
    expect(parseAll([': ping\nid: 7\nretry: 100\ndata: x\n\n'])).toEqual([
      { event: 'message', data: 'x' },
    ]);
  });

  it('strips only one leading space from values', () => {
    expect(parseAll(['data:  two spaces\n\n'])).toEqual([
      { event: 'message', data: ' two spaces' },
    ]);
  });

  it('does not dispatch an event with no data', () => {
    expect(parseAll(['event: empty\n\ndata: x\n\n'])).toEqual([{ event: 'message', data: 'x' }]);
  });

  it('flushes a final event that lacks its trailing blank line', () => {
    expect(parseAll(['event: last\ndata: done'])).toEqual([{ event: 'last', data: 'done' }]);
  });
});

describe('readSse', () => {
  it('decodes UTF-8 characters split across byte chunks', async () => {
    const bytes = new TextEncoder().encode('data: héllo — ✓\n\n');
    const split = bytes.indexOf(0xc3) + 1; // Inside the two-byte "é".
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(bytes.slice(0, split));
        controller.enqueue(bytes.slice(split));
        controller.close();
      },
    });

    const messages: SseMessage[] = [];
    for await (const message of readSse(body)) messages.push(message);

    expect(messages).toEqual([{ event: 'message', data: 'héllo — ✓' }]);
  });
});
