import { useState } from 'react';
import type { AppConfig, Navigate, Order } from '../api/types';
import { useOrder } from '../api/hooks';
import { StatusBadge } from '../components/StatusBadge';
import { Timeline } from '../components/Timeline';
import { PlatformMark } from '../components/PlatformMark';
import { ErrorState, LoadingState } from '../components/UiStates';
import { Icon } from '../components/Icon';
import { boxesLabel, dateMsk, decimalNumber, itemTitle, money, orderItemList, positionsLabel, statusLabel } from '../lib/format';
import { Exact } from '../lib/pricing';
import { platformFromUrl, platformName } from '../lib/platforms';
import { copyText, haptic, openExternal, openTelegram } from '../lib/telegram';

function eventText(event: Order['events'][number], config: AppConfig): string {
  if (event.type === 'created') return 'Заказ принят';
  if (event.type === 'tracking') {
    const number = event.payload.track_number;
    return typeof number === 'string' && number ? `Трек-номер: ${number}` : 'Трек-номер обновлён';
  }
  if (event.type === 'delivery_amount_set') {
    const amount = event.payload.delivery_amount_rub;
    return typeof amount === 'string' && /^[0-9]+$/.test(amount) ? `Сумма доставки: ${money(amount)}` : 'Уточнена сумма доставки';
  }
  if (event.to_status) return statusLabel(event.to_status, config.statuses);
  return 'Заказ обновлён';
}

