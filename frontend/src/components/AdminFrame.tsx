import type { ReactNode } from 'react';
import type { Navigate, Role } from '../api/types';
import type { AdminView } from '../api/admin-types';

const items: { view: AdminView; label: string }[] = [
  { view: 'dashboard', label: 'Обзор' }, { view: 'orders', label: 'Заказы' },
  { view: 'settings', label: 'Настройки' }, { view: 'tariffs', label: 'Тарифы' },
];
export function AdminFrame({ role, view, onNavigate, children }: { role: Role; view: AdminView; onNavigate: Navigate; children: ReactNode }) {
  const visible = role === 'owner' ? items : items.slice(0, 2);
  return <section className="admin-section">
    <header className="admin-section__header"><div><p className="eyebrow">TAOJI · УПРАВЛЕНИЕ</p><h2>Админка</h2></div><span className="chip chip--accent">{role === 'owner' ? 'Владелец' : 'Менеджер'}</span></header>
    <nav className="admin-menu" aria-label="Разделы админки">{visible.map(item => <button key={item.view} type="button" aria-current={view === item.view ? 'page' : undefined} className={view === item.view ? 'is-active' : ''} onClick={() => onNavigate({ name: 'admin', view: item.view })}>{item.label}</button>)}</nav>
    {children}
  </section>;
}
