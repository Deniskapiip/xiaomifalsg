import { useEffect, useState } from 'react';
import type { AppConfig, Navigate, User } from '../api/types';
import { useOrders } from '../api/hooks';
import { OrderCard } from '../components/OrderCard';
import { EmptyState, ErrorState, Skeleton } from '../components/UiStates';
import { Icon } from '../components/Icon';
import { decimalNumber, shortDateMsk } from '../lib/format';
import { addToHomeScreen, canAddToHomeScreen, haptic, homeScreenStatus, openTelegram } from '../lib/telegram';

const deliverySteps = [
  { icon: 'clipboard', title: 'Оформление заказа', description: 'Добавьте ссылку на товар, выберите тариф и укажите примерный вес.' },
  { icon: 'shopping-bag', title: 'Выкуп', description: 'Менеджер уточнит детали и поможет с подтверждением и оплатой выкупа.' },
  { icon: 'warehouse', title: 'Доставка на склад', description: 'На складе в Китае определят вес. Менеджер укажет итоговую стоимость доставки.' },
  { icon: 'truck', title: 'Отправка в Россию', description: 'Следите за этапами доставки в заказе — до получения посылки.' },
];

export function Home({ config, user, onNavigate }: { config: AppConfig; user: User; onNavigate: Navigate }) {
  const orders = useOrders({ limit: 3 });
  const completed = useOrders({ group: 'completed', limit: 5 });
  const [homeStatus, setHomeStatus] = useState<TelegramHomeScreenStatus | null>(null);
  const [homeHint, setHomeHint] = useState('');

  useEffect(() => {
    let cancelled = false;
    void homeScreenStatus().then(status => { if (!cancelled) setHomeStatus(status); });
    return () => { cancelled = true; };
  }, []);

  function addHome() {
    if (!addToHomeScreen()) { setHomeHint('Клиент Telegram не поддерживает добавление на главный экран.'); haptic('error'); return; }
    haptic('success');
    setHomeHint('Подтвердите добавление в окне Telegram.');
    // The native call has no callback; re-check the status to hide the offer when it worked.
    window.setTimeout(() => { void homeScreenStatus().then(status => { if (status === 'added') { setHomeStatus('added'); setHomeHint('Иконка добавлена на главный экран.'); } }); }, 2500);
  }

  const showHomeOffer = canAddToHomeScreen() && homeStatus !== 'added';
  const deliveredOrder = completed.data?.items.find(order => order.status === 'delivered');
  const reviewContact = config.contacts.review || config.contacts.manager;

  return (
    <div className="page page-stack">
      <section className="hero card card--glow">
        <div className="hero-copy">
          <p className="eyebrow">ИЗ КИТАЯ — К ВАМ</p>
          <h1 className="page-title home-greeting">Здравствуйте, {user.first_name || 'рады вас видеть'}!</h1>
          <p className="page-description">Товар по вашей ссылке. Понятный расчёт. Каждый этап — в одном приложении.</p>
        </div>
        <div className="hero-route" aria-hidden="true">
          <span>CN</span><Icon name="arrow-right" size={26} /><span>RU</span>
        </div>
        <button className="button button--primary button--block" onClick={() => onNavigate({ name: 'wizard' })}>
          Рассчитать и оформить заказ <Icon name="arrow-right" size={20} />
        </button>
      </section>

      <div className="course-badge">
        <Icon name="refresh" size={18} />
        <span><strong>Курс: {decimalNumber(config.rate_cny_rub, 4)} ₽ за 1 ¥</strong><span>Обновлён {shortDateMsk(config.rate_updated_at)}</span></span>
      </div>

      {showHomeOffer && <div className="notice notice--info">
        <Icon name="download" size={18} />
        <div>
          <p>Добавьте Taoji Cargo на главный экран — приложение будет открываться в один тап.</p>
          <button className="button button--secondary" type="button" onClick={addHome}>Добавить на главный экран</button>
          {homeHint && <p className="field-hint" role="status">{homeHint}</p>}
        </div>
      </div>}

      <section className="section">
        <div className="section-heading"><h2>Как проходит доставка</h2><span className="chip">4 этапа</span></div>
        <ol className="process-list">
          {deliverySteps.map((step, index) => (
            <li className="process-step" key={step.title}>
              <span className="process-step__number" aria-hidden="true"><Icon name={step.icon} size={22} /></span>
              <div className="process-step__text"><span className="eyebrow">ЭТАП {index + 1}</span><h3>{step.title}</h3><p>{step.description}</p></div>
            </li>
          ))}
        </ol>
      </section>

      <section className="section">
        <div className="section-heading"><h2>Мои заказы</h2><button className="button button--ghost" onClick={() => onNavigate({ name: 'orders' })}>Все <Icon name="chevron-right" size={18} /></button></div>
        {orders.isError && orders.data && <p className="notice notice--warning">Не удалось обновить заказы. Показаны последние загруженные данные. <button className="button button--ghost" onClick={() => void orders.refetch()}>Повторить</button></p>}
        {orders.isPending ? <div className="order-list" aria-label="Загрузка заказов"><Skeleton className="skeleton--card" /><Skeleton className="skeleton--card" /></div>
          : orders.isError && !orders.data ? <ErrorState message={orders.error.message} onRetry={() => void orders.refetch()} />
          : orders.data?.items.length ? <div className="order-list">{orders.data.items.map((order) => <OrderCard key={order.id} order={order} config={config} onClick={() => onNavigate({ name: 'order', id: order.id })} />)}</div>
          : <EmptyState title="Ваш первый заказ впереди" description="Найдите товар на китайской площадке и начните со ссылки. Мы покажем расчёт до оформления." actionLabel="Рассчитать заказ" onAction={() => onNavigate({ name: 'wizard' })} />}
      </section>

      <section className="card card--muted" aria-label="Трекинг посылки">
        <div className="section-heading"><h2>Трекинг посылки</h2><Icon name="truck" size={20} /></div>
        <p className="muted">Проверяйте статус посылки Добропоста — добавим трек-номер и будем обновлять его автоматически.</p>
        <button className="button button--secondary button--block" type="button" onClick={() => onNavigate({ name: 'tracking' })}><Icon name="search" size={18} />Отследить посылку</button>
      </section>

      {deliveredOrder && <section className="card card--glow" aria-label="Отзыв о заказе">
        <div className="section-heading"><h2>Отзыв о заказе</h2><Icon name="send" size={20} /></div>
        <p className="muted">Вам понравился ваш заказ {deliveredOrder.public_no}? Оставьте отзыв — это помогает нам и другим покупателям.</p>
        <button className="button button--primary button--block" type="button" onClick={() => openTelegram(reviewContact, `Здравствуйте! Хочу оставить отзыв о заказе ${deliveredOrder.public_no}.`)}><Icon name="send" size={18} />Оставить отзыв</button>
      </section>}

      <section className="contact-grid" aria-label="Связаться с нами">
        <button className="contact-card card" onClick={() => openTelegram(config.contacts.manager)}><Icon name="send" size={24} /><span><strong>Написать менеджеру</strong><small>@{config.contacts.manager}</small></span><Icon name="arrow-right" size={18} /></button>
        <button className="contact-card card" onClick={() => openTelegram(config.contacts.channel)}><Icon name="package" size={24} /><span><strong>Наш канал</strong><small>@{config.contacts.channel}</small></span><Icon name="arrow-right" size={18} /></button>
        <button className="contact-card card" onClick={() => openTelegram(reviewContact)}><Icon name="check" size={24} /><span><strong>Отзывы</strong><small>@{reviewContact}</small></span><Icon name="arrow-right" size={18} /></button>
      </section>
    </div>
  );
}
