import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { AuthResponse } from './types';

type Client = typeof import('./client');
let client: Client;

function json(value: unknown, status = 200): Response { return new Response(JSON.stringify(value), { status, headers: { 'Content-Type': 'application/json' } }); }
function session(token: string): AuthResponse {
  return { access_token: token, token_type: 'bearer', expires_in: 900, role: 'client', user: { id: 1, tg_id: 123, first_name: 'Тест', last_name: null, username: null, can_write: false } };
}
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}
function authorization(options?: RequestInit): string | null { return new Headers(options?.headers).get('Authorization'); }

beforeEach(async () => {
  vi.resetModules();
  vi.stubGlobal('window', { Telegram: { WebApp: { initData: 'signed-launch-data' } } });
  vi.stubGlobal('localStorage', { getItem: vi.fn(), setItem: vi.fn(), removeItem: vi.fn() });
  vi.stubGlobal('sessionStorage', { getItem: vi.fn(), setItem: vi.fn(), removeItem: vi.fn() });
  client = await import('./client');
});
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });

describe('in-memory authentication and request retries', () => {
  it('coalesces simultaneous initial authentication and never persists credentials', async () => {
    const pending = deferred<Response>();
    const fetchMock = vi.fn((_path: string, _options?: RequestInit) => pending.promise);
    vi.stubGlobal('fetch', fetchMock);
    const first = client.authenticate(); const second = client.authenticate();
    pending.resolve(json(session('private-token')));
    expect(await first).toEqual(await second);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(JSON.parse(fetchMock.mock.calls[0][1]?.body as string)).toEqual({ initData: 'signed-launch-data' });
    expect(localStorage.setItem).not.toHaveBeenCalled();
    expect(sessionStorage.setItem).not.toHaveBeenCalled();
  });

  it('refreshes once for parallel 401 responses and preserves an order payload on retry', async () => {
    const refresh = deferred<Response>();
    let authCalls = 0;
    const orderBodies: string[] = [];
    const fetchMock = vi.fn((path: string, options?: RequestInit) => {
      if (path === '/api/auth/telegram') return ++authCalls === 1 ? Promise.resolve(json(session('old'))) : refresh.promise;
      if (path === '/api/orders') orderBodies.push(options?.body as string);
      return Promise.resolve(authorization(options) === 'Bearer new' ? json({ ok: true }) : json({ code: 'TOKEN_EXPIRED', message: 'Срок входа истёк' }, 401));
    });
    vi.stubGlobal('fetch', fetchMock);
    await client.authenticate();
    const payload = { idempotency_key: '00000000-0000-4000-8000-000000000001', price_cny: '300.00' };
    const first = client.post('/orders', payload); const second = client.request('/config');
    await vi.waitFor(() => expect(authCalls).toBe(2));
    refresh.resolve(json(session('new')));
    expect(await first).toEqual({ ok: true }); expect(await second).toEqual({ ok: true });
    expect(authCalls).toBe(2);
    expect(orderBodies).toEqual([JSON.stringify(payload), JSON.stringify(payload)]);
  });

  it('does not refresh again when a late 401 belongs to the token that was already replaced', async () => {
    const late = deferred<Response>(); let authCalls = 0; let oldCalls = 0;
    vi.stubGlobal('fetch', vi.fn((path: string, options?: RequestInit) => {
      if (path === '/api/auth/telegram') return Promise.resolve(json(session(++authCalls === 1 ? 'old' : 'new')));
      if (authorization(options) === 'Bearer old') return ++oldCalls === 1 ? Promise.resolve(json({ code: 'TOKEN_EXPIRED', message: 'Вход истёк' }, 401)) : late.promise;
      return Promise.resolve(json({ ok: true }));
    }));
    await client.authenticate();
    const first = client.request('/first'); const second = client.request('/second');
    await first;
    late.resolve(json({ code: 'TOKEN_EXPIRED', message: 'Вход истёк' }, 401));
    expect(await second).toEqual({ ok: true });
    expect(authCalls).toBe(2);
  });

  it('does not restore a cleared session when an old authentication finishes', async () => {
    const pending = deferred<Response>(); const listener = vi.fn();
    const fetchMock = vi.fn((path: string, _options?: RequestInit) => path === '/api/auth/telegram' ? pending.promise : Promise.resolve(json({ ok: true })));
    vi.stubGlobal('fetch', fetchMock); client.setSessionListener(listener);
    const authenticating = client.authenticate().catch(() => undefined);
    client.clearSession(); pending.resolve(json(session('discard-me'))); await authenticating;
    await client.request('/probe');
    expect(listener).not.toHaveBeenCalled();
    expect(authorization(fetchMock.mock.calls[fetchMock.mock.calls.length - 1]?.[1])).toBeNull();
  });

  it('does not replay an order from a cleared session after its late 401', async () => {
    const pending = deferred<Response>(); let authCalls = 0; let orderCalls = 0;
    vi.stubGlobal('fetch', vi.fn((path: string) => {
      if (path === '/api/auth/telegram') { authCalls += 1; return Promise.resolve(json(session('old'))); }
      orderCalls += 1;
      return pending.promise;
    }));
    await client.authenticate();
    const request = client.post('/orders', { idempotency_key: '00000000-0000-4000-8000-000000000002' });
    const result = expect(request).rejects.toMatchObject({ code: 'SESSION_CHANGED' });
    client.clearSession(); pending.resolve(json({ code: 'TOKEN_EXPIRED', message: 'Вход истёк' }, 401));
    await result;
    expect(authCalls).toBe(1); expect(orderCalls).toBe(1);
  });

  it('retries a protected request at most once when the refreshed token is also rejected', async () => {
    let authCalls = 0; let protectedCalls = 0;
    vi.stubGlobal('fetch', vi.fn((path: string) => {
      if (path === '/api/auth/telegram') return Promise.resolve(json(session(`token-${++authCalls}`)));
      protectedCalls += 1;
      return Promise.resolve(json({ code: 'AUTH_EXPIRED', message: 'Откройте приложение заново' }, 401));
    }));
    await client.authenticate();
    await expect(client.request('/config')).rejects.toMatchObject({ code: 'AUTH_EXPIRED', status: 401, message: 'Откройте приложение заново' });
    expect(authCalls).toBe(2); expect(protectedCalls).toBe(2);
  });

  it('converts network failures into the same Russian error during requests and authentication', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')));
    await expect(client.request('/config')).rejects.toMatchObject({ code: 'NETWORK_ERROR', status: 0, message: expect.stringContaining('Нет связи') });
    await expect(client.authenticate()).rejects.toMatchObject({ code: 'NETWORK_ERROR', status: 0, message: expect.stringContaining('Нет связи') });
  });

  it('handles a non-object error response without exposing a TypeError', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(json(null, 503)));
    await expect(client.request('/config')).rejects.toBeInstanceOf(client.ApiError);
  });

  it('preserves cancellation without converting it into a connectivity failure', async () => {
    const aborted = new DOMException('Cancelled', 'AbortError');
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(aborted));
    await expect(client.request('/config', { signal: AbortSignal.abort() })).rejects.toBe(aborted);
  });

  it('refreshes a revoked admin role without replaying the denied mutation', async () => {
    let authCalls = 0; let mutationCalls = 0;
    const listener = vi.fn(); client.setSessionListener(listener);
    vi.stubGlobal('fetch', vi.fn((path: string) => {
      if (path === '/api/auth/telegram') return Promise.resolve(json({ ...session(`token-${++authCalls}`), role: authCalls === 1 ? 'owner' : 'manager' }));
      mutationCalls += 1;
      return Promise.resolve(json({ code: 'FORBIDDEN', message: 'Настройки доступны только владельцу' }, 403));
    }));
    await client.authenticate();
    await expect(client.request('/admin/settings', { method: 'PUT', body: JSON.stringify({ rate_cny_rub: '14' }) })).rejects.toMatchObject({ code: 'FORBIDDEN', status: 403 });
    expect(authCalls).toBe(2); expect(mutationCalls).toBe(1);
    expect(listener.mock.calls[listener.mock.calls.length - 1][0]).toMatchObject({ role: 'manager' });
  });

  it('keeps the original forbidden response if role refresh fails', async () => {
    let authCalls = 0; let deniedCalls = 0;
    vi.stubGlobal('fetch', vi.fn((path: string) => {
      if (path === '/api/auth/telegram') return Promise.resolve(++authCalls === 1 ? json(session('old')) : json({ code: 'UNAVAILABLE', message: 'Сервер недоступен' }, 503));
      deniedCalls += 1;
      return Promise.resolve(json({ code: 'FORBIDDEN', message: 'Нет прав на этот заказ' }, 403));
    }));
    await client.authenticate();
    await expect(client.post('/admin/orders/77/status', { status: 'purchased' })).rejects.toMatchObject({ code: 'FORBIDDEN', status: 403, message: 'Нет прав на этот заказ' });
    expect(authCalls).toBe(2); expect(deniedCalls).toBe(1);
  });

  it('does not trigger administrator role refresh for a public endpoint 403', async () => {
    let authCalls = 0;
    vi.stubGlobal('fetch', vi.fn((path: string) => {
      if (path === '/api/auth/telegram') { authCalls += 1; return Promise.resolve(json(session('old'))); }
      return Promise.resolve(json({ code: 'FORBIDDEN', message: 'Нет доступа' }, 403));
    }));
    await client.authenticate();
    await expect(client.request('/orders/77')).rejects.toMatchObject({ status: 403 });
    expect(authCalls).toBe(1);
  });
});
