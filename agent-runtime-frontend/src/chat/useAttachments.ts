/**
 * Files attached to the message being written.
 *
 * Each file is uploaded into the workspace as soon as it is picked, so the
 * agent can read it by path when the message is sent. A file that already
 * exists there (HTTP 409) is not overwritten: the existing copy is used and
 * the chip says so, rather than silently replacing someone's file.
 */

import { useCallback, useState } from 'react';

import { ApiError, type ApiClient } from '../api/client';

export interface Attachment {
  id: string;
  name: string;
  status: 'uploading' | 'ready' | 'error';
  /** Workspace path, once uploaded (or found to exist already). */
  path?: string;
  /** Error text, or a note such as "already in workspace". */
  message?: string;
}

export interface Attachments {
  items: Attachment[];
  add: (files: Iterable<File>) => void;
  remove: (id: string) => void;
  clear: () => void;
  /** True while any upload is still running. */
  uploading: boolean;
  /** Workspace paths of every attachment that is ready to send. */
  readyPaths: string[];
}

export function useAttachments(client: ApiClient, folder: string): Attachments {
  const [items, setItems] = useState<Attachment[]>([]);

  const update = useCallback((id: string, patch: Partial<Attachment>) => {
    setItems((current) => current.map((item) => (item.id === id ? { ...item, ...patch } : item)));
  }, []);

  const add = useCallback(
    (files: Iterable<File>) => {
      for (const file of files) {
        const id = crypto.randomUUID();
        setItems((current) => [...current, { id, name: file.name, status: 'uploading' }]);
        client.uploadFile(file, folder).then(
          (uploaded) => {
            update(id, { status: 'ready', path: uploaded.path });
          },
          (reason: unknown) => {
            if (reason instanceof ApiError && reason.status === 409) {
              update(id, {
                status: 'ready',
                path: `${folder}${file.name}`,
                message: 'already in workspace',
              });
            } else {
              update(id, {
                status: 'error',
                message: reason instanceof ApiError ? reason.message : 'Upload failed',
              });
            }
          },
        );
      }
    },
    [client, folder, update],
  );

  const remove = useCallback((id: string) => {
    setItems((current) => current.filter((item) => item.id !== id));
  }, []);

  const clear = useCallback(() => {
    setItems([]);
  }, []);

  const readyPaths = items.flatMap((item) =>
    item.status === 'ready' && item.path ? [item.path] : [],
  );

  return {
    items,
    add,
    remove,
    clear,
    uploading: items.some((item) => item.status === 'uploading'),
    readyPaths,
  };
}
