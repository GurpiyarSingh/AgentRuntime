/** One MCP server: its status, how it connects, its tools, and what can be done to it. */

import { useState } from 'react';

import { ApiError } from '../../api/client';
import type { McpServer } from '../../api/types';
import { formatRelativeTime } from '../../lib/format';
import { Icon } from '../Icon';
import styles from './McpDialog.module.css';
import { StatusPill } from './McpStatus';

interface McpServerDetailProps {
  server: McpServer;
  canManage: boolean;
  onEdit: () => void;
  onToggle: (enabled: boolean) => Promise<void>;
  onReconnect: () => Promise<void>;
  onDelete: () => Promise<void>;
}

const TRANSPORT_LABELS = { stdio: 'Local command', http: 'HTTP', sse: 'SSE' } as const;

export function McpServerDetail({
  server,
  canManage,
  onEdit,
  onToggle,
  onReconnect,
  onDelete,
}: McpServerDetailProps) {
  const [busy, setBusy] = useState<'toggle' | 'reconnect' | 'delete' | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [error, setError] = useState('');
  const { config } = server;
  const commandLine = [config.command, ...config.args].filter(Boolean).join(' ');

  const run = async (kind: 'toggle' | 'reconnect' | 'delete', action: () => Promise<void>) => {
    setBusy(kind);
    setError('');
    try {
      await action();
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : 'Something went wrong.');
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className={styles.detail}>
      <header className={styles.paneHeader}>
        <div className={styles.detailTitle}>
          <span className={styles.serverIcon}>
            <Icon name={config.type === 'stdio' ? 'terminal' : 'globe'} size={18} />
          </span>
          <div>
            <h3 className={styles.paneTitle}>{server.name}</h3>
            <p className={styles.paneSubtitle}>
              {server.server_name
                ? `${server.server_name}${server.server_version ? ` ${server.server_version}` : ''}`
                : TRANSPORT_LABELS[config.type]}
              {server.connected_at && ` · connected ${formatRelativeTime(server.connected_at)}`}
            </p>
          </div>
        </div>
        <StatusPill status={server.status} />
      </header>

      {config.description && <p className={styles.description}>{config.description}</p>}

      {canManage && (
        <div className={styles.actions}>
          <button
            type="button"
            role="switch"
            aria-checked={config.enabled}
            className={styles.switch}
            disabled={busy !== null}
            onClick={() => void run('toggle', () => onToggle(!config.enabled))}
          >
            <span className={styles.switchTrack}>
              <span className={styles.switchThumb} />
            </span>
            {config.enabled ? 'Enabled' : 'Disabled'}
          </button>
          <span className={styles.spacer} />
          <button
            type="button"
            className={styles.secondary}
            disabled={busy !== null || !config.enabled}
            onClick={() => void run('reconnect', onReconnect)}
          >
            <Icon
              name="refresh"
              size={15}
              className={busy === 'reconnect' ? styles.spin : undefined}
            />
            Reconnect
          </button>
          <button
            type="button"
            className={styles.secondary}
            disabled={busy !== null}
            onClick={onEdit}
          >
            <Icon name="pencil" size={15} />
            Edit
          </button>
          {confirming ? (
            <>
              <button
                type="button"
                className={styles.danger}
                disabled={busy !== null}
                onClick={() => void run('delete', onDelete)}
              >
                {busy === 'delete' ? 'Deleting…' : `Delete ${server.name}`}
              </button>
              <button
                type="button"
                className={styles.ghost}
                onClick={() => {
                  setConfirming(false);
                }}
              >
                Keep
              </button>
            </>
          ) : (
            <button
              type="button"
              className={styles.iconButton}
              disabled={busy !== null}
              onClick={() => {
                setConfirming(true);
              }}
            >
              <Icon name="trash" size={15} label="Delete server" />
            </button>
          )}
        </div>
      )}

      {error && (
        <p className={styles.formError} role="alert">
          <Icon name="alert" size={15} />
          {error}
        </p>
      )}
      {server.status === 'error' && server.error && (
        <div className={styles.testFail} role="alert">
          <p className={styles.testTitle}>
            <Icon name="alert" size={15} />
            Not connected
          </p>
          <pre className={styles.errorText}>{server.error}</pre>
        </div>
      )}
      {server.status === 'connecting' && (
        <p className={styles.notice}>
          <Icon name="spinner" size={15} className={styles.spin} />
          Starting the server… A first start can take a while if it downloads packages.
        </p>
      )}

      <section className={styles.section}>
        <h4 className={styles.sectionTitle}>Connection</h4>
        <dl className={styles.facts}>
          <dt>Type</dt>
          <dd>{TRANSPORT_LABELS[config.type]}</dd>
          {config.type === 'stdio' ? (
            <>
              <dt>Command</dt>
              <dd>
                <code>{commandLine}</code>
              </dd>
              {config.cwd && (
                <>
                  <dt>Folder</dt>
                  <dd>
                    <code>{config.cwd}</code>
                  </dd>
                </>
              )}
              {Object.keys(config.env).length > 0 && (
                <>
                  <dt>Environment</dt>
                  <dd className={styles.keys}>
                    {Object.keys(config.env).map((key) => (
                      <code key={key}>{key}</code>
                    ))}
                  </dd>
                </>
              )}
            </>
          ) : (
            <>
              <dt>URL</dt>
              <dd>
                <code>{config.url}</code>
              </dd>
              {Object.keys(config.headers).length > 0 && (
                <>
                  <dt>Headers</dt>
                  <dd className={styles.keys}>
                    {Object.keys(config.headers).map((key) => (
                      <code key={key}>{key}</code>
                    ))}
                  </dd>
                </>
              )}
            </>
          )}
        </dl>
      </section>

      <section className={styles.section}>
        <h4 className={styles.sectionTitle}>
          Tools
          <span className={styles.count}>{server.tools.length}</span>
        </h4>
        {server.tools.length === 0 ? (
          <p className={styles.hint}>
            {server.status === 'connected'
              ? 'This server offers no tools.'
              : 'Tools appear here once the server is connected.'}
          </p>
        ) : (
          <ul className={styles.toolList}>
            {server.tools.map((tool) => (
              <li key={tool.qualified_name}>
                <code className={styles.toolName}>{tool.qualified_name}</code>
                {tool.description && <p className={styles.toolDescription}>{tool.description}</p>}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
