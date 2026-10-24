import { describe, expect, it } from 'vitest';
import type { SettingsInput } from '../api/admin-types';
import type { StatusDefinition } from '../api/types';
import { deliveryAmountValid, statusRequiresConfirmation, validateSettings, validateTariff, type TariffFields } from './admin-validation';

const settings: SettingsInput = { rate_cny_rub: '13.5', commission_percent: '6.5', commission_min_rub: '650' };
const tariff: TariffFields = { name: 'Тариф', price_per_kg: '1800', price_on_request: false, price_currency: 'rub', insurance_available: false, eta_text: '', description: '', is_active: true, sort_order: '0' };
const keys = ['processing', 'purchased', 'to_cn_warehouse', 'at_cn_warehouse', 'awaiting_delivery_payment', 'to_cn_customs', 'cn_customs', 'to_ru_customs', 'ru_customs', 'to_recipient', 'delivered', 'cancelled'];
const statuses: StatusDefinition[] = keys.map((key, order) => ({ key, order, name: key, icon: '', stage: key === 'cancelled' ? null : order === 0 ? 1 : order === 1 ? 2 : order <= 4 ? 3 : 4, terminal: ['delivered', 'cancelled'].includes(key) }));

describe('owner settings validation', () => {
  it('normalizes commas and whitespace while keeping money as exact strings', () => {
    expect(validateSettings({ rate_cny_rub: ' 12,3456 ', commission_percent: ' 6,50 ', commission_min_rub: ' 650 ' })).toEqual({ errors: {}, input: { rate_cny_rub: '12.3456', commission_percent: '6.5', commission_min_rub: '650' } });
  });

  it('accepts the maximum rate and commission minimum without rounding them', () => {
    const fields = { rate_cny_rub: '99999999.9999', commission_percent: '100', commission_min_rub: '999999999999999' };
    expect(validateSettings(fields)).toEqual({ errors: {}, input: fields });
    expect(validateSettings({ ...settings, rate_cny_rub: '0.0001', commission_percent: '0', commission_min_rub: '0' }).input).toEqual({ rate_cny_rub: '0.0001', commission_percent: '0', commission_min_rub: '0' });
  });

  it.each([
    ['rate_cny_rub', '0'], ['rate_cny_rub', '100000000'], ['rate_cny_rub', '0.00001'], ['rate_cny_rub', '13.12345'],
    ['commission_percent', '-1'], ['commission_percent', '100.01'], ['commission_percent', '6.555'],
    ['commission_min_rub', '1000000000000000'], ['commission_min_rub', '650.0'], ['commission_min_rub', '0650'],
  ] as const)('rejects an out-of-range or imprecise %s value: %s', (field, value) => {
    const result = validateSettings({ ...settings, [field]: value });
    expect(result.input).toBeNull(); expect(result.errors).toHaveProperty(field);
  });
});

