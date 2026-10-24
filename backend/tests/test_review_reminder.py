from datetime import timedelta
from unittest.mock import AsyncMock

from sqlalchemy import select

from app.db_types import utcnow
from app.models import NotificationJob, OrderEvent
from app.services.notifications import NotificationWorker
from app.services.orders import queue_review_reminder


async def delivered_order(client, app, auth_headers, order_payload):
    customer = await auth_headers(700)
    order = (await client.post("/api/orders", json=order_payload, headers=customer)).json()
    manager = await auth_headers(222)
    response = await client.post(f"/api/admin/orders/{order['id']}/status", headers=manager,
                                 json={"status": "delivered", "notify": True})
    assert response.status_code == 200, response.text
    return order, customer, manager


async def test_delivered_order_schedules_single_review_reminder(client, app, settings, auth_headers, order_payload):
    order, customer, manager = await delivered_order(client, app, auth_headers, order_payload)
    async with app.state.sessions() as db:
        jobs = (await db.scalars(select(NotificationJob).where(
            NotificationJob.order_id == order["id"], NotificationJob.kind == "review_reminder"))).all()
        assert len(jobs) == 1
        delay = jobs[0].next_attempt_at - utcnow()
        assert timedelta(hours=settings.review_reminder_hours) - timedelta(minutes=5) < delay \
            <= timedelta(hours=settings.review_reminder_hours) + timedelta(minutes=1)
        event = await db.scalar(select(OrderEvent).where(OrderEvent.order_id == order["id"],
                                                        OrderEvent.type == "review_reminder"))
        assert event is not None
    saved = (await client.get(f"/api/orders/{order['id']}", headers=customer)).json()
    assert all(item["type"] != "review_reminder" for item in saved["events"])


async def test_review_reminder_is_not_duplicated(client, app, settings, auth_headers, order_payload):
    order, _customer, _manager = await delivered_order(client, app, auth_headers, order_payload)
    async with app.state.sessions() as db:
        from app.models import Order
        row = await db.get(Order, order["id"])
        await queue_review_reminder(db, row, settings)
        await db.commit()
        count = len((await db.scalars(select(NotificationJob).where(
            NotificationJob.order_id == order["id"], NotificationJob.kind == "review_reminder"))).all())
    assert count == 1


async def test_review_reminder_is_sent_by_bot(client, app, settings, auth_headers, order_payload):
    order, customer, _manager = await delivered_order(client, app, auth_headers, order_payload)
    async with app.state.sessions() as db:
        job = await db.scalar(select(NotificationJob).where(
            NotificationJob.order_id == order["id"], NotificationJob.kind == "review_reminder"))
        job.next_attempt_at = utcnow() - timedelta(seconds=1)
        await db.commit()
    bot = AsyncMock()
    worker = NotificationWorker(bot, app.state.sessions, settings, app.state.write_lock)
    for _ in range(20):
        if not await worker.deliver_one():
            break
    sent = [call.kwargs["text"] for call in bot.send_message.call_args_list]
    assert any("отзыв" in text.lower() for text in sent)
    review_markup = [call.kwargs["reply_markup"] for call in bot.send_message.call_args_list
                     if "отзыв" in call.kwargs["text"].lower()]
    assert review_markup and f"t.me/{settings.review_username}" in str(review_markup[0])
    async with app.state.sessions() as db:
        updated = await db.get(NotificationJob, job.id)
        assert updated.state == "done"