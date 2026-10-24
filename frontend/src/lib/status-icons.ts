/** Иконки статусов заказа для интерфейса (вместо эмодзи — строже и чище). */
const STATUS_ICONS: Record<string, string> = {
  processing: 'clipboard',
  purchased: 'shopping-bag',
  to_cn_warehouse: 'truck',
  at_cn_warehouse: 'warehouse',
  awaiting_delivery_payment: 'clock',
  to_cn_customs: 'send',
  cn_customs: 'shield',
  to_ru_customs: 'truck',
  ru_customs: 'shield',
  to_recipient: 'truck',
  delivered: 'check',
  cancelled: 'x',
};

export function statusIconName(key: string): string {
  return STATUS_ICONS[key] ?? 'package';
}
