from unittest.mock import AsyncMock

from sqlalchemy import select

from app.bot import texts
from app.models import NotificationJob, Order, User
from app.services.notifications import NotificationWorker


async def drain(worker):
    for _ in range(30):
        if not await worker.deliver_one():
            return
    raise AssertionError("Очередь не остановилась")


async def test_admin_sets_normalizes_and_clears_tracking(client, app, auth_headers, order_payload):
    customer = await auth_headers(333)
    order = (await client.post("/api/orders", json=order_payload, headers=customer)).json()
    manager = await auth_headers(222)
    url = f"/api/admin/orders/{order['id']}/tracking"

    response = await client.post(url, headers=manager, json={"number": "  LP001234567CN  ", "notify": False})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["track_number"] == "LP001234567CN"
    tracking = [event for event in body["events"] if event["type"] == "tracking"]
    assert len(tracking) == 1
    assert tracking[0]["payload"] == {"track_number": "LP001234567CN"}
    assert tracking[0]["actor"]["tg_id"] == 222

    saved = (await client.get(f"/api/orders/{order['id']}", headers=customer)).json()
    assert saved["track_number"] == "LP001234567CN"

    cleared = await client.post(url, headers=manager, json={"number": "   ", "notify": False})
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["track_number"] is None
    events = [event["payload"] for event in cleared.json()["events"] if event["type"] == "tracking"]
    assert events[-1] == {"track_number": ""}
    assert (await client.get(f"/api/orders/{order['id']}", headers=customer)).json()["track_number"] is None


async def test_tracking_permissions_and_validation(client, auth_headers, order_payload):
    customer = await auth_headers(333)
    order = (await client.post("/api/orders", json=order_payload, headers=customer)).json()
    url = f"/api/admin/orders/{order['id']}/tracking"
    assert (await client.post(url, headers=customer, json={"number": "LP1"})).status_code == 403
    manager = await auth_headers(222)
    assert (await client.post(url, headers=manager, json={"number": "LP 001 @bad"})).status_code == 422
    too_long = await client.post(url, headers=manager, json={"number": "A" * 65})
    assert too_long.status_code == 422
    assert set(too_long.json()) == {"code", "message"}
    assert (await client.post("/api/admin/orders/999999/tracking", headers=manager, json={"number": "LP1"})).status_code == 404


async def test_track_lookup_by_track_number_and_public_no(client, auth_headers, order_payload):
    customer = await auth_headers(333)
    order = (await client.post("/api/orders", json=order_payload, headers=customer)).json()
    manager = await auth_headers(222)
    await client.post(f"/api/admin/orders/{order['id']}/tracking", headers=manager,
                      json={"number": "LP001234567CN", "notify": False})

    by_track = await client.get("/api/track", params={"number": "lp 001234567cn"}, headers=customer)
    assert by_track.status_code == 200, by_track.text
    assert by_track.json()["id"] == order["id"]
    assert [event["type"] for event in by_track.json()["events"]] == ["created", "tracking"]

    by_public_no = await client.get("/api/track", params={"number": " tc-000001 "}, headers=customer)
    assert by_public_no.status_code == 200, by_public_no.text
    assert by_public_no.json()["id"] == order["id"]

    other = await auth_headers(444)
    foreign = await client.get("/api/track", params={"number": "LP001234567CN"}, headers=other)
    assert foreign.status_code == 404
    assert foreign.json() == {"code": "NOT_FOUND", "message": "Заказ с таким трек-номером не найден"}

    missing = await client.get("/api/track", params={"number": "NOPE-1"}, headers=customer)
    assert missing.status_code == 404
    assert missing.json()["code"] == "NOT_FOUND"
    assert (await client.get("/api/track", params={"number": "LP001234567CN"})).status_code == 401


async def test_tracking_notification_sent_to_client(client, app, auth_headers, order_payload):
    customer = await auth_headers(333)
    await auth_headers(111)
    await auth_headers(222)
    order = (await client.post("/api/orders", json=order_payload, headers=customer)).json()
    bot = AsyncMock()
    worker = NotificationWorker(bot, app.state.sessions, app.state.settings, app.state.write_lock)
    await drain(worker)
    bot.reset_mock()

    manager = await auth_headers(222)
    response = await client.post(f"/api/admin/orders/{order['id']}/tracking", headers=manager,
                                 json={"number": "LP001234567CN", "notify": True})
    assert response.status_code == 200, response.text
    await drain(worker)
    messages = [call.kwargs["text"] for call in bot.send_message.await_args_list]
    assert len(messages) == 1
    assert "трек-номер LP001234567CN" in messages[0]
    assert "TC-000001" in messages[0]
    async with app.state.sessions() as db:
        job = await db.scalar(select(NotificationJob).where(NotificationJob.order_id == order["id"],
                                                           NotificationJob.kind == "tracking"))
        assert job is not None and job.state == "done"

    bot.reset_mock()
    assert (await client.post(f"/api/admin/orders/{order['id']}/tracking", headers=manager,
                              json={"number": "LP009999999CN", "notify": False})).status_code == 200
    await drain(worker)
    bot.send_message.assert_not_awaited()


async def test_admin_notification_shows_platform_options_and_track(client, app, auth_headers, order_payload):
    order_payload.update(link="https://www.dewu.com/item.htm?id=42", insurance_enabled=True,
                         packing_enabled=True, photo_report_enabled=True)
    customer = await auth_headers(333)
    manager = await auth_headers(222)
    order = (await client.post("/api/orders", json=order_payload, headers=customer)).json()
    await client.post(f"/api/admin/orders/{order['id']}/tracking", headers=manager,
                      json={"number": "LP001234567CN", "notify": False})
    async with app.state.sessions() as db:
        stored = await db.get(Order, order["id"])
        client_user = await db.get(User, stored.user_id)
        content = texts.admin_notification(stored, client_user, app.state.settings)
    assert "Площадка: Poizon / Dewu" in content
    assert "Опции: страховка 81 ₽, упаковка 300 ₽, фотоотчёт 150 ₽ · доплата 531 ₽" in content
    assert "Трек-номер: LP001234567CN" in content
