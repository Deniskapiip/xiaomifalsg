import { useEffect, useRef, useState } from 'react';
import type { AppConfig, Navigate, Order, OrderPage, User } from '../api/types';
import { post, request } from '../api/client';
import { Icon } from '../components/Icon';
import { readStored, userStorageKey, writeStored } from '../lib/storage';
import { money } from '../lib/format';
import { inTelegram, openTelegram, requestWriteAccess, supports, webApp } from '../lib/telegram';

interface WriteAccessRecord { asked: true; allowed: boolean; pending: boolean }
type NotificationState = { phase: 'checking' | 'skipped' } | { phase: 'saved'; allowed: boolean } | { phase: 'failed'; allowed: boolean | null };

function validRecord(value: unknown): value is WriteAccessRecord {
  return Boolean(value && typeof value === 'object' && 'asked' in value && value.asked === true && 'allowed' in value && typeof value.allowed === 'boolean' && 'pending' in value && typeof value.pending === 'boolean');
}

async function persistPermission(key: string, allowed: boolean, isCurrent: () => boolean): Promise<NotificationState> {
  // Keep the native answer before sending it. A failed request can retry the same
  // answer after a restart without displaying the Telegram permission dialog again.
  writeStored<WriteAccessRecord>(key, { asked: true, allowed, pending: true });
  if (!isCurrent()) return { phase: 'skipped' };
  try {
    await post('/me/write-access', { allowed });
    if (!isCurrent()) return { phase: 'skipped' };
    writeStored<WriteAccessRecord>(key, { asked: true, allowed, pending: false });
    return { phase: 'saved', allowed };
  } catch {
    return { phase: 'failed', allowed };
  }
}

async function prepareNotifications(key: string, isCurrent: () => boolean): Promise<NotificationState> {
  if (!inTelegram()) return { phase: 'skipped' };
  try {
    const stored: unknown = await readStored<WriteAccessRecord>(key);
    if (!isCurrent()) return { phase: 'skipped' };
    if (validRecord(stored)) return stored.pending ? persistPermission(key, stored.allowed, isCurrent) : { phase: 'saved', allowed: stored.allowed };
    if (!supports('6.9') || !webApp()?.requestWriteAccess) return { phase: 'skipped' };
    const orders = await request<OrderPage>('/orders?limit=1&offset=0');
    if (!isCurrent() || orders.total !== 1) return { phase: 'skipped' };
    const allowed = await requestWriteAccess();
    if (allowed === null) return { phase: 'skipped' };
    return persistPermission(key, allowed, isCurrent);
  } catch {
    return { phase: 'failed', allowed: null };
  }
}

export function OrderSuccess({ order, config, user, onNavigate }: {
  order: Order; config: AppConfig; user: User; onNavigate: Navigate;
}) {
  const [notifications, setNotifications] = useState<NotificationState>({ phase: 'checking' });
  const [retrying, setRetrying] = useState(false);
  const [contactFailed, setContactFailed] = useState(false);
  const mounted = useRef(false);
  const currentKey = useRef('');
  const retryGuard = useRef(false);
  const flight = useRef<{ key: string; promise: Promise<NotificationState> } | null>(null);
  const key = userStorageKey(user.tg_id, 'write_access');
  currentKey.current = key;
  const manager = config.contacts.manager.replace(/^@/, '');

  useEffect(() => {
    mounted.current = true;
    let cancelled = false;
    // StrictMode's repeated effect subscribes to the same in-flight operation.
    // The mounted/key guards also prevent a delayed native dialog after leaving.
    if (!flight.current || flight.current.key !== key) {
      flight.current = { key, promise: prepareNotifications(key, () => mounted.current && currentKey.current === key) };
    }
    void flight.current.promise.then(result => { if (!cancelled && currentKey.current === key) setNotifications(result); });
    return () => { cancelled = true; mounted.current = false; };
  }, [key]);

  async function retryNotifications() {
    if (retryGuard.current || notifications.phase !== 'failed') return;
    retryGuard.current = true;
    setRetrying(true);
    const result = notifications.allowed === null
      ? await prepareNotifications(key, () => mounted.current && currentKey.current === key)
      : await persistPermission(key, notifications.allowed, () => mounted.current && currentKey.current === key);
    if (mounted.current && currentKey.current === key) { setNotifications(result); setRetrying(false); }
    retryGuard.current = false;
  }

  function contactManager() {
    setContactFailed(!openTelegram(manager, `Здравствуйте! Я оформил заказ ${order.public_no}. Хочу уточнить подтверждение и оплату выкупа.`));
  }

  return (
    <div className="page page-stack">
      <header className="success-header"><span className="success-mark" aria-hidden="true"><Icon name="check" size={42} /></span><span className="eyebrow">СЛЕДУЮЩИЙ ШАГ — ПОДТВЕРЖДЕНИЕ</span><h1>Заказ принят</h1><span className="success-number"><Icon name="package" size={18} />{order.public_no}</span><p>Менеджер @{manager} свяжется с вами для подтверждения деталей и оплаты выкупа.</p></header>

      <section className="card success-next"><h2>Что дальше</h2><p>Можно написать менеджеру сейчас. Номер заказа уже будет в сообщении — останется уточнить детали.</p>{order.extras_total_rub !== '0' && <p className="field-hint">Доп. услуги: {money(order.extras_total_rub)}. К оплате за выкуп с услугами: {money(order.total_with_extras_rub)}.</p>}<button className="button button--primary button--block" type="button" onClick={contactManager}><Icon name="send" size={19} />Написать менеджеру</button>{contactFailed && <p className="field-error" role="alert">Не удалось открыть чат. Найдите менеджера @{manager} в Telegram и отправьте номер {order.public_no}.</p>}</section>

      {notifications.phase === 'checking' && inTelegram() && <p className="notice notice--info" role="status"><Icon name="info" size={18} />Настраиваем уведомления о заказе…</p>}
      {notifications.phase === 'saved' && <p className={`notice ${notifications.allowed ? 'notice--success' : 'notice--info'}`} role="status"><Icon name={notifications.allowed ? 'check' : 'info'} size={18} />{notifications.allowed ? 'Уведомления о заказе будут приходить в этот чат.' : 'Уведомления выключены. Следите за статусом в разделе «Мои заказы».'}</p>}
      {notifications.phase === 'failed' && <div className="notice notice--warning" role="status"><Icon name="info" size={18} /><div><p>{notifications.allowed === null ? 'Не получилось проверить уведомления. Ваш заказ уже принят.' : 'Не получилось сохранить настройку уведомлений. Ваш заказ уже принят.'}</p><button className="button button--ghost" type="button" disabled={retrying} onClick={() => void retryNotifications()}><Icon name="refresh" size={16} />{retrying ? 'Сохраняем…' : 'Повторить'}</button></div></div>}

      <button className="button button--secondary button--block" type="button" onClick={() => onNavigate({ name: 'orders' })}><Icon name="package" size={19} />К заказам</button>
      <p className="muted text-small text-center">Расчёт и все обновления сохранены в карточке заказа.</p>
    </div>
  );
}
