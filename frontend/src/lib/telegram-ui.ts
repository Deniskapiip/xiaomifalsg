import { haptic, inTelegram, supports } from './telegram';

const TAP_SELECTOR = 'button, [role="button"], [role="radio"], [role="tab"], .nav-item, .segmented button, summary';
const SKIP_SELECTOR = 'input, textarea, select, [contenteditable="true"], [data-no-haptic]';
let installed = false;
let lastTap = 0;

/**
 * One delegated listener gives every existing button, tab and card the same
 * light haptic feedback without touching individual components or styles.
 * Explicit success / error haptics stay where they already are.
 */
export function installTapHaptics(): () => void {
  if (installed || typeof document === 'undefined') return () => {};
  installed = true;
  const onPointerDown = (event: Event) => {
    if (!inTelegram() || !supports('6.1')) return;
    const target = event.target;
    if (!(target instanceof Element)) return;
    const control = target.closest(TAP_SELECTOR);
    if (!control || control.hasAttribute('disabled') || control.getAttribute('aria-disabled') === 'true') return;
    if (target.closest(SKIP_SELECTOR)) return;
    const now = Date.now();
    // Telegram itself animates presses; one impact per gesture is enough.
    if (now - lastTap < 60) return;
    lastTap = now;
    haptic('tap');
  };
  document.addEventListener('pointerdown', onPointerDown, { capture: true, passive: true });
  return () => {
    installed = false;
    document.removeEventListener('pointerdown', onPointerDown, { capture: true });
  };
}
