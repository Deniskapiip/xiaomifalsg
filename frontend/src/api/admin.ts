import { useQuery } from '@tanstack/react-query';
import type { QueryClient } from '@tanstack/react-query';
import { ApiError, request } from './client';
import { retryQuery, useVisibleRefresh } from './hooks';
import type { Tariff } from './types';
import type { AdminDashboard, AdminOrder, AdminOrderFilters, AdminOrderPage, AdminSettingsData } from './admin-types';

export function isAccessDenied(error: unknown): boolean { return error instanceof ApiError && [401, 403].includes(error.status); }
export function useAdminDashboard() {
  const query = useQuery({ queryKey: ['admin-dashboard'], queryFn: ({ signal }) => request<AdminDashboard>('/admin/dashboard', { signal }),
    staleTime: 10000, refetchInterval: 30000, refetchIntervalInBackground: false, retry: retryQuery });
  useVisibleRefresh(query.refetch, true); return query;
}
export function useAdminOrders({ q = '', status = '', offset = 0, sort = 'newest', limit = 20 }: AdminOrderFilters = {}) {
  const params = new URLSearchParams({ limit: String(limit), offset: String(offset), sort });
  if (q.trim()) params.set('q', q.trim()); if (status) params.set('status', status);
  const query = useQuery({ queryKey: ['admin-orders', q.trim(), status, offset, sort, limit],
    queryFn: ({ signal }) => request<AdminOrderPage>('/admin/orders?' + params, { signal }), staleTime: 10000,
    refetchInterval: 30000, refetchIntervalInBackground: false, retry: retryQuery });
  useVisibleRefresh(query.refetch, true); return query;
}
export function useAdminOrder(id: number) {
  const query = useQuery({ queryKey: ['admin-order', id], queryFn: ({ signal }) => request<AdminOrder>(`/admin/orders/${id}`, { signal }),
    staleTime: 10000, refetchInterval: 30000, refetchIntervalInBackground: false, retry: retryQuery });
  useVisibleRefresh(query.refetch, true); return query;
}
export function useAdminSettings() { return useQuery({ queryKey: ['admin-settings'], queryFn: ({ signal }) => request<AdminSettingsData>('/admin/settings', { signal }), staleTime: 30000, retry: retryQuery }); }
export function useAdminTariffs() { return useQuery({ queryKey: ['admin-tariffs'], queryFn: ({ signal }) => request<Tariff[]>('/admin/tariffs', { signal }), staleTime: 30000, retry: retryQuery }); }
export async function invalidateOrderQueries(client: QueryClient, order: AdminOrder): Promise<void> {
  // Private notes, actors and notification logs are kept only in the admin cache.
  client.setQueryData(['admin-order', order.id], order);
  await Promise.all(['admin-orders', 'admin-dashboard', 'orders', 'order'].map(key => client.invalidateQueries({ queryKey: [key] })));
}
export async function invalidateConfigQueries(client: QueryClient): Promise<void> {
  await Promise.all(['config', 'admin-dashboard', 'admin-settings', 'admin-tariffs'].map(key => client.invalidateQueries({ queryKey: [key] })));
}
