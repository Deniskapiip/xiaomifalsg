import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import '@fontsource/manrope/400.css';
import '@fontsource/manrope/500.css';
import '@fontsource/manrope/600.css';
import '@fontsource/manrope/700.css';
import './styles/tokens.css';
import './styles/global.css';
import './styles/admin.css';
import { App } from './App';
import { initializeTheme } from './lib/theme';
import { installTapHaptics } from './lib/telegram-ui';

const cleanupTheme = initializeTheme();
const cleanupHaptics = installTapHaptics();
if (import.meta.hot) import.meta.hot.dispose(() => { cleanupTheme(); cleanupHaptics(); });
createRoot(document.getElementById('root')!).render(<StrictMode><App /></StrictMode>);
