import { Component, lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ApiError, authenticate, clearSession, setSessionListener } from './api/client';
import type { AuthResponse, Navigate, Screen, Tab } from './api/types';
import { useConfig } from './api/hooks';
import { initializeTelegram, useBackButton } from './lib/telegram';
import { readStored, userStorageKey, writeStored } from './lib/storage';
import { useWizard } from './store/wizard';
import { AppShell } from './components/AppShell';
import { ErrorState, LoadingState } from './components/UiStates';
import { Home } from './pages/Home';
import { Orders } from './pages/Orders';
import { Help } from './pages/Help';
import { Onboarding } from './pages/Onboarding';
import { allowedScreen, readScreen, screenUrl } from './lib/navigation';

// Тяжёлые экраны грузим по требованию: главная и заказы открываются мгновенно.
const OrderDetails = lazy(() => import('./pages/OrderDetails').then(module => ({ default: module.OrderDetails })));
const OrderWizard = lazy(() => import('./pages/OrderWizard').then(module => ({ default: module.OrderWizard })));
const OrderSuccess = lazy(() => import('./pages/OrderSuccess').then(module => ({ default: module.OrderSuccess })));
const AdminPanel = lazy(() => import('./components/AdminPanel').then(module => ({ default: module.AdminPanel })));


class Boundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  render() { return this.state.failed ? <div className="page"><ErrorState message="Не удалось показать экран. Обновите приложение и проверьте данные." onRetry={() => window.location.reload()} /></div> : this.props.children; }
}

export function App() {
  const [session, setSession] = useState<AuthResponse | null>(null);
  const [error, setError] = useState('');
  const active = useRef(false);
  const retry = useRef(0);
  const retryTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const login = useCallback(async () => {
    setError('');
    try {
      const value = await authenticate();
      if (!active.current) return;
      retry.current = 0;
      setSession(value);
    } catch (caught) {
      if (caught instanceof ApiError && caught.code === 'SESSION_CHANGED') return;
      if (!active.current) return;
      if (caught instanceof ApiError && caught.code === 'NETWORK_ERROR' && retry.current < 5) {
        // Сервер мог засыпать/перезапускаться — повторяем сами, не пугая «нет интернета».
        retry.current += 1;
        setError('Подключаемся к серверу, подождите…');
        retryTimer.current = setTimeout(() => { if (active.current) void login(); }, 1500 * retry.current);
        return;
      }
      setError(caught instanceof Error ? caught.message : 'Не удалось войти. Откройте приложение из Telegram.');
    }
  }, []);
  useEffect(() => {
    active.current = true;
    const cleanup = initializeTelegram();
    setSessionListener(value => { if (active.current) setSession(value); });
    void login();
    return () => {
      active.current = false;
      if (retryTimer.current !== null) clearTimeout(retryTimer.current);
      cleanup(); setSessionListener(null); clearSession();
    };
  }, [login]);
  if (!session) return <main className="app-canvas"><div className="page">{error ? <ErrorState message={error} onRetry={() => void login()} /> : <LoadingState label="Открываем Taoji Cargo…" />}</div></main>;
  return <Boundary><VerifiedSession key={`${session.user.tg_id}:${session.role}`} session={session} /></Boundary>;
}

function VerifiedSession({ session }: { session: AuthResponse }) {
  // Changing the verified account or role discards every cache, including private admin responses.
  const client = useMemo(() => new QueryClient({ defaultOptions: { queries: { refetchOnWindowFocus: true }, mutations: { retry: false } } }), []);
  useEffect(() => () => { client.clear(); }, [client]);
  return <QueryClientProvider client={client}><ClientContent session={session} /></QueryClientProvider>;
}

function DetailsBack({ onBack, children }: { onBack: () => void; children: ReactNode }) { useBackButton(onBack); return children; }

function ClientContent({ session }: { session: AuthResponse }) {
  const config = useConfig();
  const [ready, setReady] = useState(false);
  const [onboarding, setOnboarding] = useState(false);
  const [screen, setScreen] = useState<Screen>(() => readScreen(session.role));
  const tgId = session.user.tg_id;
  useEffect(() => {
    let cancelled = false;
    setReady(false);
    void Promise.all([useWizard.getState().hydrate(tgId), readStored<boolean>(userStorageKey(tgId, 'onboarding'))]).then(([, seen]) => {
      if (!cancelled) { setOnboarding(seen !== true); setReady(true); }
    });
    return () => { cancelled = true; };
  }, [tgId]);
  useEffect(() => {
    const onPop = () => setScreen(readScreen(session.role));
    window.addEventListener('popstate', onPop); return () => window.removeEventListener('popstate', onPop);
  }, [session.role]);
  const navigate: Navigate = useCallback(requested => {
    const next = allowedScreen(requested, session.role);
    const url = screenUrl(next);
    window.history.pushState(null, '', url); setScreen(next); window.scrollTo(0, 0);
  }, [session.role]);
  if (!ready || config.isPending) return <main className="app-canvas"><div className="page"><LoadingState label="Загружаем ваши данные…" /></div></main>;
  if (!config.data) return <main className="app-canvas"><div className="page"><ErrorState message={config.error?.message ?? 'Не удалось загрузить настройки'} onRetry={() => void config.refetch()} /></div></main>;
  if (onboarding) return <main className="app-canvas"><Onboarding config={config.data} onComplete={() => { writeStored(userStorageKey(tgId, 'onboarding'), true); setOnboarding(false); window.scrollTo(0, 0); }} /></main>;
  const data = config.data;
  let body: ReactNode;
  let activeTab: Tab;
  switch (screen.name) {
    case 'wizard': activeTab = 'wizard'; body = <OrderWizard config={data} user={session.user} role={session.role} onNavigate={navigate} />; break;
    case 'orders': activeTab = 'orders'; body = <Orders config={data} onNavigate={navigate} />; break;
    case 'order': activeTab = 'orders'; body = <DetailsBack onBack={() => navigate({ name: 'orders' })}><OrderDetails config={data} orderId={screen.id} onNavigate={navigate} /></DetailsBack>; break;
    case 'success': activeTab = 'orders'; body = <OrderSuccess config={data} user={session.user} order={screen.order} onNavigate={navigate} />; break;
    case 'help': activeTab = 'help'; body = <Help config={data} />; break;
    case 'admin': case 'admin-order': activeTab = 'admin'; body = <AdminPanel config={data} role={session.role} screen={screen} onNavigate={navigate} />; break;
    default: activeTab = 'home'; body = <Home config={data} user={session.user} onNavigate={navigate} />;
  }
  return <AppShell user={session.user} role={session.role} activeTab={activeTab} onNavigate={navigate} adminEnabled>
    {config.isError && <p className="notice notice--warning">Не удалось обновить настройки. Показаны последние загруженные данные.</p>}
    <Suspense fallback={<LoadingState label="Открываем экран…" />}>{body}</Suspense>
  </AppShell>;
}
