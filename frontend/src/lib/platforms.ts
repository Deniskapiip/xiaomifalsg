export type SharePlatform = 'poizon' | 'taobao' | 'tmall' | 'ali1688' | 'goofish' | 'unknown';

const GROUPS: [SharePlatform, string[]][] = [
  ['poizon', ['poizon.com', 'poizon.cn', 'dewu.com', 'dewu.cn', 'dw4.co', 'dw4.cn']],
  ['tmall', ['tmall.com', 'tmall.hk']],
  ['taobao', ['taobao.com', 'tb.cn']],
  ['ali1688', ['1688.com']],
  ['goofish', ['goofish.com', 'goofish.cn', 'xianyu.com', 'idlefish.com']],
];

const NAMES: Record<SharePlatform, string> = {
  poizon: 'Poizon / Dewu',
  taobao: 'Taobao',
  tmall: 'Tmall',
  ali1688: '1688',
  goofish: 'Xianyu / Goofish',
  unknown: 'Другая площадка',
};

/** Platform for a full http(s) link. Never trusts a suffix lookalike domain. */
export function platformFromUrl(link: string): SharePlatform {
  let host: string;
  try { host = new URL(link).hostname.toLowerCase().replace(/\.$/, ''); } catch { return 'unknown'; }
  // Xianyu historically lives on the same Taobao short-link host.
  if (host === '2.taobao.com') return 'goofish';
  for (const [platform, domains] of GROUPS) {
    if (domains.some(domain => host === domain || host.endsWith('.' + domain))) return platform;
  }
  return 'unknown';
}

/** Chinese share text often names the store even when the short link host is shared. */
export function platformFromShareText(text: string): SharePlatform | null {
  if (/得物|毒|dewu|poizon/i.test(text)) return 'poizon';
  if (/闲鱼|咸鱼|goofish|xianyu|idlefish/i.test(text)) return 'goofish';
  if (/天猫|tmall/i.test(text)) return 'tmall';
  if (/1688|阿里巴巴/.test(text)) return 'ali1688';
  if (/淘宝|taobao|淘口令/.test(text)) return 'taobao';
  return null;
}

export function platformName(platform: SharePlatform): string { return NAMES[platform]; }
export function isKnownPlatform(platform: SharePlatform): boolean { return platform !== 'unknown'; }
