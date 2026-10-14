/**
 * localStorage that never throws.
 *
 * Storage can be unavailable (private browsing, blocked cookies, quota), and
 * a preference failing to save must never break the app, so every access is
 * guarded and falls back to the default.
 */

const PREFIX = 'agent-runtime:';

export function loadSetting(key: string, fallback = ''): string {
  try {
    return window.localStorage.getItem(PREFIX + key) ?? fallback;
  } catch {
    return fallback;
  }
}

export function saveSetting(key: string, value: string): void {
  try {
    if (value) window.localStorage.setItem(PREFIX + key, value);
    else window.localStorage.removeItem(PREFIX + key);
  } catch {
    // Preference not persisted; it still applies for this visit.
  }
}
