import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { pasteText } from './telegram';

let browserRead: ReturnType<typeof vi.fn>;
let telegramRead: ReturnType<typeof vi.fn>;

beforeEach(() => {
  vi.useFakeTimers();
  browserRead = vi.fn().mockResolvedValue('https://m.tb.cn/h.item');
  telegramRead = vi.fn();
  vi.stubGlobal('navigator', { clipboard: { readText: browserRead } });
  vi.stubGlobal('window', { Telegram: { WebApp: {
    initData: 'user=signed-bot-menu-launch',
    isVersionAtLeast: () => true,
    readTextFromClipboard: telegramRead,
  } } });
});

afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });

describe('clipboard paste in Telegram and embedded browsers', () => {
  it('uses the browser clipboard for a bot-menu launch without calling the attachment-only SDK API', async () => {
    expect(await pasteText()).toBe('https://m.tb.cn/h.item');
    expect(browserRead).toHaveBeenCalledTimes(1);
    expect(telegramRead).not.toHaveBeenCalled();
  });

  it('preserves the full share text for subsequent link extraction', async () => {
    const shareText = '【闲鱼】\nhttps://m.tb.cn/h.item \n点击链接直接打开';
    browserRead.mockResolvedValue(shareText);
    expect(await pasteText()).toBe(shareText);
  });

  it('offers manual paste when access is denied, clipboard is absent or content is blank', async () => {
    browserRead.mockRejectedValue(new Error('Permission denied'));
    expect(await pasteText()).toBeNull();
    vi.stubGlobal('navigator', {});
    expect(await pasteText()).toBeNull();
    vi.stubGlobal('navigator', { clipboard: { readText: () => Promise.resolve(' \n ') } });
    expect(await pasteText()).toBeNull();
  });

  it('bounds a hanging browser read and ignores a result received after the fallback', async () => {
    let receive!: (value: string) => void;
    browserRead.mockReturnValue(new Promise<string>(resolve => { receive = resolve; }));
    const reading = pasteText();
    await vi.advanceTimersByTimeAsync(1200);
    expect(await reading).toBeNull();
    receive('https://m.tb.cn/late');
    await Promise.resolve();
    expect(await reading).toBeNull();
  });

  it('uses the SDK only for an explicit attachment-menu receiver', async () => {
    window.Telegram!.WebApp!.initData = 'receiver=%7B%22id%22%3A42%7D';
    telegramRead.mockImplementation((callback: (value: string | null) => void) => callback('https://m.tb.cn/attachment'));
    expect(await pasteText()).toBe('https://m.tb.cn/attachment');
    expect(browserRead).not.toHaveBeenCalled();
  });

  it('also bounds an unanswered attachment-menu read', async () => {
    window.Telegram!.WebApp!.initData = 'receiver=%7B%22id%22%3A42%7D';
    const reading = pasteText();
    await vi.advanceTimersByTimeAsync(1200);
    expect(await reading).toBeNull();
  });
});
