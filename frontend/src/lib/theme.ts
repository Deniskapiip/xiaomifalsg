import { create } from 'zustand';

export type Theme = 'dark' | 'light';
const STORAGE_KEY = 'taoji_v2_theme';
export const themeColors: Record<Theme, { background: string; button: string }> = {
  dark: { background: '#070B17', button: '#1E7BFF' },
  light: { background: '#F6F8FC', button: '#1764C0' },
};

function readTheme(): Theme {
  try { return localStorage.getItem(STORAGE_KEY) === 'light' ? 'light' : 'dark'; }
  catch { return 'dark'; }
}

export const useTheme = create<{ theme: Theme; toggle: () => void }>((set, get) => ({
  theme: readTheme(),
  toggle() {
    const theme = get().theme === 'dark' ? 'light' : 'dark';
    set({ theme });
    try { localStorage.setItem(STORAGE_KEY, theme); } catch { /* Still usable when storage is unavailable. */ }
  },
}));

function applyTheme(theme: Theme): void {
  document.documentElement.dataset.theme = theme;
  document.querySelector('meta[name="theme-color"]')?.setAttribute('content', themeColors[theme].background);
  document.querySelector('meta[name="color-scheme"]')?.setAttribute('content', theme);
}

export function initializeTheme(): () => void {
  applyTheme(useTheme.getState().theme);
  const unsubscribe = useTheme.subscribe(({ theme }) => applyTheme(theme));
  const onStorage = (event: StorageEvent) => {
    if (event.key !== STORAGE_KEY && event.key !== null) return;
    useTheme.setState({ theme: readTheme() });
  };
  window.addEventListener('storage', onStorage);
  return () => { unsubscribe(); window.removeEventListener('storage', onStorage); };
}
