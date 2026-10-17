/**
 * Add or edit one MCP server: start from a template or from scratch, fill
 * in how to reach it, try the connection, save.
 */

import { useId, useState, type SubmitEvent } from 'react';

import { ApiError } from '../../api/client';
import type { McpServerConfig, McpTestResult, McpTransport } from '../../api/types';
import { MCP_TEMPLATES, fromTemplate, type McpTemplate } from '../../lib/mcpTemplates';
import { Icon, type IconName } from '../Icon';
import { KeyValueEditor, type Pair } from './KeyValueEditor';
import styles from './McpDialog.module.css';

const NAME_RE = /^[A-Za-z0-9][A-Za-z0-9_-]{0,31}$/;

interface Draft {
  name: string;
  type: McpTransport;
  command: string;
  /** One argument per line, so arguments with spaces need no quoting. */
  args: string;
  cwd: string;
  url: string;
  env: Pair[];
  headers: Pair[];
  timeout: string;
  description: string;
  enabled: boolean;
}

const toPairs = (record: Record<string, string>): Pair[] =>
  Object.entries(record).map(([key, value]) => ({ key, value }));

const fromPairs = (pairs: Pair[]): Record<string, string> =>
  Object.fromEntries(
    pairs.filter((pair) => pair.key.trim()).map((pair) => [pair.key.trim(), pair.value]),
  );

function toDraft(name: string, config: McpServerConfig): Draft {
  return {
    name,
    type: config.type,
    command: config.command ?? '',
    args: config.args.join('\n'),
    cwd: config.cwd ?? '',
    url: config.url ?? '',
    env: toPairs(config.env),
    headers: toPairs(config.headers),
    timeout: String(config.timeout_s),
    description: config.description,
    enabled: config.enabled,
  };
}

/** The config to send: only the fields its transport uses. */
function toConfig(draft: Draft): McpServerConfig {
  const local = draft.type === 'stdio';
  const timeout = Number(draft.timeout);
  return {
    type: draft.type,
    command: local ? draft.command.trim() : null,
    args: local
      ? draft.args
          .split('\n')
          .map((line) => line.trim())
          .filter(Boolean)
      : [],
    env: local ? fromPairs(draft.env) : {},
    cwd: local && draft.cwd.trim() ? draft.cwd.trim() : null,
    url: local ? null : draft.url.trim(),
    headers: local ? {} : fromPairs(draft.headers),
    enabled: draft.enabled,
    timeout_s: Number.isFinite(timeout) && timeout > 0 ? Math.min(timeout, 600) : 60,
    description: draft.description.trim(),
  };
}

function problem(draft: Draft, allowStdio: boolean): string | undefined {
  if (!NAME_RE.test(draft.name)) {
    return 'Name: 1-32 letters, digits, _ or -, starting with a letter or digit.';
  }
  if (draft.type === 'stdio') {
    if (!allowStdio) return 'Local servers are turned off on this server; use HTTP or SSE.';
    if (!draft.command.trim()) return 'Enter the command that starts the server, e.g. npx.';
  } else if (!/^https?:\/\//i.test(draft.url.trim())) {
    return 'Enter the server URL, starting with http:// or https://.';
  }
  return undefined;
}

const TRANSPORTS: { value: McpTransport; label: string; icon: IconName; hint: string }[] = [
  {
    value: 'stdio',
    label: 'Local command',
    icon: 'terminal',
    hint: 'Runs a program (npx, uvx, …)',
  },
  { value: 'http', label: 'HTTP', icon: 'globe', hint: 'Streamable HTTP, the current standard' },
  { value: 'sse', label: 'SSE', icon: 'activity', hint: 'The older HTTP + Server-Sent Events' },
];

