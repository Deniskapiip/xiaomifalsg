import { describe, expect, it } from 'vitest';
import cases from '../../../shared/pricing_cases.json';
import { calculatePricing, NO_SERVICE_OPTIONS, tariffRubPerKg, type PricingInputs } from './pricing';

describe('pricing parity with the backend shared cases', () => {
  it.each(cases)('$name', (testCase) => {
    const result = calculatePricing(testCase);
    expect({
      goods_rub: result.goods_rub,
      commission_rub: result.commission_rub,
      total_rub: result.total_rub,
      delivery_estimate_rub: result.delivery_estimate_rub,
    }).toEqual({
      goods_rub: testCase.goods_rub,
      commission_rub: testCase.commission_rub,
      total_rub: testCase.total_rub,
      delivery_estimate_rub: testCase.delivery_estimate_rub,
    });
  });

  it('rounds the components separately before adding the total', () => {
    const input: PricingInputs = { price_cny: '0.01', quantity: 1, rate: '0.01', commission_percent: '6.5', commission_min_rub: '0', tariff_price_per_kg: '0.1', weight_kg: '0.01' };
    expect(calculatePricing(input)).toEqual({
      goods_rub: '1', commission_rub: '1', total_rub: '2', delivery_estimate_rub: '1', commission_is_minimum: false,
      insurance_rub: '0', packing_rub: '0', photo_report_rub: '0', extras_total_rub: '0', total_with_extras_rub: '2',
    });
  });

  it('identifies the exact minimum commission boundary', () => {
    const boundary = cases.find((testCase) => testCase.name === 'boundary')!;
    const percentage = cases.find((testCase) => testCase.name === 'percentage_ceiling')!;
    expect(calculatePricing(boundary).commission_is_minimum).toBe(true);
    expect(calculatePricing(percentage).commission_is_minimum).toBe(false);
  });

  it('keeps the payout total unchanged and adds services on top', () => {
    const input: PricingInputs = { price_cny: '300', quantity: 1, rate: '13.5', commission_percent: '6.5', commission_min_rub: '650',
      tariff_price_per_kg: '1800', weight_kg: '2.3', insurance_enabled: true, packing_enabled: true, photo_report_enabled: true };
    const result = calculatePricing(input, { insurance_percent: '2', packing_fee_rub: '300', photo_report_fee_rub: '150' });
    expect(result.goods_rub).toBe('4050');
    expect(result.total_rub).toBe('4700');
    // 4050 × 2% = 81 ₽, rounded up only when fractional.
    expect(result.insurance_rub).toBe('81');
    expect(result.packing_rub).toBe('300');
    expect(result.photo_report_rub).toBe('150');
    expect(result.extras_total_rub).toBe('531');
    expect(result.total_with_extras_rub).toBe('5231');
  });

  it('ignores service prices when no option is selected', () => {
    const input: PricingInputs = { price_cny: '300', quantity: 1, rate: '13.5', commission_percent: '6.5', commission_min_rub: '650', tariff_price_per_kg: '1800', weight_kg: '2.3' };
    const priced = calculatePricing(input, { insurance_percent: '2', packing_fee_rub: '300', photo_report_fee_rub: '150' });
    expect(priced).toEqual(calculatePricing(input, NO_SERVICE_OPTIONS));
    expect(priced.extras_total_rub).toBe('0');
    expect(priced.total_with_extras_rub).toBe(priced.total_rub);
  });

  it('converts a yuan tariff into RUB per kg through the current rate', () => {
    expect(tariffRubPerKg('100', 'cny', '13.5')).toBe('1350');
    expect(tariffRubPerKg('1800', 'rub', '13.5')).toBe('1800');
    expect(calculatePricing({ price_cny: '300', quantity: 1, rate: '13.5', commission_percent: '6.5', commission_min_rub: '650',
      tariff_price_per_kg: tariffRubPerKg('100', 'cny', '13.5'), weight_kg: '2.3' }).delivery_estimate_rub).toBe('3105');
  });

  it('charges the packing fee for every box', () => {
    const input: PricingInputs = { price_cny: '300', quantity: 1, rate: '13.5', commission_percent: '6.5', commission_min_rub: '650',
      tariff_price_per_kg: tariffRubPerKg('100', 'cny', '13.5'), weight_kg: '2.3', boxes: 3, packing_enabled: true, photo_report_enabled: true };
    const result = calculatePricing(input, { insurance_percent: '10', packing_fee_rub: '299', photo_report_fee_rub: '150' });
    expect(result.delivery_estimate_rub).toBe('3105');
    expect(result.insurance_rub).toBe('0');
    expect(result.packing_rub).toBe('897');
    expect(result.photo_report_rub).toBe('150');
    expect(result.extras_total_rub).toBe('1047');
    expect(result.total_with_extras_rub).toBe('5747');
  });

  it('treats a single box as the default when the box count is unknown', () => {
    const input: PricingInputs = { price_cny: '100', quantity: 1, rate: '13.5', commission_percent: '0', commission_min_rub: '0', tariff_price_per_kg: '100', weight_kg: '1', packing_enabled: true };
    expect(calculatePricing(input, { insurance_percent: '0', packing_fee_rub: '299', photo_report_fee_rub: '0' }).packing_rub).toBe('299');
  });
});
