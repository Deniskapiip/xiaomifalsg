import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { OrderItemInput, Quote } from '../api/types';
import { createDraftItem, type DraftFields } from '../lib/validation';

type Wizard = (typeof import('./wizard'))['useWizard'];
let wizard: Wizard;
let stored: Map<string, string>;

const items = [
  createDraftItem({ link: 'https://tb.cn/item42', price_cny: '300,00', quantity: '1', item_title: 'Кроссовки', comment: 'Размер 42' }),
  createDraftItem({ link: 'https://detail.1688.com/offer/1.html', price_cny: '150', quantity: '2', item_title: 'Носки', comment: '' }),
];
const fields: DraftFields = { items, tariff_id: 1, weight_kg: '2,300', boxes: '3',
  insurance_enabled: true, packing_enabled: false, photo_report_enabled: true };
const quote: Quote = { goods_rub: '4050', commission_rub: '650', total_rub: '4700', delivery_estimate_rub: '4140', commission_is_minimum: true,
  insurance_rub: '81', packing_rub: '0', photo_report_rub: '150', extras_total_rub: '231', total_with_extras_rub: '4931',
  rate: '13.5', commission_percent: '6.5', commission_min_rub: '650', tariff_name: 'Демо', tariff_price_per_kg: '1800' };
