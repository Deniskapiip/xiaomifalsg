import { safeHttpUrl } from './validation';
import { platformFromShareText, platformFromUrl, type SharePlatform } from './platforms';

export interface ShareLink { url: string; platform: SharePlatform }

const DOMAIN = String.raw`(?:[a-z0-9-]+\.)*(?:tb\.cn|taobao\.com|tmall\.com|tmall\.hk|1688\.com|goofish\.com|goofish\.cn|xianyu\.com|idlefish\.com|dewu\.com|dewu\.cn|dw4\.co|dw4\.cn|poizon\.com|poizon\.cn)`;
// No look-behind: older iOS WebKit in Telegram would fail to parse the module.
const SCHEMELESS = new RegExp(String.raw`(?:^|[^a-z0-9@._/-])(${DOMAIN}(?:\/[^\s<>"'「」【】《》“”。，；！、）)]*)?)`, 'gi');
const TRAILING_PUNCTUATION = /[),.;\]}）】，。；！、]+$/;

/** Adds https:// to a well-known store link copied without a scheme. */
function safeStoreUrl(candidate: string): string | null {
  const trimmed = candidate.replace(TRAILING_PUNCTUATION, '');
  if (!trimmed) return null;
  const direct = safeHttpUrl(trimmed);
  if (direct) return direct;
  const withScheme = safeHttpUrl('https://' + trimmed.replace(/^\/+/, ''));
  if (!withScheme) return null;
  return platformFromUrl(withScheme) === 'unknown' ? null : withScheme;
}

export function parseShareText(value: string): ShareLink | null {
  if (value.length > 10000) return null;
  const direct = safeHttpUrl(value);
  if (direct) return { url: direct, platform: platformFromUrl(direct) };
  const found = new Set<string>();
  for (const match of value.matchAll(/https?:\/\/[^\s<>"'「」【】《》“”。，；！]+/gi)) {
    const candidate = match[0].replace(TRAILING_PUNCTUATION, '');
    const safe = safeHttpUrl(candidate);
    if (safe) found.add(safe);
  }
  if (found.size === 0) {
    // Chinese apps sometimes copy only the short host, for example m.tb.cn/h.abc.
    for (const match of value.matchAll(SCHEMELESS)) {
      const safe = safeStoreUrl(match[1]);
      if (safe) found.add(safe);
    }
  }
  if (found.size !== 1) return null;
  const url = [...found][0];
  const byHost = platformFromUrl(url);
  const hinted = platformFromShareText(value);
  // Short tb.cn hosts are shared by Taobao, Tmall and Xianyu: the Chinese text
  // decides, while m.tb.cn without a hint defaults to Goofish (owner's rule).
  const ambiguousHost = /(^|\.)tb\.cn$/i.test(new URL(url).hostname);
  const platform = ambiguousHost && hinted ? hinted : byHost;
  return { url, platform };
}

/** Read shared text without requesting the store or inventing product data. */
export function extractProductUrl(value: string): string | null {
  return parseShareText(value)?.url ?? null;
}
