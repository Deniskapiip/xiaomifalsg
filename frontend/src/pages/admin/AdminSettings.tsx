import { useEffect, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { ApiError, request } from '../../api/client';
import { invalidateConfigQueries, isAccessDenied, useAdminSettings } from '../../api/admin';
import type { AdminSettingsData, SettingsInput } from '../../api/admin-types';
import type { Navigate } from '../../api/types';
import { EmptyState, ErrorState, LoadingState } from '../../components/UiStates';
import { Icon } from '../../components/Icon';
import { validateSettings } from '../../lib/admin-validation';
import { dateMsk, decimalNumber, money } from '../../lib/format';
import { Exact } from '../../lib/pricing';
import { haptic } from '../../lib/telegram';

function fieldsFrom(data: AdminSettingsData): SettingsInput {
  return { rate_cny_rub: data.rate_cny_rub, commission_percent: data.commission_percent, commission_min_rub: data.commission_min_rub };
}

export function AdminSettings({ onNavigate }: { onNavigate: Navigate }) {
  const settings = useAdminSettings();
  const queryClient = useQueryClient();
  const [fields, setFields] = useState<SettingsInput | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [failure, setFailure] = useState<Error | null>(null);
  const [message, setMessage] = useState('');
  const [messageTone, setMessageTone] = useState<'success' | 'warning'>('success');
  const [uncertain, setUncertain] = useState<SettingsInput | null>(null);
  const [busy, setBusy] = useState(false);
  const [dirty, setDirty] = useState(false);
  const dirtyRef = useRef(false);
  const inFlight = useRef(false);
  const mounted = useRef(false);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  useEffect(() => {
    if (settings.data && !dirtyRef.current && !inFlight.current) setFields(fieldsFrom(settings.data));
  }, [settings.data]);

  function change(key: keyof SettingsInput, value: string) {
    if (inFlight.current || uncertain) return;
    dirtyRef.current = true;
    setDirty(true);
    setFields(previous => previous && { ...previous, [key]: value });
    setErrors(previous => ({ ...previous, [key]: '' }));
    setMessage('');
  }

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!mounted.current || inFlight.current || !fields || uncertain) return;
    const validation = validateSettings(fields);
    setErrors(validation.errors);
    if (!validation.input) { haptic('error'); return; }
    const pending = { ...validation.input };
    inFlight.current = true;
    setBusy(true);
    setFailure(null);
    setMessage('');
    try {
      const result = await request<AdminSettingsData>('/admin/settings', { method: 'PUT', body: JSON.stringify(pending) });
      if (!mounted.current) return;
      dirtyRef.current = false;
      setDirty(false);
      setFields(fieldsFrom(result));
      queryClient.setQueryData(['admin-settings'], result);
      setMessage('Настройки сохранены. Новые заказы будут рассчитаны по этим значениям.');
      setMessageTone('success');
      haptic('success');
      await invalidateConfigQueries(queryClient).catch(() => undefined);
    } catch (error) {
      if (!mounted.current) return;
      setFailure(error instanceof Error ? error : new Error('Не удалось сохранить настройки.'));
      if (!(error instanceof ApiError) || error.status === 0 || error.status >= 500 || error.code === 'INVALID_RESPONSE') setUncertain(pending);
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
      const result = await settings.refetch();
      if (result.error) throw result.error;
      if (!mounted.current || !result.data) return;
      const saved = new Exact(result.data.rate_cny_rub).eq(pending.rate_cny_rub)
        && new Exact(result.data.commission_percent).eq(pending.commission_percent)
        && new Exact(result.data.commission_min_rub).eq(pending.commission_min_rub);
      setUncertain(null);
      setFailure(null);
      if (saved) {
        dirtyRef.current = false;
        setDirty(false);
        setFields(fieldsFrom(result.data));
        setMessage('Сохранение подтверждено: на сервере все введённые значения. Повторное сохранение не требуется.');
        setMessageTone('success');
        await invalidateConfigQueries(queryClient).catch(() => undefined);
      } else {
        setMessage('Настройки обновлены. На сервере другие значения. Сравните их с вашей формой перед повторным сохранением; введённые изменения сохранены.');
        setMessageTone('warning');
      }
    } catch (error) {
      if (mounted.current) setFailure(error instanceof Error ? error : new Error('Не удалось проверить настройки.'));
    } finally {
      inFlight.current = false;
      if (mounted.current) setBusy(false);
    }
  }

  function reset() {
    if (inFlight.current || uncertain || !settings.data) return;
    dirtyRef.current = false;
    setDirty(false);
    setFields(fieldsFrom(settings.data));
    setErrors({});
    setFailure(null);
    setMessage('');
  }

  if (isAccessDenied(settings.error) || isAccessDenied(failure)) return <EmptyState title="Настройки доступны владельцу" description="У вас нет доступа к курсу и комиссии. Вернитесь к обзору, чтобы продолжить работу с заказами." actionLabel="К обзору" onAction={() => onNavigate({ name: 'admin', view: 'dashboard' })} />;
  if (settings.isPending || !fields && settings.data) return <LoadingState label="Загружаем настройки" />;
  if (!settings.data || !fields) return <ErrorState message={settings.error?.message ?? 'Настройки пока недоступны.'} onRetry={() => void settings.refetch()} />;
  return <div className="page-stack admin-section">
    <header className="page-heading"><p className="eyebrow">ТОЛЬКО ДЛЯ ВЛАДЕЛЬЦА</p><h1 className="page-title">Курс и комиссия</h1><p className="page-description">Изменения применяются к новым заказам. Расчёты уже оформленных заказов сохраняются.</p></header>
    <section className="card card--muted"><h2>Сохранено на сервере</h2><dl className="breakdown"><div><dt>Курс за 1 ¥</dt><dd>{decimalNumber(settings.data.rate_cny_rub, 4)} ₽</dd></div><div><dt>Комиссия</dt><dd>{decimalNumber(settings.data.commission_percent, 2)}%</dd></div><div><dt>Минимальная комиссия</dt><dd>{money(settings.data.commission_min_rub)}</dd></div></dl></section>
    {settings.isError && <p className="notice notice--warning" role="status">Не удалось обновить настройки. Показаны последние загруженные данные. <button className="button button--ghost" disabled={busy || settings.isFetching} type="button" onClick={() => void settings.refetch()}>Обновить</button></p>}
    {failure && <div className="notice notice--error" role="alert"><div><p>{failure.message}</p>{uncertain && <p>Ответ сервера не получен. Повторное сохранение и редактирование заблокированы до проверки сохранённых значений. Ваши изменения в форме сохранены.</p>}</div>{uncertain && <button type="button" className="button button--ghost" disabled={busy} onClick={() => void checkSave()}>{busy ? 'Проверяем…' : 'Проверить настройки'}</button>}</div>}
    {message && <p className={`notice notice--${messageTone}`} role="status">{message}</p>}
    <form className="card form-stack admin-form" onSubmit={event => void save(event)} aria-label="Курс и комиссия" noValidate>
      <div className="field"><label className="field-label" htmlFor="admin-rate">Курс, ₽ за 1 ¥</label><input id="admin-rate" className="input admin-rate-input" inputMode="decimal" value={fields.rate_cny_rub} maxLength={30} disabled={busy || Boolean(uncertain)} onChange={event => change('rate_cny_rub', event.target.value)} aria-invalid={Boolean(errors.rate_cny_rub)} aria-describedby="admin-rate-hint admin-rate-error" /><p className="field-hint" id="admin-rate-hint">Текущий курс: {decimalNumber(settings.data.rate_cny_rub, 4)} ₽. Обновлён {dateMsk(settings.data.rate_updated_at)}.</p>{errors.rate_cny_rub && <p className="field-error" id="admin-rate-error">{errors.rate_cny_rub}</p>}</div>
      <div className="admin-form-grid"><div className="field"><label className="field-label" htmlFor="admin-commission">Комиссия, %</label><input id="admin-commission" className="input" inputMode="decimal" value={fields.commission_percent} maxLength={30} disabled={busy || Boolean(uncertain)} onChange={event => change('commission_percent', event.target.value)} aria-invalid={Boolean(errors.commission_percent)} aria-describedby="admin-commission-hint admin-commission-error" /><p className="field-hint" id="admin-commission-hint">От 0 до 100%, до двух знаков после запятой.</p>{errors.commission_percent && <p className="field-error" id="admin-commission-error">{errors.commission_percent}</p>}</div><div className="field"><label className="field-label" htmlFor="admin-minimum">Минимальная комиссия, ₽</label><input id="admin-minimum" className="input" inputMode="numeric" value={fields.commission_min_rub} maxLength={15} disabled={busy || Boolean(uncertain)} onChange={event => change('commission_min_rub', event.target.value)} aria-invalid={Boolean(errors.commission_min_rub)} aria-describedby="admin-minimum-hint admin-minimum-error" /><p className="field-hint" id="admin-minimum-hint">Целое число, можно указать 0.</p>{errors.commission_min_rub && <p className="field-error" id="admin-minimum-error">{errors.commission_min_rub}</p>}</div></div>
      {dirty && <p className="field-hint" role="status">Есть несохранённые изменения. Обновление данных не заменит введённые значения.</p>}
      <div className="admin-form-actions"><button type="submit" className="button button--primary" disabled={busy || Boolean(uncertain) || !dirty}><Icon name="check" size={18} />{busy ? 'Сохраняем…' : 'Сохранить настройки'}</button><button type="button" className="button button--secondary" disabled={busy || Boolean(uncertain) || !dirty} onClick={reset}>Отменить изменения</button></div>
    </form>
    <section className="card"><h2>История курса</h2><p className="field-hint">Последние 50 изменений курса, время московское.</p>{settings.data.rate_history.length ? <div className="admin-rate-history">{settings.data.rate_history.map(change => <article className="admin-history-row" key={change.id}><div className="inline-row space-between"><strong>{decimalNumber(change.old_rate, 4)} → {decimalNumber(change.new_rate, 4)} ₽</strong><small className="muted">{dateMsk(change.changed_at)}</small></div><p className="muted text-small">{change.changed_by_user ? `${change.changed_by_user.first_name}${change.changed_by_user.last_name ? ' ' + change.changed_by_user.last_name : ''}${change.changed_by_user.username ? ' · @' + change.changed_by_user.username : ' · Telegram ID ' + change.changed_by_user.tg_id}` : `Пользователь #${change.changed_by}`}</p></article>)}</div> : <p className="muted text-small">Изменений курса пока нет.</p>}</section>
  </div>;
}
