import { describe, expect, it } from 'vitest';
import { extractProductUrl, parseShareText } from './product-share';

describe('Chinese product share text', () => {
  it('extracts the short product URL shown in an Xianyu share message', () => {
    expect(extractProductUrl('【闲鱼】 https://m.tb.cn/h.jbKw11?tk=WrDQTsVdTS1 CZ007 「快来捡漏【转让华为matexs2 原装包装盒】」\n点击链接直接打开'))
      .toBe('https://m.tb.cn/h.jbKw11?tk=WrDQTsVdTS1');
  });
  it('keeps full direct URLs, including Unicode paths and significant punctuation', () => {
    expect(extractProductUrl(' https://shop.example/商品(蓝色)?id=42&sku=7 ')).toBe('https://shop.example/商品(蓝色)?id=42&sku=7');
  });
  it.each([
    ['Открой https://detail.1688.com/offer/123.html.', 'https://detail.1688.com/offer/123.html'],
    ['« https://item.taobao.com/item.htm?id=123 »', 'https://item.taobao.com/item.htm?id=123'],
    ['https://m.tb.cn/abc\n点击链接 https://m.tb.cn/abc', 'https://m.tb.cn/abc'],
  ])('extracts an unambiguous URL: %s', (input, expected) => expect(extractProductUrl(input)).toBe(expected));
  it.each(['复制口令打开应用', 'javascript:alert(1)', 'https://user:pass@shop.example/item', 'https://a.example/x https://b.example/y', 'x'.repeat(10001)])
    ('does not select an unsafe, missing or ambiguous link: %s', input => expect(extractProductUrl(input)).toBeNull());
});

describe('smart share parsing', () => {
  it('adds a scheme to a scheme-less store short link copied from the app', () => {
    expect(parseShareText('闲鱼 m.tb.cn/h.jbKw11?tk=abc123 快来捡漏')).toEqual({ url: 'https://m.tb.cn/h.jbKw11?tk=abc123', platform: 'goofish' });
  });

  it('detects Poizon / Dewu from the dw4.co share domain', () => {
    expect(parseShareText('得物 https://dw4.co/t/A/1a2b3c 『Nike Dunk Low』')).toEqual({ url: 'https://dw4.co/t/A/1a2b3c', platform: 'poizon' });
  });

  it('detects the store from the Chinese name when the host is ambiguous', () => {
    expect(parseShareText('【淘宝】https://m.tb.cn/h.abc?tk=1 「运动鞋」')?.platform).toBe('taobao');
    expect(parseShareText('【闲鱼】https://m.tb.cn/h.abc?tk=1 「运动鞋」')?.platform).toBe('goofish');
  });

  it('keeps the host platform when short links are not ambiguous', () => {
    expect(parseShareText('https://detail.1688.com/offer/1.html')?.platform).toBe('ali1688');
    expect(parseShareText('https://item.taobao.com/item.htm?id=1')?.platform).toBe('taobao');
    expect(parseShareText('https://www.goofish.com/item?id=1')?.platform).toBe('goofish');
  });

  it('ignores scheme-less lookalike hosts and unrelated apps', () => {
    expect(parseShareText('инструкция eviltaobao.com/item')).toBeNull();
    expect(parseShareText('email name@m.tb.cn')).toBeNull();
    expect(parseShareText('просто текст без ссылки')).toBeNull();
  });

  it('does not guess when the share text contains two different stores', () => {
    expect(parseShareText('https://m.tb.cn/a https://detail.1688.com/offer/1.html')).toBeNull();
  });
});
