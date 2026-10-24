import { useEffect, useState } from 'react';
import { platformFromUrl, PLATFORM_MONOGRAM, type SharePlatform } from '../lib/platforms';

const VALID: SharePlatform[] = ['poizon', 'taobao', 'tmall', 'ali1688', 'goofish', 'pinduoduo', 'unknown'];

/**
 * Brand badge for a shop. Prefers the official logo from /platforms/<key>.svg
 * (falls back to .png, then to a colored monogram) so the interface can switch
 * from letters to real logos without changing any layout.
 */
export function PlatformMark({ link, platform, size = 'md', label }: {
  link?: string; platform?: string; size?: 'sm' | 'md'; label?: string;
}) {
  const detected = (platform ?? (link ? platformFromUrl(link) : 'unknown'));
  const key: SharePlatform = (VALID as string[]).includes(detected) ? detected as SharePlatform : 'unknown';
  const [attempt, setAttempt] = useState(0);
  useEffect(() => setAttempt(0), [key]);
  const sources = [`/platforms/${key}.svg`, `/platforms/${key}.png`];
  const showLogo = attempt < sources.length;
  return (
    <span className={`platform-mark platform-mark--${key} platform-mark--${size} ${showLogo ? 'platform-mark--logo' : ''}`}
      aria-hidden="true" title={key === 'unknown' ? 'Площадка не определена' : undefined}>
      {showLogo
        ? <img src={sources[attempt]} alt="" loading="lazy" decoding="async" onError={() => setAttempt(value => value + 1)} />
        : (label ?? PLATFORM_MONOGRAM[key])}
    </span>
  );
}
