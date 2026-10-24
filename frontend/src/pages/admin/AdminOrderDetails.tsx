import { useEffect, useId, useRef, useState, type FormEvent } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import type { AppConfig, Navigate } from '../../api/types';
import type { AdminOrder, AdminOrderFilters } from '../../api/admin-types';
import { invalidateOrderQueries, isAccessDenied, useAdminOrder } from '../../api/admin';
import { ApiError, request } from '../../api/client';
import { Icon } from '../../components/Icon';
import { StatusBadge } from '../../components/StatusBadge';
import { Timeline } from '../../components/Timeline';
import { PlatformMark } from '../../components/PlatformMark';
import { ErrorState, LoadingState } from '../../components/UiStates';
import { boxesLabel, dateMsk, decimalNumber, itemTitle, money, orderItemList, positionsLabel, statusLabel } from '../../lib/format';
import { Exact } from '../../lib/pricing';
import { deliveryAmountValid, statusRequiresConfirmation } from '../../lib/admin-validation';
import { platformFromUrl, platformName } from '../../lib/platforms';
import { copyText, haptic, openExternal, openUserChat, showConfirm } from '../../lib/telegram';

interface StatusIntent { status: string; notify: boolean; delivery_amount_rub?: string; reason?: string }
type StatusDialog = { kind: 'delivery' | 'confirm'; intent: StatusIntent; previousStatus: string; stale?: boolean };

function uncertainResponse(error: unknown): boolean {
  return !(error instanceof ApiError) || error.status === 0 || error.status >= 500 || ['INVALID_RESPONSE', 'SESSION_CHANGED'].includes(error.code);
}
function actorName(event: AdminOrder['events'][number]): string {
  if (event.actor) return ([event.actor.first_name, event.actor.last_name].filter(Boolean).join(' ') || `Пользователь #${event.actor.id}`) + (event.actor.username ? ` · @${event.actor.username}` : '');
  return event.actor_user_id === null ? 'Система' : `Пользователь #${event.actor_user_id}`;
}
function eventTitle(event: AdminOrder['events'][number], config: AppConfig): string {
  if (event.type === 'created') return 'Заказ оформлен';
  if (event.type === 'note') return 'Внутренняя заметка изменена';
  if (event.type === 'delivery_amount_set') {
    const amount = event.payload.delivery_amount_rub;
    return typeof amount === 'string' && deliveryAmountValid(amount) ? `Итоговая доставка: ${money(amount)}` : 'Указана итоговая стоимость доставки';
  }
  if (event.type === 'tracking') {
    const number = event.payload.track_number;
    return typeof number === 'string' && number ? `Трек-номер: ${number}` : 'Трек-номер удалён';
  }
  if (event.to_status) return event.from_status ? `${statusLabel(event.from_status, config.statuses)} → ${statusLabel(event.to_status, config.statuses)}` : statusLabel(event.to_status, config.statuses);
  return 'Заказ обновлён';
}
function notificationError(code: string | null): string {
  if (code === 'WRITE_ACCESS_REQUIRED') return 'Боту не разрешено писать получателю';
  if (code === 'TELEGRAM_FORBIDDEN') return 'Получатель заблокировал бота или закрыл доступ';
  if (code === 'TELEGRAM_RETRY_AFTER') return 'Telegram попросил повторить отправку позже';
  return 'Ошибка отправки. Проверьте последующие попытки или напишите вручную';
}

