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

/** Display details for `name`; unknown tools get a neutral wrench. */
export function toolMeta(name: string): ToolMeta {
  return (
    META[name] ?? {
      icon: 'tool',
      tone: 'violet',
      label: name.replace(/_/g, ' ').replace(/^\w/, (c) => c.toUpperCase()),
    }
  );
}
