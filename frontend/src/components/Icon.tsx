import {
  ArrowLeft, ArrowRight, Check, ChevronDown, ChevronRight, Clipboard,
  Copy, ExternalLink, House, Info, Link, Package, Plus, RefreshCw,
  Scale, Send, Settings, ShieldCheck, ShoppingBag, Truck, Warehouse,
  X, CircleHelp, Sun, Moon, Camera, Download, Search, Share2, Clock3,
} from 'lucide-react';
import type { LucideIcon } from 'lucide-react';

const icons: Record<string, LucideIcon> = {
  home: House, plus: Plus, package: Package, help: CircleHelp,
  settings: Settings, 'arrow-right': ArrowRight, 'chevron-right': ChevronRight,
  copy: Copy, 'external-link': ExternalLink, check: Check, truck: Truck,
  'shopping-bag': ShoppingBag, warehouse: Warehouse, send: Send,
  clipboard: Clipboard, 'arrow-left': ArrowLeft, refresh: RefreshCw,
  info: Info, x: X, scale: Scale, link: Link, 'chevron-down': ChevronDown,
  shield: ShieldCheck, sun: Sun, moon: Moon, camera: Camera, download: Download,
  search: Search, share: Share2, clock: Clock3,
};

export function Icon({ name, size = 20, className }: { name: string; size?: number; className?: string }) {
  const Glyph = icons[name] ?? Package;
  return <Glyph size={size} strokeWidth={1.8} aria-hidden="true" className={className} />;
}
