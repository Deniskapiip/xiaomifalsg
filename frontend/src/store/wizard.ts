import { create } from 'zustand';
import type { OrderInput, Quote } from '../api/types';
import type { DraftFields } from '../lib/validation';
import { decimalValid, firstStepErrors, normalizeDecimal } from '../lib/validation';
import { readStored, userStorageKey, writeStored } from '../lib/storage';

export type WizardStep = 1 | 2 | 3 | 4;
export interface PendingSubmission { input: OrderInput; quote: Quote }
interface SavedDraft { draft: DraftFields; step: WizardStep; pending: PendingSubmission | null }
const emptyDraft = (): DraftFields => ({ link: '', price_cny: '', quantity: '1', item_title: '', comment: '', tariff_id: null, weight_kg: '',
  insurance_enabled: false, packing_enabled: false, photo_report_enabled: false });
let hydrationGeneration = 0;

function validQuote(value: unknown): value is Quote {
  if (!value || typeof value !== 'object') return false;
  const row = value as Record<string, unknown>;
  return ['goods_rub', 'commission_rub', 'total_rub', 'delivery_estimate_rub', 'commission_min_rub'].every(key => typeof row[key] === 'string' && /^\d+$/.test(row[key] as string))
    && ['rate', 'commission_percent', 'tariff_price_per_kg'].every(key => typeof row[key] === 'string' && /^\d+(?:\.\d+)?$/.test(row[key] as string))
    && typeof row.tariff_name === 'string' && typeof row.commission_is_minimum === 'boolean';
}
function savedFields(value: unknown): DraftFields {
  const result = emptyDraft(); if (!value || typeof value !== 'object') return result;
  const row = value as Record<string, unknown>;
  const max = { link: 2000, price_cny: 30, quantity: 3, item_title: 200, comment: 500, weight_kg: 30 };
  for (const key of Object.keys(max) as (keyof typeof max)[]) if (typeof row[key] === 'string') result[key] = (row[key] as string).slice(0, max[key]);
  if (typeof row.tariff_id === 'number' && Number.isSafeInteger(row.tariff_id) && row.tariff_id > 0) result.tariff_id = row.tariff_id;
  for (const key of ['insurance_enabled', 'packing_enabled', 'photo_report_enabled'] as const) if (row[key] === true) result[key] = true;
  return result;
}
function savedOptions(value: OrderInput): Pick<DraftFields, 'insurance_enabled' | 'packing_enabled' | 'photo_report_enabled'> {
  return { insurance_enabled: value.insurance_enabled === true, packing_enabled: value.packing_enabled === true, photo_report_enabled: value.photo_report_enabled === true };
}
function validPending(value: unknown): value is PendingSubmission {
  if (!value || typeof value !== 'object') return false;
  const pending = value as PendingSubmission; const input = pending.input;
  if (!input || typeof input.idempotency_key !== 'string' || !/^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(input.idempotency_key)) return false;
  if (!Number.isSafeInteger(input.quantity) || input.quantity < 1 || input.quantity > 999 || !Number.isSafeInteger(input.tariff_id) || input.tariff_id <= 0) return false;
  if ((['insurance_enabled', 'packing_enabled', 'photo_report_enabled'] as const).some(key => input[key] !== undefined && typeof input[key] !== 'boolean')) return false;
  for (const [key, max] of [['link', 2000], ['item_title', 200], ['comment', 500], ['price_cny', 30], ['weight_kg', 30]] as const) if (typeof input[key] !== 'string' || input[key].length > max) return false;
  const draft = savedFields({ ...input, quantity: String(input.quantity), ...savedOptions(input) });
  return Object.keys(firstStepErrors(draft)).length === 0 && decimalValid(draft.weight_kg, '0.01', '1000', 3) && draft.tariff_id !== null && validQuote(pending.quote);
}
interface WizardState {
  scope: number | null; hydrated: boolean; draft: DraftFields; step: WizardStep; pending: PendingSubmission | null;
  hydrate: (tgId: number) => Promise<void>; patch: (values: Partial<DraftFields>) => void; go: (step: WizardStep) => void;
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
    const pending = validPending(stored?.pending) ? stored!.pending : null;
    const draft = pending ? savedFields({ ...pending.input, quantity: String(pending.input.quantity), ...savedOptions(pending.input) }) : savedFields(stored?.draft);
    const step = pending ? 4 : [1, 2, 3, 4].includes(stored?.step ?? 0) ? stored!.step : 1;
    set({ draft, step, pending, hydrated: true });
  },
  patch: values => { if (!get().hydrated || get().pending) return; set(state => ({ draft: { ...state.draft, ...values } })); persist(get()); },
  go: step => { if (!get().hydrated || get().pending) return; set({ step }); persist(get()); },
  begin: quote => {
    const state = get(); if (state.pending) return state.pending;
    if (!state.hydrated || Object.keys(firstStepErrors(state.draft)).length || state.draft.tariff_id === null || !decimalValid(state.draft.weight_kg, '0.01', '1000', 3)) throw new Error('Проверьте данные заказа');
    const draft = state.draft;
    const pending: PendingSubmission = { input: { idempotency_key: crypto.randomUUID(), link: draft.link.trim(), price_cny: normalizeDecimal(draft.price_cny), quantity: Number(draft.quantity),
      tariff_id: draft.tariff_id!, weight_kg: normalizeDecimal(draft.weight_kg), item_title: draft.item_title, comment: draft.comment,
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
