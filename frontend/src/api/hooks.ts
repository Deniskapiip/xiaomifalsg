import { useEffect } from 'react';
import { useQuery } from '@tanstack/react-query';
import { ApiError, request } from './client';
import type { AppConfig, Order, OrderPage } from './types';

export function retryQuery(attempt: number, error: Error): boolean { return attempt < 2 && !(error instanceof ApiError && [401, 403, 404, 422, 429].includes(error.status)); }
export function useConfig() { return useQuery({ queryKey: ['config'], queryFn: ({ signal }) => request<AppConfig>('/config', { signal }), staleTime: 60000, retry: retryQuery }); }
export function useVisibleRefresh(refetch: () => unknown, enabled: boolean): void {
  useEffect(() => {
    if (!enabled) return;
    const onVisible = () => { if (document.visibilityState === 'visible') void refetch(); };
    document.addEventListener('visibilitychange', onVisible);
    return () => document.removeEventListener('visibilitychange', onVisible);
  }, [refetch, enabled]);
}
export function useOrders({ group, limit = 20, offset = 0, poll = false }: { group?: 'active' | 'completed'; limit?: number; offset?: number; poll?: boolean } = {}) {
  const params = new URLSearchParams({ limit: String(limit), offset: String(offset) }); if (group) params.set('status_group', group);
  const query = useQuery({ queryKey: ['orders', group ?? 'all', limit, offset], queryFn: ({ signal }) => request<OrderPage>('/orders?' + params, { signal }),
    refetchInterval: poll ? 30000 : false, refetchIntervalInBackground: false, staleTime: 10000, retry: retryQuery });
  useVisibleRefresh(query.refetch, poll); return query;
}
export function useOrder(orderId: number, { poll = false }: { poll?: boolean } = {}) {
  const query = useQuery({ queryKey: ['order', orderId], queryFn: ({ signal }) => request<Order>(`/orders/${orderId}`, { signal }), refetchInterval: poll ? 30000 : false,
    refetchIntervalInBackground: false, staleTime: 10000, retry: retryQuery });
  useVisibleRefresh(query.refetch, poll); return query;
}
/** Status lookup by carrier track number or public order number of the current user. */
export function useTrackOrder(number: string | null) {
  const normalized = (number ?? '').trim();
  return useQuery({ queryKey: ['track', normalized], queryFn: ({ signal }) => request<Order>('/track?number=' + encodeURIComponent(normalized), { signal }),
    enabled: normalized.length > 0, staleTime: 0, retry: false });
}
