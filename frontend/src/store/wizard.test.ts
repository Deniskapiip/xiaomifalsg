import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Quote } from '../api/types';
import type { DraftFields } from '../lib/validation';

type Wizard = (typeof import('./wizard'))['useWizard'];
let wizard: Wizard;
let stored: Map<string, string>;

const fields: DraftFields = { link: 'https://tb.cn/item42', price_cny: '300,00', quantity: '1', item_title: 'Кроссовки', comment: 'Размер 42', tariff_id: 1, weight_kg: '2,300', boxes: '3',
  insurance_enabled: true, packing_enabled: false, photo_report_enabled: true };
const quote: Quote = { goods_rub: '4050', commission_rub: '650', total_rub: '4700', delivery_estimate_rub: '4140', commission_is_minimum: true,
  insurance_rub: '81', packing_rub: '0', photo_report_rub: '150', extras_total_rub: '231', total_with_extras_rub: '4931',
  rate: '13.5', commission_percent: '6.5', commission_min_rub: '650', tariff_name: 'Демо', tariff_price_per_kg: '1800' };
const input = { idempotency_key: '00000000-0000-4000-8000-000000000001', link: fields.link, price_cny: '300.00', quantity: 1, item_title: fields.item_title, comment: fields.comment, tariff_id: 1, weight_kg: '2.300', boxes: 3,
  insurance_enabled: true, packing_enabled: false, photo_report_enabled: true };
function envelope(value: unknown, savedAt = 1) { return JSON.stringify({ savedAt, value }); }

beforeEach(async () => {
  vi.resetModules();
  stored = new Map();
  vi.stubGlobal('window', {});
  vi.stubGlobal('localStorage', { getItem: (key: string) => stored.get(key) ?? null, setItem: (key: string, value: string) => { stored.set(key, value); } });
  wizard = (await import('./wizard')).useWizard;
});
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });

describe('persistent order submission state', () => {
  it('keeps one key and payload across retries and blocks edits while the outcome is unknown', async () => {
    await wizard.getState().hydrate(101);
    wizard.getState().patch(fields);
    const pending = wizard.getState().begin(quote);
    const snapshot = JSON.stringify(pending);
    wizard.getState().patch({ price_cny: '999', comment: 'Новые данные' });
    wizard.getState().go(1);
    expect(wizard.getState().begin({ ...quote, total_rub: '999999' })).toBe(pending);
    expect(JSON.stringify(wizard.getState().pending)).toBe(snapshot);
    expect(wizard.getState().step).toBe(4);
    expect(pending.input.price_cny).toBe('300.00');
    expect(pending.input.weight_kg).toBe('2.300');
    expect(pending.input.boxes).toBe(3);
    expect(pending.input.insurance_enabled).toBe(true);
    expect(pending.input.packing_enabled).toBe(false);
    expect(wizard.getState().draft.comment).toBe('Размер 42');
  });

  it('restores an uncertain submission with the same key after reopening', async () => {
    await wizard.getState().hydrate(101); wizard.getState().patch(fields);
    const pending = wizard.getState().begin(quote);
    await wizard.getState().hydrate(101);
    expect(wizard.getState().pending).toEqual(pending);
    expect(wizard.getState().step).toBe(4);
    expect(wizard.getState().draft.insurance_enabled).toBe(true);
    expect(wizard.getState().draft.photo_report_enabled).toBe(true);
  });

  it('hydrates a draft saved before extra services existed', async () => {
    stored.set('taoji_v2_101_draft', envelope({ draft: { link: fields.link, price_cny: '300', quantity: '1', item_title: '', comment: '', tariff_id: 1, weight_kg: '2.3' }, step: 3, pending: null }));
    await wizard.getState().hydrate(101);
    expect(wizard.getState().draft.insurance_enabled).toBe(false);
    expect(wizard.getState().draft.packing_enabled).toBe(false);
    expect(wizard.getState().draft.photo_report_enabled).toBe(false);
    expect(wizard.getState().draft.boxes).toBe('1');
    expect(wizard.getState().step).toBe(3);
  });

  it('drops insurance when a tariff without insurance is selected and keeps it otherwise', async () => {
    await wizard.getState().hydrate(101);
    wizard.getState().patch(fields);
    expect(wizard.getState().draft.insurance_enabled).toBe(true);
    wizard.getState().selectTariff({ id: 2, insurance_available: false });
    expect(wizard.getState().draft.tariff_id).toBe(2);
    expect(wizard.getState().draft.insurance_enabled).toBe(false);
    wizard.getState().patch({ insurance_enabled: true });
    wizard.getState().selectTariff({ id: 3, insurance_available: true });
    expect(wizard.getState().draft.tariff_id).toBe(3);
    expect(wizard.getState().draft.insurance_enabled).toBe(true);
  });

  it('only clears the draft for the matching verified user and submission key', async () => {
    await wizard.getState().hydrate(101); wizard.getState().patch(fields);
    const pending = wizard.getState().begin(quote);
    expect(wizard.getState().complete(202, pending.input.idempotency_key)).toBe(false);
    expect(wizard.getState().complete(101, 'different-key')).toBe(false);
    expect(wizard.getState().pending).toEqual(pending);
    expect(wizard.getState().complete(101, pending.input.idempotency_key)).toBe(true);
    expect(wizard.getState().pending).toBeNull(); expect(wizard.getState().draft.link).toBe(''); expect(wizard.getState().step).toBe(1);
    expect(JSON.parse(stored.get('taoji_v2_101_draft')!).value.pending).toBeNull();
  });

  it('discards late hydration for a previous account', async () => {
    const callbacks = new Map<string, (error: string | null, value?: string) => void>();
    vi.stubGlobal('window', { Telegram: { WebApp: { initData: 'signed-launch-data', isVersionAtLeast: () => true, CloudStorage: {
      getItem: (key: string, callback: (error: string | null, value?: string) => void) => { callbacks.set(key, callback); },
      setItem: (_key: string, _value: string, callback: (error: string | null, stored?: boolean) => void) => callback(null, true),
    } } } });
    const first = wizard.getState().hydrate(101); const second = wizard.getState().hydrate(202);
    callbacks.get('taoji_v2_202_draft')!(null, envelope({ draft: { ...fields, comment: 'Другой аккаунт' }, step: 2, pending: null }, 200));
    await second;
    callbacks.get('taoji_v2_101_draft')!(null, envelope({ draft: fields, step: 3, pending: null }, 100));
    await first;
    expect(wizard.getState().scope).toBe(202);
    expect(wizard.getState().draft.comment).toBe('Другой аккаунт');
    expect(wizard.getState().step).toBe(2);
  });

  it.each([
    ['string quantity', { quantity: '1' }],
    ['too large quantity', { quantity: 1000 }],
    ['zero boxes', { boxes: 0 }],
    ['too many boxes', { boxes: 100 }],
    ['overlong title', { item_title: 'a'.repeat(201) }],
    ['overlong link', { link: 'https://example.com/' + 'a'.repeat(2000) }],
    ['string tariff', { tariff_id: '1' }],
    ['non-boolean service flag', { insurance_enabled: 'yes' }],
  ])('rejects the raw malformed pending payload: %s', async (_name, invalid) => {
    stored.set('taoji_v2_101_draft', envelope({ draft: fields, step: 1, pending: { input: { ...input, ...invalid }, quote } }));
    await wizard.getState().hydrate(101);
    expect(wizard.getState().pending).toBeNull();
    wizard.getState().patch({ comment: 'Можно редактировать' });
    expect(wizard.getState().draft.comment).toBe('Можно редактировать');
  });
});
