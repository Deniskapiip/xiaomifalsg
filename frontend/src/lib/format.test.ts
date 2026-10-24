import { describe, expect, it } from 'vitest';
import { dateMsk, decimalNumber, money, productDomain, shortDateMsk } from './format';

const normalizeSpace = (value: string) => value.replace(/[\u00a0\u202f]/g, ' ');

describe('Russian exact amount and date formatting', () => {
  it('formats integer rubles above the JavaScript safe integer range exactly', () => {
    expect(normalizeSpace(money('199799999999800200'))).toBe('199 799 999 999 800 200 ₽');
    expect(normalizeSpace(money('9007199254740993'))).toBe('9 007 199 254 740 993 ₽');
  });

  it('formats fractional tariffs and four-digit rates without converting them to Number', () => {
    expect(normalizeSpace(decimalNumber('1800.00', 2))).toBe('1 800');
    expect(decimalNumber('12.3456', 4)).toBe('12,3456');
    expect(decimalNumber('2.300', 3)).toBe('2,3');
    expect(normalizeSpace(decimalNumber('9007199254740993.125', 3))).toBe('9 007 199 254 740 993,125');
  });

  it('displays timestamps in Moscow even when the runtime timezone is UTC', () => {
    expect(dateMsk('2026-10-12T12:34:00Z')).toContain('12.10.2026');
    expect(dateMsk('2026-10-12T12:34:00Z')).toContain('15:34');
    expect(dateMsk('2026-10-12T12:34:00Z')).toContain('(МСК)');
    expect(shortDateMsk('2026-10-12T23:30:00Z')).toMatch(/13\.10.*02:30.*\(МСК\)/);
  });

  it('uses a readable domain and a safe fallback for invalid links', () => {
    expect(productDomain('https://www.taobao.com/item?id=1')).toBe('taobao.com');
    expect(productDomain('invalid')).toBe('Ссылка на товар');
  });
});
