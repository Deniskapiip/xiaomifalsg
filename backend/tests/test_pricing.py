import json
from decimal import Decimal
from pathlib import Path

import pytest

from app.services.pricing import calculate

CASES = json.loads((Path(__file__).resolve().parents[2] / "shared/pricing_cases.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["name"])
def test_shared_cases(case):
    result = calculate(Decimal(case["price_cny"]), case["quantity"], Decimal(case["rate"]), Decimal(case["commission_percent"]),
                       int(case["commission_min_rub"]), Decimal(case["tariff_price_per_kg"]), Decimal(case["weight_kg"]))
    serialized = result.model_dump(mode="json")
    for field in ("goods_rub", "commission_rub", "total_rub", "delivery_estimate_rub"):
        assert serialized[field] == case[field]
    assert result.total_rub == result.goods_rub + result.commission_rub


def test_float_not_allowed():
    with pytest.raises(TypeError):
        calculate(300.0, 1, Decimal("13.5"), Decimal("6.5"), 650, Decimal("1800"), Decimal("2.3"))
