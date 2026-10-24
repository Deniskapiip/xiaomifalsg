import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { QueryClient } from '@tanstack/react-query';
import { ApiError } from './client';
import { invalidateConfigQueries, invalidateOrderQueries, isAccessDenied } from './admin';
import type { AdminOrder } from './admin-types';

let client: QueryClient;
const publicOrder = { id: 77, public_no: 'TC-000077', status: 'processing', total_rub: '4700', events: [] };
const privateOrder = { ...publicOrder, manager_note: 'Внутренняя заметка', user_id: 10, client: { id: 10, tg_id: 12345, first_name: 'Клиент', last_name: null, username: 'client123', can_write: true }, events: [{ id: 1, type: 'note', actor_user_id: 2, payload: { note: 'Внутренняя заметка' } }], notifications: [{ user_id: 10, kind: 'purchased', ok: false, error: 'Forbidden', created_at: '2026-10-12T12:00:00Z' }], notification_warning: true } as unknown as AdminOrder;

beforeEach(() => { client = new QueryClient({ defaultOptions: { queries: { gcTime: Infinity } } }); });
afterEach(() => client.clear());

describe('admin cache privacy and refresh', () => {
  it('stores a privileged response only in the admin detail cache', async () => {
    await invalidateOrderQueries(client, privateOrder);
    expect(client.getQueryData(['admin-order', 77])).toBe(privateOrder);
    expect(client.getQueryData(['order', 77])).toBeUndefined();
    expect(client.getQueryData(['orders'])).toBeUndefined();
  });

  it('invalidates public order data without replacing it with private notes, actors or notification logs', async () => {
    const page = { items: [publicOrder], total: 1, limit: 20, offset: 0 };
    client.setQueryData(['order', 77], publicOrder);
    client.setQueryData(['orders', 'all', 20, 0], page);
    client.setQueryData(['admin-orders', '', '', 0], { items: [] });
    client.setQueryData(['admin-dashboard'], { requires_action: 1 });
    await invalidateOrderQueries(client, privateOrder);
    expect(client.getQueryData(['order', 77])).toEqual(publicOrder);
    expect(client.getQueryData(['orders', 'all', 20, 0])).toEqual(page);
    expect(client.getQueryData(['order', 77])).not.toHaveProperty('manager_note');
    expect(client.getQueryData(['order', 77])).not.toHaveProperty('notifications');
    for (const key of [['order', 77], ['orders', 'all', 20, 0], ['admin-orders', '', '', 0], ['admin-dashboard']]) expect(client.getQueryState(key)?.isInvalidated).toBe(true);
  });

  it('refreshes public configuration and owner data after settings or tariff edits', async () => {
    for (const key of ['config', 'admin-dashboard', 'admin-settings', 'admin-tariffs']) client.setQueryData([key], { before: true });
    await invalidateConfigQueries(client);
    for (const key of ['config', 'admin-dashboard', 'admin-settings', 'admin-tariffs']) expect(client.getQueryState([key])?.isInvalidated).toBe(true);
  });

  it('recognizes access-denied API responses separately from validation or connectivity failures', () => {
    expect(isAccessDenied(new ApiError('FORBIDDEN', 'Нет доступа', 403))).toBe(true);
    expect(isAccessDenied(new ApiError('AUTH_EXPIRED', 'Вход истёк', 401))).toBe(true);
    expect(isAccessDenied(new ApiError('VALIDATION_ERROR', 'Проверьте поля', 422))).toBe(false);
    expect(isAccessDenied(new Error('403'))).toBe(false);
  });
});
