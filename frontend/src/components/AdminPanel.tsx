import type { AppConfig, Navigate, Role, Screen } from '../api/types';
import { useBackButton } from '../lib/telegram';
import { AdminFrame } from './AdminFrame';
import { AdminDashboard } from '../pages/admin/AdminDashboard';
import { AdminOrders } from '../pages/admin/AdminOrders';
import { AdminOrderDetails } from '../pages/admin/AdminOrderDetails';
import { AdminSettings } from '../pages/admin/AdminSettings';
import { AdminTariffs } from '../pages/admin/AdminTariffs';

export function AdminPanel({ config, role, screen, onNavigate }: {
  config: AppConfig; role: Role; screen: Extract<Screen, { name: 'admin' | 'admin-order' }>; onNavigate: Navigate;
}) {
  const view = screen.name === 'admin-order' ? 'orders' : screen.view ?? 'dashboard';
  useBackButton(() => {
    const dialog = document.querySelector('dialog[open]');
    if (dialog) { dialog.dispatchEvent(new Event('cancel', { cancelable: true })); return; }
    if (screen.name === 'admin-order') onNavigate({ name: 'admin', view: 'orders', filters: screen.filters });
    else if (view !== 'dashboard') onNavigate({ name: 'admin', view: 'dashboard' });
    else onNavigate({ name: 'home' });
  });
  let body;
  if (screen.name === 'admin-order') body = <AdminOrderDetails key={screen.id} config={config} orderId={screen.id} filters={screen.filters} onNavigate={onNavigate} />;
  else if (view === 'orders') body = <AdminOrders config={config} filters={screen.filters ?? {}} onNavigate={onNavigate} />;
  else if (view === 'settings' && role === 'owner') body = <AdminSettings onNavigate={onNavigate} />;
  else if (view === 'tariffs' && role === 'owner') body = <AdminTariffs onNavigate={onNavigate} rate={config.rate_cny_rub} />;
  else body = <AdminDashboard config={config} role={role} onNavigate={onNavigate} />;
  return <AdminFrame role={role} view={view} onNavigate={onNavigate}>{body}</AdminFrame>;
}
