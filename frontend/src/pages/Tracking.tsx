import { useState, type FormEvent } from 'react';
import type { AppConfig, Navigate, TrackingLink } from '../api/types';
import { ApiError } from '../api/client';
import { useAddTracking, useDeleteTracking, useRefreshTracking, useTrackingLinks } from '../api/hooks';
import { Icon } from '../components/Icon';
import { EmptyState, ErrorState, LoadingState } from '../components/UiStates';
import { dateMsk } from '../lib/format';
import { normalizeTracking, trackingValid } from '../lib/validation';
import { haptic, inTelegram, showConfirm } from '../lib/telegram';

const TRACKING_HINT = 'От 3 до 64 символов: латиница, цифры, пробел, дефис и подчёркивание.';

export function Tracking({ onNavigate }: { config: AppConfig; onNavigate: Navigate }) {
  const links = useTrackingLinks({ poll: true });
  const add = useAddTracking();
  const remove = useDeleteTracking();
  const refresh = useRefreshTracking();
  const [value, setValue] = useState('');
  const [fieldError, setFieldError] = useState('');
  const [notice, setNotice] = useState('');
  const [refreshingId, setRefreshingId] = useState<number | null>(null);
  const [refreshError, setRefreshError] = useState<{ id: number; message: string } | null>(null);
  const [deleteError, setDeleteError] = useState('');

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trackNumber = normalizeTracking(value);
    if (!trackingValid(trackNumber)) { setFieldError(TRACKING_HINT); haptic('error'); return; }
    setFieldError(''); setNotice(''); setDeleteError('');
    add.mutate(trackNumber, {
      onSuccess: link => { setValue(''); setNotice(`Трек-номер ${link.track_number} добавлен в отслеживание.`); haptic('success'); },
      onError: caught => { setFieldError(caught instanceof Error ? caught.message : 'Не удалось добавить трек-номер.'); haptic('error'); },
    });
  }

  function refreshLink(link: TrackingLink) {
    if (refreshingId !== null) return;
    setRefreshingId(link.id); setRefreshError(null); setNotice('');
    refresh.mutate(link.id, {
      onSuccess: () => { haptic('success'); setNotice(`Статус по трек-номеру ${link.track_number} обновлён.`); },
      onError: caught => {
        haptic('error');
        const cooldown = caught instanceof ApiError && caught.status === 429;
        setRefreshError({ id: link.id, message: cooldown ? caught.message : caught instanceof Error ? caught.message : 'Не удалось обновить статус. Попробуйте ещё раз.' });
      },
      onSettled: () => setRefreshingId(null),
    });
  }

  async function deleteLink(link: TrackingLink) {
    if (remove.isPending || refreshingId !== null) return;
    // The native Telegram confirmation is unavailable in a plain browser, where deletion can proceed at once.
    if (inTelegram() && !(await showConfirm(`Удалить трек-номер ${link.track_number} из отслеживания?`))) return;
    setNotice(''); setRefreshError(null); setDeleteError('');
    remove.mutate(link.id, {
      onSuccess: () => { setNotice(`Трек-номер ${link.track_number} удалён.`); haptic('success'); },
      onError: caught => { setDeleteError(caught instanceof Error ? caught.message : 'Не удалось удалить трек-номер.'); haptic('error'); },
    });
  }

  return (
    <div className="page page-stack">
      <header className="page-heading">
        <p className="eyebrow">ДОБРОПОСТ</p>
        <h1 className="page-title">Трекинг посылки</h1>
        <p className="page-description">Введите трек-номер Добропоста — статус будет обновляться автоматически каждые 6 часов.</p>
      </header>

      <form className="card form-stack" onSubmit={submit}>
        <div className="field">
          <label className="field-label" htmlFor="tracking-number">Трек-номер посылки</label>
          <input id="tracking-number" className="input" value={value} maxLength={64} autoComplete="off" spellCheck={false}
            placeholder="Например, CN123456789" aria-invalid={Boolean(fieldError)} aria-describedby={fieldError ? 'tracking-number-error' : 'tracking-number-hint'}
            onChange={event => { setValue(event.target.value); setFieldError(''); setNotice(''); }} />
          <p className="field-hint" id="tracking-number-hint">Можно вставить номер с сайта или из приложения Добропоста.</p>
          {fieldError && <p className="field-error" id="tracking-number-error" role="alert">{fieldError}</p>}
        </div>
        <button className="button button--primary button--block" type="submit" disabled={add.isPending || !value.trim()}>
          <Icon name="truck" size={18} />{add.isPending ? 'Добавляем…' : 'Добавить в отслеживание'}
        </button>
      </form>

      {notice && <p className="notice notice--success" role="status">{notice}</p>}
      {deleteError && <p className="notice notice--warning" role="alert">{deleteError}</p>}
      <div className="inline-row space-between">
        <p className="field-hint">Мы проверяем статусы автоматически. Можно обновить вручную, но не чаще, чем раз в 15 минут.</p>
        <button className="button button--ghost" type="button" onClick={() => onNavigate({ name: 'orders' })}>К заказам<Icon name="chevron-right" size={16} /></button>
      </div>

      {links.isError && links.data && <p className="notice notice--warning" role="status">Не удалось обновить список. Показаны последние загруженные треки. <button className="button button--ghost" type="button" disabled={links.isFetching} onClick={() => void links.refetch()}>Повторить</button></p>}
      {links.isPending ? <LoadingState label="Загружаем трек-номера" />
        : links.isError && !links.data ? <ErrorState message={links.error.message} onRetry={() => void links.refetch()} />
        : links.data?.length ? <div className="page-stack" aria-label="Сохранённые трек-номера">
          {links.data.map(link => <article className="card" key={link.id}>
            <div className="section-heading">
              <div><p className="eyebrow">{link.provider ? link.provider.toUpperCase() : 'ДОБРОПОСТ'}</p><strong className="details-number">{link.track_number}</strong></div>
              <span className="chip">{link.ok ? 'Статус получен' : 'Ожидает обновления'}</span>
            </div>
            <p className={link.ok ? 'notice notice--success' : 'notice notice--warning'} role="status">{link.status_text || 'Ожидает первого обновления'}</p>
            <div className="breakdown">
              <div className="breakdown-row"><span>Обновлено</span><strong>{link.last_checked_at ? dateMsk(link.last_checked_at) : 'ещё не обновлялось'}</strong></div>
              <div className="breakdown-row"><span>Следующее обновление</span><strong>{dateMsk(link.next_check_at)}</strong></div>
            </div>
            <div className="inline-row space-between">
              <button className="icon-button" type="button" aria-label={`Обновить статус трек-номера ${link.track_number}`} title="Обновить статус"
                disabled={refreshingId !== null || remove.isPending} onClick={() => refreshLink(link)}>
                <Icon name={refreshingId === link.id ? 'clock' : 'refresh'} size={20} />
              </button>
              <button className="icon-button" type="button" aria-label={`Удалить трек-номер ${link.track_number}`} title="Удалить из отслеживания"
                disabled={remove.isPending || refreshingId !== null} onClick={() => void deleteLink(link)}>
                <Icon name="x" size={20} />
              </button>
            </div>
            {refreshingId === link.id && <p className="field-hint" role="status">Обновляем статус…</p>}
            {refreshError?.id === link.id && <p className="notice notice--warning field-hint" role="status">{refreshError.message}</p>}
          </article>)}
        </div> : <EmptyState title="Пока нет трек-номеров" description="Добавьте трек-номер Добропоста — приложение будет проверять его статус автоматически каждые 6 часов." />}
    </div>
  );
}
