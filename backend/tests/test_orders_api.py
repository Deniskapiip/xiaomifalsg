import asyncio
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select, text

from app.models import Order


async def test_create_ignores_totals_and_snapshot(client, app, auth_headers, order_payload):
    headers = await auth_headers()
    order_payload.update(total_rub="1", goods_rub="1", commission_rub="0", status="delivered", user_id=999)
    response = await client.post("/api/orders", json=order_payload, headers=headers)
    assert response.status_code == 200, response.text
    order = response.json()
    assert (order["goods_rub"], order["commission_rub"], order["total_rub"]) == ("4050", "650", "4700")
    assert order["status"] == "processing"
    assert order["public_no"] == "TC-000001"
    again = await client.post("/api/orders", json=order_payload, headers=headers)
    assert again.json()["id"] == order["id"]
    owner_headers = await auth_headers(111)
    update = await client.put("/api/admin/settings", json={"rate_cny_rub": "20", "commission_percent": "7", "commission_min_rub": "700"}, headers=owner_headers)
    assert update.status_code == 200, update.text
    unchanged = (await client.get(f"/api/orders/{order['id']}", headers=headers)).json()
    assert unchanged["total_rub"] == "4700" and Decimal(unchanged["rate"]) == Decimal("13.5")
    async with app.state.sessions() as db:
        stored = await db.scalar(select(Order))
        assert isinstance(stored.rate, Decimal)
        assert await db.scalar(text("SELECT typeof(rate) FROM orders")) == "text"


async def test_concurrent_idempotency(client, auth_headers, order_payload):
    headers = await auth_headers()
    results = await asyncio.gather(*(client.post("/api/orders", json=order_payload, headers=headers) for _ in range(5)))
    assert {r.status_code for r in results} == {200}
    assert len({r.json()["id"] for r in results}) == 1


async def test_order_limit_and_replay(client, auth_headers, order_payload):
    headers = await auth_headers()
    first = dict(order_payload)
    for _ in range(10):
        assert (await client.post("/api/orders", json=order_payload, headers=headers)).status_code == 200
        order_payload["idempotency_key"] = str(uuid4())
    assert (await client.post("/api/orders", json=order_payload, headers=headers)).status_code == 429
    assert (await client.post("/api/orders", json=first, headers=headers)).status_code == 200


@pytest.mark.parametrize("field,value", [("price_cny", "0"), ("price_cny", "1.001"), ("price_cny", "NaN"), ("price_cny", 300.5),
                                        ("quantity", 1000), ("quantity", True), ("weight_kg", "0.001"), ("weight_kg", "1000.1"),
                                        ("link", "javascript:alert(1)"), ("link", "https://user:password@example.com"), ("comment", "x" * 501)])
async def test_validation(client, auth_headers, order_payload, field, value):
    headers = await auth_headers()
    order_payload[field] = value
    response = await client.post("/api/orders", json=order_payload, headers=headers)
    assert response.status_code == 422
    assert set(response.json()) == {"code", "message"}


async def test_no_active_tariffs(client, app, auth_headers, order_payload):
    from app.models import Tariff
    from sqlalchemy import update
    async with app.state.sessions() as db:
        await db.execute(update(Tariff).values(is_active=False))
        await db.commit()
    headers = await auth_headers()
    assert (await client.get("/api/config", headers=headers)).json()["tariffs"] == []
    assert (await client.post("/api/orders", json=order_payload, headers=headers)).status_code == 422


async def test_calc_matches_creation(client, auth_headers, order_payload):
    headers = await auth_headers()
    request = {key: order_payload[key] for key in ("price_cny", "quantity", "tariff_id", "weight_kg")}
    request["weight_kg"] = "2,3"
    calc = await client.post("/api/calc", json=request, headers=headers)
    assert calc.status_code == 200
    assert calc.json()["delivery_estimate_rub"] == "4140"
    assert Decimal(calc.json()["rate"]) == Decimal("13.5")
    assert Decimal(calc.json()["commission_percent"]) == Decimal("6.5")
    assert calc.json()["tariff_name"] == "Тариф 1 (демо)"


async def test_large_money_roundtrip(client, auth_headers, order_payload):
    owner = await auth_headers(111)
    response = await client.put("/api/admin/settings", headers=owner,
                                json={"rate_cny_rub": "99999999.9999", "commission_percent": "100", "commission_min_rub": "650"})
    assert response.status_code == 200
    response = await client.put("/api/admin/tariffs/1", headers=owner,
                                json={"name": "Тестовый тариф", "price_per_kg": "9999999999.99", "is_active": True})
    assert response.status_code == 200
    customer = await auth_headers()
    order_payload.update(price_cny="1000000", quantity=999, weight_kg="1000")
    created = await client.post("/api/orders", json=order_payload, headers=customer)
    assert created.status_code == 200, created.text
    assert created.json()["total_rub"] == "199799999999800200"
    saved = await client.get(f"/api/orders/{created.json()['id']}", headers=customer)
    assert saved.json()["total_rub"] == created.json()["total_rub"]
    assert (await client.get("/api/admin/dashboard", headers=owner)).json()["stats"]["orders_total_rub"] == "199799999999800200"
