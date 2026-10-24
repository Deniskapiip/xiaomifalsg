import { Exact } from './pricing';
import type { Order, OrderItem, StatusDefinition, TariffCurrency } from '../api/types';

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
export function currencySymbol(currency: TariffCurrency): string { return currency === 'cny' ? '¥' : '₽'; }
/** «1 коробка», «3 коробки», «7 коробок». */
export function boxesLabel(value: number): string {
  const last = value % 10, lastTwo = value % 100;
  const word = last === 1 && lastTwo !== 11 ? 'коробка' : [2, 3, 4].includes(last) && ![12, 13, 14].includes(lastTwo) ? 'коробки' : 'коробок';
  return `${value} ${word}`;
}
/** «1 позиция», «3 позиции», «7 позиций». */
export function positionsLabel(value: number): string {
  const last = value % 10, lastTwo = value % 100;
  const word = last === 1 && lastTwo !== 11 ? 'позиция' : [2, 3, 4].includes(last) && ![12, 13, 14].includes(lastTwo) ? 'позиции' : 'позиций';
  return `${value} ${word}`;
}
export function itemTitle(item: Pick<OrderItem, 'item_title' | 'link'>): string {
  if (item.item_title.trim()) return item.item_title;
  return productDomain(item.link);
}
/** Позиции заказа; для старых заказов без items — одна позиция из legacy-полей. */
export function orderItemList(order: Order): OrderItem[] {
  if (order.items?.length) return order.items;
  return [{ id: 0, position: 1, link: order.link, platform: order.platform, item_title: order.item_title, price_cny: order.price_cny, quantity: order.quantity, comment: order.comment, goods_rub: order.goods_rub }];
}

