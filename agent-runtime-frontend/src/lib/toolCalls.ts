/** Reading meaning out of a tool call's name and arguments, for display. */

import type { ToolCall } from '../chat/chatReducer';

/** The argument that best identifies a call at a glance (a path or a query). */
export function primaryArgument(args: Record<string, unknown>): string | undefined {
  for (const key of ['path', 'query']) {
    const value = args[key];
    if (typeof value === 'string' && value) return value;
  }
  return undefined;
}

/** Path of the file a call created, if it is a successful `write_file`. */
export function createdFile(call: ToolCall): string | undefined {
  if (call.toolName !== 'write_file' || call.status !== 'ok') return undefined;
  const path = call.arguments.path;
  return typeof path === 'string' ? path : undefined;
}
