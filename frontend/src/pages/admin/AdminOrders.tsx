import { useEffect, useState, type FormEvent } from 'react';
import type { AppConfig, Navigate } from '../../api/types';
import type { AdminOrderFilters } from '../../api/admin-types';
import { isAccessDenied, useAdminOrders } from '../../api/admin';
import { OrderCard } from '../../components/OrderCard';
import { EmptyState, ErrorState, LoadingState } from '../../components/UiStates';
import { Icon } from '../../components/Icon';

const pageSize = 20;

export function AdminOrders({ config, filters, onNavigate }: { config: AppConfig; filters: AdminOrderFilters; onNavigate: Navigate }) {
  const offset = filters.offset ?? 0;
  const [search, setSearch] = useState(filters.q ?? '');
  const orders = useAdminOrders({ ...filters, limit: pageSize, offset });
  useEffect(() => { setSearch(filters.q ?? ''); }, [filters.q]);

  function changeFilters(changes: AdminOrderFilters) {
    onNavigate({ name: 'admin', view: 'orders', filters: { ...filters, ...changes, limit: pageSize } });
  }

  function submitSearch(event: FormEvent) {
    event.preventDefault();
    changeFilters({ q: search.trim(), offset: 0 });
  }

  if (isAccessDenied(orders.error)) return <ErrorState message="Доступ к заказам закрыт. Ваша роль могла измениться." onRetry={() => void orders.refetch()} />;

  return <div className="page-stack admin-section">
    <header className="page-heading">
      <h2 className="page-title">Заказы клиентов</h2>
      <p className="page-description">Поиск по номеру заказа, @username клиента или ссылке на товар.</p>
    </header>
    <form className="card admin-filters" onSubmit={submitSearch}>
      <label className="field admin-filter-field">
        <span className="field-label">Поиск</span>
        <input className="input" type="search" value={search} maxLength={2000} placeholder="TC-000001, @username или ссылка" onChange={event => setSearch(event.target.value)} />
      </label>
      <label className="field admin-filter-field">
        <span className="field-label">Статус</span>
        <select className="input" aria-label="Статус" value={filters.status ?? ''} onChange={event => changeFilters({ status: event.target.value || undefined, offset: 0 })}>
          <option value="">Все статусы</option>
          {[...config.statuses].sort((a, b) => a.order - b.order).map(status => <option key={status.key} value={status.key}>{status.icon} {status.name}</option>)}
        </select>
      </label>
      <label className="field admin-filter-field">
        <span className="field-label">Порядок</span>
        <select className="input" aria-label="Порядок" value={filters.sort ?? 'newest'} onChange={event => changeFilters({ sort: event.target.value as 'newest' | 'oldest', offset: 0 })}>
          <option value="newest">Сначала новые</option><option value="oldest">Сначала старые</option>
        </select>
      </label>
      <div className="admin-form-actions">
        <button className="button button--primary" type="submit">Найти<Icon name="arrow-right" size={17} /></button>
        {(filters.q || filters.status || filters.sort === 'oldest') && <button className="button button--ghost" type="button" onClick={() => { setSearch(''); onNavigate({ name: 'admin', view: 'orders', filters: { limit: pageSize, offset: 0, sort: 'newest' } }); }}>Сбросить</button>}
      </div>
    </form>

    {orders.isError && orders.data && <p className="notice notice--warning">Список не удалось обновить. Показаны последние загруженные данные.</p>}
    {orders.data && <div className="inline-row space-between">
      <p className="muted text-small" role="status">Найдено: {orders.data.total}</p>
      <button className="button button--ghost" type="button" disabled={orders.isFetching} onClick={() => void orders.refetch()}><Icon name="refresh" size={16} />{orders.isFetching ? 'Обновляем…' : 'Обновить'}</button>
    </div>}

    {orders.isPending ? <LoadingState label="Загружаем заказы клиентов" />
      : !orders.data ? <ErrorState message={orders.error?.message || 'Не удалось получить список заказов'} onRetry={() => void orders.refetch()} />
      : orders.data.items.length ? <div className="order-list">{orders.data.items.map(order => <div className="admin-order-wrap" key={order.id}>
        <OrderCard order={order} config={config} onClick={() => onNavigate({ name: 'admin-order', id: order.id, filters: { ...filters, limit: pageSize, offset } })} />
        <p className="admin-order-client"><Icon name="send" size={14} /><span>{[order.client.first_name, order.client.last_name].filter(Boolean).join(' ') || 'Клиент'}{order.client.username ? ` · @${order.client.username}` : ` · Telegram ID ${order.client.tg_id}`}</span></p>
      </div>)}</div>
      : <EmptyState title={filters.q || filters.status ? 'Заказы не найдены' : 'Пока нет заказов'} description={filters.q || filters.status ? 'Проверьте запрос или выберите другой статус.' : 'Первый заказ появится здесь после оформления клиентом.'} />}

    {orders.data && (offset > 0 || orders.data.total > pageSize) && <nav className="pagination" aria-label="Страницы заказов">
      <button className="button button--secondary" type="button" disabled={offset === 0 || orders.isFetching} onClick={() => changeFilters({ offset: Math.max(0, offset - pageSize) })}><Icon name="arrow-left" size={18} />Назад</button>
      <span>{Math.floor(offset / pageSize) + 1} / {Math.max(1, Math.ceil(orders.data.total / pageSize))}</span>
      <button className="button button--secondary" type="button" disabled={offset + pageSize >= orders.data.total || orders.isFetching} onClick={() => changeFilters({ offset: offset + pageSize })}>Далее<Icon name="arrow-right" size={18} /></button>
    </nav>}
  </div>;
}
