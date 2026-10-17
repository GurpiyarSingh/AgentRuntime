/** Human labels for an MCP server's connection status. */

import type { McpStatus } from '../api/types';

const LABELS: Record<McpStatus, string> = {
  connected: 'Connected',
  connecting: 'Connecting…',
  error: 'Error',
  disabled: 'Disabled',
};

export function statusLabel(status: McpStatus): string {
  return LABELS[status];
}
