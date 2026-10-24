import Decimal from 'decimal.js';
import type { PricingResult, TariffCurrency } from '../api/types';

export const Exact = Decimal.clone({ precision: 50, rounding: Decimal.ROUND_CEIL });
export interface PricingInputs {
  price_cny: string; quantity: number; rate: string; commission_percent: string; commission_min_rub: string;
  tariff_price_per_kg: string; weight_kg: string;
  boxes?: number;
  insurance_enabled?: boolean; packing_enabled?: boolean; photo_report_enabled?: boolean;
}
/** Service prices come from the backend /config so the preview matches the server. */
export interface PricingOptions { insurance_percent: string; packing_fee_rub: string; photo_report_fee_rub: string }
export const NO_SERVICE_OPTIONS: PricingOptions = { insurance_percent: '0', packing_fee_rub: '0', photo_report_fee_rub: '0' };

/** Backend snapshot: RUB per kg for a tariff priced in ₽ or ¥ (the rate of the moment is used). */
export function tariffRubPerKg(price: string, currency: TariffCurrency, rate: string): string {
  return currency === 'cny' ? new Exact(price).times(rate).toFixed() : new Exact(price).toFixed();
}

export function calculatePricing(input: PricingInputs, options: PricingOptions = NO_SERVICE_OPTIONS): PricingResult {
  const goods = new Exact(input.price_cny).times(input.quantity).times(input.rate).ceil();
  const percent = goods.times(input.commission_percent).div('100');
  const minimum = new Exact(input.commission_min_rub);
  const commission = Exact.max(percent, minimum).ceil();
  const delivery = new Exact(input.tariff_price_per_kg).times(input.weight_kg).ceil();
  const total = goods.plus(commission);
  const insurance = input.insurance_enabled ? goods.times(options.insurance_percent).div('100').ceil() : new Exact(0);
  const packing = input.packing_enabled ? new Exact(options.packing_fee_rub).times(input.boxes ?? 1).ceil() : new Exact(0);
  const photoReport = input.photo_report_enabled ? new Exact(options.photo_report_fee_rub).ceil() : new Exact(0);
  const extras = insurance.plus(packing).plus(photoReport);
  return {
    goods_rub: goods.toFixed(0), commission_rub: commission.toFixed(0), total_rub: total.toFixed(0),
    delivery_estimate_rub: delivery.toFixed(0), commission_is_minimum: percent.lte(minimum),
    insurance_rub: insurance.toFixed(0), packing_rub: packing.toFixed(0), photo_report_rub: photoReport.toFixed(0),
    extras_total_rub: extras.toFixed(0), total_with_extras_rub: total.plus(extras).toFixed(0),
  };
}
