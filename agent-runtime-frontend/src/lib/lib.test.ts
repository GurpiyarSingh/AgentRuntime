import type { ToolCall } from '../chat/chatReducer';
import { firstSentence, formatBytes, formatCost, formatDuration, formatUsage } from './format';
import { describeType } from './schema';
import { loadSetting, saveSetting } from './storage';
import { createdFile, primaryArgument } from './toolCalls';

describe('format', () => {
  it('formats costs without rounding small runs up or down to nothing', () => {
    expect(formatCost(0)).toBe('$0');
    expect(formatCost(0.0004)).toBe('$0.0004');
    expect(formatCost(0.0156)).toBe('$0.0156');
    expect(formatCost(2.5)).toBe('$2.50');
  });

  it('formats usage, leaving out an unknown cost', () => {
    const usage = { input_tokens: 4000, output_tokens: 722, total_tokens: 4722 };
    expect(formatUsage({ ...usage, cost_usd: 0.0156 })).toBe('4,722 tokens · $0.0156');
    expect(formatUsage({ ...usage, cost_usd: null })).toBe('4,722 tokens');
  });

  it('formats sizes and durations', () => {
    expect(formatBytes(512)).toBe('512 B');
    expect(formatBytes(1536)).toBe('1.5 KB');
    expect(formatBytes(5 * 1024 ** 2)).toBe('5.0 MB');
    expect(formatDuration(0.08)).toBe('80 ms');
    expect(formatDuration(2.345)).toBe('2.3 s');
  });

  it('takes the first sentence, without splitting on a dot inside a word', () => {
    expect(firstSentence('Read a file as text. Works for PDF.')).toBe('Read a file as text.');
    expect(firstSentence('Supports .docx files. More here.')).toBe('Supports .docx files.');
    expect(firstSentence('No full stop')).toBe('No full stop');
  });
});

describe('describeType', () => {
  it('describes plain, nullable and enumerated types', () => {
    expect(describeType({ type: 'string' })).toBe('string');
    expect(describeType({ anyOf: [{ type: 'integer' }, { type: 'null' }] })).toBe('integer | null');
    expect(describeType({ enum: ['auto', 'low'] })).toBe('"auto" | "low"');
    expect(describeType({})).toBe('any');
  });
});

describe('tool call helpers', () => {
  const call = (overrides: Partial<ToolCall>): ToolCall => ({
    callId: 'c1',
    toolName: 'write_file',
    arguments: { path: 'out/plan.docx' },
    status: 'ok',
    imageCount: 0,
    ...overrides,
  });

  it('picks the identifying argument', () => {
    expect(primaryArgument({ path: 'a.txt', content: 'x' })).toBe('a.txt');
    expect(primaryArgument({ query: 'invoice' })).toBe('invoice');
    expect(primaryArgument({})).toBeUndefined();
  });

  it('offers a download only for files that were actually written', () => {
    expect(createdFile(call({}))).toBe('out/plan.docx');
    expect(createdFile(call({ status: 'error' }))).toBeUndefined();
    expect(createdFile(call({ status: 'running' }))).toBeUndefined();
    expect(createdFile(call({ toolName: 'read_file' }))).toBeUndefined();
  });
});

describe('storage', () => {
  it('round-trips settings and removes empty ones', () => {
    saveSetting('model', 'gpt-5.2');
    expect(loadSetting('model')).toBe('gpt-5.2');
    saveSetting('model', '');
    expect(loadSetting('model', 'fallback')).toBe('fallback');
  });

  it('falls back instead of throwing when storage is unavailable', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new DOMException('denied', 'SecurityError');
    });
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new DOMException('full', 'QuotaExceededError');
    });
    expect(loadSetting('apiKey', 'none')).toBe('none');
    expect(() => {
      saveSetting('apiKey', 'secret');
    }).not.toThrow();
  });
});
