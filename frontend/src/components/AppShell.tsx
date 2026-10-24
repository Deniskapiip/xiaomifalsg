import type { ReactNode } from 'react';
import type { Navigate, Role, Tab, User } from '../api/types';
import { Icon } from './Icon';
import { OfflineBanner } from './UiStates';
import { ThemeToggle } from './ThemeToggle';

const tabs: { key: Tab; label: string; icon: string }[] = [
  { key: 'home', label: 'Главная', icon: 'home' },
  { key: 'wizard', label: 'Заказать', icon: 'plus' },
  { key: 'orders', label: 'Мои заказы', icon: 'package' },
  { key: 'help', label: 'Помощь', icon: 'help' },
];

export function AppShell({ user, role, activeTab, onNavigate, children, adminEnabled = false }: {
  user: User; role: Role; activeTab: Tab; onNavigate: Navigate; children: ReactNode; adminEnabled?: boolean;
}) {
  const navigation = role !== 'client' && adminEnabled
    ? [...tabs, { key: 'admin' as Tab, label: 'Админка', icon: 'settings' }]
    : tabs;
  const firstName = user.first_name?.trim() || 'Пользователь';
  return (
    <div className="app-canvas">
      <header className="app-header">
        <button className="app-brand" type="button" onClick={() => onNavigate({ name: 'home' })} aria-label="Taoji Cargo — на главную">
          <img src="/logo.png" width="48" height="48" alt="" />
          <span><strong>TAOJI <em>CARGO</em></strong><small>ВЫКУП · ДОСТАВКА</small></span>
        </button>
        <div className="app-header__actions">
          <ThemeToggle />
          <span className="app-avatar" title={firstName} aria-label={`Пользователь: ${firstName}`}>{firstName.slice(0, 1).toLocaleUpperCase('ru-RU')}</span>
        </div>
      </header>
      <OfflineBanner />
      <main className="app-main" id="main-content">{children}</main>
      <nav className="bottom-nav" aria-label="Основная навигация">
        {navigation.map((tab) => (
          <button key={tab.key} className={`nav-item ${activeTab === tab.key ? 'is-active' : ''}`} aria-current={activeTab === tab.key ? 'page' : undefined} type="button" onClick={() => onNavigate({ name: tab.key })}>
            <span className={`nav-item__icon ${tab.key === 'wizard' ? 'nav-item__icon--order' : ''}`}><Icon name={tab.icon} size={22} /></span>
            <span>{tab.label}</span>
          </button>
        ))}
      </nav>
    </div>
  );
}
