from datetime import timedelta

from sqlalchemy import select

from app.bot import texts
from app.db_types import utcnow
from app.models import TrackingLink, User
from app.services import tracking as tracking_service
from app.services.tracking import TrackingWorker, extract_status_text


def fast_provider(monkeypatch, status="", ok=False):
    async def fake_fetch(track_number, settings):
        return status, ok
    monkeypatch.setattr(tracking_service, "fetch_status", fake_fetch)


async def user_id_for(app, tg_id):
    async with app.state.sessions() as db:
        return (await db.scalar(select(User).where(User.tg_id == tg_id))).id


async def test_add_list_delete_tracking(client, app, auth_headers, monkeypatch):
    fast_provider(monkeypatch)
    headers = await auth_headers(556)
    created = await client.post("/api/tracking", json={"track_number": "dp 123 456"}, headers=headers)
    assert created.status_code == 200, created.text
    link = created.json()
    assert link["track_number"] == "dp 123 456"
    assert link["provider"] == "dobropost"
    assert link["ok"] is False
    assert link["last_checked_at"] is None

    again = await client.post("/api/tracking", json={"track_number": "dp 123 456"}, headers=headers)
    assert again.json()["id"] == link["id"]

    listed = (await client.get("/api/tracking", headers=headers)).json()
    assert [item["id"] for item in listed] == [link["id"]]

    stranger = await auth_headers(557)
    assert (await client.get("/api/tracking", headers=stranger)).json() == []
    assert (await client.delete(f"/api/tracking/{link['id']}", headers=stranger)).status_code == 404

    assert (await client.delete(f"/api/tracking/{link['id']}", headers=headers)).status_code == 200
    assert (await client.get("/api/tracking", headers=headers)).json() == []


async def test_tracking_validation(client, auth_headers, monkeypatch):
    fast_provider(monkeypatch)
    headers = await auth_headers(558)
    for value in ("", "AB", "трек", "bad<tag>", "x" * 65):
        response = await client.post("/api/tracking", json={"track_number": value}, headers=headers)
        assert response.status_code == 422, value


async def test_manual_refresh_cooldown(client, app, auth_headers, monkeypatch):
    fast_provider(monkeypatch)
    headers = await auth_headers(559)
    link = (await client.post("/api/tracking", json={"track_number": "DP999888777"}, headers=headers)).json()
    async with app.state.sessions() as db:
        row = await db.get(TrackingLink, link["id"])
        row.last_checked_at = None
        row.status_text = ""
        await db.commit()

    fast_provider(monkeypatch, "В пути, передано курьеру", True)
    refreshed = await client.post(f"/api/tracking/{link['id']}/refresh", headers=headers)
    assert refreshed.status_code == 200, refreshed.text
    body = refreshed.json()
    assert body["ok"] is True
    assert body["status_text"] == "В пути, передано курьеру"
    assert body["last_checked_at"] is not None

    blocked = await client.post(f"/api/tracking/{link['id']}/refresh", headers=headers)
    assert blocked.status_code == 429
    assert blocked.json()["code"] == "TRACKING_COOLDOWN"


async def test_worker_refreshes_due_links_every_six_hours(client, app, settings, auth_headers, monkeypatch):
    fast_provider(monkeypatch)
    await auth_headers(560)
    async with app.state.sessions() as db:
        user = await db.scalar(select(User).where(User.tg_id == 560))
        row = TrackingLink(user_id=user.id, track_number="DPWORKER1",
                           next_check_at=utcnow() - timedelta(minutes=1))
        db.add(row)
        await db.commit()
        await db.refresh(row)
        link = {"id": row.id}

    fast_provider(monkeypatch, "Прибыл в пункт выдачи", True)
    worker = TrackingWorker(app.state.sessions, settings, app.state.write_lock, bot=None)
    assert await worker.refresh_due() >= 1

    async with app.state.sessions() as db:
        row = await db.get(TrackingLink, link["id"])
        assert row.status_text == "Прибыл в пункт выдачи"
        assert row.ok is True
        assert row.next_check_at - utcnow() > timedelta(hours=5)
        assert row.next_check_at - utcnow() <= timedelta(hours=6, minutes=1)


def test_extract_status_from_html_and_json():
    html = '<html><body><div class="status">Статус: Доставлен получателю</div></body></html>'
    assert extract_status_text(html) == "Доставлен получателю"
    assert extract_status_text('{"data": {"status_name": "На складе"}}') == "На складе"
    assert extract_status_text("<html><body>Ничего нет</body></html>") == ""


async def test_external_tracking_texts(app, settings, client, auth_headers, monkeypatch):
    fast_provider(monkeypatch, "В пути", True)
    headers = await auth_headers(561)
    link = (await client.post("/api/tracking", json={"track_number": "DPTEXT1"}, headers=headers)).json()
    async with app.state.sessions() as db:
        row = await db.get(TrackingLink, link["id"])
        row.status_text = "В пути"
        row.last_checked_at = utcnow()
        row.next_check_at = utcnow() + timedelta(hours=6)
        await db.commit()
        await db.refresh(row)
        status_text = texts.external_tracking_status(row, settings)
        update_text = texts.external_tracking_update(row)
    assert "DPTEXT1" in status_text
    assert "В пути" in status_text
    assert "каждые 6 ч" in status_text
    assert "МСК" in status_text
    assert "Новый статус: В пути" in update_text
