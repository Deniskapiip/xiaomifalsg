import { describe, expect, it } from 'vitest';
import { allowedScreen, readScreen, screenUrl } from './navigation';
import type { Role, Screen } from '../api/types';

const href = 'https://cargo.example/?tgWebAppStartParam=launch#tgWebAppData=signed%26user%3D123';

describe('role-aware navigation and browser history', () => {
  it('routes bot order links to administration only for administrator roles', () => {
    expect(readScreen('client', 'https://cargo.example/?open=order_77')).toEqual({ name: 'order', id: 77 });
    expect(readScreen('manager', 'https://cargo.example/?open=order_77')).toMatchObject({ name: 'admin-order', id: 77 });
    expect(readScreen('owner', 'https://cargo.example/?open=order_77')).toMatchObject({ name: 'admin-order', id: 77 });
  });

  it.each(['client', 'manager', 'owner'] as Role[])('keeps explicit personal order links in the client view for %s', (role) => {
    const url = screenUrl({ name: 'order', id: 77 }, href);
    expect(readScreen(role, url.href)).toEqual({ name: 'order', id: 77 });
    expect(url.searchParams.get('tab')).toBe('orders');
  });

  it('prevents client admin routes and manager owner-only routes', () => {
    expect(readScreen('client', 'https://cargo.example/?tab=admin&view=settings')).toEqual({ name: 'home' });
    expect(allowedScreen({ name: 'admin-order', id: 77 }, 'client')).toEqual({ name: 'home' });
    expect(readScreen('manager', 'https://cargo.example/?tab=admin&view=settings')).toEqual({ name: 'admin', view: 'dashboard' });
    expect(readScreen('manager', 'https://cargo.example/?tab=admin&view=tariffs')).toEqual({ name: 'admin', view: 'dashboard' });
    expect(readScreen('owner', 'https://cargo.example/?tab=admin&view=settings')).toMatchObject({ name: 'admin', view: 'settings' });
  });

  it('round-trips administrator list filters and preserves Telegram launch data', () => {
    const screen: Screen = { name: 'admin', view: 'orders', filters: { q: '@user + Китай & товар', status: 'to_recipient', offset: 40, sort: 'oldest' } };
    const url = screenUrl(screen, href);
    expect(readScreen('owner', url.href)).toEqual(screen);
    expect(url.hash).toBe(new URL(href).hash);
    expect(url.searchParams.get('tgWebAppStartParam')).toBe('launch');
    const details = screenUrl({ name: 'admin-order', id: 77, filters: screen.filters }, url.href);
    expect(readScreen('manager', details.href)).toEqual({ name: 'admin-order', id: 77, filters: screen.filters });
  });

  it('removes private search filters when navigating back to a public page', () => {
    const current = 'https://cargo.example/?tab=admin&view=orders&search=%40client&status=processing&offset=40&sort=oldest&open=order_77#launch';
    const url = screenUrl({ name: 'home' }, current);
    expect(url.search).toBe(''); expect(url.hash).toBe('#launch');
    expect(readScreen('client', url.href)).toEqual({ name: 'home' });
  });

  it.each(['order_0', 'order_-1', 'order_1x', 'order_9007199254740993'])('rejects an invalid order identifier: %s', (open) => {
    expect(readScreen('client', `https://cargo.example/?open=${open}`)).toEqual({ name: 'home' });
  });

  it('bounds restored filters and rejects invalid offsets and sorting values', () => {
    const url = new URL('https://cargo.example/?tab=admin&view=orders&offset=-1&sort=random');
    url.searchParams.set('search', 'x'.repeat(2100)); url.searchParams.set('status', 'x'.repeat(100));
    const screen = readScreen('owner', url.href);
    expect(screen).toMatchObject({ name: 'admin', view: 'orders', filters: { offset: 0, sort: 'newest' } });
    if (screen.name !== 'admin') throw new Error('Expected administrator list');
    expect(screen.filters?.q?.length).toBe(2000); expect(screen.filters?.status?.length).toBe(64);
  });
});
