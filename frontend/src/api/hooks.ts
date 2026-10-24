import { useEffect } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ApiError, post, request } from './client';
import type { AppConfig, Order, OrderPage, TrackingLink } from './types';

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
/** Saved Dobropost tracking numbers; the backend refreshes them every TRACKING_REFRESH_HOURS. */
export function useTrackingLinks({ poll = false }: { poll?: boolean } = {}) {
  const query = useQuery({ queryKey: ['tracking'], queryFn: ({ signal }) => request<TrackingLink[]>('/tracking', { signal }),
    staleTime: 60000, refetchInterval: poll ? 30 * 60000 : false, refetchIntervalInBackground: false, retry: retryQuery });
  useVisibleRefresh(query.refetch, true); return query;
}
function useInvalidateTracking() {
  const queryClient = useQueryClient();
  return () => queryClient.invalidateQueries({ queryKey: ['tracking'] });
}
export function useAddTracking() {
  const invalidate = useInvalidateTracking();
  return useMutation({ mutationFn: (trackNumber: string) => post<TrackingLink>('/tracking', { track_number: trackNumber }), onSuccess: () => invalidate() });
}
export function useDeleteTracking() {
  const invalidate = useInvalidateTracking();
  return useMutation({ mutationFn: (id: number) => request<{ ok: boolean }>(`/tracking/${id}`, { method: 'DELETE' }), onSuccess: () => invalidate() });
}
export function useRefreshTracking() {
  const invalidate = useInvalidateTracking();
  return useMutation({ mutationFn: (id: number) => request<TrackingLink>(`/tracking/${id}/refresh`, { method: 'POST' }), onSuccess: () => invalidate() });
}
