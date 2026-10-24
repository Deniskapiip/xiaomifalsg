import { describe, expect, it } from 'vitest';
import { platformFromShareText, platformFromUrl, platformName, type SharePlatform } from './platforms';

describe('platform recognition', () => {
  it.each<[string, SharePlatform]>([
    ['https://dw4.co/t/A/abc', 'poizon'],
    ['https://dewu.com/item/1', 'poizon'],
    ['https://m.dewu.com/item/1', 'poizon'],
    ['https://www.poizon.com/item/1', 'poizon'],
    ['https://item.taobao.com/item.htm?id=1', 'taobao'],
    ['https://m.tb.cn/h.abc', 'taobao'],
    ['https://detail.tmall.com/item.htm?id=1', 'tmall'],
    ['https://detail.1688.com/offer/1.html', 'ali1688'],
    ['https://www.goofish.com/item?id=1', 'goofish'],
    ['https://2.taobao.com/item?id=1', 'goofish'],
  ])('detects %s as %s', (link, expected) => expect(platformFromUrl(link)).toBe(expected));

  it.each(['https://eviltaobao.com/item', 'https://taobao.com.evil.example/item', 'https://dw4.co.evil.example/x', 'not a link'])('keeps lookalike or invalid hosts unknown: %s', link => {
    expect(platformFromUrl(link)).toBe('unknown');
  });

  it('reads the store name from Chinese share text', () => {
    expect(platformFromShareText('【闲鱼】 https://m.tb.cn/h.abc 「华为手机」')).toBe('goofish');
    expect(platformFromShareText('【淘宝】 https://m.tb.cn/h.abc')).toBe('taobao');
    expect(platformFromShareText('得物 App 分享 https://dw4.co/x')).toBe('poizon');
    expect(platformFromShareText('天猫精选 https://detail.tmall.com/x')).toBe('tmall');
    expect(platformFromShareText('1688 批发 https://detail.1688.com/x')).toBe('ali1688');
    expect(platformFromShareText('просто ссылка')).toBeNull();
  });

  it('has a Russian display name for every platform', () => {
    expect(platformName('poizon')).toBe('Poizon / Dewu');
    expect(platformName('goofish')).toBe('Xianyu / Goofish');
    expect(platformName('ali1688')).toBe('1688');
    expect(platformName('unknown')).toBe('Другая площадка');
  });
});
