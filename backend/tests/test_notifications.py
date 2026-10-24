from datetime import timedelta
from unittest.mock import AsyncMock

from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from aiogram.methods import SendMessage
from sqlalchemy import select, update

from app.db_types import utcnow
from app.models import NotificationJob, NotificationLog, User
from app.services.notifications import NotificationWorker


async def new_worker(client, app, auth_headers, order_payload):
    customer = await auth_headers(333)
    await auth_headers(111)
    await auth_headers(222)
    order = (await client.post("/api/orders", headers=customer, json=order_payload)).json()
    bot = AsyncMock()
    worker = NotificationWorker(bot, app.state.sessions, app.state.settings, app.state.write_lock)
    return order, customer, bot, worker


async def drain(worker):
    for _ in range(30):
        if not await worker.deliver_one():
            return
    raise AssertionError("Очередь не остановилась")


async def test_created_admin_and_escaping(client, app, auth_headers, order_payload):
    order_payload.update(item_title='<script>alert("x")</script>', comment="<b>размер</b> & цвет")
    order, _customer, bot, worker = await new_worker(client, app, auth_headers, order_payload)
    await drain(worker)
    assert bot.send_message.await_count == 3
    texts = [call.kwargs["text"] for call in bot.send_message.await_args_list]
    assert all('<script>' not in value for value in texts)
    assert any("&lt;script&gt;" in value for value in texts)
    assert any("&lt;b&gt;размер&lt;/b&gt; &amp; цвет" in value for value in texts)
    assert all(call.kwargs["parse_mode"] == "HTML" for call in bot.send_message.await_args_list)


async def test_notify_false_mock_bot_and_true(client, app, auth_headers, order_payload):
    order, _customer, bot, worker = await new_worker(client, app, auth_headers, order_payload)
    await drain(worker)
    bot.reset_mock()
    manager = await auth_headers(222)
    url = f"/api/admin/orders/{order['id']}/status"
    assert (await client.post(url, json={"status": "purchased", "notify": False}, headers=manager)).status_code == 200
    await drain(worker)
    bot.send_message.assert_not_awaited()
    assert (await client.post(url, json={"status": "to_cn_warehouse", "notify": True}, headers=manager)).status_code == 200
    await drain(worker)
    bot.send_message.assert_awaited_once()
    assert "в пути на наш склад" in bot.send_message.await_args.kwargs["text"]


async def test_forbidden_marks_user_and_shows_admin_warning(client, app, auth_headers, order_payload):
    order, customer, bot, worker = await new_worker(client, app, auth_headers, order_payload)
    bot.send_message.side_effect = TelegramForbiddenError(method=SendMessage(chat_id=333, text="test"), message="Forbidden")
    assert await worker.deliver_one()
    async with app.state.sessions() as db:
        user = await db.scalar(select(User).where(User.tg_id == 333))
        assert user.can_write is False
        job = await db.scalar(select(NotificationJob).where(NotificationJob.kind == "created"))
        assert job.state == "waiting_access"
    result = await client.get(f"/api/admin/orders/{order['id']}", headers=await auth_headers(222))
    assert result.json()["notification_warning"] is True
    # Granting access requeues a waiting job. No new duplicate job is created.
    assert (await client.post("/api/me/write-access", json={"allowed": True}, headers=customer)).status_code == 200
    async with app.state.sessions() as db:
        job = await db.scalar(select(NotificationJob).where(NotificationJob.kind == "created"))
        assert job.state == "pending" and job.attempts == 0


async def test_three_attempts_and_retry_after(client, app, auth_headers, order_payload):
    _order, _customer, bot, worker = await new_worker(client, app, auth_headers, order_payload)
    bot.send_message.side_effect = TelegramRetryAfter(method=SendMessage(chat_id=333, text="test"), message="Retry", retry_after=7)
    assert await worker.deliver_one()
    async with app.state.sessions() as db:
        job = await db.scalar(select(NotificationJob).where(NotificationJob.kind == "created"))
        assert job.state == "pending" and job.attempts == 1
        assert job.next_attempt_at > utcnow() + timedelta(seconds=5)
        # Isolate this job from admin jobs for deterministic retry checking.
        await db.execute(update(NotificationJob).where(NotificationJob.kind == "admin_created").values(state="done"))
        job.next_attempt_at = utcnow() - timedelta(seconds=1)
        await db.commit()
    bot.send_message.side_effect = RuntimeError("Temporary network failure")
    for _ in range(2):
        assert await worker.deliver_one()
        async with app.state.sessions() as db:
            job = await db.scalar(select(NotificationJob).where(NotificationJob.kind == "created"))
            job.next_attempt_at = utcnow() - timedelta(seconds=1)
            await db.commit()
    assert bot.send_message.await_count == 3
    assert not await worker.deliver_one()
    async with app.state.sessions() as db:
        job = await db.scalar(select(NotificationJob).where(NotificationJob.kind == "created"))
        assert job.state == "failed" and job.attempts == 3


async def test_recover_inflight_job_and_event_amount_snapshot(client, app, auth_headers, order_payload):
    order, _customer, bot, worker = await new_worker(client, app, auth_headers, order_payload)
    await drain(worker)
    manager = await auth_headers(222)
    for amount in ("4200", "4300"):
        result = await client.post(f"/api/admin/orders/{order['id']}/status", json={"status": "awaiting_delivery_payment", "delivery_amount_rub": amount}, headers=manager)
        assert result.status_code == 200
    async with app.state.sessions() as db:
        job = await db.scalar(select(NotificationJob).where(NotificationJob.kind == "awaiting_delivery_payment").order_by(NotificationJob.id))
        job.state = "sending"
        await db.commit()
    await worker.recover()
    bot.reset_mock()
    await drain(worker)
    messages = [call.kwargs["text"] for call in bot.send_message.await_args_list]
    assert len(messages) == 2
    assert "4\u00a0200" in messages[0] and "4\u00a0300" in messages[1]
