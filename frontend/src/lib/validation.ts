import { Exact } from './pricing';
import { platformFromUrl, platformName } from './platforms';

/** Одна позиция мультизаказа в черновике: ключ нужен только для React и хранилища. */
export interface DraftItem { key: string; link: string; price_cny: string; quantity: string; item_title: string; comment: string }
export interface DraftFields {
  items: DraftItem[];
  tariff_id: number | null; weight_kg: string;
  boxes: string;
  insurance_enabled: boolean; packing_enabled: boolean; photo_report_enabled: boolean;
}
export const MAX_ITEMS = 40;
let itemSequence = 0;

export function newItemKey(): string {
  try { return crypto.randomUUID(); } catch { itemSequence += 1; return `item-${Date.now().toString(36)}-${itemSequence}`; }
}
export function createDraftItem(values: Partial<Omit<DraftItem, 'key'>> = {}, key: string = newItemKey()): DraftItem {
  return { key, link: '', price_cny: '', quantity: '1', item_title: '', comment: '', ...values };
}
export function normalizeDecimal(value: string): string { return value.trim().replace(',', '.'); }
export function decimalValid(value: string, min: string, max: string, places: number): boolean {
  const normalized = normalizeDecimal(value);
  if (!/^\d+(?:\.\d+)?$/.test(normalized) || normalized.length > 30) return false;
  const fraction = normalized.split('.')[1] ?? '';
  if (fraction.length > places) return false;
  const decimal = new Exact(normalized);
  return decimal.gte(min) && decimal.lte(max);
}
export function boxesValid(value: string): boolean { return /^[1-9]\d?$/.test(value) && Number(value) <= 99; }
export function quantityValid(value: string): boolean { return /^\d+$/.test(value) && new Exact(value || '0').gte(1) && new Exact(value || '0').lte(999); }
/** Трек-номер: обрезаем края и схлопываем повторные пробелы перед проверкой и отправкой. */
export function normalizeTracking(value: string): string { return value.trim().replace(/\s+/g, ' '); }
export function trackingValid(value: string): boolean { return /^[A-Za-z0-9 _-]{3,64}$/.test(normalizeTracking(value)); }
export function safeHttpUrl(value: string): string | null {
  const trimmed = value.trim();
  if (!trimmed || trimmed.length > 2000 || !/^https?:\/\/[^/\\]/i.test(trimmed) || /\\|\s|[\u0000-\u001f]/.test(trimmed)) return null;
  try { const url = new URL(trimmed); return ['http:', 'https:'].includes(url.protocol) && !url.username && !url.password ? trimmed : null; }
  catch { return null; }
}
export function platformLabel(value: string): { name: string; known: boolean } {
  const link = safeHttpUrl(value); if (!link) return { name: 'Добавьте ссылку', known: false };
  const platform = platformFromUrl(link);
  return platform === 'unknown' ? { name: platformName('unknown'), known: false } : { name: platformName(platform), known: true };
}
export function itemErrors(item: DraftItem): Record<string, string> {
  const errors: Record<string, string> = {};
  if (!safeHttpUrl(item.link)) errors.link = 'Укажите полную ссылку http:// или https://, до 2000 символов.';
  if (!decimalValid(item.price_cny, '0.01', '1000000', 2)) errors.price_cny = 'Цена: от 0,01 до 1 000 000 ¥, не больше двух знаков после запятой.';
  if (!quantityValid(item.quantity)) errors.quantity = 'Количество: целое число от 1 до 999.';
  if (item.item_title.length > 200) errors.item_title = 'Название: до 200 символов.';
  if (item.comment.length > 500) errors.comment = 'Комментарий: до 500 символов.';
  return errors;
}
/** Ошибки позиций, у которых они есть, по ключу позиции. */
export function itemsErrors(draft: DraftFields): Record<string, Record<string, string>> {
  const result: Record<string, Record<string, string>> = {};
  for (const item of draft.items) {
    const errors = itemErrors(item);
    if (Object.keys(errors).length) result[item.key] = errors;
  }
  return result;
}
export function firstStepErrors(draft: DraftFields): Record<string, string> {
  const errors: Record<string, string> = {};
  if (draft.items.length < 1 || draft.items.length > MAX_ITEMS) errors.items = `В заказе от 1 до ${MAX_ITEMS} позиций.`;
  for (const [key, fields] of Object.entries(itemsErrors(draft))) {
    for (const [field, message] of Object.entries(fields)) errors[`${key}.${field}`] = message;
  }
  return errors;
}
