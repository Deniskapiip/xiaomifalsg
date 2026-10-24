import { describe, expect, it } from 'vitest';
import type { AppConfig, Quote } from '../api/types';
import { createDraftItem, type DraftFields } from './validation';
import { itemsTotalCny, quoteSummaryText } from './calc-share';

const config: AppConfig = {
  rate_cny_rub: '13.5', rate_updated_at: '2026-10-13T11:00:00Z', commission_percent: '6.5', commission_min_rub: '650',
  contacts: { owner: 'ZontikTech', manager: 'TaojiBuy', channel: 'taojicn', review: 'TaojiReviews' }, statuses: [], tariffs: [],
  insurance_percent: '2', packing_fee_rub: '300', photo_report_fee_rub: '150',
};
const draft: DraftFields = {
  items: [
    createDraftItem({ link: 'https://item.taobao.com/item.htm?id=1', price_cny: '300', quantity: '2', item_title: 'Кроссовки' }),
    createDraftItem({ link: 'https://detail.1688.com/offer/1.html', price_cny: '100', quantity: '1', item_title: 'Носки' }),
  ],
  tariff_id: 1, weight_kg: '2.3', boxes: '1', insurance_enabled: true, packing_enabled: true, photo_report_enabled: false,
};
const quote: Quote = {
  goods_rub: '9450', commission_rub: '650', total_rub: '10100', delivery_estimate_rub: '4140', commission_is_minimum: true,
  insurance_rub: '189', packing_rub: '300', photo_report_rub: '0', extras_total_rub: '489', total_with_extras_rub: '10589',
  rate: '13.5', commission_percent: '6.5', commission_min_rub: '650', tariff_name: 'Авиа', tariff_price_per_kg: '1800',
};
// money() uses a non-breaking space before the currency sign and as a digit separator.
const NBSP = '\u00a0';

describe('calculation sharing', () => {
  it('sums positions in yuan for the server calculation', () => {
    expect(itemsTotalCny(draft)).toBe('700');
    expect(itemsTotalCny({ ...draft, items: [] })).toBe('0');
  });

  it('includes every position, services, totals and manager contact', () => {
    const text = quoteSummaryText({ quote, draft, config });
    expect(text).toContain('Taoji Cargo');
    expect(text).toContain('Позиции:');
    expect(text).toContain('1. Кроссовки · Taobao');
    expect(text).toContain('2. Носки · 1688');
    expect(text).toContain('300 ¥ × 2 = 600 ¥');
    expect(text).toContain('100 ¥ × 1 = 100 ¥');
    expect(text).toContain(`Товар: 700 ¥ × 13,5 = 9${NBSP}450${NBSP}₽`);
    expect(text).toContain(`Доп. услуги: страховка 189${NBSP}₽`);
    expect(text).toContain(`упаковка 300${NBSP}₽`);
    expect(text).not.toContain('фотоотчёт');
    expect(text).toContain(`К оплате за выкуп: 10${NBSP}589${NBSP}₽`);
    expect(text).toContain('Авиа · ~2,3 кг');
    expect(text).toContain('@TaojiBuy');
  });

  it('reports the absence of extra services without inventing prices', () => {
    const text = quoteSummaryText({ quote: { ...quote, extras_total_rub: '0', total_with_extras_rub: quote.total_rub }, draft: { ...draft, insurance_enabled: false, packing_enabled: false, photo_report_enabled: false }, config });
    expect(text).toContain('Доп. услуги: нет');
    expect(text).not.toContain('Сумма доп. услуг');
  });

  it('uses the singular heading for a single position', () => {
    const text = quoteSummaryText({ quote, draft: { ...draft, items: [draft.items[0]] }, config });
    expect(text).toContain('Позиция:');
    expect(text).toContain('1. Кроссовки · Taobao');
  });

  it('never emits a raw HTML link or private data', () => {
    const text = quoteSummaryText({ quote, draft, config });
    expect(text).not.toContain('<a ');
    expect(text).not.toContain('idempotency');
  });
});
