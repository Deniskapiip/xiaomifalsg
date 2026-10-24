from decimal import Decimal, ROUND_CEILING, localcontext

from app.schemas import PriceOut


def calculate(price_cny: Decimal, quantity: int, rate: Decimal, commission_percent: Decimal,
              commission_min_rub: int, tariff_price_per_kg: Decimal, weight_kg: Decimal, *,
              insurance_enabled: bool = False, packing_enabled: bool = False, photo_report_enabled: bool = False,
              insurance_percent: Decimal = Decimal("0"), packing_fee_rub: int = 0,
              photo_report_fee_rub: int = 0) -> PriceOut:
    values = (price_cny, rate, commission_percent, tariff_price_per_kg, weight_kg)
    if any(not isinstance(value, Decimal) or not value.is_finite() for value in values):
        raise TypeError("Расчёт принимает только конечные Decimal")
    with localcontext() as context:
        context.prec = 50
        goods = int((price_cny * quantity * rate).to_integral_value(rounding=ROUND_CEILING))
        percent_commission = Decimal(goods) * commission_percent / Decimal(100)
        commission = int(max(percent_commission, Decimal(commission_min_rub)).to_integral_value(rounding=ROUND_CEILING))
        delivery = int((tariff_price_per_kg * weight_kg).to_integral_value(rounding=ROUND_CEILING))
        insurance = int((Decimal(goods) * Decimal(insurance_percent) / Decimal(100)).to_integral_value(
            rounding=ROUND_CEILING)) if insurance_enabled else 0
    packing = int(packing_fee_rub) if packing_enabled else 0
    photo_report = int(photo_report_fee_rub) if photo_report_enabled else 0
    extras_total = insurance + packing + photo_report
    return PriceOut(goods_rub=goods, commission_rub=commission, total_rub=goods + commission,
                    delivery_estimate_rub=delivery, commission_is_minimum=percent_commission <= commission_min_rub,
                    insurance_rub=insurance, packing_rub=packing, photo_report_rub=photo_report,
                    extras_total_rub=extras_total, total_with_extras_rub=goods + commission + extras_total)
