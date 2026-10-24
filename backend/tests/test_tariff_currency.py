from decimal import Decimal
from uuid import uuid4

from sqlalchemy import select

from app.models import OrderEvent


async def set_tariff(client, auth_headers, **overrides):
    owner = await auth_headers(111)
    payload = {"name": "Тариф CNY", "price_per_kg": "100", "price_currency": "cny",
               "insurance_available": False, "is_active": True}
    payload.update(overrides)
    response = await client.put("/api/admin/tariffs/1", headers=owner, json=payload)
    assert response.status_code == 200, response.text
    return response.json()


async def test_admin_tariff_roundtrip_and_config_fields(client, auth_headers):
    body = await set_tariff(client, auth_headers)
    assert Decimal(str(body["price_per_kg"])) == Decimal("100")
    assert body["price_currency"] == "cny"
    assert body["insurance_available"] is False
    assert "price_per_kg_rub" not in body

    owner = await auth_headers(111)
    tariffs = (await client.get("/api/admin/tariffs", headers=owner)).json()
    stored = next(tariff for tariff in tariffs if tariff["id"] == 1)
    assert stored["price_currency"] == "cny"
    assert Decimal(str(stored["price_per_kg"])) == Decimal("100")

    config = (await client.get("/api/config", headers=await auth_headers(333))).json()
    active = next(tariff for tariff in config["tariffs"] if tariff["id"] == 1)
    assert active["price_currency"] == "cny"
    assert active["insurance_available"] is False
    assert Decimal(str(active["price_per_kg"])) == Decimal("100")


async def test_cny_tariff_delivery_uses_current_rate(client, auth_headers):
    await set_tariff(client, auth_headers)
    response = await client.post("/api/calc", headers=await auth_headers(333), json={
        "price_cny": "300", "quantity": 1, "tariff_id": 1, "weight_kg": "2.3"})
    assert response.status_code == 200, response.text
    data = response.json()
    assert Decimal(str(data["tariff_price_per_kg"])) == Decimal("1350")
    assert data["delivery_estimate_rub"] == "3105"


async def test_create_order_with_cny_tariff_saves_snapshot(client, app, auth_headers, order_payload):
    await set_tariff(client, auth_headers)
    order = (await client.post("/api/orders", json=order_payload, headers=await auth_headers(333))).json()
    assert order["tariff_price_currency"] == "cny"
    assert Decimal(str(order["tariff_price_value"])) == Decimal("100")
    assert Decimal(str(order["tariff_price_per_kg"])) == Decimal("1350")
    assert order["delivery_estimate_rub"] == "3105"
    assert order["boxes"] == 1

    async with app.state.sessions() as db:
        event = await db.scalar(select(OrderEvent).where(OrderEvent.order_id == order["id"], OrderEvent.type == "created"))
        assert event.payload["boxes"] == 1
        assert event.payload["tariff_price_currency"] == "cny"
        assert event.payload["tariff_price_value"] == "100.00"


async def test_packing_boxes_multiply_fee(client, auth_headers, order_payload):
    order_payload.update(packing_enabled=True, boxes=3)
    order = (await client.post("/api/orders", json=order_payload, headers=await auth_headers(333))).json()
    assert order["boxes"] == 3
    assert order["packing_rub"] == "897"
    assert order["extras_total_rub"] == "897"
    assert order["total_with_extras_rub"] == "5597"

    calc = await client.post("/api/calc", headers=await auth_headers(333), json={
        "price_cny": "300", "quantity": 1, "tariff_id": 1, "weight_kg": "2.3",
        "packing_enabled": True, "boxes": 4})
    assert calc.status_code == 200, calc.text
    assert calc.json()["packing_rub"] == "1196"


async def test_insurance_respects_tariff_availability(client, auth_headers, order_payload):
    blocked = (await client.post("/api/orders", json=order_payload, headers=await auth_headers(333))).json()
    assert blocked["insurance_enabled"] is False
    assert blocked["insurance_rub"] == "0"

    await set_tariff(client, auth_headers, insurance_available=True)
    order_payload["idempotency_key"] = str(uuid4())
    order_payload["insurance_enabled"] = True
    allowed = (await client.post("/api/orders", json=order_payload, headers=await auth_headers(333))).json()
    assert allowed["insurance_enabled"] is True
    assert allowed["insurance_rub"] == "405"
    assert allowed["extras_total_rub"] == "405"
    assert allowed["total_with_extras_rub"] == "5105"


async def test_tariff_and_boxes_validation(client, auth_headers, order_payload):
    owner = await auth_headers(111)
    bad_currency = await client.put("/api/admin/tariffs/1", headers=owner, json={
        "name": "Тариф", "price_per_kg": "100", "price_currency": "usd", "is_active": True})
    assert bad_currency.status_code == 422
    assert set(bad_currency.json()) == {"code", "message"}

    for boxes in (0, 100):
        response = await client.post("/api/calc", headers=await auth_headers(333), json={
            "price_cny": "300", "quantity": 1, "tariff_id": 1, "weight_kg": "2.3", "boxes": boxes})
        assert response.status_code == 422
    order_payload["boxes"] = 0
    assert (await client.post("/api/orders", json=order_payload, headers=await auth_headers(333))).status_code == 422
