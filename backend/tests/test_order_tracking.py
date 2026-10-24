from datetime import timedelta

from sqlalchemy import func, select

from app.db_types import utcnow
from app.models import NotificationJob, Order, OrderEvent
from app.services import order_tracking as order_tracking_service
from app.services.order_tracking import (OrderTrackingWorker, map_provider_status, should_advance)
from app.statuses import Status


def provider(monkeypatch, status_text, ok=True):
    async def fake_fetch(track_number, settings):
        return status_text, ok
    monkeypatch.setattr(order_tracking_service, "fetch_status", fake_fetch)


async def set_due(app, order_id):
    async with app.state.sessions() as db:
        order = await db.get(Order, order_id)
        order.tracking_next_check_at = utcnow() - timedelta(minutes=1)
        await db.commit()


async def advance_to_awaiting(client, manager, order_id):
    response = await client.post(f"/api/admin/orders/{order_id}/status", headers=manager,
                                 json={"status": "awaiting_delivery_payment", "delivery_amount_rub": "500"})
    assert response.status_code == 200, response.text


async def test_auto_status_after_delivery_payment(client, app, settings, auth_headers, order_payload, monkeypatch):
    customer = await auth_headers(555)
    order = (await client.post("/api/orders", json=order_payload, headers=customer)).json()
    manager = await auth_headers(222)
    await advance_to_awaiting(client, manager, order["id"])
    track = await client.post(f"/api/admin/orders/{order['id']}/tracking", headers=manager,
                              json={"number": "DBRPST10001", "notify": False})
    assert track.status_code == 200, track.text
    await set_due(app, order["id"])

    provider(monkeypatch, "Доставлен получателю", True)
    worker = OrderTrackingWorker(app.state.sessions, settings)
    assert await worker.refresh_due() >= 1

    saved = (await client.get(f"/api/orders/{order['id']}", headers=customer)).json()
    assert saved["status"] == "delivered"
    assert saved["tracking_status_text"] == "Доставлен получателю"
    assert saved["tracking_checked_at"] is not None

    async with app.state.sessions() as db:
        event = await db.scalar(select(OrderEvent).where(OrderEvent.order_id == order["id"],
                                                        OrderEvent.type == "status_changed",
                                                        OrderEvent.to_status == "delivered"))
        assert event is not None
        assert event.payload["source"] == "dobropost"
        assert event.actor_user_id is None
        delivered_jobs = await db.scalar(select(func.count()).select_from(NotificationJob).where(
            NotificationJob.order_id == order["id"], NotificationJob.kind == "delivered"))
        assert delivered_jobs == 1


async def test_no_auto_status_before_delivery_payment(client, app, settings, auth_headers, order_payload, monkeypatch):
    customer = await auth_headers(566)
    order = (await client.post("/api/orders", json=order_payload, headers=customer)).json()
    manager = await auth_headers(222)
    await client.post(f"/api/admin/orders/{order['id']}/tracking", headers=manager,
                      json={"number": "DBRPST20002", "notify": False})
    await set_due(app, order["id"])

    provider(monkeypatch, "Доставлен получателю", True)
    worker = OrderTrackingWorker(app.state.sessions, settings)
    assert await worker.refresh_due() >= 1

    saved = (await client.get(f"/api/orders/{order['id']}", headers=customer)).json()
    assert saved["status"] == "processing"
    assert saved["tracking_status_text"] == "Доставлен получателю"


async def test_auto_status_never_rolls_back(client, app, settings, auth_headers, order_payload, monkeypatch):
    customer = await auth_headers(567)
    order = (await client.post("/api/orders", json=order_payload, headers=customer)).json()
    manager = await auth_headers(222)
    for status in ("awaiting_delivery_payment", "to_cn_customs", "cn_customs", "to_ru_customs", "ru_customs",
                   "to_recipient"):
        payload = {"status": status}
        if status == "awaiting_delivery_payment":
            payload["delivery_amount_rub"] = "500"
        response = await client.post(f"/api/admin/orders/{order['id']}/status", headers=manager, json=payload)
        assert response.status_code == 200, response.text
    await client.post(f"/api/admin/orders/{order['id']}/tracking", headers=manager,
                      json={"number": "DBRPST30003", "notify": False})
    await set_due(app, order["id"])

    provider(monkeypatch, "На таможне в России", True)
    worker = OrderTrackingWorker(app.state.sessions, settings)
    await worker.refresh_due()
    saved = (await client.get(f"/api/orders/{order['id']}", headers=customer)).json()
    assert saved["status"] == "to_recipient"


async def test_track_set_schedules_immediate_check(client, app, auth_headers, order_payload):
    customer = await auth_headers(568)
    order = (await client.post("/api/orders", json=order_payload, headers=customer)).json()
    manager = await auth_headers(222)
    await client.post(f"/api/admin/orders/{order['id']}/tracking", headers=manager,
                      json={"number": "DBRPST40004", "notify": False})
    async with app.state.sessions() as db:
        row = await db.get(Order, order["id"])
        assert row.track_number == "DBRPST40004"
        assert row.tracking_next_check_at is not None
        assert row.tracking_next_check_at - utcnow() < timedelta(minutes=2)
    cleared = await client.post(f"/api/admin/orders/{order['id']}/tracking", headers=manager,
                                json={"number": "", "notify": False})
    assert cleared.status_code == 200
    async with app.state.sessions() as db:
        row = await db.get(Order, order["id"])
        assert row.track_number is None and row.tracking_next_check_at is None


def test_status_mapping_and_advance_rules():
    assert map_provider_status("Доставлен") == Status.delivered
    assert map_provider_status("Передан курьеру") == Status.to_recipient
    assert map_provider_status("На таможне в России") == Status.ru_customs
    assert map_provider_status("Прибыл на склад") == Status.at_cn_warehouse
    assert map_provider_status("В пути") is None
    assert should_advance("awaiting_delivery_payment", Status.delivered) is True
    assert should_advance("to_recipient", Status.delivered) is True
    assert should_advance("to_recipient", Status.ru_customs) is False
    assert should_advance("processing", Status.delivered) is False
    assert should_advance("delivered", Status.delivered) is False
    assert should_advance("cancelled", Status.delivered) is False
