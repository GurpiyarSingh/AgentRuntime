/** Entry point: mounts the app into #root. */

import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';

import { Root } from './Root';
import './styles/global.css';

const container = document.getElementById('root');
if (!container) throw new Error('Missing #root element in index.html');

createRoot(container).render(
  <StrictMode>
    <Root />
  </StrictMode>,
);
