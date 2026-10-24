import { supports, webApp } from './telegram';

interface Envelope<T> { savedAt: number; value: T }
const queuedCloudWrites = new Map<string, string>();
let flushing = false;
let debounce: ReturnType<typeof setTimeout> | null = null;
function localRead(key: string): string | null { try { return localStorage.getItem(key); } catch { return null; } }
function localWrite(key: string, value: string): void { try { localStorage.setItem(key, value); } catch { /* Private mode / quota. */ } }
function decode<T>(raw: string | null | undefined): Envelope<T> | null {
  try { const value = JSON.parse(raw ?? ''); return typeof value?.savedAt === 'number' && 'value' in value ? value : null; } catch { return null; }
}
export async function readStored<T>(key: string): Promise<T | null> {
  const local = decode<T>(localRead(key));
  const cloud = webApp()?.CloudStorage;
  if (!supports('6.9') || !cloud) return local?.value ?? null;
  const remote = await new Promise<Envelope<T> | null>(resolve => {
    const timer = setTimeout(() => resolve(null), 1200);
    try { cloud.getItem(key, (error, value) => { clearTimeout(timer); resolve(error ? null : decode<T>(value)); }); }
    catch { clearTimeout(timer); resolve(null); }
  });
  const currentLocal = decode<T>(localRead(key));
  const newest = !remote || (currentLocal && currentLocal.savedAt >= remote.savedAt) ? currentLocal : remote;
  if (newest) localWrite(key, JSON.stringify(newest));
  return newest?.value ?? null;
}
export function writeStored<T>(key: string, value: T): void {
  const raw = JSON.stringify({ savedAt: Date.now(), value });
  localWrite(key, raw);
  const cloud = webApp()?.CloudStorage;
  if (!supports('6.9') || !cloud || raw.length > 4096) return;
  queuedCloudWrites.set(key, raw);
  if (debounce) clearTimeout(debounce);
  debounce = setTimeout(() => { debounce = null; void flushCloud(); }, 250);
}
async function flushCloud(): Promise<void> {
  if (flushing) return; flushing = true;
  try {
    while (queuedCloudWrites.size) {
      const [key, raw] = queuedCloudWrites.entries().next().value!;
      queuedCloudWrites.delete(key);
      const cloud = webApp()?.CloudStorage;
      if (!cloud || !supports('6.9')) continue;
      await new Promise<void>(resolve => {
        const timer = setTimeout(resolve, 1200);
        try { cloud.setItem(key, raw, () => { clearTimeout(timer); resolve(); }); }
        catch { clearTimeout(timer); resolve(); }
      });
    }
  } finally { flushing = false; }
}
export function userStorageKey(tgId: number, purpose: string): string { return `taoji_v2_${tgId}_${purpose}`; }
