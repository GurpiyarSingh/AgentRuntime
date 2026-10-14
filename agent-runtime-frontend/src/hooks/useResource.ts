/**
 * Load data on mount, and again on `reload` or when `refreshKey` changes.
 *
 * Deliberately small: the app reads three static endpoints (health, tools,
 * models), which doesn't justify a caching library. State is only set when
 * a request settles; `loading` is derived by comparing the settled request
 * with the current one, so the previous data stays on screen while a reload
 * is in flight.
 */

import { useCallback, useEffect, useState } from 'react';

import { ApiError } from '../api/client';

export interface Resource<T> {
  data: T | undefined;
  error: ApiError | undefined;
  loading: boolean;
  reload: () => void;
}

interface Request<T> {
  load: (signal: AbortSignal) => Promise<T>;
  attempt: number;
  refreshKey: unknown;
}

interface Settled<T> extends Request<T> {
  data: T | undefined;
  error: ApiError | undefined;
}

function sameRequest<T>(a: Request<T>, b: Request<T>): boolean {
  return a.load === b.load && a.attempt === b.attempt && Object.is(a.refreshKey, b.refreshKey);
}

/**
 * @param load Fetches the data; must be stable (wrap it in useCallback).
 * @param refreshKey Any value; when it changes the data is fetched again
 *   (e.g. the API key, so entering a key retries everything).
 */
export function useResource<T>(
  load: (signal: AbortSignal) => Promise<T>,
  refreshKey?: unknown,
): Resource<T> {
  const [attempt, setAttempt] = useState(0);
  const [settled, setSettled] = useState<Settled<T>>();

  useEffect(() => {
    const request: Request<T> = { load, attempt, refreshKey };
    const controller = new AbortController();
    load(controller.signal).then(
      (data) => {
        setSettled({ ...request, data, error: undefined });
      },
      (reason: unknown) => {
        if (controller.signal.aborted) return;
        const error = reason instanceof ApiError ? reason : new ApiError(0, String(reason));
        setSettled((previous) => ({ ...request, data: previous?.data, error }));
      },
    );
    return () => {
      controller.abort();
    };
  }, [load, attempt, refreshKey]);

  const reload = useCallback(() => {
    setAttempt((n) => n + 1);
  }, []);

  const current: Request<T> = { load, attempt, refreshKey };
  return {
    data: settled?.data,
    error: settled?.error,
    loading: !settled || !sameRequest(settled, current),
    reload,
  };
}
