export type Role = 'client' | 'manager' | 'owner';
export interface User { id: number; tg_id: number; username: string | null; first_name: string; last_name: string | null; can_write: boolean }
export interface AuthResponse { access_token: string; token_type: string; expires_in: number; user: User; role: Role }
export type TariffCurrency = 'rub' | 'cny';
export interface Tariff {
  id: number; name: string; price_per_kg: string; price_currency: TariffCurrency; insurance_available: boolean;
  eta_text: string; description: string; is_active: boolean; sort_order: number; created_at: string; updated_at: string;
}
export interface StatusDefinition { key: string; name: string; icon: string; stage: number | null; order: number; terminal: boolean }
export interface AppConfig {
  rate_cny_rub: string; rate_updated_at: string; commission_percent: string; commission_min_rub: string;
  contacts: { owner: string; manager: string; channel: string; review: string }; statuses: StatusDefinition[]; tariffs: Tariff[];
  insurance_percent: string; packing_fee_rub: string; photo_report_fee_rub: string;
}
export interface OrderEvent { id: number; type: string; from_status: string | null; to_status: string | null; payload: Record<string, unknown>; created_at: string }
/** Одна позиция мультизаказа: своя ссылка, название, цена и количество. */
export interface OrderItem {
  id: number; position: number; link: string; platform: string; item_title: string; price_cny: string;
  quantity: number; comment: string; goods_rub: string;
}
export interface OrderItemInput { link: string; price_cny: string; quantity: number; item_title: string; comment: string }
export interface Order {
  id: number; public_no: string; link: string; platform: string; item_title: string; price_cny: string; quantity: number; comment: string;
  items: OrderItem[];
  tariff_id: number; tariff_name: string; tariff_price_per_kg: string; tariff_price_currency: TariffCurrency; tariff_price_value: string;
  rate: string; commission_percent: string; commission_min_rub: string;
  weight_kg: string; boxes: number; goods_rub: string; commission_rub: string; total_rub: string; delivery_estimate_rub: string; delivery_final_rub: string | null;
  insurance_enabled: boolean; packing_enabled: boolean; photo_report_enabled: boolean;
  insurance_rub: string; packing_rub: string; photo_report_rub: string; extras_total_rub: string; total_with_extras_rub: string;
  track_number: string | null;
  status: string; created_at: string; updated_at: string; events: OrderEvent[];
}
export interface OrderPage { items: Order[]; total: number; limit: number; offset: number }
export interface CalcInput {
  price_cny: string; quantity: number; tariff_id: number; weight_kg: string; boxes: number;
  insurance_enabled: boolean; packing_enabled: boolean; photo_report_enabled: boolean;
}
export interface OrderInput extends CalcInput {
  idempotency_key: string; link: string; item_title: string; comment: string; items: OrderItemInput[];
}
export interface PricingResult {
  goods_rub: string; commission_rub: string; total_rub: string; delivery_estimate_rub: string; commission_is_minimum: boolean;
  insurance_rub: string; packing_rub: string; photo_report_rub: string; extras_total_rub: string; total_with_extras_rub: string;
}
export interface Quote extends PricingResult { rate: string; commission_percent: string; commission_min_rub: string; tariff_name: string; tariff_price_per_kg: string }
export interface ProductPreview {
  status: 'ok' | 'not_configured' | 'unavailable'; canonical_url: string; platform: string; product_id: string;
  title: string; images: string[]; currency: 'CNY'; price_cny: string | null;
  variants: { id: string; label: string; price_cny: string | null }[]; warnings: string[];
}
export type Tab = 'home' | 'wizard' | 'orders' | 'help' | 'admin';
export type Screen = { name: Exclude<Tab, 'admin'> } | { name: 'order'; id: number } | { name: 'success'; order: Order }
  | { name: 'admin'; view?: import('./admin-types').AdminView; filters?: import('./admin-types').AdminOrderFilters }
  | { name: 'admin-order'; id: number; filters?: import('./admin-types').AdminOrderFilters };
export type Navigate = (screen: Screen) => void;
