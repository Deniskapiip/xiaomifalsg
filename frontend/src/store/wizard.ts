import { create } from 'zustand';
import type { OrderInput, OrderItemInput, Quote } from '../api/types';
import type { DraftFields, DraftItem } from '../lib/validation';
import { boxesValid, createDraftItem, decimalValid, firstStepErrors, MAX_ITEMS, newItemKey, normalizeDecimal, quantityValid, safeHttpUrl } from '../lib/validation';
import { readStored, userStorageKey, writeStored } from '../lib/storage';

export type WizardStep = 1 | 2 | 3 | 4;
export interface PendingSubmission { input: OrderInput; quote: Quote }
interface SavedDraft { draft: DraftFields; step: WizardStep; pending: PendingSubmission | null }
const emptyDraft = (): DraftFields => ({ items: [createDraftItem()], tariff_id: null, weight_kg: '', boxes: '1',
  insurance_enabled: false, packing_enabled: false, photo_report_enabled: false });
const ITEM_MAX = { link: 2000, price_cny: 30, quantity: 3, item_title: 200, comment: 500 } as const;
let hydrationGeneration = 0;

function validQuote(value: unknown): value is Quote {
  if (!value || typeof value !== 'object') return false;
  const row = value as Record<string, unknown>;
  return ['goods_rub', 'commission_rub', 'total_rub', 'delivery_estimate_rub', 'commission_min_rub'].every(key => typeof row[key] === 'string' && /^\d+$/.test(row[key] as string))
    && ['rate', 'commission_percent', 'tariff_price_per_kg'].every(key => typeof row[key] === 'string' && /^\d+(?:\.\d+)?$/.test(row[key] as string))
    && typeof row.tariff_name === 'string' && typeof row.commission_is_minimum === 'boolean';
}
function savedItem(value: unknown): DraftItem {
  const item = createDraftItem();
  if (!value || typeof value !== 'object') return item;
  const row = value as Record<string, unknown>;
  for (const key of Object.keys(ITEM_MAX) as (keyof typeof ITEM_MAX)[]) if (typeof row[key] === 'string') item[key] = (row[key] as string).slice(0, ITEM_MAX[key]);
  if (typeof row.key === 'string' && /^[A-Za-z0-9_-]{1,64}$/.test(row.key)) item.key = row.key;
  return item;
}
function uniqueItems(items: DraftItem[]): DraftItem[] {
  const seen = new Set<string>();
  return items.map(item => {
    const key = seen.has(item.key) ? newItemKey() : item.key;
    seen.add(key);
    return key === item.key ? item : { ...item, key };
  });
}
function savedItems(value: unknown): DraftItem[] {
  if (!Array.isArray(value)) return [];
  return uniqueItems(value.slice(0, MAX_ITEMS).map(savedItem));
}
function savedFields(value: unknown): DraftFields {
  const result = emptyDraft(); if (!value || typeof value !== 'object') return result;
  const row = value as Record<string, unknown>;
  if (typeof row.weight_kg === 'string') result.weight_kg = row.weight_kg.slice(0, 30);
  if (typeof row.boxes === 'string') result.boxes = row.boxes.slice(0, 2);
  if (!boxesValid(result.boxes)) result.boxes = '1';
  if (typeof row.tariff_id === 'number' && Number.isSafeInteger(row.tariff_id) && row.tariff_id > 0) result.tariff_id = row.tariff_id;
  for (const key of ['insurance_enabled', 'packing_enabled', 'photo_report_enabled'] as const) if (row[key] === true) result[key] = true;
  const items = savedItems(row.items);
  if (items.length) result.items = items;
  else if (['link', 'price_cny', 'quantity', 'item_title', 'comment'].some(key => typeof row[key] === 'string')) result.items = [savedItem(row)];
  return result;
}
/** Валидная позиция из сохранённой заявки в нормализованном виде. */
function pendingItem(value: unknown): OrderItemInput | null {
  if (!value || typeof value !== 'object') return null;
  const row = value as Record<string, unknown>;
  if (typeof row.link !== 'string' || !safeHttpUrl(row.link)) return null;
  if (typeof row.price_cny !== 'string' || !decimalValid(row.price_cny, '0.01', '1000000', 2)) return null;
  if (!Number.isSafeInteger(row.quantity) || (row.quantity as number) < 1 || (row.quantity as number) > 999) return null;
  if (typeof row.item_title !== 'string' || row.item_title.length > 200) return null;
  if (typeof row.comment !== 'string' || row.comment.length > 500) return null;
  return { link: row.link, price_cny: normalizeDecimal(row.price_cny), quantity: row.quantity as number, item_title: row.item_title, comment: row.comment };
}
function pendingItems(input: Record<string, unknown>): OrderItemInput[] | null {
  if (input.items === undefined) {
    // Заявки, сохранённые до мультизаказа, содержат одну позицию в legacy-полях.
    const legacy = pendingItem({ link: input.link, price_cny: input.price_cny, quantity: input.quantity, item_title: input.item_title, comment: input.comment });
    return legacy ? [legacy] : null;
  }
  if (!Array.isArray(input.items) || input.items.length < 1 || input.items.length > MAX_ITEMS) return null;
  const items: OrderItemInput[] = [];
  for (const value of input.items) { const item = pendingItem(value); if (!item) return null; items.push(item); }
  return items;
}
function normalizedPending(value: unknown): PendingSubmission | null {
  if (!value || typeof value !== 'object') return null;
  const pending = value as { input?: unknown; quote?: unknown };
  if (!pending.input || typeof pending.input !== 'object') return null;
  const input = pending.input as Record<string, unknown>;
  if (typeof input.idempotency_key !== 'string' || !/^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(input.idempotency_key)) return null;
  if (!Number.isSafeInteger(input.tariff_id) || (input.tariff_id as number) <= 0) return null;
  if (typeof input.weight_kg !== 'string' || !decimalValid(input.weight_kg, '0.01', '1000', 3)) return null;
  const boxes = input.boxes === undefined ? 1 : input.boxes;
  if (!Number.isSafeInteger(boxes) || (boxes as number) < 1 || (boxes as number) > 99) return null;
  if ((['insurance_enabled', 'packing_enabled', 'photo_report_enabled'] as const).some(key => input[key] !== undefined && typeof input[key] !== 'boolean')) return null;
  const items = pendingItems(input); if (!items) return null;
  const first = items[0];
  const normalized: OrderInput = { idempotency_key: input.idempotency_key, items,
    link: first.link, price_cny: first.price_cny, quantity: first.quantity, item_title: first.item_title, comment: first.comment,
    tariff_id: input.tariff_id as number, weight_kg: normalizeDecimal(input.weight_kg), boxes: boxes as number,
    insurance_enabled: input.insurance_enabled === true, packing_enabled: input.packing_enabled === true, photo_report_enabled: input.photo_report_enabled === true };
  const draft = savedFields({ ...normalized, boxes: String(normalized.boxes), items: normalized.items.map(item => ({ ...item, quantity: String(item.quantity), key: newItemKey() })) });
  if (Object.keys(firstStepErrors(draft)).length || !validQuote(pending.quote)) return null;
  return { input: normalized, quote: pending.quote };
}
interface WizardState {
  scope: number | null; hydrated: boolean; draft: DraftFields; step: WizardStep; pending: PendingSubmission | null;
  hydrate: (tgId: number) => Promise<void>; patch: (values: Partial<DraftFields>) => void;
  addItem: () => string | null; removeItem: (key: string) => void; patchItem: (key: string, values: Partial<DraftItem>) => void;
  selectTariff: (tariff: { id: number; insurance_available: boolean }) => void; go: (step: WizardStep) => void;
  begin: (quote: Quote) => PendingSubmission; complete: (tgId: number, key: string) => boolean; release: (tgId: number, key: string) => void;
}
function persist(state: WizardState): void {
  if (state.scope === null || !state.hydrated) return;
  writeStored<SavedDraft>(userStorageKey(state.scope, 'draft'), { draft: state.draft, step: state.step, pending: state.pending });
}
export const useWizard = create<WizardState>((set, get) => ({
  scope: null, hydrated: false, draft: emptyDraft(), step: 1, pending: null,
  hydrate: async tgId => {
    const generation = ++hydrationGeneration;
    set({ scope: tgId, hydrated: false, draft: emptyDraft(), step: 1, pending: null });
    const stored = await readStored<SavedDraft>(userStorageKey(tgId, 'draft'));
    if (generation !== hydrationGeneration || get().scope !== tgId) return;
    const pending = normalizedPending(stored?.pending);
    const draft = pending
      ? savedFields({ ...pending.input, boxes: String(pending.input.boxes), items: pending.input.items.map(item => ({ ...item, quantity: String(item.quantity), key: newItemKey() })) })
      : savedFields(stored?.draft);
    const step = pending ? 4 : [1, 2, 3, 4].includes(stored?.step ?? 0) ? stored!.step : 1;
    set({ draft, step, pending, hydrated: true });
  },
  patch: values => { if (!get().hydrated || get().pending) return; set(state => ({ draft: { ...state.draft, ...values } })); persist(get()); },
  addItem: () => {
    if (!get().hydrated || get().pending || get().draft.items.length >= MAX_ITEMS) return null;
    const item = createDraftItem();
    set(state => ({ draft: { ...state.draft, items: [...state.draft.items, item] } })); persist(get()); return item.key;
  },
  removeItem: key => {
    if (!get().hydrated || get().pending || get().draft.items.length <= 1) return;
    set(state => ({ draft: { ...state.draft, items: state.draft.items.filter(item => item.key !== key) } })); persist(get());
  },
  patchItem: (key, values) => {
    if (!get().hydrated || get().pending) return;
    set(state => ({ draft: { ...state.draft, items: state.draft.items.map(item => item.key === key ? { ...item, ...values, key } : item) } }));
    persist(get());
  },
  selectTariff: tariff => {
    if (!get().hydrated || get().pending) return;
    set(state => ({ draft: { ...state.draft, tariff_id: tariff.id, ...(tariff.insurance_available ? {} : { insurance_enabled: false }) } }));
    persist(get());
  },
  go: step => { if (!get().hydrated || get().pending) return; set({ step }); persist(get()); },
  begin: quote => {
    const state = get(); if (state.pending) return state.pending;
    if (!state.hydrated || Object.keys(firstStepErrors(state.draft)).length || state.draft.tariff_id === null || !decimalValid(state.draft.weight_kg, '0.01', '1000', 3)) throw new Error('Проверьте данные заказа');
    const draft = state.draft;
    const items: OrderItemInput[] = draft.items.map(item => ({ link: item.link.trim(), price_cny: normalizeDecimal(item.price_cny), quantity: Number(item.quantity), item_title: item.item_title, comment: item.comment }));
    if (!items.length || items.some(item => !quantityValid(String(item.quantity)) || !safeHttpUrl(item.link))) throw new Error('Проверьте данные заказа');
    const first = items[0];
    const pending: PendingSubmission = { input: { idempotency_key: crypto.randomUUID(), items,
      link: first.link, price_cny: first.price_cny, quantity: first.quantity, item_title: first.item_title, comment: first.comment,
      tariff_id: draft.tariff_id!, weight_kg: normalizeDecimal(draft.weight_kg), boxes: boxesValid(draft.boxes) ? Number(draft.boxes) : 1,
      insurance_enabled: draft.insurance_enabled, packing_enabled: draft.packing_enabled, photo_report_enabled: draft.photo_report_enabled }, quote };
    set({ pending, step: 4 }); persist(get()); return pending;
  },
  complete: (tgId, key) => {
    if (get().scope !== tgId || get().pending?.input.idempotency_key !== key) return false;
    ++hydrationGeneration; set({ draft: emptyDraft(), step: 1, pending: null }); persist(get()); return true;
  },
  release: (tgId, key) => {
    if (get().scope !== tgId || get().pending?.input.idempotency_key !== key) return;
    set({ pending: null, step: 2 }); persist(get());
  },
}));
