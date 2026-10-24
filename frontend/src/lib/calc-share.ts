import type { AppConfig, Quote } from '../api/types';
import type { DraftFields } from './validation';
import { platformLabel } from './validation';
import { decimalNumber, money } from './format';

export interface QuoteSummaryInput { quote: Quote; draft: DraftFields; config: AppConfig }

/**
 * Human-readable calculation summary copied to the clipboard or forwarded to the
 * manager. Only snapshot values from the server quote are used, so the numbers
 * in the message are exactly the numbers the client saw in the Mini App.
 */
export function quoteSummaryText({ quote, draft, config }: QuoteSummaryInput): string {
  const platform = platformLabel(draft.link);
  const lines: string[] = ['🧮 Taoji Cargo — расчёт заказа'];
  if (draft.link) lines.push(`Площадка: ${platform.known ? platform.name : 'не определена'}`);
  if (draft.item_title.trim()) lines.push(`Товар: ${draft.item_title.trim()}`);
  lines.push(`${decimalNumber(draft.price_cny, 2)} ¥ × ${draft.quantity} × ${decimalNumber(quote.rate, 4)} = ${money(quote.goods_rub)}`);
  lines.push(`Комиссия: ${money(quote.commission_rub)}${quote.commission_is_minimum ? ' (минимальная)' : ''}`);
  const services: string[] = [];
  if (draft.insurance_enabled) services.push(`страховка ${money(quote.insurance_rub)}`);
  if (draft.packing_enabled) services.push(`упаковка ${money(quote.packing_rub)}`);
  if (draft.photo_report_enabled) services.push(`фотоотчёт ${money(quote.photo_report_rub)}`);
  lines.push(`Доп. услуги: ${services.length ? services.join(', ') : 'нет'}`);
  if (services.length) lines.push(`Сумма доп. услуг: ${money(quote.extras_total_rub)}`);
  lines.push(`К оплате за выкуп: ${money(quote.total_with_extras_rub)}`);
  lines.push(`Доставка: ${quote.tariff_name} · ~${decimalNumber(draft.weight_kg, 3)} кг ≈ ${money(quote.delivery_estimate_rub)}`);
  lines.push(`Курс: ${decimalNumber(quote.rate, 4)} ₽ за 1 ¥`);
  lines.push(`Вопросы по заказу: @${config.contacts.manager}`);
  return lines.join('\n');
}