describe('tariff validation', () => {
  it('treats a zero or empty price as «цена по запросу» for any tariff', () => {
    const inactive = validateTariff({ ...tariff, is_active: false, price_per_kg: '0' });
    expect(inactive.input?.price_per_kg).toBe('0');
    expect(inactive.input?.price_on_request).toBe(true);
    const active = validateTariff({ ...tariff, price_per_kg: '0' });
    expect(active.input?.price_on_request).toBe(true);
    expect(validateTariff({ ...tariff, price_per_kg: '0.01' }).input?.price_per_kg).toBe('0.01');
  });

  it('normalizes decimal input and accepts the maximum price and sort order', () => {
    expect(validateTariff({ ...tariff, name: ' Тариф ', price_per_kg: '9999999999,99', sort_order: ' 10000 ', eta_text: ' Уточняйте ', description: ' Описание ' })).toEqual({ errors: {}, input: { name: 'Тариф', price_per_kg: '9999999999.99', price_on_request: false, price_currency: 'rub', insurance_available: false, sort_order: 10000, eta_text: 'Уточняйте', description: 'Описание', is_active: true } });
  });

  it('accepts a yuan tariff and carries the insurance flag', () => {
    const result = validateTariff({ ...tariff, price_per_kg: '100', price_currency: 'cny', insurance_available: true });
    expect(result.errors).toEqual({});
    expect(result.input).toMatchObject({ price_per_kg: '100', price_currency: 'cny', insurance_available: true });
  });

  it('restricts the currency to rub or cny', () => {
    const invalid = validateTariff({ ...tariff, price_currency: 'usd' });
    expect(invalid.input).toBeNull();
    expect(invalid.errors).toHaveProperty('price_currency');
    expect(validateTariff({ ...tariff, price_currency: 'cny' }).errors).toEqual({});
  });

  it('allows an active tariff with the price on request flag', () => {
    const result = validateTariff({ ...tariff, price_per_kg: '', price_on_request: true });
    expect(result.errors).toEqual({});
    expect(result.input?.price_on_request).toBe(true);
    expect(result.input?.price_per_kg).toBe('0');
  });

  it.each(['', '0', '0.00', '0,00'])('turns an empty or zero price into «цена по запросу»: %s', (price_per_kg) => {
    const result = validateTariff({ ...tariff, price_per_kg });
    expect(result.errors).toEqual({});
    expect(result.input?.price_on_request).toBe(true);
    expect(result.input?.price_per_kg).toBe('0');
  });

  it.each(['10000000000', '1.001', '-1', '1e3'])('rejects an invalid tariff price: %s', (price_per_kg) => {
    expect(validateTariff({ ...tariff, price_per_kg }).input).toBeNull();
  });

  it.each(['-1', '10001', '1.5', '1e3', ''])('rejects an invalid sort order: %s', (sort_order) => {
    expect(validateTariff({ ...tariff, sort_order }).errors).toHaveProperty('sort_order');
  });

  it('enforces the backend name, delivery-text and description limits', () => {
    expect(validateTariff({ ...tariff, name: 'a'.repeat(100), eta_text: 'b'.repeat(200), description: 'c'.repeat(1000) }).errors).toEqual({});
    const invalid = validateTariff({ ...tariff, name: 'a'.repeat(101), eta_text: 'b'.repeat(201), description: 'c'.repeat(1001) });
    expect(Object.keys(invalid.errors).sort()).toEqual(['description', 'eta_text', 'name']);
    expect(validateTariff({ ...tariff, name: '   ' }).input).toBeNull();
  });
});

describe('admin status changes', () => {
  it('requires confirmation for a rollback within the same delivery stage', () => {
    expect(statusRequiresConfirmation('cn_customs', 'to_cn_customs', [...statuses].reverse())).toBe(true);
    expect(statusRequiresConfirmation('at_cn_warehouse', 'to_cn_warehouse', statuses)).toBe(true);
    expect(statusRequiresConfirmation('delivered', 'to_recipient', statuses)).toBe(true);
  });

  it('requires cancellation confirmation and follows the backend rule when restoring a cancelled order', () => {
    expect(statusRequiresConfirmation('processing', 'cancelled', statuses)).toBe(true);
    expect(statusRequiresConfirmation('cancelled', 'cancelled', statuses)).toBe(true);
    expect(statusRequiresConfirmation('cancelled', 'processing', statuses)).toBe(false);
  });

  it('allows forward progress and repeating the delivery-payment status without rollback confirmation', () => {
    expect(statusRequiresConfirmation('processing', 'delivered', statuses)).toBe(false);
    expect(statusRequiresConfirmation('awaiting_delivery_payment', 'awaiting_delivery_payment', statuses)).toBe(false);
  });

  it('accepts positive whole delivery amounts up to the backend 15-digit limit', () => {
    expect(deliveryAmountValid('1')).toBe(true);
    expect(deliveryAmountValid(' 4140 ')).toBe(true);
    expect(deliveryAmountValid('999999999999999')).toBe(true);
  });

  it.each(['0', '01', '-1', '4140.00', '1 800', '1e3', '1000000000000000', ''])('rejects an invalid final delivery amount: %s', (amount) => {
    expect(deliveryAmountValid(amount)).toBe(false);
  });
});
