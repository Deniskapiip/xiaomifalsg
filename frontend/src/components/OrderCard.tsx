import type { AppConfig, Order } from '../api/types';
import { Icon } from './Icon';
import { StatusBadge } from './StatusBadge';

function orderTitle(order: Order) {
  if (order.item_title.trim()) return order.item_title;
  try { return new URL(order.link).hostname.replace(/^www\./, ''); }
  catch { return 'Товар из Китая'; }
}

export function OrderCard({ order, config, onClick }: { order: Order; config: AppConfig; onClick: () => void }) {
  const price = new Intl.NumberFormat('ru-RU').format(BigInt(order.total_rub));
  const date = new Intl.DateTimeFormat('ru-RU', { day: '2-digit', month: 'short', timeZone: 'Europe/Moscow' }).format(new Date(order.created_at));
  return (
    <button className="order-card" type="button" onClick={onClick} aria-label={`Открыть заказ ${order.public_no}, ${orderTitle(order)}`}>
      <span className="order-card__top"><span className="order-number">{order.public_no}</span><span className="order-card__date">{date}</span></span>
      <span className="order-card__body"><span className="order-card__parcel"><Icon name="package" size={23} /></span><span className="order-card__title">{orderTitle(order)}</span><Icon name="chevron-right" size={18} /></span>
      <span className="order-card__bottom"><StatusBadge status={order.status} statuses={config.statuses} /><span className="order-card__amount">{price} ₽</span></span>
    </button>
  );
}
