import type { AppConfig, Navigate, Role } from '../../api/types';
import { isAccessDenied, useAdminDashboard } from '../../api/admin';
import { EmptyState, ErrorState, LoadingState } from '../../components/UiStates';
import { Icon } from '../../components/Icon';
import { dateMsk, decimalNumber, money } from '../../lib/format';
import { statusIconName } from '../../lib/status-icons';

export function AdminDashboard({ config, role, onNavigate }: { config: AppConfig; role: Role; onNavigate: Navigate }) {
  const dashboard = useAdminDashboard();
  if (isAccessDenied(dashboard.error)) return <EmptyState title="Нет доступа к админке" description="Права доступа изменились. Обратитесь к владельцу, если вам нужен доступ к заказам." actionLabel="На главную" onAction={() => onNavigate({ name: 'home' })} />;
  if (dashboard.isPending) return <LoadingState label="Загружаем сводку" />;
  if (!dashboard.data) return <ErrorState message={dashboard.error?.message ?? 'Сводка пока недоступна.'} onRetry={() => void dashboard.refetch()} />;
  const data = dashboard.data;
  const openOrders = (status?: string) => onNavigate({ name: 'admin', view: 'orders', filters: status ? { status, offset: 0 } : { offset: 0 } });
  const statuses = [...config.statuses].sort((left, right) => left.order - right.order);
  return <div className="page-stack admin-section">
    <header className="page-heading"><p className="eyebrow">ОПЕРАЦИОННАЯ СВОДКА</p><h1 className="page-title">Обзор</h1><p className="page-description">Заказы всех клиентов. Сегодня — по московскому времени.</p></header>
    {dashboard.isError && <p className="notice notice--warning" role="status">Не удалось обновить сводку. Показаны последние загруженные данные.</p>}
    <div className="inline-row space-between"><p className="muted text-small">Обновляется каждые 30 секунд</p><button type="button" className="button button--ghost" disabled={dashboard.isFetching} onClick={() => void dashboard.refetch()}><Icon name="refresh" size={16} />{dashboard.isFetching ? 'Обновляем…' : 'Обновить'}</button></div>
    <div className="admin-stat-grid">
      <button type="button" className="card admin-stat-card" onClick={() => openOrders()}><span className="muted">Всего заказов</span><strong className="admin-stat-value">{data.total_orders}</strong><span className="field-hint">Открыть все заказы</span></button>
      <section className="card admin-stat-card"><span className="muted">Новых сегодня</span><strong className="admin-stat-value">{data.new_today}</strong><span className="field-hint">С 00:00 МСК</span></section>
      <section className="card admin-stat-card"><span className="muted">Требуют действий</span><strong className="admin-stat-value">{data.requires_action}</strong><span className="field-hint">Обработка и склад в Китае</span></section>
    </div>
    {data.stale_orders.length > 0 && <section className="card card--glow stale-card">
      <div className="section-heading"><h2>Зависшие заказы</h2><span className="chip chip--accent">{data.stale_orders.length}</span></div>
      <p className="field-hint">Статус не менялся больше {data.stale_order_days} дн. — проверьте заказ и обновите этап.</p>
      <div className="stale-list">{data.stale_orders.map(row => <button type="button" className="stale-item" key={row.id} onClick={() => onNavigate({ name: 'admin-order', id: row.id })}>
        <span className="stale-item__no">{row.public_no}</span>
        <span className="stale-item__status">{row.status_name}</span>
        <span className="stale-item__days">{row.days} дн.</span>
        <Icon name="chevron-right" size={16} />
      </button>)}</div>
    </section>}
    <section className="page-stack"><div className="section-heading"><h2>По статусам</h2><p className="muted text-small">Выберите статус, чтобы открыть заказы</p></div><div className="admin-status-grid">{statuses.map(status => <button type="button" className="card admin-status-card" key={status.key} onClick={() => openOrders(status.key)}><span aria-hidden="true" className="admin-status-card__icon"><Icon name={statusIconName(status.key)} size={18} /></span><span>{status.name}</span><strong>{data.counts[status.key] ?? 0}</strong></button>)}</div></section>
    {role === 'owner' && data.stats !== null && <>
      <section className="card card--glow"><div className="inline-row space-between"><h2>Курс и комиссия</h2><Icon name="settings" size={24} /></div><p className="admin-money">1 ¥ = {decimalNumber(config.rate_cny_rub, 4)} ₽</p><p className="muted text-small">Курс обновлён: {dateMsk(config.rate_updated_at)}</p><p className="muted text-small">Комиссия {decimalNumber(config.commission_percent, 2)}%, минимум {money(config.commission_min_rub)}.</p>{data.rate_stale && <p className="notice notice--warning" role="status">Курс не обновлялся больше 24 часов. Проверьте его перед оформлением новых заказов.</p>}<button type="button" className="button button--secondary" onClick={() => onNavigate({ name: 'admin', view: 'settings' })}>Изменить настройки<Icon name="arrow-right" size={18} /></button></section>
      <section className="card"><h2>Расчётные суммы</h2><dl className="breakdown"><div><dt>Выкуп по заказам</dt><dd>{money(data.stats.orders_total_rub)}</dd></div><div><dt>Начисленная комиссия</dt><dd>{money(data.stats.calculated_commission_rub)}</dd></div></dl><p className="field-hint">Суммы по всем заказам, кроме отменённых. Это расчёт по заказам; поступление оплат здесь не учитывается.</p></section>
    </>}
  </div>;
}
