/** How each tool looks in the UI: an icon, a colour tone, and a readable name. */

import type { IconName } from '../components/Icon';

export type Tone = 'blue' | 'violet' | 'pink' | 'amber' | 'green' | 'cyan';

export interface ToolMeta {
  icon: IconName;
  tone: Tone;
  /** Short human name, e.g. "Read file". */
  label: string;
}

const META: Record<string, ToolMeta> = {
  list_files: { icon: 'folder', tone: 'amber', label: 'List files' },
  read_file: { icon: 'fileText', tone: 'blue', label: 'Read file' },
  read_image: { icon: 'image', tone: 'pink', label: 'View image' },
  search_files: { icon: 'search', tone: 'cyan', label: 'Search files' },
  write_file: { icon: 'filePlus', tone: 'green', label: 'Create file' },
  edit_file: { icon: 'pencil', tone: 'violet', label: 'Edit file' },
};

/** For an MCP tool (`server__tool`), its server and its own name. */
export function mcpParts(name: string): { server: string; tool: string } | undefined {
  const at = name.indexOf('__');
  if (at <= 0) return undefined;
  return { server: name.slice(0, at), tool: name.slice(at + 2) };
}

/** Display details for `name`: built-ins by kind, MCP tools by server, others a wrench. */
export function toolMeta(name: string): ToolMeta {
  const mcp = META[name] ? undefined : mcpParts(name);
  if (mcp) return { icon: 'plug', tone: 'cyan', label: `${mcp.server} · ${mcp.tool}` };
  return (
    META[name] ?? {
      icon: 'tool',
      tone: 'violet',
      label: name.replace(/_/g, ' ').replace(/^\w/, (c) => c.toUpperCase()),
    }
  );
}
