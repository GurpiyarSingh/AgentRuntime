/**
 * Light, dark, or follow the system. The choice is an attribute on <html>
 * (`data-theme`), which global.css keys its tokens on; "system" removes it
 * so the `prefers-color-scheme` media query decides.
 */

import { useCallback, useState } from 'react';

import { loadSetting, saveSetting } from './storage';

export type ThemeChoice = 'system' | 'light' | 'dark';

const CHOICES: readonly ThemeChoice[] = ['system', 'light', 'dark'];

export function savedTheme(): ThemeChoice {
  const saved = loadSetting('theme');
  return (CHOICES as readonly string[]).includes(saved) ? (saved as ThemeChoice) : 'system';
}

export function applyTheme(choice: ThemeChoice): void {
  const root = document.documentElement;
  if (choice === 'system') root.removeAttribute('data-theme');
  else root.setAttribute('data-theme', choice);
}

/** The current choice and a setter that applies and remembers it. */
export function useTheme(): [ThemeChoice, (choice: ThemeChoice) => void] {
  const [choice, setChoice] = useState(savedTheme);
  const change = useCallback((next: ThemeChoice) => {
    applyTheme(next);
    saveSetting('theme', next === 'system' ? '' : next);
    setChoice(next);
  }, []);
  return [choice, change];
}
