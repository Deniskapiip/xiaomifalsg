import { describe, expect, it } from 'vitest';
import {
  boxesValid, createDraftItem, decimalValid, firstStepErrors, itemErrors, itemsErrors,
  normalizeDecimal, normalizeTracking, platformLabel, quantityValid, safeHttpUrl, trackingValid,
  type DraftFields, type DraftItem,
} from './validation';

const item: DraftItem = createDraftItem({ link: 'https://shop.example/item/42', price_cny: '300', quantity: '1' });
const validDraft: DraftFields = { items: [item], tariff_id: 1, weight_kg: '2.3', boxes: '1',
  insurance_enabled: false, packing_enabled: false, photo_report_enabled: false };

describe('order input validation', () => {
  it('accepts decimal comma and preserves decimal digits as strings', () => {
    expect(normalizeDecimal(' 12,345 ')).toBe('12.345');
    expect(decimalValid('0,01', '0.01', '1000', 3)).toBe(true);
    expect(decimalValid('1000', '0.01', '1000', 3)).toBe(true);
    expect(decimalValid('0.001', '0.01', '1000', 3)).toBe(false);
    expect(decimalValid('1000.001', '0.01', '1000', 3)).toBe(false);
    expect(decimalValid('13.555', '0.01', '1000000', 2)).toBe(false);
  });

  it.each(['', 'NaN', 'Infinity', '-1', '+1', '1e3', '.5', '1.', '1,2,3'])('rejects unsupported numeric input %s', (value) => {
    expect(decimalValid(value, '0.01', '1000', 3)).toBe(false);
  });

  it('accepts a valid single position and an unknown store', () => {
    expect(firstStepErrors(validDraft)).toEqual({});
    expect(platformLabel(item.link)).toEqual({ name: 'Другая площадка', known: false });
  });

  it('requires at least one position', () => {
    expect(firstStepErrors({ ...validDraft, items: [] })).toHaveProperty('items');
  });

  it('rejects more than forty positions', () => {
    const items = Array.from({ length: 41 }, () => createDraftItem({ ...item }));
    expect(firstStepErrors({ ...validDraft, items })).toHaveProperty('items');
  });

  it.each(['https://eviltaobao.com/item', 'https://taobao.com.evil.example/item', 'https://dewu.com.evil.example/item'])('does not confuse suffixes with trusted platform domains: %s', (link) => {
    expect(safeHttpUrl(link)).toBe(link);
    expect(platformLabel(link).known).toBe(false);
  });

  it.each(['https://tb.cn/abc', 'https://m.tb.cn/abc', 'https://e.tb.cn/abc', 'https://item.taobao.com/item.htm?id=1'])('recognizes Taobao full and short links: %s', (link) => {
    const expected = link.includes('m.tb.cn') ? 'Xianyu / Goofish' : 'Taobao';
    expect(platformLabel(link)).toEqual({ name: expected, known: true });
  });

  it.each([
    ['https://dw4.co/t/A/abc', 'Poizon / Dewu'],
    ['https://dewu.com/item/1', 'Poizon / Dewu'],
    ['https://detail.tmall.com/item.htm?id=1', 'Tmall'],
    ['https://detail.1688.com/offer/1.html', '1688'],
    ['https://www.goofish.com/item?id=1', 'Xianyu / Goofish'],
    ['https://mobile.yangkeduo.com/goods.html?goods_id=1', 'Pinduoduo'],
  ])('labels every supported store: %s', (link, name) => {
    expect(platformLabel(link)).toEqual({ name, known: true });
  });

  it.each(['javascript:alert(1)', 'data:text/html,hello', 'ftp://example.com/item', '//example.com/item', 'https:example.com/item', 'http:/example.com/item', 'https:///example.com/item', 'https://example.com\\@evil.example/item', 'https://user:pass@example.com/item', 'https://example.com/with space', 'https://example.com/\nitem'])('rejects an unsafe link: %s', (link) => {
    expect(safeHttpUrl(link)).toBeNull();
  });

  it('enforces quantity and text limits per position', () => {
    const limit = createDraftItem({ ...item, quantity: '999', item_title: 'a'.repeat(200), comment: 'b'.repeat(500) });
    expect(itemErrors(limit)).toEqual({});
    const invalid = createDraftItem({ ...item, quantity: '1000', item_title: 'a'.repeat(201), comment: 'b'.repeat(501), link: 'https://example.com/' + 'x'.repeat(2000) });
    expect(Object.keys(itemErrors(invalid)).sort()).toEqual(['comment', 'item_title', 'link', 'quantity']);
    expect(quantityValid('1.5')).toBe(false);
    expect(quantityValid('0')).toBe(false);
    expect(quantityValid('1')).toBe(true);
    expect(quantityValid('999')).toBe(true);
  });

  it('reports only broken positions through itemsErrors', () => {
    const broken = createDraftItem({ ...item, link: '' });
    const draft = { ...validDraft, items: [item, broken] };
    expect(Object.keys(itemsErrors(draft))).toEqual([broken.key]);
    expect(firstStepErrors(draft)).toHaveProperty(`${broken.key}.link`);
  });

  it('does not treat extra service flags as invalid input', () => {
    expect(firstStepErrors({ ...validDraft, insurance_enabled: true, packing_enabled: true, photo_report_enabled: true })).toEqual({});
  });

  it('accepts packing box counts from 1 to 99 only', () => {
    expect(boxesValid('1')).toBe(true);
    expect(boxesValid('99')).toBe(true);
    for (const boxes of ['0', '100', '01', '1.5', '', 'abc']) expect(boxesValid(boxes)).toBe(false);
    expect(firstStepErrors({ ...validDraft, boxes: '0' })).toEqual({});
  });
});

describe('tracking number validation', () => {
  it('normalizes outer and repeated spaces', () => {
    expect(normalizeTracking('  CN  123  ')).toBe('CN 123');
    expect(normalizeTracking('AB123456789CN')).toBe('AB123456789CN');
  });

  it('accepts 3..64 Latin letters, digits, spaces, dashes and underscores', () => {
    for (const value of ['AB123456789CN', 'CN 123 456', 'track_1-2', '  AB123  ', 'A1-', '1_2']) expect(trackingValid(value)).toBe(true);
  });

  it('rejects empty, too short, too long and foreign characters', () => {
    for (const value of ['', '  ', 'AB', 'A'.repeat(65), 'АБВ123', 'трек-номер', 'track#1', 'AB/123', '123\u0000']) expect(trackingValid(value)).toBe(false);
  });

  it('counts the normalized value against the length limit', () => {
    expect(trackingValid('A'.repeat(64))).toBe(true);
    expect(trackingValid('A'.repeat(62) + '  ')).toBe(true);
    expect(trackingValid('A'.repeat(65) + '  ')).toBe(false);
  });
});
