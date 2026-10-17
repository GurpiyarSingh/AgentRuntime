/**
 * Builds the one API client and decides what to show: a splash while it
 * checks the server, the sign-in page when the server requires it, or the
 * app. Owns the credentials (sign-in token, optional API key), so signing
 * out simply unmounts the app and everything it held.
 */

import { useCallback, useEffect, useState } from 'react';

import { ApiProvider } from './api/ApiContext';
import { ApiClient, ApiError } from './api/client';
import type { LoginResponse, User } from './api/types';
import { App } from './App';
import { LoginPage } from './components/auth/LoginPage';
import { Splash } from './components/brand/Splash';
import { API_BASE_URL } from './config';
import { loadSetting, saveSetting } from './lib/storage';

/** A value the client reads on every request, so changes apply without rebuilding it. */
function createStore(initial: string) {
  let value = initial;
  return {
    get: () => value,
    set: (next: string) => {
      value = next;
    },
  };
}

type Phase =
  | { kind: 'checking' }
  | { kind: 'unreachable'; message: string }
  /** The server has no sign-in (no database, or AUTH_ENABLED=false). */
  | { kind: 'open' }
  | { kind: 'login'; notice?: string }
  | { kind: 'setup' }
  | { kind: 'signedIn'; user: User };

export function Root() {
  const [apiKey, setApiKey] = useState(() => loadSetting('apiKey'));
  const [phase, setPhase] = useState<Phase>({ kind: 'checking' });
  const [attempt, setAttempt] = useState(0);
  // Created once: the client reads these per request.
  const [keyStore] = useState(() => createStore(apiKey));
  const [tokenStore] = useState(() => createStore(loadSetting('token')));

  const forgetToken = useCallback(() => {
    tokenStore.set('');
    saveSetting('token', '');
  }, [tokenStore]);

  const [client] = useState(
    () =>
      new ApiClient({
        baseUrl: API_BASE_URL,
        getApiKey: keyStore.get,
        getToken: tokenStore.get,
        // A token that stops working (expired, revoked) sends you back to sign in.
        onUnauthorized: () => {
          forgetToken();
          setPhase({ kind: 'login', notice: 'Your session expired. Sign in again.' });
        },
      }),
  );

  useEffect(() => {
    const controller = new AbortController();
    const check = async () => {
      try {
        const status = await client.authStatus(controller.signal);
        if (!status.enabled) {
          setPhase({ kind: 'open' });
        } else if (status.setup_required) {
          setPhase({ kind: 'setup' });
        } else if (tokenStore.get()) {
          setPhase({ kind: 'signedIn', user: await client.me(controller.signal) });
        } else {
          setPhase({ kind: 'login' });
        }
      } catch (error) {
        if (controller.signal.aborted) return;
        if (error instanceof ApiError && error.status === 401) {
          forgetToken(); // A remembered token that no longer works.
          setPhase({ kind: 'login' });
          return;
        }
        if (error instanceof ApiError && error.status === 404) {
          setPhase({ kind: 'open' }); // An older server without /v1/auth.
          return;
        }
        setPhase({
          kind: 'unreachable',
          message: error instanceof Error ? error.message : 'Cannot reach the agent server.',
        });
      }
    };
    void check();
    return () => {
      controller.abort();
    };
  }, [client, tokenStore, forgetToken, attempt]);

  const changeApiKey = (key: string) => {
    keyStore.set(key);
    setApiKey(key); // Re-render: resources keyed on the API key refetch.
    saveSetting('apiKey', key);
  };

  const signedIn = (response: LoginResponse) => {
    tokenStore.set(response.token);
    saveSetting('token', response.token);
    setPhase({ kind: 'signedIn', user: response.user });
  };

  const signOut = () => {
    void client.logout().catch(() => undefined); // Best effort: the token is forgotten anyway.
    forgetToken();
    setPhase({ kind: 'login' });
  };

  let content;
  switch (phase.kind) {
    case 'checking':
      content = <Splash />;
      break;
    case 'unreachable':
      content = (
        <Splash
          error={phase.message}
          onRetry={() => {
            setPhase({ kind: 'checking' });
            setAttempt((n) => n + 1);
          }}
        />
      );
      break;
    case 'login':
    case 'setup':
      content = (
        <LoginPage
          mode={phase.kind}
          notice={phase.kind === 'login' ? phase.notice : undefined}
          onSignedIn={signedIn}
        />
      );
      break;
    case 'open':
    case 'signedIn':
      content = (
        <App
          apiKey={apiKey}
          onApiKeyChange={changeApiKey}
          user={phase.kind === 'signedIn' ? phase.user : undefined}
          onSignOut={phase.kind === 'signedIn' ? signOut : undefined}
        />
      );
      break;
  }

  return <ApiProvider client={client}>{content}</ApiProvider>;
}
