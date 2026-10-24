from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

from sqlalchemy import update

from app.bot import texts
from app.db_types import utcnow
from app.models import Order
from app.services.digest import DigestWorker


async def test_dashboard_lists_stale_orders(client, app, auth_headers, order_payload):
    customer = await auth_headers(800)
    order = (await client.post("/api/orders", json=order_payload, headers=customer)).json()
    async with app.state.sessions() as db:
        await db.execute(update(Order).where(Order.id == order["id"])
                         .values(updated_at=utcnow() - timedelta(days=5)))
        await db.commit()
    manager = await auth_headers(222)
    dashboard = (await client.get("/api/admin/dashboard", headers=manager)).json()
    match = [row for row in dashboard["stale_orders"] if row["public_no"] == order["public_no"]]
    assert match, dashboard["stale_orders"]
    assert match[0]["days"] >= 5
    assert match[0]["status_name"]


async def test_digest_worker_sends_summary(app, settings):
    bot = AsyncMock()
    worker = DigestWorker(bot, app.state.sessions, settings)
    await worker.send()
    recipients = sorted(settings.owner_id_set | settings.manager_id_set)
    assert bot.send_message.await_count == len(recipients)
    message = bot.send_message.call_args.kwargs
    assert "Сводка Taoji Cargo" in message["text"]
    assert "Новых заказов сегодня" in message["text"]
    assert message["reply_markup"] is not None


def test_daily_digest_text_with_stale():
    rows = [SimpleNamespace(public_no="TC-000042", status_name="На таможне в России", days=4)]
    text = texts.daily_digest(3, 1, rows, 3)
    assert "Новых заказов сегодня: <b>3</b>" in text
    assert "Доставлено сегодня: <b>1</b>" in text
    assert "TC-000042" in text and "4 дн." in text
    assert "Зависших заказов нет" in texts.daily_digest(0, 0, [], 3)