const orderItems: OrderItemInput[] = items.map(item => ({ link: item.link, price_cny: item.price_cny.replace(',', '.'), quantity: Number(item.quantity), item_title: item.item_title, comment: item.comment }));
const input = { idempotency_key: '00000000-0000-4000-8000-000000000001', items: orderItems,
  link: orderItems[0].link, price_cny: orderItems[0].price_cny, quantity: orderItems[0].quantity, item_title: orderItems[0].item_title, comment: orderItems[0].comment,
  tariff_id: 1, weight_kg: '2.300', boxes: 3, insurance_enabled: true, packing_enabled: false, photo_report_enabled: true };
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
    wizard.getState().patch({ weight_kg: '9.9' });
    wizard.getState().go(1);
    expect(wizard.getState().begin({ ...quote, total_rub: '999999' })).toBe(pending);
    expect(JSON.stringify(wizard.getState().pending)).toBe(snapshot);
    expect(wizard.getState().step).toBe(4);
    expect(pending.input.items).toHaveLength(2);
    expect(pending.input.items[0]).toEqual(orderItems[0]);
    expect(pending.input.price_cny).toBe('300.00');
    expect(pending.input.quantity).toBe(1);
    expect(pending.input.weight_kg).toBe('2.300');
    expect(pending.input.boxes).toBe(3);
    expect(pending.input.insurance_enabled).toBe(true);
    expect(wizard.getState().draft.items[1].comment).toBe('');
  });

  it('restores an uncertain submission with the same key after reopening', async () => {
    await wizard.getState().hydrate(101); wizard.getState().patch(fields);
    const pending = wizard.getState().begin(quote);
    await wizard.getState().hydrate(101);
    expect(wizard.getState().pending).toEqual(pending);
    expect(wizard.getState().step).toBe(4);
    expect(wizard.getState().draft.items).toHaveLength(2);
    expect(wizard.getState().draft.items[1].quantity).toBe('2');
    expect(wizard.getState().draft.insurance_enabled).toBe(true);
  });

  it('migrates a draft saved before multi-item orders into one position', async () => {
    stored.set('taoji_v2_101_draft', envelope({ draft: { link: fields.items[0].link, price_cny: '300', quantity: '1', item_title: '', comment: '', tariff_id: 1, weight_kg: '2.3' }, step: 3, pending: null }));
    await wizard.getState().hydrate(101);
    expect(wizard.getState().draft.items).toHaveLength(1);
    expect(wizard.getState().draft.items[0].link).toBe(fields.items[0].link);
    expect(wizard.getState().draft.items[0].price_cny).toBe('300');
    expect(wizard.getState().draft.insurance_enabled).toBe(false);
    expect(wizard.getState().draft.boxes).toBe('1');
    expect(wizard.getState().step).toBe(3);
  });

  it('restores a legacy pending submission as one position', async () => {
    const legacy = { idempotency_key: input.idempotency_key, link: input.link, price_cny: input.price_cny, quantity: input.quantity, item_title: input.item_title, comment: input.comment,
      tariff_id: 1, weight_kg: '2.300', insurance_enabled: true, packing_enabled: false, photo_report_enabled: true };
    stored.set('taoji_v2_101_draft', envelope({ draft: fields, step: 1, pending: { input: legacy, quote } }));
    await wizard.getState().hydrate(101);
    expect(wizard.getState().pending?.input.items).toEqual([orderItems[0]]);
    expect(wizard.getState().draft.items).toHaveLength(1);
    expect(wizard.getState().draft.items[0].quantity).toBe('1');
    expect(wizard.getState().step).toBe(4);
  });

  it('adds, patches and removes positions while keeping at least one', async () => {
    await wizard.getState().hydrate(101);
    const first = wizard.getState().draft.items[0];
    wizard.getState().patchItem(first.key, { link: fields.items[0].link, price_cny: '300', quantity: '1' });
    const added = wizard.getState().addItem();
    expect(added).toBeTruthy();
    expect(wizard.getState().draft.items).toHaveLength(2);
    wizard.getState().patchItem(added!, { link: fields.items[1].link, price_cny: '150', quantity: '2' });
    expect(wizard.getState().draft.items[1].price_cny).toBe('150');
    wizard.getState().removeItem(first.key);
    expect(wizard.getState().draft.items).toHaveLength(1);
    expect(wizard.getState().draft.items[0].key).toBe(added);
    wizard.getState().removeItem(added!);
    expect(wizard.getState().draft.items).toHaveLength(1);
  });

  it('does not start a submission while a position is invalid', async () => {
    await wizard.getState().hydrate(101);
    wizard.getState().patch(fields);
    wizard.getState().patchItem(fields.items[1].key, { link: '' });
    expect(() => wizard.getState().begin(quote)).toThrow();
    expect(wizard.getState().pending).toBeNull();
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
    expect(wizard.getState().pending).toBeNull(); expect(wizard.getState().draft.items[0].link).toBe(''); expect(wizard.getState().step).toBe(1);
    expect(JSON.parse(stored.get('taoji_v2_101_draft')!).value.pending).toBeNull();
  });

  it('discards late hydration for a previous account', async () => {
    const callbacks = new Map<string, (error: string | null, value?: string) => void>();
    vi.stubGlobal('window', { Telegram: { WebApp: { initData: 'signed-launch-data', isVersionAtLeast: () => true, CloudStorage: {
      getItem: (key: string, callback: (error: string | null, value?: string) => void) => { callbacks.set(key, callback); },
      setItem: (_key: string, _value: string, callback: (error: string | null, stored?: boolean) => void) => callback(null, true),
    } } } });
    const first = wizard.getState().hydrate(101); const second = wizard.getState().hydrate(202);
    callbacks.get('taoji_v2_202_draft')!(null, envelope({ draft: { ...fields, items: [createDraftItem({ ...items[0], comment: 'Другой аккаунт' })] }, step: 2, pending: null }, 200));
    await second;
    callbacks.get('taoji_v2_101_draft')!(null, envelope({ draft: fields, step: 3, pending: null }, 100));
    await first;
    expect(wizard.getState().scope).toBe(202);
    expect(wizard.getState().draft.items[0].comment).toBe('Другой аккаунт');
    expect(wizard.getState().step).toBe(2);
  });

  it.each([
    ['empty items', { items: [] }],
    ['too many items', { items: Array.from({ length: 41 }, () => orderItems[0]) }],
    ['invalid item link', { items: [{ ...orderItems[0], link: 'javascript:alert(1)' }] }],
    ['string quantity', { items: [{ ...orderItems[0], quantity: '1' }] }],
    ['too large quantity', { items: [{ ...orderItems[0], quantity: 1000 }] }],
    ['zero boxes', { boxes: 0 }],
    ['too many boxes', { boxes: 100 }],
    ['overlong title', { items: [{ ...orderItems[0], item_title: 'a'.repeat(201) }] }],
    ['string tariff', { tariff_id: '1' }],
    ['non-boolean service flag', { insurance_enabled: 'yes' }],
  ])('rejects the raw malformed pending payload: %s', async (_name, invalid) => {
    stored.set('taoji_v2_101_draft', envelope({ draft: fields, step: 1, pending: { input: { ...input, ...invalid }, quote } }));
    await wizard.getState().hydrate(101);
    expect(wizard.getState().pending).toBeNull();
    wizard.getState().patch({ weight_kg: '2.5' });
    expect(wizard.getState().draft.weight_kg).toBe('2.5');
  });
});
