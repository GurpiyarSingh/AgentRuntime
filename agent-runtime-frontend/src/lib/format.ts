/** Display formatting for sizes, durations, tokens and money. */

import type { Usage } from '../api/types';

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  const units = ['KB', 'MB', 'GB'];
  let value = bytes / 1024;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value.toFixed(1)} ${units[unit] ?? 'GB'}`;
}

export function formatDuration(seconds: number): string {
  return seconds < 1 ? `${Math.round(seconds * 1000)} ms` : `${seconds.toFixed(1)} s`;
}

/**
 * USD, to four decimal places below $1 (as the CLI shows it) so a run that
 * costs a fraction of a cent never reads "$0.00" or gets rounded up, and to
 * cents above that.
 */
export function formatCost(usd: number): string {
  if (usd === 0) return '$0';
  return usd < 1 ? `$${usd.toFixed(4)}` : `$${usd.toFixed(2)}`;
}

/** e.g. "4,722 tokens · $0.0156", or without cost when the model is unpriced. */
export function formatUsage(usage: Usage): string {
  const tokens = `${usage.total_tokens.toLocaleString('en-US')} tokens`;
  return usage.cost_usd === null ? tokens : `${tokens} · ${formatCost(usage.cost_usd)}`;
}

/** The first sentence of a tool description, for the compact sidebar view. */
export function firstSentence(text: string): string {
  const match = /^.*?[.!?](?=\s|$)/s.exec(text);
  return (match ? match[0] : text).trim();
}
