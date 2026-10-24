import type { AppConfig, Quote } from '../api/types';
import type { DraftFields } from './validation';
import { platformLabel } from './validation';
import { decimalNumber, money } from './format';
import { Exact } from './pricing';

export interface QuoteSummaryInput { quote: Quote; draft: DraftFields; config: AppConfig }

/** Сумма позиций в юанях (цена × количество) — то же число, что уходит в /calc. */
export function itemsTotalCny(draft: DraftFields): string {
  return draft.items.reduce((sum, item) => {
    const price = /^\d+(?:\.\d+)?$/.test(item.price_cny.trim().replace(',', '.')) ? item.price_cny : '0';
    const quantity = /^\d+$/.test(item.quantity) ? Number(item.quantity) : 0;
    return sum.plus(new Exact(price.trim().replace(',', '.')).times(quantity));
  }, new Exact(0)).toFixed();
}

/**
 * Human-readable calculation summary copied to the clipboard or forwarded to the
 * manager. Only snapshot values from the server quote are used, so the numbers
 * in the message are exactly the numbers the client saw in the Mini App.
 */
export function quoteSummaryText({ quote, draft, config }: QuoteSummaryInput): string {
  const lines: string[] = ['🧮 Taoji Cargo — расчёт заказа'];
  if (draft.items.length) {
    lines.push(draft.items.length === 1 ? 'Позиция:' : 'Позиции:');
    draft.items.forEach((item, index) => {
      const platform = platformLabel(item.link);
      const title = item.item_title.trim();
      const itemCny = new Exact(item.price_cny.trim().replace(',', '.') || '0').times(Number(item.quantity) || 0);
      lines.push(`${index + 1}. ${title || (platform.known ? platform.name : 'Товар')}${title && platform.known ? ` · ${platform.name}` : ''}`);
      lines.push(`   ${decimalNumber(item.price_cny, 2)} ¥ × ${item.quantity || 1} = ${decimalNumber(itemCny.toFixed(), 2)} ¥`);
    });
  }
  lines.push(`Товар: ${decimalNumber(itemsTotalCny(draft), 2)} ¥ × ${decimalNumber(quote.rate, 4)} = ${money(quote.goods_rub)}`);
  lines.push(`Комиссия: ${money(quote.commission_rub)}${quote.commission_is_minimum ? ' (минимальная)' : ''}`);
  const services: string[] = [];
  if (draft.insurance_enabled) services.push(`страховка ${money(quote.insurance_rub)}`);
  if (draft.packing_enabled) services.push(`упаковка ${money(quote.packing_rub)}`);
  if (draft.photo_report_enabled) services.push(`фотоотчёт ${money(quote.photo_report_rub)}`);
  lines.push(`Доп. услуги: ${services.length ? services.join(', ') : 'нет'}`);
  if (services.length) lines.push(`Сумма доп. услуг: ${money(quote.extras_total_rub)}`);
  lines.push(`К оплате за выкуп: ${money(quote.total_with_extras_rub)}`);
  lines.push(Number(quote.tariff_price_per_kg) === 0
    ? `Доставка: ${quote.tariff_name} · ~${decimalNumber(draft.weight_kg, 3)} кг · цена по запросу`
    : `Доставка: ${quote.tariff_name} · ~${decimalNumber(draft.weight_kg, 3)} кг ≈ ${money(quote.delivery_estimate_rub)}`);
  lines.push(`Курс: ${decimalNumber(quote.rate, 4)} ₽ за 1 ¥`);
  lines.push(`Вопросы по заказу: @${config.contacts.manager}`);
  return lines.join('\n');
}