export function TestResultView({ result }: { result: McpTestResult }) {
  if (!result.ok) {
    return (
      <div className={styles.testFail} role="alert">
        <p className={styles.testTitle}>
          <Icon name="alert" size={15} />
          Couldn&apos;t connect
        </p>
        <pre className={styles.errorText}>{result.error}</pre>
      </div>
    );
  }
  return (
    <div className={styles.testOk} role="status">
      <p className={styles.testTitle}>
        <Icon name="check" size={15} />
        Connected to {result.server_name ?? 'the server'}
        {result.server_version && ` ${result.server_version}`} in {result.duration_s.toFixed(1)} s ·{' '}
        {result.tools.length} {result.tools.length === 1 ? 'tool' : 'tools'}
      </p>
      {result.tools.length > 0 && (
        <ul className={styles.toolChips}>
          {result.tools.map((tool) => (
            <li key={tool.name} title={tool.description}>
              {tool.name}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

interface McpServerFormProps {
  mode: 'add' | 'edit';
  initialName: string;
  initialConfig: McpServerConfig;
  allowStdio: boolean;
  /** Names already in use (adding only). */
  takenNames: string[];
  onTest: (config: McpServerConfig, name?: string) => Promise<McpTestResult>;
  onSave: (name: string, config: McpServerConfig) => Promise<void>;
  onCancel: () => void;
}

export function McpServerForm({
  mode,
  initialName,
  initialConfig,
  allowStdio,
  takenNames,
  onTest,
  onSave,
  onCancel,
}: McpServerFormProps) {
  const [draft, setDraft] = useState(() => toDraft(initialName, initialConfig));
  const [template, setTemplate] = useState<McpTemplate>();
  const [testing, setTesting] = useState(false);
  const [saving, setSaving] = useState(false);
  const [result, setResult] = useState<McpTestResult>();
  const [error, setError] = useState('');
  const ids = { name: useId(), command: useId(), args: useId(), cwd: useId(), url: useId() };
  const ids2 = { timeout: useId(), description: useId() };
  const adding = mode === 'add';

  const change = (patch: Partial<Draft>) => {
    setDraft((current) => ({ ...current, ...patch }));
    setResult(undefined); // A test result describes the old settings.
  };

  const pick = (chosen: McpTemplate) => {
    setTemplate(chosen);
    setError('');
    setResult(undefined);
    let name = chosen.name;
    for (let n = 2; takenNames.includes(name); n += 1) name = `${chosen.name}-${n}`;
    setDraft(toDraft(name, fromTemplate(chosen)));
  };

  const check = (): McpServerConfig | undefined => {
    const message = problem(draft, allowStdio);
    if (message) {
      setError(message);
      return undefined;
    }
    if (adding && takenNames.includes(draft.name)) {
      setError(`A server named “${draft.name}” already exists.`);
      return undefined;
    }
    setError('');
    return toConfig(draft);
  };

  const test = async () => {
    const config = check();
    if (!config) return;
    setTesting(true);
    setResult(undefined);
    try {
      setResult(await onTest(config, adding ? undefined : initialName));
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : 'The test could not run.');
    } finally {
      setTesting(false);
    }
  };

  const save = async (event: SubmitEvent<HTMLFormElement>) => {
    event.preventDefault();
    const config = check();
    if (!config) return;
    setSaving(true);
    try {
      await onSave(draft.name, config);
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : 'Could not save the server.');
      setSaving(false);
    }
  };

  return (
    <form className={styles.form} onSubmit={(event) => void save(event)} noValidate>
      <header className={styles.paneHeader}>
        <div>
          <h3 className={styles.paneTitle}>
            {adding ? 'Add an MCP server' : `Edit ${initialName}`}
          </h3>
          <p className={styles.paneSubtitle}>
            {adding
              ? 'Start from a popular server, or describe your own.'
              : 'Changes reconnect the server. Saved secrets stay unless you replace them.'}
          </p>
        </div>
      </header>

      {adding && (
        <div className={styles.templates} role="group" aria-label="Templates">
          {MCP_TEMPLATES.map((option) => (
            <button
              key={option.id}
              type="button"
              className={styles.template}
              data-tone={option.tone}
              aria-pressed={template?.id === option.id}
              onClick={() => {
                pick(option);
              }}
            >
              <span className={styles.templateIcon}>
                <Icon name={option.icon} size={16} />
              </span>
              {option.title}
            </button>
          ))}
        </div>
      )}
      {template && (
        <p className={styles.templateHint}>
          <Icon name="sparkles" size={14} />
          {template.hint}
        </p>
      )}

      <div className={styles.fieldRow}>
        <div className={styles.field}>
          <label htmlFor={ids.name} className={styles.label}>
            Name
          </label>
          <input
            id={ids.name}
            className={`${styles.input ?? ''} ${styles.mono ?? ''}`}
            value={draft.name}
            disabled={!adding}
            placeholder="github"
            spellCheck={false}
            onChange={(event) => {
              change({ name: event.target.value });
            }}
          />
          <span className={styles.hint}>
            Its tools are named <code>{draft.name || 'name'}__tool</code>.
          </span>
        </div>
        <label className={styles.switchField}>
          <input
            type="checkbox"
            checked={draft.enabled}
            onChange={(event) => {
              change({ enabled: event.target.checked });
            }}
          />
          <span>Enabled</span>
        </label>
      </div>

      <div className={styles.field}>
        <span className={styles.label}>Connection</span>
        <div className={styles.segmented} role="radiogroup" aria-label="Connection type">
          {TRANSPORTS.map((option) => (
            <button
              key={option.value}
              type="button"
              role="radio"
              aria-checked={draft.type === option.value}
              className={styles.segment}
              disabled={option.value === 'stdio' && !allowStdio}
              title={option.hint}
              onClick={() => {
                change({ type: option.value });
              }}
            >
              <Icon name={option.icon} size={15} />
              {option.label}
            </button>
          ))}
        </div>
      </div>

      {draft.type === 'stdio' ? (
        <>
          <div className={styles.field}>
            <label htmlFor={ids.command} className={styles.label}>
              Command
            </label>
            <input
              id={ids.command}
              className={`${styles.input ?? ''} ${styles.mono ?? ''}`}
              value={draft.command}
              placeholder="npx"
              spellCheck={false}
              onChange={(event) => {
                change({ command: event.target.value });
              }}
            />
          </div>
          <div className={styles.field}>
            <label htmlFor={ids.args} className={styles.label}>
              Arguments <span className={styles.optional}>one per line</span>
            </label>
            <textarea
              id={ids.args}
              className={`${styles.input ?? ''} ${styles.mono ?? ''} ${styles.textarea ?? ''}`}
              value={draft.args}
              rows={3}
              placeholder={'-y\n@modelcontextprotocol/server-memory'}
              spellCheck={false}
              onChange={(event) => {
                change({ args: event.target.value });
              }}
            />
          </div>
          <KeyValueEditor
            label="Environment variables"
            hint="API keys and settings the server reads, e.g. JIRA_API_TOKEN."
            pairs={draft.env}
            keyPlaceholder="NAME"
            valuePlaceholder="value"
            onChange={(env) => {
              change({ env });
            }}
          />
          <div className={styles.field}>
            <label htmlFor={ids.cwd} className={styles.label}>
              Working folder <span className={styles.optional}>optional</span>
            </label>
            <input
              id={ids.cwd}
              className={`${styles.input ?? ''} ${styles.mono ?? ''}`}
              value={draft.cwd}
              placeholder="Where to run the command"
              spellCheck={false}
              onChange={(event) => {
                change({ cwd: event.target.value });
              }}
            />
          </div>
        </>
      ) : (
        <>
          <div className={styles.field}>
            <label htmlFor={ids.url} className={styles.label}>
              Server URL
            </label>
            <input
              id={ids.url}
              className={`${styles.input ?? ''} ${styles.mono ?? ''}`}
              value={draft.url}
              placeholder={
                draft.type === 'sse' ? 'https://example.com/sse' : 'https://example.com/mcp'
              }
              spellCheck={false}
              onChange={(event) => {
                change({ url: event.target.value });
              }}
            />
          </div>
          <KeyValueEditor
            label="Headers"
            hint="For example Authorization: Bearer <token>. OAuth sign-in isn't supported; use a token."
            pairs={draft.headers}
            keyPlaceholder="Authorization"
            valuePlaceholder="Bearer …"
            onChange={(headers) => {
              change({ headers });
            }}
          />
        </>
      )}

      <details className={styles.advanced}>
        <summary>Advanced</summary>
        <div className={styles.fieldRow}>
          <div className={styles.field}>
            <label htmlFor={ids2.timeout} className={styles.label}>
              Start-up timeout (seconds)
            </label>
            <input
              id={ids2.timeout}
              className={styles.input}
              type="number"
              min={1}
              max={600}
              value={draft.timeout}
              onChange={(event) => {
                change({ timeout: event.target.value });
              }}
            />
          </div>
          <div className={styles.field}>
            <label htmlFor={ids2.description} className={styles.label}>
              Note <span className={styles.optional}>optional</span>
            </label>
            <input
              id={ids2.description}
              className={styles.input}
              value={draft.description}
              maxLength={500}
              placeholder="What it's for"
              onChange={(event) => {
                change({ description: event.target.value });
              }}
            />
          </div>
        </div>
      </details>

      {error && (
        <p className={styles.formError} role="alert">
          <Icon name="alert" size={15} />
          {error}
        </p>
      )}
      {result && <TestResultView result={result} />}

      <footer className={styles.formActions}>
        <button
          type="button"
          className={styles.secondary}
          disabled={testing || saving}
          onClick={() => void test()}
        >
          <Icon
            name={testing ? 'spinner' : 'beaker'}
            size={15}
            className={testing ? styles.spin : undefined}
          />
          {testing ? 'Testing…' : 'Test connection'}
        </button>
        <span className={styles.spacer} />
        <button type="button" className={styles.ghost} onClick={onCancel} disabled={saving}>
          Cancel
        </button>
        <button type="submit" className={styles.primary} disabled={saving || testing}>
          {saving ? 'Saving…' : adding ? 'Add server' : 'Save changes'}
        </button>
      </footer>
    </form>
  );
}
