import type { Role, Screen } from '../api/types';
import type { AdminOrderFilters, AdminView } from '../api/admin-types';

export function allowedScreen(screen: Screen, role: Role): Screen {
  if ((screen.name === 'admin' || screen.name === 'admin-order') && role === 'client') return { name: 'home' };
  if (screen.name === 'admin' && role !== 'owner' && (screen.view === 'settings' || screen.view === 'tariffs')) return { name: 'admin', view: 'dashboard' };
  return screen;
}
export function readScreen(role: Role, href = window.location.href): Screen {
  const query = new URL(href).searchParams;
  const offset = query.get('offset') ?? '';
  const filters: AdminOrderFilters = { q: (query.get('search') ?? '').slice(0, 2000), status: (query.get('status') ?? '').slice(0, 64),
    offset: /^\d{1,7}$/.test(offset) ? Number(offset) : 0, sort: query.get('sort') === 'oldest' ? 'oldest' : 'newest' };
  const tab = query.get('tab');
  const match = /^order_([1-9]\d*)$/.exec(query.get('open') ?? '');
  if (match && Number.isSafeInteger(Number(match[1]))) {
    return role !== 'client' && tab !== 'orders' ? { name: 'admin-order', id: Number(match[1]), filters } : { name: 'order', id: Number(match[1]) };
  }
  if (tab === 'admin' || tab === 'admin-info') {
    const view = query.get('view');
    return allowedScreen({ name: 'admin', view: ['orders', 'settings', 'tariffs'].includes(view ?? '') ? view as AdminView : 'dashboard', filters }, role);
  }
  return { name: tab === 'orders' || tab === 'wizard' ? tab : 'home' };
}
export function screenUrl(screen: Screen, href = window.location.href): URL {
  const url = new URL(href);
  for (const key of ['open', 'tab', 'view', 'search', 'status', 'offset', 'sort']) url.searchParams.delete(key);
  if (screen.name === 'order' || screen.name === 'success') {
    url.searchParams.set('open', `order_${screen.name === 'order' ? screen.id : screen.order.id}`);
    url.searchParams.set('tab', 'orders');
  } else if (screen.name === 'admin' || screen.name === 'admin-order') {
    url.searchParams.set('tab', 'admin');
    url.searchParams.set('view', screen.name === 'admin-order' ? 'orders' : screen.view ?? 'dashboard');
    if (screen.name === 'admin-order') url.searchParams.set('open', `order_${screen.id}`);
    const filters = screen.filters;
    if (filters?.q) url.searchParams.set('search', filters.q);
    if (filters?.status) url.searchParams.set('status', filters.status);
    if (filters?.offset) url.searchParams.set('offset', String(filters.offset));
    if (filters?.sort === 'oldest') url.searchParams.set('sort', 'oldest');
  } else if (screen.name !== 'home') url.searchParams.set('tab', screen.name);
  return url;
}
