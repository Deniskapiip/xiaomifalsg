import { useEffect, useState } from 'react';
import { Icon } from './Icon';

export function Skeleton({ className = '' }: { className?: string }) {
  return <span className={`skeleton ${className}`} aria-hidden="true" />;
}

export function LoadingState({ label = 'Загружаем…' }: { label?: string }) {
  return (
    <div className="loading-state" role="status" aria-live="polite">
      <div className="loading-state__brand">
        <img src="/logo.png" alt="Taoji Cargo" width="104" height="104" />
        <span className="loading-track"><span /></span>
      </div>
      <p>{label}</p>
      <div className="loading-skeletons"><Skeleton /><Skeleton /><Skeleton /></div>
    </div>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <section className="state-card state-card--error" role="alert">
      <span className="state-icon"><Icon name="info" size={28} /></span>
      <h2>Не удалось загрузить</h2>
      <p>{message}</p>
      <button className="button button--secondary" type="button" onClick={onRetry}>
        <Icon name="refresh" size={18} />Повторить
      </button>
    </section>
  );
}

export function EmptyState({ title, description, actionLabel, onAction }: {
  title: string; description: string; actionLabel?: string; onAction?: () => void;
}) {
  return (
    <section className="state-card">
      <div className="parcel-illustration" aria-hidden="true">
        <div className="parcel-illustration__orbit" />
        <div className="parcel-illustration__box"><Icon name="package" size={52} /></div>
        <span className="parcel-illustration__spark parcel-illustration__spark--one" />
        <span className="parcel-illustration__spark parcel-illustration__spark--two" />
      </div>
      <h2>{title}</h2>
      <p>{description}</p>
      {actionLabel && onAction && <button className="button button--primary" type="button" onClick={onAction}>{actionLabel}<Icon name="arrow-right" size={18} /></button>}
    </section>
  );
}

export function OfflineBanner() {
  // navigator.onLine в Telegram WebView часто врёт («офлайн» при живом интернете),
  // поэтому показываем баннер только если реальный запрос к серверу тоже не проходит.
  const [serverDown, setServerDown] = useState(false);
  useEffect(() => {
    let cancelled = false;
    const check = async () => {
      if (navigator.onLine !== false) { if (!cancelled) setServerDown(false); return; }
      try {
        const response = await fetch('/api/health', { cache: 'no-store' });
        if (!cancelled) setServerDown(!response.ok);
      } catch { if (!cancelled) setServerDown(true); }
    };
    const onOffline = () => void check();
    const onOnline = () => setServerDown(false);
    window.addEventListener('offline', onOffline);
    window.addEventListener('online', onOnline);
    const timer = window.setInterval(() => { if (navigator.onLine === false) void check(); }, 15000);
    void check();
    return () => {
      cancelled = true;
      window.removeEventListener('offline', onOffline);
      window.removeEventListener('online', onOnline);
      window.clearInterval(timer);
    };
  }, []);
  if (!serverDown) return null;
  return <div className="offline-banner" role="status" aria-live="polite"><Icon name="info" size={18} /><span>Нет связи с сервером. Пробуем подключиться снова…</span></div>;
}
