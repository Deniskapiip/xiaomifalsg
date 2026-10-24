import { Exact } from './pricing';
import { decimalValid, normalizeDecimal } from './validation';
import type { StatusDefinition } from '../api/types';
import type { SettingsInput, TariffInput } from '../api/admin-types';

export function deliveryAmountValid(raw: string): boolean { return /^[1-9]\d{0,14}$/.test(raw.trim()); }
export function statusRequiresConfirmation(oldStatus: string, newStatus: string, statuses: StatusDefinition[]): boolean {
  if (newStatus === 'cancelled') return true;
  if (oldStatus === 'cancelled') return false;
  const old = statuses.find(status => status.key === oldStatus), next = statuses.find(status => status.key === newStatus);
  return Boolean(old && next && next.order < old.order);
}
export function validateSettings(fields: SettingsInput): { errors: Record<string, string>; input: SettingsInput | null } {
  const errors: Record<string, string> = {};
  if (!decimalValid(fields.rate_cny_rub, '0.0001', '99999999.9999', 4)) errors.rate_cny_rub = 'Курс: больше нуля и меньше 100 000 000, до 4 знаков после запятой.';
  if (!decimalValid(fields.commission_percent, '0', '100', 2)) errors.commission_percent = 'Процент: от 0 до 100, до 2 знаков после запятой.';
  if (!/^(0|[1-9]\d{0,14})$/.test(fields.commission_min_rub.trim())) errors.commission_min_rub = 'Минимум: целое число от 0, до 15 цифр.';
  return { errors, input: Object.keys(errors).length ? null : {
    rate_cny_rub: new Exact(normalizeDecimal(fields.rate_cny_rub)).toFixed(),
    commission_percent: new Exact(normalizeDecimal(fields.commission_percent)).toFixed(), commission_min_rub: fields.commission_min_rub.trim(),
  } };
}
export interface TariffFields extends Omit<TariffInput, 'sort_order'> { sort_order: string }
export function validateTariff(fields: TariffFields): { errors: Record<string, string>; input: TariffInput | null } {
  const errors: Record<string, string> = {};
  const name = fields.name.trim();
  if (!name || name.length > 100) errors.name = 'Название: от 1 до 100 символов.';
  if (!decimalValid(fields.price_per_kg_rub, fields.is_active ? '0.01' : '0', '9999999999.99', 2)) errors.price_per_kg_rub = 'Цена: до 9 999 999 999,99 ₽, до 2 знаков после запятой. Для активного тарифа больше нуля.';
  if (fields.eta_text.length > 200) errors.eta_text = 'Срок: до 200 символов.';
  if (fields.description.length > 1000) errors.description = 'Описание: до 1000 символов.';
  if (!/^\d{1,5}$/.test(fields.sort_order.trim()) || Number(fields.sort_order) > 10000) errors.sort_order = 'Порядок: целое число от 0 до 10 000.';
  return { errors, input: Object.keys(errors).length ? null : { name, price_per_kg_rub: new Exact(normalizeDecimal(fields.price_per_kg_rub)).toFixed(),
    eta_text: fields.eta_text.trim(), description: fields.description.trim(), is_active: fields.is_active, sort_order: Number(fields.sort_order),
  } };
}
