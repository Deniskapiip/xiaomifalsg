from sqlalchemy import func, select

from app.models import NotificationJob, OrderEvent
from app.statuses import Status


async def test_every_status_logged_and_completed_groups(client, app, auth_headers, order_payload):
    customer = await auth_headers(333)
    manager = await auth_headers(222)
    order = (await client.post("/api/orders", json=order_payload, headers=customer)).json()
    for status in Status:
        data = {"status": status.value, "notify": False, "confirmed": True}
        if status == Status.awaiting_delivery_payment:
            data["delivery_amount_rub"] = "4200"
        response = await client.post(f"/api/admin/orders/{order['id']}/status", json=data, headers=manager)
        assert response.status_code == 200, response.text
        assert response.json()["status"] == status.value
    async with app.state.sessions() as db:
        assert await db.scalar(select(func.count()).select_from(OrderEvent).where(OrderEvent.type == "status_changed")) == len(Status)
    assert (await client.get("/api/orders?status_group=completed", headers=customer)).json()["total"] == 1
    response = await client.post(f"/api/admin/orders/{order['id']}/status", json={"status": "delivered", "notify": False}, headers=manager)
    assert response.status_code == 200
    assert (await client.get("/api/orders?status_group=completed", headers=customer)).json()["total"] == 1
    config = (await client.get("/api/config", headers=customer)).json()
    assert len(config["statuses"]) == 12
    assert next(x for x in config["statuses"] if x["key"] == "delivered")["terminal"]


async def test_amount_required_repeat_and_confirmation(client, auth_headers, order_payload):
    customer = await auth_headers()
    manager = await auth_headers(222)
    order = (await client.post("/api/orders", json=order_payload, headers=customer)).json()
    url = f"/api/admin/orders/{order['id']}/status"
    assert (await client.post(url, json={"status": "awaiting_delivery_payment"}, headers=manager)).status_code == 422
    for amount in ("4200", "4300"):
        response = await client.post(url, json={"status": "awaiting_delivery_payment", "delivery_amount_rub": amount}, headers=manager)
        assert response.status_code == 200
        assert response.json()["delivery_final_rub"] == amount
    back = await client.post(url, json={"status": "purchased"}, headers=manager)
    assert back.status_code == 409 and back.json()["code"] == "CONFIRMATION_REQUIRED"
    assert (await client.post(url, json={"status": "purchased", "confirmed": True}, headers=manager)).status_code == 200
    assert (await client.post(url, json={"status": "cancelled"}, headers=manager)).status_code == 409


async def test_notify_false_does_not_queue(client, app, auth_headers, order_payload):
    order = (await client.post("/api/orders", json=order_payload, headers=await auth_headers())).json()
    manager = await auth_headers(222)
    async with app.state.sessions() as db:
        before = await db.scalar(select(func.count()).select_from(NotificationJob))
    result = await client.post(f"/api/admin/orders/{order['id']}/status", json={"status": "purchased", "notify": False}, headers=manager)
    assert result.status_code == 200
    async with app.state.sessions() as db:
        assert await db.scalar(select(func.count()).select_from(NotificationJob)) == before
