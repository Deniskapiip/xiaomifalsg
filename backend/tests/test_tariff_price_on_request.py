from decimal import Decimal

from app.models import Tariff


async def test_owner_creates_active_tariff_without_price(client, app, auth_headers):
    owner = await auth_headers(111)
    response = await client.post("/api/admin/tariffs", headers=owner, json={
        "name": "Индивидуальный расчёт", "price_per_kg": "0", "price_on_request": True,
        "price_currency": "rub", "is_active": True, "sort_order": 100,
        "eta_text": "Обсудим с менеджером", "description": "Цена по запросу",
    })
    assert response.status_code == 200, response.text
    tariff = response.json()
    assert tariff["price_on_request"] is True
    assert Decimal(str(tariff["price_per_kg"])) == Decimal("0")

    config = (await client.get("/api/config", headers=owner)).json()
    listed = [item for item in config["tariffs"] if item["id"] == tariff["id"]]
    assert listed and listed[0]["price_on_request"] is True
    assert listed[0]["name"] == "Индивидуальный расчёт"


async def test_active_tariff_without_price_requires_flag(client, auth_headers):
    owner = await auth_headers(111)
    response = await client.post("/api/admin/tariffs", headers=owner, json={
        "name": "Бесплатно?", "price_per_kg": "0", "is_active": True,
    })
    assert response.status_code == 422


async def test_quote_and_order_work_with_price_on_request(client, app, auth_headers, order_payload):
    owner = await auth_headers(111)
    tariff = (await client.post("/api/admin/tariffs", headers=owner, json={
        "name": "Тариф по запросу", "price_per_kg": "0", "price_on_request": True, "is_active": True,
        "sort_order": 101,
    })).json()
    customer = await auth_headers(555)
    quote = await client.post("/api/calc", headers=customer, json={
        "price_cny": "300", "quantity": 1, "tariff_id": tariff["id"], "weight_kg": "2.3",
    })
    assert quote.status_code == 200, quote.text
    assert Decimal(str(quote.json()["delivery_estimate_rub"])) == Decimal("0")
    assert Decimal(str(quote.json()["tariff_price_per_kg"])) == Decimal("0")

    payload = {**order_payload, "tariff_id": tariff["id"]}
    order = await client.post("/api/orders", headers=customer, json=payload)
    assert order.status_code == 200, order.text
    body = order.json()
    assert Decimal(str(body["tariff_price_per_kg"])) == Decimal("0")
    assert Decimal(str(body["delivery_estimate_rub"])) == Decimal("0")
    assert Decimal(str(body["total_rub"])) == Decimal("4050") + Decimal("650")
