import { Exact } from './pricing';
import type { StatusDefinition } from '../api/types';

const integerFormat = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 });

export function decimalNumber(value: string, maxFractionDigits = 3): string {
  const fixed = new Exact(value).toDecimalPlaces(maxFractionDigits, Exact.ROUND_HALF_UP).toFixed();
  const [integer, fraction] = fixed.split('.');
  const formatted = integerFormat.format(BigInt(integer));
  return formatted + (fraction ? ',' + fraction : '');
}
export function money(value: string): string { return integerFormat.format(BigInt(value)) + '\u00a0₽'; }
export function dateMsk(value: string): string {
  return new Intl.DateTimeFormat('ru-RU', { timeZone: 'Europe/Moscow', day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' }).format(new Date(value)) + ' (МСК)';
}
export function shortDateMsk(value: string): string {
  return new Intl.DateTimeFormat('ru-RU', { timeZone: 'Europe/Moscow', day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' }).format(new Date(value)) + ' (МСК)';
}
export function productDomain(value: string): string { try { return new URL(value).hostname.replace(/^www\./, ''); } catch { return 'Ссылка на товар'; } }
export function statusLabel(value: string, statuses: StatusDefinition[]): string { return statuses.find(status => status.key === value)?.name ?? 'Статус уточняется'; }
