import { useEffect, useState } from 'react';
import type { AppConfig, Navigate } from '../api/types';
import { useOrders, useTrackOrder } from '../api/hooks';
import { ApiError } from '../api/client';
import { OrderCard } from '../components/OrderCard';
import { StatusBadge } from '../components/StatusBadge';
import { Timeline } from '../components/Timeline';
import { EmptyState, ErrorState, LoadingState } from '../components/UiStates';
import { Icon } from '../components/Icon';
import { dateMsk, decimalNumber, money } from '../lib/format';
import { platformFromUrl, platformName } from '../lib/platforms';
import { haptic } from '../lib/telegram';

const pageSize = 20;

export function Orders({ config, onNavigate }: { config: AppConfig; onNavigate: Navigate }) {
  const [group, setGroup] = useState<'active' | 'completed'>('active');
  const [offset, setOffset] = useState(0);
  const orders = useOrders({ group, limit: pageSize, offset, poll: true });
  const [trackInput, setTrackInput] = useState('');
  const [trackLookup, setTrackLookup] = useState<string | null>(null);
  const tracked = useTrackOrder(trackLookup);

  useEffect(() => {
    if (tracked.data) haptic('success');
    else if (tracked.isError) haptic('error');
  }, [tracked.data, tracked.isError]);

  function selectGroup(value: 'active' | 'completed') {
    if (group === value) return;
    haptic('selection');
    setGroup(value);
    setOffset(0);
  }

  function checkTrack(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const value = trackInput.trim();
    if (!value) { haptic('error'); return; }
    haptic('selection');
    if (value === trackLookup) void tracked.refetch(); else setTrackLookup(value);
  }

  const trackError = tracked.error instanceof ApiError && tracked.error.status === 404
    ? 'Заказ с таким номером не найден. Проверьте трек-номер или откройте заказ в списке.'
    : tracked.error?.message;

  return (
    <div className="page page-stack">
      <header className="page-heading">
        <p className="eyebrow">ВСЁ ПОД РУКОЙ</p><h1 className="page-title">Мои заказы</h1>
        <p className="page-description">От оформления до получения. Статусы обновляются автоматически.</p>
      </header>

      <section className="section" aria-label="Проверка статуса по трек-номеру">
        <div className="section-heading"><h2>Статус по трек-номеру</h2><span className="chip">Быстрая проверка</span></div>
        <form className="card form-stack" onSubmit={checkTrack}>
          <div className="field">
            <label className="field-label" htmlFor="track-number">Номер заказа или трек-номер</label>
            <input id="track-number" className="input" value={trackInput} maxLength={64} autoComplete="off" spellCheck={false}
              placeholder="Например, TC-000123 или трек" onChange={event => { setTrackInput(event.target.value); }} />
            <p className="field-hint">Покажем текущий этап доставки. Доступны только ваши заказы.</p>
            {trackError && <p className="field-error" role="alert">{trackError}</p>}
            {tracked.data && <p className="notice notice--success" role="status">Найден заказ {tracked.data.public_no}.</p>}
          </div>
          <button className="button button--primary button--block" type="submit" disabled={!trackInput.trim() || tracked.isFetching}>
            <Icon name="search" size={18} />{tracked.isFetching ? 'Проверяем…' : 'Проверить статус'}
          </button>
        </form>
        {tracked.isPending && trackLookup && <LoadingState label="Ищем заказ по номеру" />}
        {tracked.data && <section className="card card--glow" aria-label="Результат проверки трек-номера">
          <div className="section-heading">
            <div><p className="eyebrow">НАЙДЕН ЗАКАЗ</p><h2>{tracked.data.public_no}</h2></div>
            <StatusBadge status={tracked.data.status} statuses={config.statuses} />
          </div>
          <Timeline statuses={config.statuses} status={tracked.data.status} />
          <div className="breakdown">
            <div className="breakdown-row"><span>Трек-номер</span><strong>{tracked.data.track_number || 'ещё не присвоен'}</strong></div>
            <div className="breakdown-row"><span>Площадка</span><strong>{platformName(platformFromUrl(tracked.data.link))}</strong></div>
            <div className="breakdown-row"><span>Примерный вес</span><strong>{decimalNumber(tracked.data.weight_kg, 3)} кг</strong></div>
            <div className="breakdown-row"><span>К оплате за выкуп</span><strong>{money(tracked.data.total_with_extras_rub)}</strong></div>
            <div className="breakdown-row"><span>Обновлён</span><strong>{dateMsk(tracked.data.updated_at)}</strong></div>
          </div>
          <button className="button button--secondary button--block" type="button" onClick={() => onNavigate({ name: 'order', id: tracked.data!.id })}>Открыть заказ<Icon name="arrow-right" size={18} /></button>
        </section>}
      </section>

      <div className="segmented orders-filter" role="group" aria-label="Какие заказы показать">
        <button className={group === 'active' ? 'is-active' : ''} aria-pressed={group === 'active'} onClick={() => selectGroup('active')}>Активные</button>
        <button className={group === 'completed' ? 'is-active' : ''} aria-pressed={group === 'completed'} onClick={() => selectGroup('completed')}>Завершённые</button>
      </div>
      {orders.isError && orders.data && <p className="notice notice--warning">Не удалось обновить список. Показаны последние загруженные данные. <button className="button button--ghost" onClick={() => void orders.refetch()}>Повторить</button></p>}

      {orders.isPending ? <LoadingState label="Загружаем ваши заказы" />
        : orders.isError && !orders.data ? <ErrorState message={orders.error.message} onRetry={() => void orders.refetch()} />
        : orders.data?.items.length ? <>
          <div className="inline-row space-between"><p className="muted text-small">Всего: {orders.data.total}</p><button className="button button--ghost" disabled={orders.isFetching} onClick={() => void orders.refetch()}><Icon name="refresh" size={16} />{orders.isFetching ? 'Обновляем…' : 'Обновить'}</button></div>
          <div className="order-list">{orders.data.items.map((order) => <OrderCard key={order.id} order={order} config={config} onClick={() => onNavigate({ name: 'order', id: order.id })} />)}</div>
          {orders.data.total > pageSize && <nav className="pagination" aria-label="Страницы заказов">
            <button className="button button--secondary" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - pageSize))}><Icon name="arrow-left" size={18} />Назад</button>
            <span className="muted text-small">{offset + 1}–{Math.min(offset + orders.data.items.length, orders.data.total)} из {orders.data.total}</span>
            <button className="button button--secondary" disabled={offset + pageSize >= orders.data.total} onClick={() => setOffset(offset + pageSize)}>Далее<Icon name="arrow-right" size={18} /></button>
          </nav>}
        </>
        : <EmptyState title={offset > 0 ? 'Эта страница уже пуста' : group === 'active' ? 'Активных заказов пока нет' : 'Завершённых заказов пока нет'} description={offset > 0 ? 'Статусы изменились. Вернитесь к началу списка, чтобы увидеть актуальные заказы.' : group === 'active' ? 'Добавьте ссылку на товар — приложение рассчитает выкуп и ориентировочную доставку.' : 'Здесь появятся доставленные и отменённые заказы. Активные заказы находятся в соседней вкладке.'} actionLabel={offset > 0 ? 'К началу списка' : group === 'active' ? 'Оформить заказ' : 'Показать активные'} onAction={() => offset > 0 ? setOffset(0) : group === 'active' ? onNavigate({ name: 'wizard' }) : selectGroup('active')} />}
    </div>
  );
}
