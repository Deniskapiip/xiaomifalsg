// Ambient SDK types use a different basename from telegram.ts.
interface TelegramButton {
  setParams(params: { text?: string; color?: string; text_color?: string; is_active?: boolean; is_visible?: boolean }): void;
  show(): void; hide(): void; enable(): void; disable(): void;
  onClick(callback: () => void): void; offClick(callback: () => void): void;
  showProgress(leaveActive?: boolean): void; hideProgress(): void;
}
interface TelegramBackButton { show(): void; hide(): void; onClick(callback: () => void): void; offClick(callback: () => void): void }
interface TelegramCloudStorage {
  getItem(key: string, callback: (error: string | null, value?: string) => void): void;
  setItem(key: string, value: string, callback?: (error: string | null, stored?: boolean) => void): void;
}
interface TelegramHapticFeedback {
  impactOccurred(style: 'light' | 'medium' | 'heavy' | 'rigid' | 'soft'): void;
  notificationOccurred(type: 'error' | 'success' | 'warning'): void;
  selectionChanged(): void;
}
interface TelegramPopupButton { id?: string; type?: 'default' | 'ok' | 'close' | 'cancel' | 'destructive'; text?: string }
interface TelegramPopupParams { title?: string; message: string; buttons?: TelegramPopupButton[] }
type TelegramHomeScreenStatus = 'unsupported' | 'unknown' | 'added' | 'missed';
interface TelegramWebApp {
  initData: string; version: string; platform: string;
  isVersionAtLeast(version: string): boolean;
  ready(): void; expand(): void;
  setHeaderColor(color: string): void; setBackgroundColor(color: string): void; setBottomBarColor?(color: string): void;
  disableVerticalSwipes?(): void; enableClosingConfirmation?(): void; disableClosingConfirmation?(): void;
  MainButton: TelegramButton; BackButton: TelegramBackButton;
  HapticFeedback?: TelegramHapticFeedback;
  CloudStorage?: TelegramCloudStorage;
  openLink(url: string): void; openTelegramLink(url: string): void;
  requestWriteAccess?(callback: (allowed: boolean) => void): void;
  readTextFromClipboard?(callback: (text: string | null) => void): void;
  safeAreaInset?: { top: number; bottom: number; left: number; right: number };
  contentSafeAreaInset?: { top: number; bottom: number; left: number; right: number };
  onEvent(event: string, callback: () => void): void; offEvent(event: string, callback: () => void): void;
  showAlert?(message: string, callback?: () => void): void;
  showConfirm?(message: string, callback?: (confirmed: boolean) => void): void;
  showPopup?(params: TelegramPopupParams, callback?: (buttonId: string) => void): void;
  addToHomeScreen?(): void;
  checkHomeScreenStatus?(callback: (status: TelegramHomeScreenStatus) => void): void;
}
interface Window { Telegram?: { WebApp?: TelegramWebApp } }