function ChangeDialog({ dialog, config, amount, setAmount, reason, setReason, onCancel, onSubmit }: {
  dialog: StatusDialog; config: AppConfig; amount: string; setAmount: (value: string) => void;
  reason: string; setReason: (value: string) => void; onCancel: () => void; onSubmit: () => void;
}) {
  const element = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  const descriptionId = useId();
  const errorId = useId();
  const [attempted, setAttempted] = useState(false);
  const delivery = dialog.kind === 'delivery';
  const valid = !delivery || deliveryAmountValid(amount);
  useEffect(() => {
    const node = element.current;
    if (!node) return;
    if (typeof node.showModal === 'function') node.showModal(); else node.setAttribute('open', '');
    return () => { if (node.open) node.close(); };
  }, []);
  function submit(event: FormEvent) { event.preventDefault(); setAttempted(true); if (valid) onSubmit(); }
  return <dialog className="admin-dialog" ref={element} aria-labelledby={titleId} aria-describedby={descriptionId} onCancel={event => { event.preventDefault(); onCancel(); }}>
    <form className="page-stack" onSubmit={submit}>
      <div className="admin-dialog__header"><h2 id={titleId}>{delivery ? 'Стоимость доставки' : dialog.intent.status === 'cancelled' ? 'Отменить заказ?' : 'Подтвердить смену статуса'}</h2></div>
      <p className="muted" id={descriptionId}>{delivery ? 'Укажите итоговую сумму в рублях. Клиент увидит её в своём заказе.' : `${statusLabel(dialog.previousStatus, config.statuses)} → ${statusLabel(dialog.intent.status, config.statuses)}.`}</p>
      {dialog.stale && <p className="notice notice--warning">Статус успел измениться. Данные обновлены; проверьте переход ещё раз.</p>}
      {delivery ? <label className="field">
        <span className="field-label">Итоговая доставка, ₽</span>
        <input className="input" aria-label="Итоговая доставка, ₽" inputMode="numeric" maxLength={15} autoFocus value={amount} aria-invalid={attempted && !valid} aria-describedby={attempted && !valid ? errorId : undefined} onChange={event => setAmount(event.target.value)} />
        <span className="field-hint">Целое положительное число, не больше 15 цифр.</span>
        {attempted && !valid && <span className="field-error" id={errorId} role="alert">Укажите сумму от 1 ₽ без копеек, пробелов и знаков.</span>}
      </label> : <>
        {dialog.intent.delivery_amount_rub && <p>Итоговая доставка: <strong>{money(dialog.intent.delivery_amount_rub)}</strong></p>}
        <p className="text-small muted">{dialog.intent.notify ? 'Уведомить клиента о смене статуса.' : 'Уведомление клиенту отправлено не будет.'}</p>
        {dialog.intent.status === 'cancelled' && <label className="field">
          <span className="field-label">Что случилось? Причина отмены</span>
          <textarea className="textarea" aria-label="Причина отмены" maxLength={300} rows={3} value={reason} placeholder="Например, товар недоступен у продавца" onChange={event => setReason(event.target.value)} />
          <span className="field-hint">{reason.length}/300. Необязательно — клиент увидит причину в истории заказа.</span>
        </label>}
      </>}
      <div className="admin-dialog__actions">
        <button className="button button--secondary" type="button" autoFocus={!delivery} onClick={onCancel}>Не менять</button>
        <button className="button button--primary" type="submit">{delivery ? 'Продолжить' : 'Подтвердить'}</button>
      </div>
    </form>
  </dialog>;
}

