import type { AuthResponse } from './types';
import { webApp } from '../lib/telegram';

export class ApiError extends Error {
  constructor(public code: string, message: string, public status: number) { super(message); this.name = 'ApiError'; }
}
let accessToken: string | null = null;
let authentication: Promise<AuthResponse> | null = null;
let generation = 0;
let sessionListener: ((session: AuthResponse) => void) | null = null;
export function setSessionListener(listener: ((session: AuthResponse) => void) | null): void { sessionListener = listener; }

async function parseResponse<T>(response: Response): Promise<T> {
  let data: unknown;
  try { data = await response.json(); } catch { throw new ApiError('INVALID_RESPONSE', 'Сервер вернул неполный ответ. Попробуйте ещё раз.', response.status); }
  if (!response.ok) {
    const error = data && typeof data === 'object' ? data as { code?: string; message?: string } : {};
    throw new ApiError(error.code ?? 'REQUEST_FAILED', error.message ?? 'Не удалось выполнить запрос.', response.status);
  }
  return data as T;
}
export async function authenticate(): Promise<AuthResponse> {
  if (authentication) return authentication;
  const epoch = generation;
  const attempt = (async () => {
    let response: Response;
    try { response = await fetch('/api/auth/telegram', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ initData: webApp()?.initData ?? '' }) }); }
    catch { throw new ApiError('NETWORK_ERROR', 'Сервер не отвечает. Повторите попытку.', 0); }
    const session = await parseResponse<AuthResponse>(response);
    if (epoch !== generation) throw new ApiError('SESSION_CHANGED', 'Сессия изменилась. Повторите вход.', 401);
    accessToken = session.access_token;
    sessionListener?.(session);
    return session;
  })();
  authentication = attempt;
  try { return await attempt; } catch (error) { if (epoch === generation) accessToken = null; throw error; } finally { if (authentication === attempt) authentication = null; }
}
export async function request<T>(path: string, options: RequestInit = {}, renewed = false): Promise<T> {
  const epoch = generation;
  const usedToken = accessToken;
  let response: Response;
  try {
    response = await fetch('/api' + path, { ...options, headers: { 'Content-Type': 'application/json', ...(usedToken ? { Authorization: `Bearer ${usedToken}` } : {}), ...options.headers } });
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error;
    throw new ApiError('NETWORK_ERROR', 'Сервер не отвечает. Повторите попытку.', 0);
  }
  if (epoch !== generation) throw new ApiError('SESSION_CHANGED', 'Сессия изменилась. Повторите вход.', 401);
  if (response.status === 401 && !renewed) {
    if (!accessToken || accessToken === usedToken) await authenticate();
    if (epoch !== generation) throw new ApiError('SESSION_CHANGED', 'Сессия изменилась. Повторите вход.', 401);
    return request<T>(path, options, true);
  }
  if (response.status === 403 && path.startsWith('/admin/') && !renewed) {
    // Recheck the role after a server-side permissions change, without replaying the denied request.
    try { await authenticate(); } catch { /* Preserve the original access-denied response. */ }
    if (epoch !== generation) throw new ApiError('SESSION_CHANGED', 'Сессия изменилась. Повторите вход.', 401);
  }
  return parseResponse<T>(response);
}
export function post<T>(path: string, body: unknown): Promise<T> { return request<T>(path, { method: 'POST', body: JSON.stringify(body) }); }
export function clearSession(): void { generation++; accessToken = null; authentication = null; }
