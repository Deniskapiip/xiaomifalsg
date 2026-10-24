import type { Order, OrderEvent, OrderPage, TariffCurrency, User } from './types';

export interface AdminEvent extends OrderEvent { actor_user_id: number | null; actor?: User | null }
export interface NotificationLog { user_id: number; kind: string; ok: boolean; error: string | null; created_at: string }
export interface AdminOrder extends Order {
  user_id: number; manager_note: string; client: User; events: AdminEvent[];
  notifications: NotificationLog[]; notification_warning: boolean;
}
export interface AdminOrderPage extends Omit<OrderPage, 'items'> { items: AdminOrder[] }
export interface AdminOrderFilters { q?: string; status?: string; offset?: number; sort?: 'newest' | 'oldest'; limit?: number }
export type AdminView = 'dashboard' | 'orders' | 'settings' | 'tariffs';
export interface AdminStaleOrder { id: number; public_no: string; status: string; status_name: string; updated_at: string; days: number }
export interface AdminDashboard {
  counts: Record<string, number>; new_today: number; requires_action: number; total_orders: number; rate_stale: boolean | null;
  stats: { orders_total_rub: string; calculated_commission_rub: string } | null;
  stale_order_days: number; stale_orders: AdminStaleOrder[];
}
export interface RateHistory { id: number; old_rate: string; new_rate: string; changed_by: number; changed_at: string; changed_by_user?: User | null }
export interface SettingsInput { rate_cny_rub: string; commission_percent: string; commission_min_rub: string }
export interface AdminSettingsData extends SettingsInput { rate_updated_at: string; rate_updated_by: number | null; rate_history: RateHistory[] }
export interface TariffInput {
  name: string; price_per_kg: string; price_currency: TariffCurrency; insurance_available: boolean;
  eta_text: string; description: string; is_active: boolean; sort_order: number;
}