export function AdminOrderDetails({ config, orderId, onNavigate, filters }: { config: AppConfig; orderId: number; onNavigate: Navigate; filters?: AdminOrderFilters }) {
  const query = useAdminOrder(orderId);
  const queryClient = useQueryClient();
  const [selectedStatus, setSelectedStatus] = useState('');
  const [statusDirty, setStatusDirty] = useState(false);
  const [notify, setNotify] = useState(true);
  const [note, setNote] = useState('');
  const [noteDirty, setNoteDirty] = useState(false);
  const [trackNumber, setTrackNumber] = useState('');
  const [trackDirty, setTrackDirty] = useState(false);
  const [busy, setBusy] = useState<'status' | 'note' | 'check' | 'track' | null>(null);
  const [dialog, setDialog] = useState<StatusDialog | null>(null);
  const [amount, setAmount] = useState('');
  const [reason, setReason] = useState('');
  const [message, setMessage] = useState<string | null>(null);
  const [mutationError, setMutationError] = useState<Error | null>(null);
  const [uncertain, setUncertain] = useState(false);
  const [copyState, setCopyState] = useState<'idle' | 'copied' | 'failed'>('idle');
  const [linkError, setLinkError] = useState(false);
  const [chatError, setChatError] = useState(false);
  const mounted = useRef(false);
  const activeOrderId = useRef(orderId); activeOrderId.current = orderId;
  const locked = useRef(false);
  const initializedFor = useRef<number | null>(null);
  const order = query.data;
  const current = (id: number) => mounted.current && activeOrderId.current === id;

  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);
  useEffect(() => {
    if (!order) return;
    if (initializedFor.current !== order.id) {
      initializedFor.current = order.id;
      setSelectedStatus(order.status); setStatusDirty(false); setNote(order.manager_note); setNoteDirty(false);
      setTrackNumber(order.track_number ?? ''); setTrackDirty(false);
      setNotify(true); setDialog(null); setMessage(null); setMutationError(null); setUncertain(false); setBusy(null); locked.current = false;
    } else {
      if (!statusDirty) setSelectedStatus(order.status);
      if (!noteDirty) setNote(order.manager_note);
      if (!trackDirty) setTrackNumber(order.track_number ?? '');
    }
  }, [order, statusDirty, noteDirty, trackDirty]);

  async function refreshAndCheck() {
    if (locked.current || !current(orderId)) return;
    const id = orderId; locked.current = true; setBusy('check');
    try {
      const refreshed = await query.refetch();
      if (!current(id)) return;
      if (refreshed.error || !refreshed.data) { setMutationError(refreshed.error ?? new Error('Не удалось проверить заказ. Попробуйте обновить ещё раз.')); return; }
      setMutationError(null); setUncertain(false);
      if (refreshed.data.manager_note === note) setNoteDirty(false);
      if (refreshed.data.status === selectedStatus) setStatusDirty(false);
      setMessage(`Данные проверены. Текущий статус: ${statusLabel(refreshed.data.status, config.statuses)}. Проверьте сумму и историю перед повторным сохранением.`);
      await invalidateOrderQueries(queryClient, refreshed.data).catch(() => { /* The refreshed server data remains valid. */ });
    } finally { if (current(id)) { locked.current = false; setBusy(null); } }
  }

  async function saveStatus(intent: StatusIntent, confirmed = false) {
    if (locked.current || uncertain || !current(orderId)) return;
    const id = orderId; locked.current = true; setBusy('status'); setDialog(null); setMessage(null); setMutationError(null);
    try {
      const updated = await request<AdminOrder>(`/admin/orders/${id}/status`, { method: 'POST', body: JSON.stringify({ ...intent, confirmed }) });
      await invalidateOrderQueries(queryClient, updated).catch(() => { /* The server already saved the change. */ });
      if (!current(id)) return;
      setSelectedStatus(updated.status); setStatusDirty(false);
      setMessage(intent.notify ? 'Статус сохранён. Уведомление клиенту поставлено в очередь.' : 'Статус сохранён без уведомления клиента.');
      haptic('success');
    } catch (error) {
      if (!current(id)) return;
      if (error instanceof ApiError && error.code === 'CONFIRMATION_REQUIRED') {
        const refreshed = await query.refetch();
        if (!current(id)) return;
        if (refreshed.error || !refreshed.data) { setMutationError(refreshed.error ?? new Error('Не удалось обновить статус. Проверьте заказ перед подтверждением.')); return; }
        setDialog({ kind: 'confirm', intent, previousStatus: refreshed.data.status, stale: true });
      } else {
        setMutationError(error instanceof Error ? error : new Error('Не удалось сохранить статус'));
        if (uncertainResponse(error)) setUncertain(true);
        haptic('error');
      }
    } finally { if (current(id)) { locked.current = false; setBusy(null); } }
  }

  function prepareStatus() {
    if (!order || !selectedStatus || locked.current || uncertain) return;
    const intent: StatusIntent = { status: selectedStatus, notify };
    setMutationError(null); setMessage(null); setReason('');
    if (selectedStatus === 'awaiting_delivery_payment') {
      const initialAmount = order.delivery_final_rub ?? order.delivery_estimate_rub;
      setAmount(deliveryAmountValid(initialAmount) ? initialAmount : '');
      setDialog({ kind: 'delivery', intent, previousStatus: order.status });
    } else if (statusRequiresConfirmation(order.status, selectedStatus, config.statuses)) setDialog({ kind: 'confirm', intent, previousStatus: order.status });
    else void saveStatus(intent);
  }

  function submitDialog() {
    if (!dialog || locked.current) return;
    if (dialog.kind === 'delivery') {
      if (!deliveryAmountValid(amount)) return;
      const intent = { ...dialog.intent, delivery_amount_rub: amount.trim() };
      if (statusRequiresConfirmation(dialog.previousStatus, intent.status, config.statuses)) setDialog({ kind: 'confirm', intent, previousStatus: dialog.previousStatus });
      else void saveStatus(intent);
    } else {
      const note = dialog.intent.status === 'cancelled' && reason.trim() ? { reason: reason.trim().slice(0, 300) } : {};
      void saveStatus({ ...dialog.intent, ...note }, true);
    }
  }

  async function saveNote(event: FormEvent) {
    event.preventDefault();
    if (locked.current || uncertain || !noteDirty || note.length > 2000 || !current(orderId)) return;
    const id = orderId; locked.current = true; setBusy('note'); setMessage(null); setMutationError(null);
    try {
      const updated = await request<AdminOrder>(`/admin/orders/${id}/note`, { method: 'PATCH', body: JSON.stringify({ note }) });
      await invalidateOrderQueries(queryClient, updated).catch(() => { /* The server already saved the change. */ });
      if (!current(id)) return;
      setNote(updated.manager_note); setNoteDirty(false); setMessage('Заметка сохранена. Клиент её не видит.'); haptic('success');
    } catch (error) {
      if (!current(id)) return;
      setMutationError(error instanceof Error ? error : new Error('Не удалось сохранить заметку'));
      if (uncertainResponse(error)) setUncertain(true);
      haptic('error');
    } finally { if (current(id)) { locked.current = false; setBusy(null); } }
  }

  async function saveTrack(clear = false) {
    if (locked.current || uncertain || !current(orderId)) return;
    const id = orderId;
    if (clear && !(await showConfirm('Удалить трек-номер из заказа? Клиент увидит изменение в истории и не получит уведомление.'))) return;
    const number = clear ? '' : trackNumber.trim().replace(/\s+/g, ' ');
    if (!clear && (!number || !/^[A-Za-z0-9 _-]{3,64}$/.test(number))) {
      setMutationError(new Error('Трек-номер: от 3 до 64 символов, латиница, цифры, пробел, дефис и подчёркивание.'));
      haptic('error'); return;
    }
    locked.current = true; setBusy('track'); setMessage(null); setMutationError(null);
    try {
      const updated = await request<AdminOrder>(`/admin/orders/${id}/tracking`, { method: 'POST', body: JSON.stringify({ number, notify: !clear }) });
      await invalidateOrderQueries(queryClient, updated).catch(() => { /* The server already saved the change. */ });
      if (!current(id)) return;
      setTrackNumber(updated.track_number ?? ''); setTrackDirty(false);
      setMessage(clear ? 'Трек-номер удалён.' : 'Трек-номер сохранён. Уведомление клиенту поставлено в очередь.');
      haptic('success');
    } catch (error) {
      if (!current(id)) return;
      setMutationError(error instanceof Error ? error : new Error('Не удалось сохранить трек-номер'));
      if (uncertainResponse(error)) setUncertain(true);
      haptic('error');
    } finally { if (current(id)) { locked.current = false; setBusy(null); } }
  }

  async function copyNumber() {
    if (!order) return;
    const id = orderId; const copied = await copyText(order.public_no);
    if (current(id)) { setCopyState(copied ? 'copied' : 'failed'); haptic(copied ? 'success' : 'error'); }
  }

  if (isAccessDenied(query.error) || isAccessDenied(mutationError)) return <ErrorState message="Доступ к заказу закрыт. Ваша роль могла измениться." onRetry={() => void refreshAndCheck()} />;
  if (query.isPending) return <LoadingState label="Открываем заказ клиента" />;
  if (!order) return <ErrorState message={query.error?.message || 'Заказ не найден'} onRetry={() => void query.refetch()} />;
  const minimumCommission = new Exact(order.goods_rub).mul(order.commission_percent).div(100).lte(order.commission_min_rub);
  const events = [...order.events].sort((a, b) => a.created_at.localeCompare(b.created_at) || a.id - b.id);
  const items = orderItemList(order);
  const blocked = Boolean(busy) || uncertain;

  return <div className="page-stack admin-section">
    <button className="button button--ghost" type="button" onClick={() => onNavigate({ name: 'admin', view: 'orders', filters })}><Icon name="arrow-left" size={18} />К списку заказов</button>
    <header className="page-heading admin-detail-heading">
      <div className="details-header"><h2 className="page-title details-number">{order.public_no}</h2><button className="icon-button" type="button" aria-label="Скопировать номер заказа" onClick={() => void copyNumber()}><Icon name={copyState === 'copied' ? 'check' : 'copy'} size={22} /></button></div>
      {copyState === 'copied' && <p className="field-hint" role="status">Номер скопирован</p>}
      {copyState === 'failed' && <p className="field-error" role="status">Скопируйте номер вручную: {order.public_no}</p>}
      <StatusBadge status={order.status} statuses={config.statuses} />
      <p className="muted text-small">Оформлен {dateMsk(order.created_at)} · обновлён {dateMsk(order.updated_at)}</p>
    </header>
    {query.isError && <p className="notice notice--warning">Не удалось обновить заказ. Показаны последние загруженные данные.</p>}
    {mutationError && !uncertain && <p className="notice notice--warning" role="alert">{mutationError.message}</p>}
    {uncertain && <div className="notice notice--warning" role="alert"><p>Связь оборвалась: изменение могло сохраниться. Обновите заказ и проверьте историю перед повторным действием, чтобы не отправить уведомление дважды.</p><button className="button button--secondary" type="button" disabled={Boolean(busy)} onClick={() => void refreshAndCheck()}><Icon name="refresh" size={17} />{busy === 'check' ? 'Проверяем…' : 'Обновить и проверить'}</button></div>}
    {message && <p className="notice notice--info" role="status">{message}</p>}

    <section className="card page-stack">
      <div className="section-heading"><h3>Клиент</h3><Icon name="send" size={20} /></div>
      <div className="admin-meta"><strong>{[order.client.first_name, order.client.last_name].filter(Boolean).join(' ') || 'Клиент'}</strong>{order.client.username && <span>@{order.client.username}</span>}<span className="muted text-small">Telegram ID: {order.client.tg_id}</span></div>
      {(order.notification_warning || !order.client.can_write) && <p className="notice notice--warning">Клиент не получил уведомление. Напишите вручную.{!order.client.can_write && ' Боту не разрешено писать этому клиенту.'}</p>}
      <button className="button button--secondary button--block" type="button" onClick={() => setChatError(!openUserChat(order.client))}>Написать клиенту<Icon name="external-link" size={18} /></button>
      {chatError && <p className="field-error" role="alert">Не удалось открыть чат. Найдите клиента по username или Telegram ID, указанному выше.</p>}
    </section>

    <section className="card" aria-label="Этапы заказа"><Timeline statuses={config.statuses} status={order.status} /></section>
    <section className="card page-stack">
      <div className="section-heading"><h3>Смена статуса</h3><button className="button button--ghost" type="button" disabled={blocked || query.isFetching} onClick={() => void refreshAndCheck()}><Icon name="refresh" size={16} />Обновить</button></div>
      <label className="field"><span className="field-label">Новый статус</span><select className="input" aria-label="Новый статус" value={selectedStatus} disabled={blocked} onChange={event => { setSelectedStatus(event.target.value); setStatusDirty(event.target.value !== order.status); }}>
        {[...config.statuses].sort((a, b) => a.order - b.order).map(status => <option key={status.key} value={status.key}>{status.icon} {status.name}</option>)}
      </select></label>
      <label className="admin-check"><input type="checkbox" checked={notify} disabled={blocked} onChange={event => setNotify(event.target.checked)} /><span>Уведомить клиента</span></label>
      <button className="button button--primary button--block" type="button" disabled={blocked || !selectedStatus || (!statusDirty && selectedStatus !== 'awaiting_delivery_payment')} onClick={prepareStatus}>{busy === 'status' ? 'Сохраняем…' : 'Сохранить статус'}</button>
      <p className="field-hint">Откат статуса и отмена требуют подтверждения. Для ожидания оплаты доставки нужна итоговая сумма.</p>
    </section>

    <section className="card product-details page-stack">
      <div className="section-heading"><h3>Товары</h3><span className="chip">{positionsLabel(items.length)}</span></div>
      <div className="breakdown">
        {items.map(item => <div className="breakdown-row" key={item.id || item.position}>
          <dt>
            <span className="inline-row"><PlatformMark link={item.link} size="sm" /><strong>{itemTitle(item)}</strong></span>
            <small>{decimalNumber(item.price_cny, 2)} ¥ × {item.quantity} · {platformName(platformFromUrl(item.link))}</small>
            {item.comment && <small>{item.comment}</small>}
          </dt>
          <dd><button className="icon-button" type="button" aria-label={`Открыть товар «${itemTitle(item)}»`} onClick={() => setLinkError(!openExternal(item.link))}><Icon name="external-link" size={20} /></button></dd>
        </div>)}
        <div className="breakdown-row"><dt>Стоимость товаров</dt><dd>{money(order.goods_rub)}</dd></div>
      </div>
      {linkError && <p className="field-error" role="alert">Не удалось открыть ссылку. Допустимы только ссылки http:// и https://.</p>}
    </section>

    <section className="card page-stack">
      <div className="section-heading"><h3>Трек-номер</h3><Icon name="truck" size={20} /></div>
      <label className="field"><span className="field-label">Номер отслеживания</span><input className="input" aria-label="Номер отслеживания" maxLength={64} disabled={blocked} value={trackNumber} placeholder="Например, CN123456789" onChange={event => { setTrackNumber(event.target.value); setTrackDirty(event.target.value.trim() !== (order.track_number ?? '')); }} /><span className="field-hint">От 3 до 64 символов: латиница, цифры, пробел, дефис, подчёркивание. Клиент увидит номер в заказе и сможет проверить статус в приложении или командой /track.</span></label>
      <div className="admin-dialog__actions">
        <button className="button button--secondary" type="button" disabled={blocked || !trackDirty} onClick={() => void saveTrack()}>{busy === 'track' ? 'Сохраняем…' : 'Сохранить трек-номер'}</button>
        {order.track_number && <button className="button button--danger" type="button" disabled={blocked} onClick={() => void saveTrack(true)}>Удалить</button>}
      </div>
    </section>

    <div className="admin-detail-grid">
      <section className="card card--glow">
        <div className="section-heading"><h3>Расчёт при оформлении</h3><Icon name="shield" size={20} /></div>
        <p className="snapshot-note muted text-small">Сохранённый курс и тариф. Текущие настройки не меняют этот заказ.</p>
        <div className="breakdown">
          <div className="breakdown-row"><div><span>Товар</span><small>{decimalNumber(order.price_cny, 2)} ¥ × {order.quantity} × {decimalNumber(order.rate, 4)}</small></div><strong>{money(order.goods_rub)}</strong></div>
          <div className="breakdown-row"><div><span>Комиссия</span><small>{minimumCommission ? `Минимальная: ${money(order.commission_min_rub)}` : `${decimalNumber(order.commission_percent, 2)}% от стоимости товара`}</small></div><strong>{money(order.commission_rub)}</strong></div>
          <div className="breakdown-row breakdown-row--total"><span>К оплате за выкуп</span><strong className="money">{money(order.total_rub)}</strong></div>
        </div>
      </section>
      <section className="card card--muted">
        <div className="section-heading"><h3>Доставка</h3><Icon name="truck" size={22} /></div>
        <div className="breakdown">
          <div className="breakdown-row"><span>Тариф при оформлении</span><strong>{order.tariff_name}</strong></div>
          {order.tariff_price_currency === 'cny' && <div className="breakdown-row"><span>Цена тарифа</span><strong>{decimalNumber(order.tariff_price_value, 2)} ¥ / кг</strong></div>}
          <div className="breakdown-row"><span>Ставка за кг</span><strong>{decimalNumber(order.tariff_price_per_kg, 2)} ₽ / кг</strong></div>
          {order.boxes > 1 && <div className="breakdown-row"><span>Обрешётка</span><strong>{boxesLabel(order.boxes)}</strong></div>}
          <div className="breakdown-row"><span>Примерный вес</span><strong>{decimalNumber(order.weight_kg, 3)} кг</strong></div>
          <div className="breakdown-row"><span>Ориентировочно</span><strong>{money(order.delivery_estimate_rub)}</strong></div>
          {order.delivery_final_rub !== null && <div className="breakdown-row breakdown-row--total"><span>Итоговая доставка</span><strong className="money">{money(order.delivery_final_rub)}</strong></div>}
        </div>
      </section>
    </div>

    <form className="card page-stack" onSubmit={event => void saveNote(event)}>
      <div className="section-heading"><h3>Внутренняя заметка</h3><Icon name="clipboard" size={20} /></div>
      <label className="field"><span className="field-label">Только для владельца и менеджеров</span><textarea className="textarea" aria-label="Только для владельца и менеджеров" maxLength={2000} disabled={Boolean(busy)} value={note} onChange={event => { setNote(event.target.value); setNoteDirty(event.target.value !== order.manager_note); }} /><span className="field-hint">{note.length} / 2000. Клиент заметку не видит.</span></label>
      <button className="button button--secondary button--block" type="submit" disabled={blocked || !noteDirty || note.length > 2000}>{busy === 'note' ? 'Сохраняем…' : 'Сохранить заметку'}</button>
    </form>

    <section className="section">
      <div className="section-heading"><h3>История заказа</h3><span className="muted text-small">МСК</span></div>
      {events.length ? <ol className="event-list admin-history-list">{events.map(event => <li className="event-item" key={event.id}><span className="event-dot" aria-hidden="true" /><div><strong>{eventTitle(event, config)}</strong><p className="muted text-small">{actorName(event)}</p>{event.type === 'note' && <p className="admin-event-note">{typeof event.payload.note === 'string' && event.payload.note ? event.payload.note : 'Заметка очищена'}</p>}{event.type === 'status_changed' && typeof event.payload.cancel_reason === 'string' && event.payload.cancel_reason && <p className="admin-event-note">Причина отмены: {event.payload.cancel_reason}</p>}<time className="event-time" dateTime={event.created_at}>{dateMsk(event.created_at)}</time></div></li>)}</ol> : <p className="muted">История пока пуста.</p>}
    </section>

    <section className="card page-stack">
      <div className="section-heading"><h3>Уведомления</h3><Icon name="send" size={20} /></div>
      <p className="muted text-small">Здесь отражены выполненные попытки отправки. Новое уведомление появится после обработки очереди ботом.</p>
      {order.notifications.length ? <ul className="admin-notification-list">{[...order.notifications].reverse().map((entry, index) => <li key={`${entry.created_at}-${entry.user_id}-${entry.kind}-${index}`}>
        <strong>{entry.user_id === order.user_id ? 'Клиент' : `Администратор #${entry.user_id}`} · {entry.kind === 'created' ? 'Заказ оформлен' : entry.kind === 'admin_created' ? 'Новый заказ' : entry.kind === 'tracking' ? 'Трек-номер' : statusLabel(entry.kind, config.statuses)}</strong>
        <p className={entry.ok ? 'text-small muted' : 'field-error'}>{entry.ok ? 'Отправлено' : notificationError(entry.error)}</p><time className="event-time" dateTime={entry.created_at}>{dateMsk(entry.created_at)}</time>
      </li>)}</ul> : <p className="muted">Попыток отправки ещё нет.</p>}
    </section>
    {dialog && <ChangeDialog key={dialog.kind} dialog={dialog} config={config} amount={amount} setAmount={setAmount} reason={reason} setReason={setReason} onCancel={() => setDialog(null)} onSubmit={submitDialog} />}
  </div>;
}
