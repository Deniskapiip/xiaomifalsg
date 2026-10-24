import { useEffect, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { ApiError, request } from '../../api/client';
import { invalidateConfigQueries, isAccessDenied, useAdminTariffs } from '../../api/admin';
import type { TariffInput } from '../../api/admin-types';
import type { Navigate, Tariff } from '../../api/types';
import { EmptyState, ErrorState, LoadingState } from '../../components/UiStates';
import { Icon } from '../../components/Icon';
import { validateTariff } from '../../lib/admin-validation';
import type { TariffFields } from '../../lib/admin-validation';
import { dateMsk, decimalNumber } from '../../lib/format';
import { Exact } from '../../lib/pricing';
import { haptic } from '../../lib/telegram';

interface Editor { id: number | null; fields: TariffFields }
interface UncertainSave { id: number | null; input: TariffInput; beforeIds: number[] }
function fieldsFrom(tariff: Tariff): TariffFields {
  return { name: tariff.name, price_per_kg_rub: tariff.price_per_kg_rub, eta_text: tariff.eta_text, description: tariff.description, is_active: tariff.is_active, sort_order: String(tariff.sort_order) };
}
function sameValues(tariff: Tariff, input: TariffInput): boolean {
  return tariff.name === input.name && new Exact(tariff.price_per_kg_rub).eq(input.price_per_kg_rub) && tariff.eta_text === input.eta_text && tariff.description === input.description && tariff.is_active === input.is_active && tariff.sort_order === input.sort_order;
}
function outcomeUnknown(error: unknown): boolean {
  return !(error instanceof ApiError) || error.status === 0 || error.status >= 500 || error.code === 'INVALID_RESPONSE';
}

export function AdminTariffs({ onNavigate }: { onNavigate: Navigate }) {
  const tariffs = useAdminTariffs();
  const queryClient = useQueryClient();
  const [editor, setEditor] = useState<Editor | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [failure, setFailure] = useState<Error | null>(null);
  const [message, setMessage] = useState('');
  const [messageTone, setMessageTone] = useState<'success' | 'warning'>('success');
  const [busy, setBusy] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [uncertain, setUncertain] = useState<UncertainSave | null>(null);
  const inFlight = useRef(false);
  const mounted = useRef(false);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);

  function revealEditor(next: Editor) {
    if (inFlight.current || uncertain) return;
    setEditor(next);
    setDirty(next.id === null);
    setErrors({});
    setFailure(null);
    setMessage('');
    requestAnimationFrame(() => {
      if (!mounted.current) return;
      document.getElementById('admin-tariff-editor')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
      document.getElementById('admin-tariff-name')?.focus({ preventScroll: true });
    });
  }

  function newTariff() {
    const sortOrder = Math.min(10000, Math.max(0, ...(tariffs.data ?? []).map(tariff => tariff.sort_order)) + 10);
    revealEditor({ id: null, fields: { name: '', price_per_kg_rub: '', eta_text: '', description: '', is_active: false, sort_order: String(sortOrder) } });
  }

  function change<K extends keyof TariffFields>(key: K, value: TariffFields[K]) {
    if (inFlight.current || uncertain) return;
    setEditor(previous => previous && { ...previous, fields: { ...previous.fields, [key]: value } });
    setDirty(true);
    setErrors(previous => ({ ...previous, [key]: '' }));
    setMessage('');
  }

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!mounted.current || inFlight.current || !editor || uncertain) return;
    const validation = validateTariff(editor.fields);
    setErrors(validation.errors);
    if (!validation.input) { haptic('error'); return; }
    const pending = { id: editor.id, input: validation.input, beforeIds: (tariffs.data ?? []).map(tariff => tariff.id) };
    inFlight.current = true;
    setBusy(true);
    setFailure(null);
    setMessage('');
    try {
      const result = await request<Tariff>(editor.id === null ? '/admin/tariffs' : `/admin/tariffs/${editor.id}`, { method: editor.id === null ? 'POST' : 'PUT', body: JSON.stringify(validation.input) });
      if (!mounted.current) return;
      queryClient.setQueryData<Tariff[]>(['admin-tariffs'], previous => [...(previous ?? []).filter(tariff => tariff.id !== result.id), result].sort((left, right) => left.sort_order - right.sort_order || left.id - right.id));
      setEditor({ id: result.id, fields: fieldsFrom(result) });
      setDirty(false);
      setMessage(result.is_active ? 'Тариф сохранён и доступен для новых заказов.' : 'Тариф сохранён. Он скрыт при оформлении новых заказов.');
      setMessageTone('success');
      haptic('success');
      await invalidateConfigQueries(queryClient).catch(() => undefined);
    } catch (error) {
      if (!mounted.current) return;
      setFailure(error instanceof Error ? error : new Error('Не удалось сохранить тариф.'));
      if (outcomeUnknown(error)) setUncertain(pending);
      haptic('error');
    } finally {
      inFlight.current = false;
      if (mounted.current) setBusy(false);
    }
  }

  async function checkSave() {
    if (!mounted.current || inFlight.current || !uncertain) return;
    const pending = uncertain;
    inFlight.current = true;
    setBusy(true);
    try {
      const result = await tariffs.refetch();
      if (result.error) throw result.error;
      if (!mounted.current || !result.data) return;
      const match = pending.id !== null ? result.data.find(tariff => tariff.id === pending.id && sameValues(tariff, pending.input)) : result.data.find(tariff => !pending.beforeIds.includes(tariff.id) && sameValues(tariff, pending.input));
      setUncertain(null);
      setFailure(null);
      if (match) {
        setEditor({ id: match.id, fields: fieldsFrom(match) });
        setDirty(false);
        setMessage('Тариф с сохранёнными значениями найден в обновлённом списке. Открыто его редактирование. Повторное создание не требуется.');
        setMessageTone('success');
        await invalidateConfigQueries(queryClient).catch(() => undefined);
      } else {
        setMessage('Список обновлён. Сохранение введённых значений не подтверждено. Проверьте тарифы ниже; после проверки можно повторить сохранение.');
        setMessageTone('warning');
      }
    } catch (error) {
      if (mounted.current) setFailure(error instanceof Error ? error : new Error('Не удалось проверить список тарифов.'));
    } finally {
      inFlight.current = false;
      if (mounted.current) setBusy(false);
    }
  }

  function closeEditor() {
    if (inFlight.current || uncertain) return;
    setEditor(null);
    setDirty(false);
    setErrors({});
    setFailure(null);
  }

  if (isAccessDenied(tariffs.error) || isAccessDenied(failure)) return <EmptyState title="Тарифы доступны владельцу" description="У вас нет доступа к изменению тарифов. Вернитесь к обзору, чтобы продолжить работу с заказами." actionLabel="К обзору" onAction={() => onNavigate({ name: 'admin', view: 'dashboard' })} />;
  if (tariffs.isPending) return <LoadingState label="Загружаем тарифы" />;
  if (!tariffs.data) return <ErrorState message={tariffs.error?.message ?? 'Тарифы пока недоступны.'} onRetry={() => void tariffs.refetch()} />;
  const list = [...tariffs.data].sort((left, right) => left.sort_order - right.sort_order || left.id - right.id);
  return <div className="page-stack admin-section">
    <header className="page-heading"><p className="eyebrow">ТОЛЬКО ДЛЯ ВЛАДЕЛЬЦА</p><h1 className="page-title">Тарифы доставки</h1><p className="page-description">Активные тарифы видны клиентам. Неактивные остаются в списке для дальнейшей настройки.</p></header>
    <p className="notice notice--info"><Icon name="info" size={18} />Изменения тарифа действуют для новых заказов. Название и цена в уже оформленных заказах сохраняются.</p>
    <div className="inline-row space-between"><span className="muted text-small">Всего тарифов: {list.length}</span><button type="button" className="button button--primary" disabled={busy || Boolean(uncertain)} onClick={newTariff}><Icon name="plus" size={18} />Новый тариф</button></div>
    {tariffs.isError && <p className="notice notice--warning" role="status">Не удалось обновить список. Показаны последние загруженные тарифы. <button type="button" className="button button--ghost" disabled={busy || tariffs.isFetching} onClick={() => void tariffs.refetch()}>Обновить</button></p>}
    {failure && <div className="notice notice--error" role="alert"><div><p>{failure.message}</p>{uncertain && <p>Сервер мог сохранить тариф, но подтверждение не пришло. Сначала проверьте список: повторное создание до проверки заблокировано.</p>}</div>{uncertain && <button type="button" className="button button--secondary" disabled={busy} onClick={() => void checkSave()}>{busy ? 'Проверяем…' : 'Проверить список'}</button>}</div>}
    {message && <p className={`notice notice--${messageTone}`} role="status">{message}</p>}
    {editor && <form id="admin-tariff-editor" className="card form-stack admin-tariff-form" aria-labelledby="admin-tariff-editor-title" onSubmit={event => void save(event)} noValidate>
      <div className="inline-row space-between"><h2 id="admin-tariff-editor-title">{editor.id === null ? 'Новый тариф' : 'Редактирование тарифа'}</h2><button type="button" className="icon-button" disabled={busy || Boolean(uncertain)} aria-label="Закрыть форму тарифа" onClick={closeEditor}><Icon name="x" size={20} /></button></div>
      <div className="field"><label className="field-label" htmlFor="admin-tariff-name">Название</label><input id="admin-tariff-name" className="input" value={editor.fields.name} maxLength={100} disabled={busy || Boolean(uncertain)} onChange={event => change('name', event.target.value)} aria-invalid={Boolean(errors.name)} aria-describedby={errors.name ? 'admin-tariff-name-error' : undefined} />{errors.name && <p className="field-error" id="admin-tariff-name-error">{errors.name}</p>}</div>
      <div className="admin-form-grid"><div className="field"><label className="field-label" htmlFor="admin-tariff-price">Цена, ₽ за кг</label><input id="admin-tariff-price" className="input" inputMode="decimal" value={editor.fields.price_per_kg_rub} maxLength={30} disabled={busy || Boolean(uncertain)} onChange={event => change('price_per_kg_rub', event.target.value)} aria-invalid={Boolean(errors.price_per_kg_rub)} aria-describedby="admin-tariff-price-hint admin-tariff-price-error" /><p className="field-hint" id="admin-tariff-price-hint">До двух знаков после запятой. Для активного тарифа больше нуля.</p>{errors.price_per_kg_rub && <p className="field-error" id="admin-tariff-price-error">{errors.price_per_kg_rub}</p>}</div><div className="field"><label className="field-label" htmlFor="admin-tariff-sort">Порядок в списке</label><input id="admin-tariff-sort" className="input" inputMode="numeric" value={editor.fields.sort_order} maxLength={5} disabled={busy || Boolean(uncertain)} onChange={event => change('sort_order', event.target.value)} aria-invalid={Boolean(errors.sort_order)} aria-describedby="admin-tariff-sort-hint admin-tariff-sort-error" /><p className="field-hint" id="admin-tariff-sort-hint">От 0 до 10 000. Меньшие значения показываются первыми.</p>{errors.sort_order && <p className="field-error" id="admin-tariff-sort-error">{errors.sort_order}</p>}</div></div>
      <div className="field"><label className="field-label" htmlFor="admin-tariff-eta">Срок доставки</label><input id="admin-tariff-eta" className="input" value={editor.fields.eta_text} placeholder="Укажите реальный срок доставки" maxLength={200} disabled={busy || Boolean(uncertain)} onChange={event => change('eta_text', event.target.value)} aria-invalid={Boolean(errors.eta_text)} />{errors.eta_text && <p className="field-error">{errors.eta_text}</p>}</div>
      <div className="field"><label className="field-label" htmlFor="admin-tariff-description">Описание</label><textarea id="admin-tariff-description" className="textarea" rows={4} value={editor.fields.description} maxLength={1000} disabled={busy || Boolean(uncertain)} onChange={event => change('description', event.target.value)} aria-invalid={Boolean(errors.description)} />{errors.description && <p className="field-error">{errors.description}</p>}</div>
      <label className="admin-check"><input type="checkbox" checked={editor.fields.is_active} disabled={busy || Boolean(uncertain)} onChange={event => change('is_active', event.target.checked)} /><span>Активен — доступен клиентам для новых заказов</span></label>
      <p className="field-hint">Чтобы скрыть тариф, снимите отметку «Активен» и сохраните изменения. Тариф останется доступен владельцу.</p>
      {dirty && <p className="field-hint" role="status">Есть несохранённые изменения. Обновление списка не заменит значения в форме.</p>}
      <div className="admin-form-actions"><button type="submit" className="button button--primary" disabled={busy || Boolean(uncertain) || !dirty}><Icon name="check" size={18} />{busy ? 'Сохраняем…' : 'Сохранить тариф'}</button><button type="button" className="button button--secondary" disabled={busy || Boolean(uncertain)} onClick={closeEditor}>{dirty ? 'Закрыть без сохранения' : 'Закрыть форму'}</button></div>
    </form>}
    {list.length ? <div className="admin-tariff-list">{list.map(tariff => <article className="card admin-tariff-card" key={tariff.id}><div className="inline-row space-between"><h2>{tariff.name}</h2><button type="button" className="button button--ghost" disabled={busy || Boolean(uncertain)} aria-label={`Редактировать тариф ${tariff.name}`} onClick={() => revealEditor({ id: tariff.id, fields: fieldsFrom(tariff) })}>Изменить<Icon name="settings" size={16} /></button></div><p className="admin-money">{decimalNumber(tariff.price_per_kg_rub, 2)} ₽ <span className="muted text-small">/ кг</span></p><p className="muted">{tariff.eta_text || 'Срок не указан'}</p>{tariff.description && <p className="text-small">{tariff.description}</p>}<dl className="breakdown"><div><dt>Доступность</dt><dd>{tariff.is_active ? 'Активен' : 'Скрыт от клиентов'}</dd></div><div><dt>Порядок в списке</dt><dd>{tariff.sort_order}</dd></div></dl><p className="field-hint">Обновлён {dateMsk(tariff.updated_at)}</p></article>)}</div> : <EmptyState title="Тарифов пока нет" description="Создайте тариф, задайте цену и включите его, чтобы клиенты могли оформлять заказы." actionLabel="Новый тариф" onAction={newTariff} />}
  </div>;
}
