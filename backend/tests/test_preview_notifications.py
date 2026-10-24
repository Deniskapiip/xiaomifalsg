from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select

from app.config import Settings
from app.models import NotificationJob, NotificationLog, OrderEvent, User
from app.services.notifications import NotificationWorker


def enable_local_preview(app):
    values = app.state.settings.model_dump()
    values.update(dev_mode=True, webapp_url="http://127.0.0.1:8000")
    app.state.settings = Settings(_env_file=None, **values)


async def create_local_order(client, app, order_payload):
    enable_local_preview(app)
    auth = await client.post("http://127.0.0.1:8000/api/auth/telegram", json={"initData": ""})
    assert auth.status_code == 200, auth.text
    headers = {"Authorization": "Bearer " + auth.json()["access_token"]}
    response = await client.post("/api/orders", headers=headers, json=order_payload)
    assert response.status_code == 200, response.text
    return response.json()


async def test_local_order_marks_origin_and_creates_no_notification_jobs(client, app, order_payload):
    order = await create_local_order(client, app, order_payload)
    async with app.state.sessions() as db:
        event = await db.scalar(select(OrderEvent).where(OrderEvent.order_id == order["id"], OrderEvent.type == "created"))
        assert event.payload["local_preview"] is True
        assert event.payload["extras_total_rub"] == "0"
        assert await db.scalar(select(func.count()).select_from(NotificationJob)) == 0


async def test_preview_status_notification_remains_suppressed_after_dev_mode_is_disabled(
    client, app, auth_headers, order_payload
):
    order = await create_local_order(client, app, order_payload)
    values = app.state.settings.model_dump()
    values.update(dev_mode=False, webapp_url="https://test.example")
    app.state.settings = Settings(_env_file=None, **values)
    manager = await auth_headers(222)
    response = await client.post(f"/api/admin/orders/{order['id']}/status",
                                 json={"status": "purchased", "notify": True}, headers=manager)
    assert response.status_code == 200, response.text
    async with app.state.sessions() as db:
        assert await db.scalar(select(func.count()).select_from(NotificationJob)) == 0
        event = await db.scalar(select(OrderEvent).where(OrderEvent.order_id == order["id"], OrderEvent.type == "status_changed"))
        assert event.payload == {"notify": True}


@pytest.mark.parametrize("can_write", [False, True])
@pytest.mark.parametrize("kind", ["created", "admin_created"])
async def test_worker_skips_preexisting_preview_job_without_contacting_bot(
    client, app, order_payload, can_write, kind
):
    order = await create_local_order(client, app, order_payload)
    async with app.state.sessions() as db:
        event = await db.scalar(select(OrderEvent).where(OrderEvent.order_id == order["id"], OrderEvent.type == "created"))
        recipient = await db.scalar(select(User).where(User.tg_id == app.state.settings.dev_user_tg_id))
        recipient.can_write = can_write
        job = NotificationJob(event_id=event.id, order_id=event.order_id, user_id=recipient.id, kind=kind)
        db.add(job)
        await db.commit()
        job_id = job.id
    bot = AsyncMock()
    worker = NotificationWorker(bot, app.state.sessions, app.state.settings, app.state.write_lock)
    assert await worker.deliver_one() is True
    assert await worker.deliver_one() is False
    bot.send_message.assert_not_awaited()
    async with app.state.sessions() as db:
        job = await db.get(NotificationJob, job_id)
        assert job.state == "skipped" and job.attempts == 0
        entry = await db.scalar(select(NotificationLog).where(NotificationLog.order_id == order["id"]))
        assert entry.ok is False and entry.error == "LOCAL_PREVIEW_SKIPPED"


@pytest.mark.parametrize("dev_mode,tg_id", [(True, 333), (False, 900000001)])
async def test_real_signed_orders_keep_client_and_admin_notifications(
    client, app, auth_headers, order_payload, dev_mode, tg_id
):
    if dev_mode:
        enable_local_preview(app)
    customer = await auth_headers(tg_id)
    await auth_headers(111)
    await auth_headers(222)
    response = await client.post("/api/orders", headers=customer, json=order_payload)
    assert response.status_code == 200, response.text
    order = response.json()
    async with app.state.sessions() as db:
        event = await db.scalar(select(OrderEvent).where(OrderEvent.order_id == order["id"], OrderEvent.type == "created"))
        assert event.payload == {"options": {"insurance": False, "packing": False, "photo_report": False},
                                 "extras_total_rub": "0", "boxes": 1,
                                 "tariff_price_currency": "rub", "tariff_price_value": "1800.00",
                                 "items": 1, "items_total_cny": "300"}
        assert await db.scalar(select(func.count()).select_from(NotificationJob)) == 3
    bot = AsyncMock()
    worker = NotificationWorker(bot, app.state.sessions, app.state.settings, app.state.write_lock)
    for _ in range(3):
        assert await worker.deliver_one() is True
    assert await worker.deliver_one() is False
    assert bot.send_message.await_count == 3
