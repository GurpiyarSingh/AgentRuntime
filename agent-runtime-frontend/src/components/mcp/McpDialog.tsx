/**
 * The MCP servers manager: the list of servers on the left, and on the right
 * the selected server, a form to add or edit one, or a JSON import.
 */

import { useState } from 'react';
import { createPortal } from 'react-dom';

import { emptyConfig } from '../../lib/mcpTemplates';
import { statusLabel } from '../../lib/mcpStatus';
import { Icon } from '../Icon';
import styles from './McpDialog.module.css';
import { McpImport } from './McpImport';
import { McpServerDetail } from './McpServerDetail';
import { McpServerForm } from './McpServerForm';
import { StatusDot } from './McpStatus';
import type { McpServers } from './useMcpServers';

export type McpPane =
  | { kind: 'view'; name: string }
  | { kind: 'add' }
  | { kind: 'edit'; name: string }
  | { kind: 'import' };

interface McpDialogProps {
  mcp: McpServers;
  initialPane: McpPane | undefined;
  onClose: () => void;
}

export function McpDialog({ mcp, initialPane, onClose }: McpDialogProps) {
  const servers = mcp.data?.servers ?? [];
  const canManage = mcp.data?.can_manage ?? false;
  const [chosen, setPane] = useState<McpPane | undefined>(initialPane);
  // On narrow screens the list and the pane take turns.
  const [showPane, setShowPane] = useState(initialPane !== undefined);

  // Until something is chosen, show the first server.
  const first = servers[0]?.name;
  const pane: McpPane | undefined = chosen ?? (first ? { kind: 'view', name: first } : undefined);

  const open = (next: McpPane) => {
    setPane(next);
    setShowPane(true);
  };

  const selected =
    pane && (pane.kind === 'view' || pane.kind === 'edit')
      ? servers.find((server) => server.name === pane.name)
      : undefined;

  let content;
  if (pane?.kind === 'add') {
    content = (
      <McpServerForm
        key="add"
        mode="add"
        initialName=""
        initialConfig={emptyConfig()}
        allowStdio={mcp.data?.allow_stdio ?? true}
        takenNames={servers.map((server) => server.name)}
        onTest={mcp.test}
        onSave={async (name, config) => {
          await mcp.create(name, config);
          setPane({ kind: 'view', name });
        }}
        onCancel={() => {
          setPane(first ? { kind: 'view', name: first } : undefined);
          setShowPane(false);
        }}
      />
    );
  } else if (pane?.kind === 'import') {
    content = (
      <McpImport
        onImport={mcp.importJson}
        onDone={(name) => {
          setPane(name ? { kind: 'view', name } : undefined);
        }}
        onCancel={() => {
          setPane(first ? { kind: 'view', name: first } : undefined);
          setShowPane(false);
        }}
      />
    );
  } else if (pane?.kind === 'edit' && selected) {
    content = (
      <McpServerForm
        key={`edit-${selected.name}`}
        mode="edit"
        initialName={selected.name}
        initialConfig={selected.config}
        allowStdio={mcp.data?.allow_stdio ?? true}
        takenNames={[]}
        onTest={mcp.test}
        onSave={async (name, config) => {
          await mcp.update(name, config);
          setPane({ kind: 'view', name });
        }}
        onCancel={() => {
          setPane({ kind: 'view', name: selected.name });
        }}
      />
    );
  } else if (selected) {
    content = (
      <McpServerDetail
        key={selected.name}
        server={selected}
        canManage={canManage}
        onEdit={() => {
          setPane({ kind: 'edit', name: selected.name });
        }}
        onToggle={(enabled) => mcp.setEnabled(selected.name, enabled)}
        onReconnect={() => mcp.reconnect(selected.name)}
        onDelete={async () => {
          await mcp.remove(selected.name);
          setPane(undefined);
          setShowPane(false);
        }}
      />
    );
  } else {
    content = (
      <div className={styles.welcome}>
        <span className={styles.welcomeIcon}>
          <Icon name="plug" size={28} />
        </span>
        <h3 className={styles.paneTitle}>Connect your tools</h3>
        <p className={styles.paneSubtitle}>
          MCP servers give the agent new abilities: GitHub, Jira, a real browser with Playwright,
          databases, and thousands more. Their tools appear in the agent&apos;s tool list as soon as
          they connect.
        </p>
        {canManage ? (
          <div className={styles.welcomeActions}>
            <button
              type="button"
              className={styles.primary}
              onClick={() => {
                open({ kind: 'add' });
              }}
            >
              <Icon name="plus" size={15} />
              Add a server
            </button>
            <button
              type="button"
              className={styles.secondary}
              onClick={() => {
                open({ kind: 'import' });
              }}
            >
              <Icon name="upload" size={15} />
              Import JSON
            </button>
          </div>
        ) : (
          <p className={styles.hint}>Only admins can add MCP servers.</p>
        )}
      </div>
    );
  }

  return createPortal(
    <div
      className={styles.backdrop}
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div
        className={`${styles.dialog ?? ''} ${showPane ? (styles.paneOpen ?? '') : ''}`}
        role="dialog"
        aria-modal="true"
        aria-labelledby="mcp-title"
        onKeyDown={(event) => {
          if (event.key === 'Escape') {
            event.stopPropagation();
            onClose();
          }
        }}
      >
        <aside className={styles.listColumn}>
          <header className={styles.listHeader}>
            <h2 id="mcp-title" className={styles.dialogTitle}>
              <Icon name="plug" size={18} />
              MCP servers
            </h2>
            <button type="button" className={styles.iconButton} onClick={onClose}>
              <Icon name="x" label="Close" />
            </button>
          </header>

          {canManage && (
            <div className={styles.listActions}>
              <button
                type="button"
                className={styles.primary}
                onClick={() => {
                  open({ kind: 'add' });
                }}
              >
                <Icon name="plus" size={15} />
                New server
              </button>
              <button
                type="button"
                className={styles.secondary}
                onClick={() => {
                  open({ kind: 'import' });
                }}
              >
                <Icon name="upload" size={15} />
                Import
              </button>
            </div>
          )}

          {mcp.error && <p className={styles.formError}>{mcp.error}</p>}
          <ul className={styles.serverList}>
            {servers.map((server) => {
              const active = pane && 'name' in pane && pane.name === server.name ? true : undefined;
              return (
                <li key={server.name} className={styles.serverRow} data-active={active}>
                  <button
                    type="button"
                    className={styles.serverButton}
                    aria-current={active}
                    onClick={() => {
                      open({ kind: 'view', name: server.name });
                    }}
                  >
                    <StatusDot status={server.status} />
                    <span className={styles.serverText}>
                      <span className={styles.serverName}>{server.name}</span>
                      <span className={styles.serverMeta}>
                        {server.config.type === 'stdio'
                          ? 'Local'
                          : server.config.type.toUpperCase()}
                        {' · '}
                        {server.status === 'connected'
                          ? `${server.tools.length} ${server.tools.length === 1 ? 'tool' : 'tools'}`
                          : statusLabel(server.status)}
                      </span>
                    </span>
                  </button>
                  {canManage && (
                    <button
                      type="button"
                      role="switch"
                      aria-checked={server.config.enabled}
                      aria-label={`${server.config.enabled ? 'Disable' : 'Enable'} ${server.name}`}
                      className={styles.miniSwitch}
                      onClick={() => void mcp.setEnabled(server.name, !server.config.enabled)}
                    >
                      <span className={styles.switchTrack}>
                        <span className={styles.switchThumb} />
                      </span>
                    </button>
                  )}
                </li>
              );
            })}
          </ul>
          {servers.length === 0 && mcp.data && <p className={styles.emptyList}>No servers yet.</p>}
        </aside>

        <section className={styles.pane} aria-live="polite">
          <button
            type="button"
            className={styles.back}
            onClick={() => {
              setShowPane(false);
            }}
          >
            <Icon name="chevron" size={14} className={styles.backIcon} />
            All servers
          </button>
          {content}
        </section>
      </div>
    </div>,
    document.body,
  );
}
