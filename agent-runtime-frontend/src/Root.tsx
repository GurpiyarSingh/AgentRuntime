/**
 * Builds the one API client, owns the API key, and renders the app.
 */

import { useState } from 'react';

import { ApiProvider } from './api/ApiContext';
import { ApiClient } from './api/client';
import { App } from './App';
import { API_BASE_URL } from './config';
import { loadSetting, saveSetting } from './lib/storage';

/** Holds the current API key where the client can read it on every request. */
function createKeyStore(initial: string) {
  let key = initial;
  return {
    get: () => key,
    set: (next: string) => {
      key = next;
    },
  };
}

export function Root() {
  const [apiKey, setApiKey] = useState(() => loadSetting('apiKey'));
  // Created once: the client stays a single instance and reads the key from
  // the store per request, so a new key applies without rebuilding anything.
  const [keyStore] = useState(() => createKeyStore(apiKey));
  const [client] = useState(
    () => new ApiClient({ baseUrl: API_BASE_URL, getApiKey: keyStore.get }),
  );

  const changeApiKey = (key: string) => {
    keyStore.set(key);
    setApiKey(key); // Re-render: resources keyed on the API key refetch.
    saveSetting('apiKey', key);
  };

  return (
    <ApiProvider client={client}>
      <App apiKey={apiKey} onApiKeyChange={changeApiKey} />
    </ApiProvider>
  );
}
