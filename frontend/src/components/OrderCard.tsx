import type { AppConfig, Order } from '../api/types';
import { Icon } from './Icon';
import { PlatformMark } from './PlatformMark';
import { StatusBadge } from './StatusBadge';
import { itemTitle, orderItemList, positionsLabel } from '../lib/format';

export function OrderCard({ order, config, onClick }: { order: Order; config: AppConfig; onClick: () => void }) {
  const price = new Intl.NumberFormat('ru-RU').format(BigInt(order.total_rub));
  const date = new Intl.DateTimeFormat('ru-RU', { day: '2-digit', month: 'short', timeZone: 'Europe/Moscow' }).format(new Date(order.created_at));
  const items = orderItemList(order);
  const first = items[0];
  const title = items.length > 1 ? `${itemTitle(first)} и ещё ${items.length - 1}` : itemTitle(first);
  return (
    <button className="order-card" type="button" onClick={onClick} aria-label={`Открыть заказ ${order.public_no}, ${title}`}>
      <span className="order-card__top"><span className="order-number">{order.public_no}</span>{items.length > 1 && <span className="chip">{positionsLabel(items.length)}</span>}<span className="order-card__date">{date}</span></span>
      <span className="order-card__body"><span className="order-card__parcel"><PlatformMark link={first.link} size="sm" /></span><span className="order-card__title">{title}</span><Icon name="chevron-right" size={18} /></span>
      <span className="order-card__bottom"><StatusBadge status={order.status} statuses={config.statuses} /><span className="order-card__amount">{price} ₽</span></span>
    </button>
  );
}