export function OrderDetails({ config, orderId, onNavigate }: { config: AppConfig; orderId: number; onNavigate: Navigate }) {
  const query = useOrder(orderId, { poll: true });
  const [copyState, setCopyState] = useState<'idle' | 'copied' | 'failed'>('idle');
  const [trackCopy, setTrackCopy] = useState<'idle' | 'copied' | 'failed'>('idle');
  const [linkError, setLinkError] = useState(false);
  const order = query.data;

  async function copyNumber(value: string) {
    const ok = await copyText(value);
    setCopyState(ok ? 'copied' : 'failed');
    haptic(ok ? 'success' : 'error');
  }
  async function copyTrack(value: string) {
    const ok = await copyText(value);
    setTrackCopy(ok ? 'copied' : 'failed');
    haptic(ok ? 'success' : 'error');
  }

  if (query.isPending) return <div className="page"><LoadingState label="Открываем ваш заказ" /></div>;
  if (!order) return <div className="page page-stack"><button className="button button--ghost" onClick={() => onNavigate({ name: 'orders' })}><Icon name="arrow-left" size={18} />К заказам</button><ErrorState message={query.error?.message || 'Не удалось найти заказ'} onRetry={() => void query.refetch()} /></div>;

  const minimumCommission = new Exact(order.goods_rub).mul(order.commission_percent).div(100).lte(order.commission_min_rub);
  const visibleEvents = order.events.filter((event) => ['created', 'status_changed', 'delivery_amount_set', 'tracking'].includes(event.type)).sort((a, b) => a.created_at.localeCompare(b.created_at) || a.id - b.id);
  const awaitingPayment = order.status === 'awaiting_delivery_payment';
  const hasExtras = order.extras_total_rub !== '0';
  const items = orderItemList(order);
  const reviewContact = config.contacts.review || config.contacts.manager;

  return (
    <div className="page page-stack">
      {query.isError && <p className="notice notice--warning">Не удалось обновить заказ. Показаны последние загруженные данные. <button className="button button--ghost" onClick={() => void query.refetch()}>Повторить</button></p>}
      <header className="page-heading">
        <p className="eyebrow">ВАШ ЗАКАЗ</p>
        <div className="details-header"><h1 className="page-title details-number">{order.public_no}</h1><button className="icon-button" aria-label="Скопировать номер заказа" onClick={() => void copyNumber(order.public_no)}><Icon name={copyState === 'copied' ? 'check' : 'copy'} size={22} /></button></div>
        {copyState === 'copied' && <p className="field-hint" role="status">Номер скопирован</p>}
        {copyState === 'failed' && <p className="field-error" role="status">Не получилось скопировать. Номер заказа: {order.public_no}</p>}
        <StatusBadge status={order.status} statuses={config.statuses} />
        <p className="muted text-small">Оформлен {dateMsk(order.created_at)}</p>
      </header>

      <section className="card" aria-label="Этапы вашего заказа"><Timeline statuses={config.statuses} status={order.status} /></section>

      {order.track_number && <section className="card" aria-label="Трек-номер заказа">
        <div className="section-heading"><h2>Трек-номер</h2><Icon name="truck" size={22} /></div>
        <div className="inline-row space-between">
          <strong className="details-number">{order.track_number}</strong>
          <button className="icon-button" type="button" aria-label="Скопировать трек-номер" onClick={() => void copyTrack(order.track_number!)}><Icon name={trackCopy === 'copied' ? 'check' : 'copy'} size={20} /></button>
        </div>
        {trackCopy === 'copied' && <p className="field-hint" role="status">Трек-номер скопирован</p>}
        {trackCopy === 'failed' && <p className="field-error" role="status">Не получилось скопировать. Трек-номер: {order.track_number}</p>}
        {(order.tracking_status_text || order.tracking_checked_at) && <div className="breakdown">
          {order.tracking_status_text && <div className="breakdown-row"><span>Статус Добропоста</span><strong>{order.tracking_status_text}</strong></div>}
          {order.tracking_checked_at && <div className="breakdown-row"><span>Проверено</span><strong>{dateMsk(order.tracking_checked_at)}</strong></div>}
          {order.tracking_next_check_at && <div className="breakdown-row"><span>Следующая проверка</span><strong>{dateMsk(order.tracking_next_check_at)}</strong></div>}
        </div>}
        <p className="field-hint">Проверить этап по номеру можно в разделе «Мои заказы» или командой /track в боте. После «Ожидает оплаты доставки» статус обновляется автоматически по Добропосту.</p>
      </section>}

      <section className="card product-details">
        <div className="section-heading"><h2>Товары</h2><span className="chip">{positionsLabel(items.length)}</span></div>
        <div className="breakdown">
          {items.map(item => <div className="breakdown-row" key={item.id || item.position}>
            <dt>
              <span className="inline-row"><PlatformMark link={item.link} size="sm" /><strong>{itemTitle(item)}</strong></span>
              <small>{decimalNumber(item.price_cny, 2)} ¥ × {item.quantity} · {platformName(platformFromUrl(item.link))}</small>
              {item.comment && <small>{item.comment}</small>}
            </dt>
            <dd><button className="icon-button" type="button" aria-label={`Открыть товар «${itemTitle(item)}»`} onClick={() => setLinkError(!openExternal(item.link))}><Icon name="external-link" size={20} /></button></dd>
          </div>)}
          <div className="breakdown-row"><dt>Стоимость товаров</dt><dd>{money(order.goods_rub)}</dd></div>
        </div>
        {linkError && <p className="field-error" role="alert">Не удалось открыть ссылку. Допустимы только ссылки http:// и https://.</p>}
      </section>

      <section className="card card--glow">
        <div className="section-heading"><h2>Расчёт выкупа</h2><Icon name="shield" size={20} /></div>
        <p className="snapshot-note muted text-small">Сохранён при оформлении. Изменение курса или тарифов не меняет этот заказ.</p>
        <div className="breakdown">
          <div className="breakdown-row"><div><span>Товар</span><small>{decimalNumber(order.price_cny, 2)} ¥ × {order.quantity} × {decimalNumber(order.rate, 4)}</small></div><strong>{money(order.goods_rub)}</strong></div>
          <div className="breakdown-row"><div><span>Комиссия</span><small>{minimumCommission ? `Минимальная: ${money(order.commission_min_rub)}` : `${decimalNumber(order.commission_percent, 2)}% от стоимости товара`}</small></div><strong>{money(order.commission_rub)}</strong></div>
          {order.insurance_enabled && <div className="breakdown-row"><div><span>Страховка груза</span><small>Доп. услуга при оформлении</small></div><strong>{money(order.insurance_rub)}</strong></div>}
          {order.packing_enabled && <div className="breakdown-row"><div><span>Обрешётка / упаковка</span><small>Доп. услуга при оформлении</small></div><strong>{money(order.packing_rub)}</strong></div>}
          {order.photo_report_enabled && <div className="breakdown-row"><div><span>Фотоотчёт на складе</span><small>Доп. услуга при оформлении</small></div><strong>{money(order.photo_report_rub)}</strong></div>}
          {hasExtras && <div className="breakdown-row"><div><span>Сумма доп. услуг</span><small>Сохранена в заказе</small></div><strong>{money(order.extras_total_rub)}</strong></div>}
          <div className="breakdown-row breakdown-row--total"><span>К оплате за выкуп</span><strong className="money">{money(order.total_with_extras_rub)}</strong></div>
        </div>
      </section>

      <section className={awaitingPayment ? 'card card--glow' : 'card card--muted'}>
        <div className="section-heading"><h2>Доставка</h2><Icon name="truck" size={22} /></div>
        <div className="breakdown">
          <div className="breakdown-row"><span>Тариф при оформлении</span><strong>{order.tariff_name}</strong></div>
          {order.tariff_price_currency === 'cny' && <div className="breakdown-row"><span>Цена тарифа</span><strong>{decimalNumber(order.tariff_price_value, 2)} ¥ / кг</strong></div>}
          <div className="breakdown-row"><span>Ставка за кг</span><strong>{decimalNumber(order.tariff_price_per_kg, 2)} ₽ / кг</strong></div>
          {order.boxes > 1 && <div className="breakdown-row"><span>Обрешётка</span><strong>{boxesLabel(order.boxes)}</strong></div>}
          <div className="breakdown-row"><span>Примерный вес</span><strong>{decimalNumber(order.weight_kg, 3)} кг</strong></div>
          <div className="breakdown-row"><span>Ориентировочно</span><strong>{money(order.delivery_estimate_rub)}</strong></div>
          {order.delivery_final_rub !== null && <div className="breakdown-row breakdown-row--total"><span>Итоговая доставка</span><strong className="money">{money(order.delivery_final_rub)}</strong></div>}
        </div>
        {awaitingPayment ? <><p className="notice notice--info">Менеджер указал итоговую стоимость доставки. Напишите ему, чтобы уточнить оплату.</p><button className="button button--primary button--block" onClick={() => openTelegram(config.contacts.manager, `Здравствуйте! Хочу уточнить оплату доставки заказа ${order.public_no}. Сумма: ${order.delivery_final_rub ? money(order.delivery_final_rub) : 'уточните, пожалуйста'}.`)}><Icon name="send" size={18} />Написать менеджеру</button></>
          : <p className="muted text-small">Доставка оплачивается отдельно после прибытия на склад. Итоговую сумму укажет менеджер.</p>}
      </section>

      <section className="section">
        <div className="section-heading"><h2>История заказа</h2><span className="muted text-small">МСК</span></div>
        {visibleEvents.length ? <ol className="event-list">{visibleEvents.map((event) => <li className="event-item" key={event.id}><span className="event-dot" aria-hidden="true" /><div><strong>{eventText(event, config)}</strong><time className="event-time" dateTime={event.created_at}>{dateMsk(event.created_at)}</time></div></li>)}</ol> : <p className="muted">История появится после первого обновления заказа.</p>}
      </section>

      {order.status === 'delivered' && <section className="card card--glow" aria-label="Отзыв о заказе">
        <div className="section-heading"><h2>Отзыв о заказе</h2><Icon name="send" size={22} /></div>
        <p className="muted">Заказ доставлен. Расскажите, как всё прошло — это помогает нам и другим покупателям.</p>
        <button className="button button--primary button--block" type="button" onClick={() => openTelegram(reviewContact, `Здравствуйте! Хочу оставить отзыв о заказе ${order.public_no}.`)}><Icon name="send" size={18} />Оставить отзыв</button>
      </section>}

      <button className="button button--secondary button--block" onClick={() => openTelegram(config.contacts.manager, `Здравствуйте! У меня вопрос по заказу ${order.public_no}.`)}><Icon name="send" size={18} />Вопрос по заказу</button>
    </div>
  );
}
