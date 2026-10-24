import { useEffect, useLayoutEffect, useRef, useState, type PointerEvent as ReactPointerEvent, type ReactNode } from 'react';
import type { Navigate, Role, Screen, Tab, User } from '../api/types';
import { Icon } from './Icon';
import { OfflineBanner } from './UiStates';
import { ThemeToggle } from './ThemeToggle';
import { haptic } from '../lib/telegram';

const homeTab: { key: Tab; label: string; icon: string } = { key: 'home', label: 'Главная', icon: 'home' };
const wizardTab = { key: 'wizard' as Tab, label: 'Заказать', icon: 'plus' };
const ordersTab = { key: 'orders' as Tab, label: 'Мои заказы', icon: 'package' };
const adminTab = { key: 'admin' as Tab, label: 'Админка', icon: 'settings' };

function tabScreen(key: Tab): Screen {
  return key === 'admin' ? { name: 'admin' } : { name: key };
}

export function AppShell({ user, role, activeTab, onNavigate, children, adminEnabled = false }: {
  user: User; role: Role; activeTab: Tab; onNavigate: Navigate; children: ReactNode; adminEnabled?: boolean;
}) {
  // Клиенту «Заказать» стоит по центру; сотрудникам добавляем админку справа.
  const navigation = role !== 'client' && adminEnabled
    ? [homeTab, ordersTab, wizardTab, adminTab]
    : [homeTab, wizardTab, ordersTab];
  const firstName = user.first_name?.trim() || 'Пользователь';

  const navRef = useRef<HTMLElement | null>(null);
  const items = useRef(new Map<string, HTMLButtonElement>());
  const [lens, setLens] = useState<{ x: number; width: number } | null>(null);
  const [dragging, setDragging] = useState<{ hovering: Tab; moved: boolean } | null>(null);
  const dragStart = useRef<number | null>(null);
  const movedRef = useRef(false);
  const suppressClick = useRef(false);
  const longPress = useRef<number | null>(null);

  const updateLens = (target: Tab | string) => {
    const nav = navRef.current;
    const element = items.current.get(target);
    if (!nav || !element) return;
    const navRect = nav.getBoundingClientRect();
    const rect = element.getBoundingClientRect();
    const width = Math.min(64, Math.max(32, rect.width - 16));
    setLens({ x: rect.left - navRect.left + (rect.width - width) / 2, width });
  };

  useLayoutEffect(() => {
    updateLens(dragging?.hovering ?? activeTab);
    const nav = navRef.current;
    if (!nav) return;
    const observer = new ResizeObserver(() => updateLens(dragging?.hovering ?? activeTab));
    observer.observe(nav);
    const onResize = () => updateLens(dragging?.hovering ?? activeTab);
    window.addEventListener('resize', onResize);
    return () => { observer.disconnect(); window.removeEventListener('resize', onResize); };
  }, [activeTab, dragging?.hovering, navigation.length]);

  useEffect(() => () => { if (longPress.current !== null) window.clearTimeout(longPress.current); }, []);

  function tabFromPoint(clientX: number): Tab | null {
    let best: { key: Tab; distance: number } | null = null;
    items.current.forEach((element, key) => {
      const rect = element.getBoundingClientRect();
      const distance = Math.abs(clientX - (rect.left + rect.width / 2));
      if (!best || distance < best.distance) best = { key: key as Tab, distance };
    });
    return best ? (best as { key: Tab }).key : null;
  }

  function pointerDown(event: ReactPointerEvent<HTMLElement>) {
    const target = (event.target as HTMLElement).closest<HTMLElement>('[data-tab]');
    if (!target) return;
    event.currentTarget.setPointerCapture(event.pointerId);
    dragStart.current = event.clientX;
    movedRef.current = false;
    setDragging({ hovering: activeTab, moved: false });
    longPress.current = window.setTimeout(() => haptic('selection'), 220);
  }

  function pointerMove(event: ReactPointerEvent<HTMLElement>) {
    if (!dragging) return;
    if (dragStart.current !== null && Math.abs(event.clientX - dragStart.current) > 4) {
      movedRef.current = true;
      setDragging(current => current ? { ...current, moved: true } : current);
    }
    const hovered = tabFromPoint(event.clientX);
    if (hovered && hovered !== dragging.hovering) {
      setDragging(current => current ? { hovering: hovered, moved: true } : current);
      haptic('selection');
    }
  }

  function pointerUp() {
    if (longPress.current !== null) { window.clearTimeout(longPress.current); longPress.current = null; }
    const target = dragging?.hovering;
    const moved = movedRef.current;
    setDragging(null);
    dragStart.current = null;
    updateLens(activeTab);
    if (moved && target && target !== activeTab) {
      suppressClick.current = true;
      onNavigate(tabScreen(target));
    }
    movedRef.current = false;
  }

  return (
    <div className="app-canvas">
      <header className="app-header">
        <button className="app-brand" type="button" onClick={() => onNavigate({ name: 'home' })} aria-label="Taoji Cargo — на главную">
          <img src="/logo.png" width="48" height="48" alt="" />
          <span><strong>TAOJI <em>CARGO</em></strong><small>ВЫКУП · ДОСТАВКА</small></span>
        </button>
        <div className="app-header__actions">
          <ThemeToggle />
          <span className="app-avatar" title={firstName} aria-label={`Пользователь: ${firstName}`}>{firstName.slice(0, 1).toLocaleUpperCase('ru-RU')}</span>
        </div>
      </header>
      <OfflineBanner />
      <main className="app-main" id="main-content">{children}</main>
      <footer className="app-footer">TAOJI CARGO · выкуп и доставка из Китая</footer>
      <nav ref={navRef} className={`bottom-nav ${dragging ? 'is-dragging' : ''}`} aria-label="Основная навигация"
        onPointerDown={pointerDown} onPointerMove={pointerMove} onPointerUp={pointerUp} onPointerCancel={pointerUp}>
        {lens && <span className="nav-lens" aria-hidden="true" style={{ transform: `translateX(${lens.x}px)`, width: `${lens.width}px` }} />}
        {navigation.map((tab) => (
          <button key={tab.key} data-tab={tab.key} ref={element => { if (element) items.current.set(tab.key, element); else items.current.delete(tab.key); }}
            className={`nav-item ${tab.key === 'wizard' ? 'nav-item--order' : ''} ${activeTab === tab.key ? 'is-active' : ''} ${dragging?.hovering === tab.key ? 'is-hovered' : ''}`}
            aria-current={activeTab === tab.key ? 'page' : undefined} type="button"
            onClick={() => { if (suppressClick.current) { suppressClick.current = false; return; } onNavigate(tabScreen(tab.key)); }}>
            <span className={`nav-item__icon ${tab.key === 'wizard' ? 'nav-item__icon--order' : ''}`}><Icon name={tab.icon} size={22} /></span>
            <span>{tab.label}</span>
          </button>
        ))}
      </nav>
    </div>
  );
}
