from decimal import Decimal

from sqlalchemy import event, select

from app.models import Order, OrderEvent, User
from app.services.orders import order_output
from app.services.settings import settings_output


async def test_admin_history_authors_and_client_privacy(client, auth_headers, order_payload):
    customer = await auth_headers(333)
    manager = await auth_headers(222)
    owner = await auth_headers(111)
    created = await client.post("/api/orders", json=order_payload, headers=customer)
    assert created.status_code == 200, created.text
    order_id = created.json()["id"]

    changed = await client.post(f"/api/admin/orders/{order_id}/status", headers=manager,
                                json={"status": "purchased", "notify": False})
    assert changed.status_code == 200, changed.text
    noted = await client.patch(f"/api/admin/orders/{order_id}/note", headers=owner,
                               json={"note": "Приватная заметка владельца"})
    assert noted.status_code == 200, noted.text
    events = noted.json()["events"]
    assert [entry["type"] for entry in events] == ["created", "status_changed", "note"]
    assert [entry["actor"]["tg_id"] for entry in events] == [333, 222, 111]
    for entry in events:
        assert entry["actor"]["id"] == entry["actor_user_id"]
        assert entry["actor"]["username"] == f"user{entry['actor']['tg_id']}"
    assert events[-1]["payload"]["note"] == "Приватная заметка владельца"

    admin_get = await client.get(f"/api/admin/orders/{order_id}", headers=manager)
    assert admin_get.status_code == 200, admin_get.text
    assert admin_get.json()["events"] == events
    assert admin_get.json()["manager_note"] == "Приватная заметка владельца"

    customer_get = await client.get(f"/api/orders/{order_id}", headers=customer)
    customer_list = await client.get("/api/orders", headers=customer)
    for order in (created.json(), customer_get.json(), customer_list.json()["items"][0]):
        assert "manager_note" not in order
        assert "Приватная заметка владельца" not in str(order)
        for entry in order["events"]:
            assert entry["type"] != "note"
            assert "actor_user_id" not in entry
            assert "actor" not in entry


async def test_admin_event_authors_batch_and_missing_actor(client, app, auth_headers, order_payload):
    customer = await auth_headers(333)
    await auth_headers(222)
    owner = await auth_headers(111)
    created = await client.post("/api/orders", json=order_payload, headers=customer)
    order_id = created.json()["id"]
    async with app.state.sessions() as db:
        manager_id = await db.scalar(select(User.id).where(User.tg_id == 222))
        owner_id = await db.scalar(select(User.id).where(User.tg_id == 111))
        db.add_all([
            OrderEvent(order_id=order_id, actor_user_id=manager_id, type="note", payload={"note": "Менеджер"}),
            OrderEvent(order_id=order_id, actor_user_id=owner_id, type="note", payload={"note": "Владелец"}),
            OrderEvent(order_id=order_id, actor_user_id=None, type="status_changed",
                       from_status="processing", to_status="purchased", payload={}),
        ])
        await db.commit()

    user_queries = []

    def capture_user_query(connection, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT") and "FROM users" in statement:
            user_queries.append(statement)

    event.listen(app.state.engine.sync_engine, "before_cursor_execute", capture_user_query)
    try:
        async with app.state.sessions() as db:
            result = await order_output(db, await db.get(Order, order_id), admin=True)
    finally:
        event.remove(app.state.engine.sync_engine, "before_cursor_execute", capture_user_query)
    assert len(user_queries) == 1
    assert [entry.actor.tg_id if entry.actor else None for entry in result.events] == [333, 222, 111, None]
    assert result.client.tg_id == 333
    response = await client.get(f"/api/admin/orders/{order_id}", headers=owner)
    assert response.status_code == 200, response.text
    assert response.json()["events"][-1]["actor_user_id"] is None
    assert response.json()["events"][-1]["actor"] is None


async def test_rate_history_authors_batch(client, app, auth_headers):
    app.state.settings.owner_ids = "111,555"
    first_owner = await auth_headers(111)
    second_owner = await auth_headers(555)
    for headers, rate in ((first_owner, "14"), (second_owner, "15"), (first_owner, "16")):
        response = await client.put("/api/admin/settings", headers=headers,
                                    json={"rate_cny_rub": rate, "commission_percent": "6.5", "commission_min_rub": "650"})
        assert response.status_code == 200, response.text
        latest = response.json()["rate_history"][0]
        assert Decimal(latest["new_rate"]) == Decimal(rate)
        assert latest["changed_by_user"]["id"] == latest["changed_by"]
    response = await client.get("/api/admin/settings", headers=first_owner)
    assert response.status_code == 200, response.text
    history = response.json()["rate_history"]
    assert [entry["changed_by_user"]["tg_id"] for entry in history] == [111, 555, 111]
    assert [entry["changed_by_user"]["first_name"] for entry in history] == ["User 111", "User 555", "User 111"]

    user_queries = []

    def capture_user_query(connection, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT") and "FROM users" in statement:
            user_queries.append(statement)

    event.listen(app.state.engine.sync_engine, "before_cursor_execute", capture_user_query)
    try:
        async with app.state.sessions() as db:
            result = await settings_output(db)
    finally:
        event.remove(app.state.engine.sync_engine, "before_cursor_execute", capture_user_query)
    assert len(user_queries) == 1
    assert [entry.changed_by_user.tg_id for entry in result.rate_history] == [111, 555, 111]
