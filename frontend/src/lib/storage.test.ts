import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

type StorageApi = typeof import('./storage');
let api: StorageApi;
let values: Map<string, string>;
let getCloud: ReturnType<typeof vi.fn>;
let setCloud: ReturnType<typeof vi.fn>;

const envelope = (value: unknown, savedAt: number) => JSON.stringify({ savedAt, value });

beforeEach(async () => {
  vi.resetModules(); values = new Map();
  getCloud = vi.fn((_key: string, callback: (error: string | null, value?: string) => void) => callback(null, ''));
  setCloud = vi.fn((_key: string, _value: string, callback: (error: string | null, stored?: boolean) => void) => callback(null, true));
  vi.stubGlobal('window', { Telegram: { WebApp: { initData: 'signed-launch-data', isVersionAtLeast: () => true, CloudStorage: { getItem: getCloud, setItem: setCloud } } } });
  vi.stubGlobal('localStorage', { getItem: (key: string) => values.get(key) ?? null, setItem: (key: string, value: string) => { values.set(key, value); } });
  api = await import('./storage');
});
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });

describe('Telegram storage with local fallback', () => {
  it('does not let a late cloud read overwrite a local edit made during hydration', async () => {
    let receive!: (error: string | null, value?: string) => void;
    getCloud.mockImplementation((_key: string, callback: typeof receive) => { receive = callback; });
    values.set('draft', envelope('old-local', 100));
    const reading = api.readStored<string>('draft');
    vi.spyOn(Date, 'now').mockReturnValue(300);
    api.writeStored('draft', 'new-local');
    receive(null, envelope('middle-cloud', 200));
    expect(await reading).toBe('new-local');
    expect(JSON.parse(values.get('draft')!).value).toBe('new-local');
  });

  it('uses cloud values when they are newer than the local copy', async () => {
    values.set('draft', envelope('old-local', 100));
    getCloud.mockImplementation((_key: string, callback: (error: string | null, value?: string) => void) => callback(null, envelope('new-cloud', 200)));
    expect(await api.readStored<string>('draft')).toBe('new-cloud');
    expect(JSON.parse(values.get('draft')!).value).toBe('new-cloud');
  });

  it('keeps long serialized values locally without exceeding the CloudStorage 4096-character limit', async () => {
    const longDraft = { comment: 'x'.repeat(4096) };
    api.writeStored('draft', longDraft);
    await Promise.resolve();
    expect(setCloud).not.toHaveBeenCalled();
    expect(await api.readStored<typeof longDraft>('draft')).toEqual(longDraft);
  });

  it('keeps the local copy when CloudStorage returns an error', async () => {
    values.set('draft', envelope({ link: 'https://tb.cn/item' }, 100));
    getCloud.mockImplementation((_key: string, callback: (error: string | null, value?: string) => void) => callback('Storage unavailable'));
    expect(await api.readStored<{ link: string }>('draft')).toEqual({ link: 'https://tb.cn/item' });
  });

  it('works in the ordinary browser without attempting Telegram cloud operations', async () => {
    vi.stubGlobal('window', {});
    api.writeStored('draft', { comment: 'Местный черновик' });
    expect(await api.readStored('draft')).toEqual({ comment: 'Местный черновик' });
    expect(getCloud).not.toHaveBeenCalled(); expect(setCloud).not.toHaveBeenCalled();
  });

  it('scopes keys to the verified Telegram user', () => {
    expect(api.userStorageKey(101, 'draft')).toBe('taoji_v2_101_draft');
    expect(api.userStorageKey(202, 'draft')).not.toBe(api.userStorageKey(101, 'draft'));
  });
});
