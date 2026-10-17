/** Entry point: fonts, theme, then mounts the app into #root. */

import '@fontsource-variable/inter';
import '@fontsource-variable/jetbrains-mono';
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';

import { applyTheme, savedTheme } from './lib/theme';
import { Root } from './Root';
import './styles/global.css';

// Before the first render, so a saved theme never flashes the other one.
applyTheme(savedTheme());

const container = document.getElementById('root');
if (!container) throw new Error('Missing #root element in index.html');

createRoot(container).render(
  <StrictMode>
    <Root />
  </StrictMode>,
);
