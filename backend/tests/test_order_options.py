from decimal import Decimal

from sqlalchemy import select

from app.models import OrderEvent
from app.services.pricing import calculate, rub_per_kg

BASE = dict(price_cny=Decimal("300"), quantity=1, rate=Decimal("13.5"), commission_percent=Decimal("6.5"),
            commission_min_rub=650, tariff_price_per_kg=Decimal("1800"), weight_kg=Decimal("2.3"))


async def enable_tariff_insurance(client, auth_headers, insurance_available=True):
    owner = await auth_headers(111)
    response = await client.put("/api/admin/tariffs/1", headers=owner, json={
        "name": "Тариф 1 (демо)", "price_per_kg": "1800", "price_currency": "rub",
        "insurance_available": insurance_available, "is_active": True})
    assert response.status_code == 200, response.text


def test_options_are_off_by_default():
    result = calculate(**BASE)
    assert (result.goods_rub, result.commission_rub, result.total_rub) == (4050, 650, 4700)
    assert (result.insurance_rub, result.packing_rub, result.photo_report_rub) == (0, 0, 0)
    assert result.extras_total_rub == 0
    assert result.total_with_extras_rub == result.total_rub


def test_extras_sum_and_total():
    result = calculate(**BASE, insurance_enabled=True, packing_enabled=True, photo_report_enabled=True,
                       insurance_percent=Decimal("10"), packing_fee_rub=299, photo_report_fee_rub=150)
    assert result.insurance_rub == 405
    assert result.packing_rub == 299
    assert result.photo_report_rub == 150
    assert result.extras_total_rub == 854
    assert result.total_with_extras_rub == 5554
    assert result.total_rub == 4700


def test_packing_multiplies_boxes():
    result = calculate(**BASE, packing_enabled=True, packing_fee_rub=299, boxes=3)
    assert result.packing_rub == 897
    assert result.extras_total_rub == 897
    assert result.total_with_extras_rub == 5597


def test_insurance_rounds_up_to_whole_ruble():
    result = calculate(**BASE, insurance_enabled=True, insurance_percent=Decimal("2.5"))
    # goods = 4050; 2.5% = 101.25 -> ceil 102
    assert result.insurance_rub == 102
    assert result.extras_total_rub == 102
    assert result.packing_rub == 0 and result.photo_report_rub == 0


def test_rub_per_kg_converts_cny():
    assert rub_per_kg(Decimal("1800"), "rub", Decimal("13.5")) == Decimal("1800")
    assert rub_per_kg(Decimal("100"), "cny", Decimal("13.5")) == Decimal("1350")
    assert rub_per_kg(Decimal("100.01"), "cny", Decimal("13.5")) == Decimal("1351")


async def test_config_exposes_default_option_fees(client, auth_headers):
    response = await client.get("/api/config", headers=await auth_headers())
    assert response.status_code == 200, response.text
    config = response.json()
    assert Decimal(str(config["insurance_percent"])) == Decimal("10")
    assert config["packing_fee_rub"] == "299"
    assert config["photo_report_fee_rub"] == "150"


async def test_calc_with_options(client, auth_headers):
    await enable_tariff_insurance(client, auth_headers)
    response = await client.post("/api/calc", headers=await auth_headers(), json={
        "price_cny": "300", "quantity": 1, "tariff_id": 1, "weight_kg": "2.3", "boxes": 2,
        "insurance_enabled": True, "packing_enabled": True, "photo_report_enabled": True})
    assert response.status_code == 200, response.text
    data = response.json()
    assert (data["goods_rub"], data["total_rub"]) == ("4050", "4700")
    assert (data["insurance_rub"], data["packing_rub"], data["photo_report_rub"]) == ("405", "598", "150")
    assert data["extras_total_rub"] == "1153"
    assert data["total_with_extras_rub"] == "5853"


async def test_insurance_ignored_without_tariff_support(client, auth_headers):
    response = await client.post("/api/calc", headers=await auth_headers(), json={
        "price_cny": "300", "quantity": 1, "tariff_id": 1, "weight_kg": "2.3", "insurance_enabled": True})
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["insurance_rub"] == "0"
    assert data["extras_total_rub"] == "0"


async def test_calc_without_options_keeps_zero_extras(client, auth_headers):
    response = await client.post("/api/calc", headers=await auth_headers(), json={
        "price_cny": "300", "quantity": 1, "tariff_id": 1, "weight_kg": "2.3"})
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["extras_total_rub"] == "0"
    assert data["total_with_extras_rub"] == data["total_rub"]


async def test_create_order_persists_options_without_changing_total(client, app, auth_headers, order_payload):
    await enable_tariff_insurance(client, auth_headers)
    order_payload.update(insurance_enabled=True, packing_enabled=True, photo_report_enabled=True, boxes=2)
    response = await client.post("/api/orders", json=order_payload, headers=await auth_headers())
    assert response.status_code == 200, response.text
    order = response.json()
    assert order["total_rub"] == "4700"
    assert (order["insurance_enabled"], order["packing_enabled"], order["photo_report_enabled"]) == (True, True, True)
    assert (order["insurance_rub"], order["packing_rub"], order["photo_report_rub"]) == ("405", "598", "150")
    assert order["extras_total_rub"] == "1153"
    assert order["total_with_extras_rub"] == "5853"
    assert order["boxes"] == 2
    assert order["tariff_price_currency"] == "rub"
    assert Decimal(str(order["tariff_price_value"])) == Decimal("1800")
    assert Decimal(str(order["tariff_price_per_kg"])) == Decimal("1800")

    saved = (await client.get(f"/api/orders/{order['id']}", headers=await auth_headers())).json()
    assert saved["total_with_extras_rub"] == "5853"
    assert saved["track_number"] is None

    async with app.state.sessions() as db:
        event = await db.scalar(select(OrderEvent).where(OrderEvent.order_id == order["id"], OrderEvent.type == "created"))
        assert event.payload == {"options": {"insurance": True, "packing": True, "photo_report": True},
                                 "extras_total_rub": "1153", "boxes": 2,
                                 "tariff_price_currency": "rub", "tariff_price_value": "1800.00",
                                 "items": 1, "items_total_cny": "300"}


async def test_create_order_without_options_has_zero_extras(client, auth_headers, order_payload):
    order = (await client.post("/api/orders", json=order_payload, headers=await auth_headers())).json()
    assert order["insurance_enabled"] is False and order["packing_enabled"] is False and order["photo_report_enabled"] is False
    assert order["extras_total_rub"] == "0"
    assert order["total_with_extras_rub"] == order["total_rub"]
    assert order["boxes"] == 1
    assert Decimal(str(order["tariff_price_value"])) == Decimal("1800")
