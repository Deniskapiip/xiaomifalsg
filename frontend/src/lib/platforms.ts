export type SharePlatform = 'poizon' | 'taobao' | 'tmall' | 'ali1688' | 'goofish' | 'pinduoduo' | 'unknown';

const GROUPS: [SharePlatform, string[]][] = [
  ['poizon', ['poizon.com', 'poizon.cn', 'dewu.com', 'dewu.cn', 'dw4.co', 'dw4.cn']],
  ['tmall', ['tmall.com', 'tmall.hk']],
  ['taobao', ['taobao.com', 'tb.cn']],
  ['ali1688', ['1688.com']],
  ['goofish', ['goofish.com', 'goofish.cn', 'xianyu.com', 'idlefish.com']],
  ['pinduoduo', ['pinduoduo.com', 'yangkeduo.com', 'pinduoduo.cn']],
];

const NAMES: Record<SharePlatform, string> = {
  poizon: 'Poizon / Dewu',
  taobao: 'Taobao',
  tmall: 'Tmall',
  ali1688: '1688',
  goofish: 'Xianyu / Goofish',
  pinduoduo: 'Pinduoduo',
  unknown: 'Другая площадка',
};

/**
 * Platform for a full http(s) link. Never trusts a suffix lookalike domain.
 * `m.tb.cn` is the short host of Xianyu/Goofish share links: the owner confirmed
 * that these short links belong to Goofish, while e.tb.cn/tb.cn stay Taobao.
 */
export function platformFromUrl(link: string): SharePlatform {
  let host: string;
  try { host = new URL(link).hostname.toLowerCase().replace(/\.$/, ''); } catch { return 'unknown'; }
  // Xianyu historically lives on the same Taobao short-link hosts.
  if (host === '2.taobao.com' || host === 'm.tb.cn') return 'goofish';
  for (const [platform, domains] of GROUPS) {
    if (domains.some(domain => host === domain || host.endsWith('.' + domain))) return platform;
  }
  return 'unknown';
}

/** Chinese share text often names the store even when the short link host is shared. */
export function platformFromShareText(text: string): SharePlatform | null {
  if (/得物|毒|dewu|poizon/i.test(text)) return 'poizon';
  if (/闲鱼|咸鱼|goofish|xianyu|idlefish/i.test(text)) return 'goofish';
  if (/拼多多|pinduoduo|yangkeduo/i.test(text)) return 'pinduoduo';
  if (/天猫|tmall/i.test(text)) return 'tmall';
  if (/1688|阿里巴巴/.test(text)) return 'ali1688';
  if (/淘宝|taobao|淘口令/.test(text)) return 'taobao';
  return null;
}

export function platformName(platform: SharePlatform): string { return NAMES[platform]; }
export function isKnownPlatform(platform: SharePlatform): boolean { return platform !== 'unknown'; }

/** Short monogram for the colored platform badge. */
export const PLATFORM_MONOGRAM: Record<SharePlatform, string> = {
  poizon: '得', taobao: '淘', tmall: '天', ali1688: '16', goofish: '闲', pinduoduo: '拼', unknown: '?',
};
