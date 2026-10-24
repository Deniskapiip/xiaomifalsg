import { useEffect, useRef, useState } from 'react';
import { safeHttpUrl } from './validation';
import { themeColors, useTheme } from './theme';
import type { User } from '../api/types';

export function webApp(): TelegramWebApp | undefined { return typeof window === 'undefined' ? undefined : window.Telegram?.WebApp; }
export function inTelegram(): boolean { return Boolean(webApp()?.initData); }
export function supports(version: string): boolean {
  try { return inTelegram() && Boolean(webApp()?.isVersionAtLeast(version)); } catch { return false; }
}
export function initializeTelegram(): () => void {
  const app = webApp();
  if (!app || !inTelegram()) return () => {};
  try {
    app.ready(); app.expand();
    if (supports('7.7')) app.disableVerticalSwipes?.();
  } catch { /* An older Telegram client keeps the normal HTML interface. */ }
  const syncColors = () => {
    const { background } = themeColors[useTheme.getState().theme];
    if (supports('6.1')) {
      try { app.setHeaderColor(supports('6.9') ? background : 'bg_color'); } catch { /* Optional. */ }
      try { app.setBackgroundColor(background); } catch { /* Optional. */ }
    }
    if (supports('7.10')) { try { app.setBottomBarColor?.(background); } catch { /* Optional. */ } }
  };
  syncColors();
  const unsubscribeTheme = useTheme.subscribe(syncColors);
  const safeAreas = () => {
    if (!supports('8.0')) return;
    for (const side of ['top', 'bottom', 'left', 'right'] as const) {
      document.documentElement.style.setProperty(`--tg-safe-area-inset-${side}`, `${app.safeAreaInset?.[side] ?? 0}px`);
      document.documentElement.style.setProperty(`--tg-content-safe-area-inset-${side}`, `${app.contentSafeAreaInset?.[side] ?? 0}px`);
    }
  };
  safeAreas();
  app.onEvent?.('safeAreaChanged', safeAreas); app.onEvent?.('contentSafeAreaChanged', safeAreas); app.onEvent?.('themeChanged', syncColors);
  return () => { unsubscribeTheme(); app.offEvent?.('safeAreaChanged', safeAreas); app.offEvent?.('contentSafeAreaChanged', safeAreas); app.offEvent?.('themeChanged', syncColors); };
}
export type HapticKind = 'selection' | 'tap' | 'impact' | 'success' | 'error' | 'warning';
/** Light impact for ordinary taps, selection for controls, notifications for outcomes. */
export function haptic(kind: HapticKind): void {
  if (!supports('6.1')) return;
  try {
    const feedback = webApp()?.HapticFeedback;
    if (!feedback) return;
    if (kind === 'selection') feedback.selectionChanged();
    else if (kind === 'tap') feedback.impactOccurred('light');
    else if (kind === 'impact') feedback.impactOccurred('medium');
    else feedback.notificationOccurred(kind);
  } catch { /* Optional. */ }
}
const POPUP_TIMEOUT_MS = 120000;
/** Native Telegram alert; resolves immediately in a plain browser where no popup API exists. */
export function showAlert(message: string): Promise<void> {
  const app = webApp();
  if (!supports('6.2') || !app?.showAlert) return Promise.resolve();
  return new Promise(resolve => {
    const timer = setTimeout(resolve, POPUP_TIMEOUT_MS);
    try { app.showAlert!(message, () => { clearTimeout(timer); resolve(); }); }
    catch { clearTimeout(timer); resolve(); }
  });
}
/** Native Telegram confirmation; a browser without the popup API resolves to false and changes nothing. */
export function showConfirm(message: string): Promise<boolean> {
  const app = webApp();
  if (!supports('6.2') || !app?.showConfirm) return Promise.resolve(false);
  return new Promise(resolve => {
    const timer = setTimeout(() => resolve(false), POPUP_TIMEOUT_MS);
    try { app.showConfirm!(message, confirmed => { clearTimeout(timer); resolve(Boolean(confirmed)); }); }
    catch { clearTimeout(timer); resolve(false); }
  });
}
/** Native Telegram popup. Resolves with the pressed button id or null when dismissed. */
export function showPopup(params: TelegramPopupParams): Promise<string | null> {
  const app = webApp();
  if (!supports('6.2') || !app?.showPopup) return Promise.resolve(null);
  return new Promise(resolve => {
    const timer = setTimeout(() => resolve(null), POPUP_TIMEOUT_MS);
    try { app.showPopup!(params, id => { clearTimeout(timer); resolve(id || null); }); }
    catch { clearTimeout(timer); resolve(null); }
  });
}
export function canAddToHomeScreen(): boolean {
  return supports('8.0') && typeof webApp()?.addToHomeScreen === 'function';
}
/** Adds the Mini App icon to the Telegram home screen. Returns false when the client cannot. */
export function addToHomeScreen(): boolean {
  const app = webApp();
  if (!canAddToHomeScreen() || !app?.addToHomeScreen) return false;
  try { app.addToHomeScreen(); return true; } catch { return false; }
}
/** Reports whether the app icon is already on the user's Telegram home screen. */
export function homeScreenStatus(): Promise<TelegramHomeScreenStatus | null> {
  const app = webApp();
  if (!supports('8.0') || !app?.checkHomeScreenStatus) return Promise.resolve(null);
  return new Promise(resolve => {
    const timer = setTimeout(() => resolve(null), 2000);
    try { app.checkHomeScreenStatus!(status => { clearTimeout(timer); resolve(status); }); }
    catch { clearTimeout(timer); resolve(null); }
  });
}
export function openExternal(value: string): boolean {
  const url = safeHttpUrl(value); if (!url) return false;
  try { if (inTelegram()) webApp()!.openLink(url); else window.open(url, '_blank', 'noopener,noreferrer'); return true; }
  catch { return false; }
}
export function openTelegram(username: string, text?: string): boolean {
  const clean = username.replace(/^@/, '');
  if (!/^[A-Za-z0-9_]{5,32}$/.test(clean)) return false;
  const url = `https://t.me/${clean}` + (text ? `?text=${encodeURIComponent(text)}` : '');
  try { if (inTelegram()) webApp()!.openTelegramLink(url); else window.open(url, '_blank', 'noopener,noreferrer'); return true; }
  catch { return false; }
}
export async function copyText(text: string): Promise<boolean> {
  try { await navigator.clipboard.writeText(text); return true; } catch { return false; }
}
export function openUserChat(user: User): boolean {
  if (user.username && /^[A-Za-z0-9_]{5,32}$/.test(user.username)) return openTelegram(user.username);
  if (!Number.isSafeInteger(user.tg_id) || user.tg_id <= 0) return false;
  try { window.location.assign(`tg://user?id=${user.tg_id}`); return true; } catch { return false; }
}
export async function pasteText(): Promise<string | null> {
  const read = (start: (done: (value: string | null) => void) => void) => new Promise<string | null>(resolve => {
    let settled = false;
    const done = (value: string | null) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      resolve(typeof value === 'string' && value.trim() ? value : null);
    };
    // Some embedded browsers leave clipboard reads pending indefinitely.
    // A manual paste stays available even when permission prompts never finish.
    const timer = setTimeout(() => done(null), 1200);
    try { start(done); } catch { done(null); }
  });
  // Launching from the bot menu does not permit Telegram readTextFromClipboard.
  // Use it only if Telegram explicitly passed the attachment-menu launch context.
  const app = webApp();
  const attachmentLaunch = app && new URLSearchParams(app.initData).has('receiver');
  if (attachmentLaunch && supports('6.4') && app.readTextFromClipboard) {
    return read(done => app.readTextFromClipboard!(done));
  }
  return read(done => {
    navigator.clipboard.readText().then(done, () => done(null));
  });
}
export async function requestWriteAccess(): Promise<boolean | null> {
  const app = webApp(); if (!supports('6.9') || !app?.requestWriteAccess) return null;
  return new Promise(resolve => {
    const timer = setTimeout(() => resolve(null), 30000);
    try { app.requestWriteAccess!(allowed => { clearTimeout(timer); resolve(allowed); }); } catch { clearTimeout(timer); resolve(null); }
  });
}
export function useMainButton(text: string, active: boolean, busy: boolean, onClick: () => void): boolean {
  const theme = useTheme(state => state.theme);
  const callback = useRef(onClick); callback.current = onClick;
  const [failed, setFailed] = useState(false);
  const buttonCandidate = webApp()?.MainButton;
  const methods: (keyof TelegramButton)[] = ['setParams', 'onClick', 'offClick', 'hide', 'enable', 'disable', 'showProgress', 'hideProgress'];
  const native = supports('6.1') && Boolean(buttonCandidate) && methods.every(method => typeof buttonCandidate?.[method] === 'function') && !failed;
  useEffect(() => {
    const button = webApp()?.MainButton; if (!native || !button) return;
    const listener = () => callback.current();
    try { button.onClick(listener); } catch { setFailed(true); return; }
    return () => { try { button.offClick(listener); button.hideProgress(); button.hide(); } catch { /* HTML fallback remains available. */ } };
  }, [native]);
  useEffect(() => {
    const button = webApp()?.MainButton; if (!native || !button) return;
    try {
      button.setParams({ text, color: themeColors[theme].button, text_color: '#FFFFFF', is_active: active && !busy, is_visible: true });
      if (busy) button.showProgress(); else { button.hideProgress(); active ? button.enable() : button.disable(); }
    } catch { setFailed(true); }
  }, [native, text, active, busy, theme]);
  return native;
}
export function useBackButton(onBack: (() => void) | null): void {
  const callback = useRef(onBack); callback.current = onBack;
  const enabled = Boolean(onBack) && supports('6.1');
  useEffect(() => {
    const button = webApp()?.BackButton; if (!button) return;
    if (!enabled) { if (inTelegram()) button.hide(); return; }
    const listener = () => callback.current?.();
    button.show(); button.onClick(listener);
    return () => { button.offClick(listener); button.hide(); };
  }, [enabled]);
}
export function closingConfirmation(enabled: boolean): void {
  if (!supports('6.2')) return;
  try { enabled ? webApp()?.enableClosingConfirmation?.() : webApp()?.disableClosingConfirmation?.(); } catch { /* Optional. */ }
}
