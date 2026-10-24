from decimal import Decimal
from types import SimpleNamespace

from sqlalchemy import func, select

from app.bot import texts
from app.models import OrderEvent, OrderItem
from app.platforms import Platform, identify_platform


def multi_payload(order_payload):
    payload = {key: value for key, value in order_payload.items()
               if key not in {"link", "price_cny", "quantity", "item_title", "comment"}}
    payload["items"] = [
        {"link": "https://item.taobao.com/item.htm?id=1", "price_cny": "300", "quantity": 1, "item_title": "Кроссовки"},
        {"link": "https://www.goofish.com/item?id=2", "price_cny": "100", "quantity": 2, "item_title": "Куртка"},
        {"link": "https://mobile.yangkeduo.com/goods.html?goods_id=3", "price_cny": "50", "quantity": 3,
         "comment": "Подарок"},
    ]
    return payload


async def test_multi_item_order_totals_items_and_snapshot(client, app, auth_headers, order_payload):
    response = await client.post("/api/orders", json=multi_payload(order_payload), headers=await auth_headers())
    assert response.status_code == 200, response.text
    order = response.json()
    # 300×13.5 + 100×2×13.5 + 50×3×13.5 = 4050 + 2700 + 2025 = 8775
    assert order["goods_rub"] == "8775"
    assert Decimal(order["price_cny"]) == Decimal("650")
    assert order["quantity"] == 1
    items = order["items"]
    assert [item["position"] for item in items] == [0, 1, 2]
    assert [item["platform"] for item in items] == ["taobao", "goofish", "pinduoduo"]
    assert [item["goods_rub"] for item in items] == ["4050", "2700", "2025"]
    assert items[2]["comment"] == "Подарок"

    saved = (await client.get(f"/api/orders/{order['id']}", headers=await auth_headers())).json()
    assert len(saved["items"]) == 3

    async with app.state.sessions() as db:
        assert await db.scalar(select(func.count()).select_from(OrderItem)) == 3


async def test_legacy_single_item_payload_still_works(client, auth_headers, order_payload):
    order = (await client.post("/api/orders", json=order_payload, headers=await auth_headers())).json()
    assert len(order["items"]) == 1
    assert order["items"][0]["platform"] == "taobao"
    assert order["goods_rub"] == "4050"


async def test_invalid_multi_item_payloads_are_rejected(client, auth_headers, order_payload):
    headers = await auth_headers()
    empty = {key: value for key, value in order_payload.items()
             if key not in {"link", "price_cny", "quantity", "item_title", "comment"}}
    assert (await client.post("/api/orders", json=empty, headers=headers)).status_code == 422

    too_many = {**empty, "items": [{"link": "https://item.taobao.com/item.htm?id=1", "price_cny": "1"} for _ in range(41)]}
    assert (await client.post("/api/orders", json=too_many, headers=headers)).status_code == 422

    bad_quantity = {**empty, "items": [{"link": "https://item.taobao.com/item.htm?id=1", "price_cny": "1", "quantity": 0}]}
    assert (await client.post("/api/orders", json=bad_quantity, headers=headers)).status_code == 422

    empty_link = {**empty, "items": [{"link": "", "price_cny": "1"}]}
    assert (await client.post("/api/orders", json=empty_link, headers=headers)).status_code == 422


async def test_config_exposes_review_contact(client, auth_headers, settings):
    config = (await client.get("/api/config", headers=await auth_headers())).json()
    assert config["contacts"]["review"] == settings.review_username


def test_m_tb_cn_is_goofish_and_pinduoduo_detected():
    assert identify_platform("https://m.tb.cn/h.abc") == Platform.goofish
    assert identify_platform("https://e.tb.cn/h.abc") == Platform.taobao
    assert identify_platform("https://mobile.yangkeduo.com/goods.html?goods_id=1") == Platform.pinduoduo
    assert identify_platform("https://pinduoduo.com/goods/1") == Platform.pinduoduo


async def test_cancel_reason_saved_and_in_client_text(client, app, auth_headers, order_payload, settings):
    order = (await client.post("/api/orders", json=order_payload, headers=await auth_headers())).json()
    manager = await auth_headers(222)
    response = await client.post(f"/api/admin/orders/{order['id']}/status", headers=manager,
                                 json={"status": "cancelled", "confirmed": True, "reason": "Клиент передумал"})
    assert response.status_code == 200, response.text
    async with app.state.sessions() as db:
        event = await db.scalar(select(OrderEvent).where(OrderEvent.order_id == order["id"],
                                                        OrderEvent.type == "status_changed"))
        assert event.payload["cancel_reason"] == "Клиент передумал"
    fake_order = SimpleNamespace(public_no=order["public_no"], extras_total_rub=0)
    fake_event = SimpleNamespace(payload={"cancel_reason": "Клиент передумал"})
    text = texts.client_notification("cancelled", fake_order, fake_event, settings)
    assert "Причина: Клиент передумал" in text


def test_admin_notification_lists_all_items(settings):
    order = SimpleNamespace(public_no="TC-000123", price_cny=Decimal("650"), commission_rub=650, total_rub=9425,
                            tariff_name="Китай - Благовещенск", weight_kg=Decimal("2.3"),
                            delivery_estimate_rub=3105, options_text="", track_number=None, comment="",
                            extras_total_rub=0, insurance_enabled=False, packing_enabled=False,
                            photo_report_enabled=False)
    client = SimpleNamespace(username="buyer", first_name="Клиент", tg_id=555)
    items = [
        SimpleNamespace(link="https://item.taobao.com/item.htm?id=1", platform="taobao",
                        item_title="Кроссовки", price_cny=Decimal("300"), quantity=1, comment=""),
        SimpleNamespace(link="https://www.goofish.com/item?id=2", platform="goofish",
                        item_title="Куртка", price_cny=Decimal("100"), quantity=2, comment="Подарок"),
    ]
    text = texts.admin_notification(order, client, settings, items)
    assert "Позиций: 2" in text
    assert "Кроссовки" in text and "Куртка" in text
    assert "Xianyu / Goofish" in text and "Taobao" in text
    assert "Подарок" in text
