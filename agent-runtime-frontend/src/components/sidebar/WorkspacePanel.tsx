/**
 * The folder the agent works in: shows its path, and lets the user browse
 * the server for another one or go back to the server's default.
 */

import { useState } from 'react';

import type { Health } from '../../api/types';
import type { Resource } from '../../hooks/useResource';
import { Icon } from '../Icon';
import { DirectoryBrowser } from './DirectoryBrowser';
import styles from './WorkspacePanel.module.css';

interface WorkspacePanelProps {
  health: Resource<Health>;
  /** The chosen folder; empty for the server's default workspace. */
  workspace: string;
  onWorkspaceChange: (path: string) => void;
  /** True while a run is streaming: the folder can't change mid-run. */
  busy: boolean;
}

export function WorkspacePanel({
  health,
  workspace,
  onWorkspaceChange,
  busy,
}: WorkspacePanelProps) {
  const [browsing, setBrowsing] = useState(false);
  const status = health.data?.workspace;
  const selectable = status?.selectable === true;
  const shown = workspace || status?.path || 'Server default';

  return (
    <section className={styles.panel} aria-labelledby="workspace-heading">
      <h2 id="workspace-heading" className={styles.heading}>
        <Icon name="folder" size={15} />
        Workspace
        <span className={workspace ? styles.tagCustom : styles.tag}>
          {workspace ? 'chosen' : 'default'}
        </span>
      </h2>

      <p className={styles.path} title={shown}>
        {shown}
      </p>

      {selectable ? (
        <div className={styles.actions}>
          <button
            type="button"
            className={styles.browse}
            disabled={busy}
            onClick={() => {
              setBrowsing(true);
            }}
          >
            <Icon name="folder" size={14} />
            Browse…
          </button>
          {workspace && (
            <button
              type="button"
              className={styles.reset}
              disabled={busy}
              onClick={() => {
                onWorkspaceChange('');
              }}
            >
              Use default
            </button>
          )}
        </div>
      ) : (
        status && <p className={styles.hint}>This server only works in its configured folder.</p>
      )}

      {browsing && (
        <DirectoryBrowser
          initialPath={workspace || status?.path || ''}
          onClose={() => {
            setBrowsing(false);
          }}
          onSelect={(path) => {
            setBrowsing(false);
            // Choosing the default folder by path is the same as the default.
            onWorkspaceChange(path === status?.path ? '' : path);
          }}
        />
      )}
    </section>
  );
}
