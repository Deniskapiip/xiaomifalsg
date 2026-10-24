import { platformFromUrl, PLATFORM_MONOGRAM, type SharePlatform } from '../lib/platforms';

const VALID: SharePlatform[] = ['poizon', 'taobao', 'tmall', 'ali1688', 'goofish', 'pinduoduo', 'unknown'];

/**
 * Colored brand badge for a shop: Goofish — yellow, Poizon — cyan, Taobao — orange,
 * Tmall — red, 1688 — orange-red, Pinduoduo — red. Uses only the project's CSS tokens;
 * the platform is derived from the link, never from user text alone.
 */
export function PlatformMark({ link, platform, size = 'md', label }: {
  link?: string; platform?: string; size?: 'sm' | 'md'; label?: string;
}) {
  const detected = (platform ?? (link ? platformFromUrl(link) : 'unknown'));
  const key: SharePlatform = (VALID as string[]).includes(detected) ? detected as SharePlatform : 'unknown';
  const text = label ?? PLATFORM_MONOGRAM[key];
  return (
    <span className={`platform-mark platform-mark--${key} platform-mark--${size}`} aria-hidden="true" title={key === 'unknown' ? 'Площадка не определена' : undefined}>
      {text}
    </span>
  );
}
