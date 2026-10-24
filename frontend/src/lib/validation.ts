import { Exact } from './pricing';
import { platformFromUrl, platformName } from './platforms';

export interface DraftFields {
  link: string; price_cny: string; quantity: string; item_title: string; comment: string; tariff_id: number | null; weight_kg: string;
  insurance_enabled: boolean; packing_enabled: boolean; photo_report_enabled: boolean;
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
export function firstStepErrors(draft: DraftFields): Record<string, string> {
  const errors: Record<string, string> = {};
  if (!safeHttpUrl(draft.link)) errors.link = 'Укажите полную ссылку http:// или https://, до 2000 символов.';
  if (!decimalValid(draft.price_cny, '0.01', '1000000', 2)) errors.price_cny = 'Цена: от 0,01 до 1 000 000 ¥, не больше двух знаков после запятой.';
  if (!/^\d+$/.test(draft.quantity) || !new Exact(draft.quantity || '0').gte(1) || !new Exact(draft.quantity || '0').lte(999)) errors.quantity = 'Количество: целое число от 1 до 999.';
  if (draft.item_title.length > 200) errors.item_title = 'Название: до 200 символов.';
  if (draft.comment.length > 500) errors.comment = 'Комментарий: до 500 символов.';
  return errors;
}
