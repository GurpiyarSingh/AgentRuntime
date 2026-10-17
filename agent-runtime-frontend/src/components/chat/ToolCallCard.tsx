/**
 * One tool call inside an assistant turn: what was called, with what, and
 * what came back. Collapsed to a single line by default so a multi-step run
 * stays readable; files the agent created can be downloaded from here.
 */

import { useId, useState } from 'react';

import { useApi } from '../../api/ApiContext';
import { ApiError } from '../../api/client';
import type { ToolCall } from '../../chat/chatReducer';
import { saveBlob } from '../../lib/download';
import { formatDuration } from '../../lib/format';
import { createdFile, primaryArgument } from '../../lib/toolCalls';
import { toolMeta } from '../../lib/toolMeta';
import { Icon, type IconName } from '../Icon';
import styles from './ToolCallCard.module.css';

const STATUS: Record<ToolCall['status'], { icon: IconName; label: string }> = {
  running: { icon: 'spinner', label: 'Running' },
  ok: { icon: 'check', label: 'Succeeded' },
  error: { icon: 'alert', label: 'Failed' },
  cancelled: { icon: 'x', label: 'Cancelled' },
};

function DownloadButton({ path }: { path: string }) {
  const client = useApi();
  const [state, setState] = useState<'idle' | 'busy' | 'error'>('idle');
  const [error, setError] = useState('');

  const download = async () => {
    setState('busy');
    try {
      saveBlob(await client.downloadFile(path), path.split('/').pop() ?? path);
      setState('idle');
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : 'Download failed.');
      setState('error');
    }
  };

  return (
    <span className={styles.downloadWrap}>
      <button
        type="button"
        className={styles.download}
        disabled={state === 'busy'}
        onClick={() => void download()}
      >
        <Icon name="download" size={14} />
        {state === 'busy' ? 'Downloading…' : `Download ${path.split('/').pop() ?? ''}`}
      </button>
      {state === 'error' && <span className={styles.downloadError}>{error}</span>}
    </span>
  );
}

export function ToolCallCard({ call }: { call: ToolCall }) {
  const [open, setOpen] = useState(false);
  const bodyId = useId();
  const status = STATUS[call.status];
  const meta = toolMeta(call.toolName);
  const target = primaryArgument(call.arguments);
  const file = createdFile(call);

  return (
    <div className={`${styles.card ?? ''} ${styles[call.status] ?? ''}`} data-tone={meta.tone}>
      <div className={styles.row}>
        <button
          type="button"
          className={styles.header}
          aria-expanded={open}
          aria-controls={bodyId}
          onClick={() => {
            setOpen((value) => !value);
          }}
        >
          <span className={styles.chip}>
            <Icon name={meta.icon} size={15} />
          </span>
          <span className={styles.label}>{meta.label}</span>
          <span className={styles.name}>{call.toolName}</span>
          {target && <span className={styles.target}>{target}</span>}
          <span className={styles.spacer} />
          {call.durationS !== undefined && (
            <span className={styles.duration}>{formatDuration(call.durationS)}</span>
          )}
          <span className={styles.status}>
            <Icon
              name={status.icon}
              size={13}
              label={status.label}
              className={call.status === 'running' ? styles.spin : undefined}
            />
          </span>
          <Icon name="chevron" size={14} className={open ? styles.chevronOpen : styles.chevron} />
        </button>
        {file && <DownloadButton path={file} />}
      </div>

      {open && (
        <div id={bodyId} className={styles.body}>
          <div className={styles.section}>Arguments</div>
          <pre className={styles.pre}>{JSON.stringify(call.arguments, null, 2)}</pre>
          {call.content !== undefined && (
            <>
              <div className={styles.section}>{call.status === 'error' ? 'Error' : 'Result'}</div>
              <pre className={styles.pre}>{call.content}</pre>
            </>
          )}
          {call.imageCount > 0 && (
            <p className={styles.note}>
              <Icon name="image" size={13} />
              {call.imageCount === 1 ? 'An image was' : `${call.imageCount} images were`} shown to
              the agent.
            </p>
          )}
        </div>
      )}
    </div>
  );
}
