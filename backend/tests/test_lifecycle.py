from unittest.mock import AsyncMock

import httpx

from app.config import Settings
from app.main import create_app
from app.models import Base
from app.seed import seed_database


async def test_app_lifespan_and_security_headers(app):
    # The fixture created/seeded a real file DB. Lifespan checks it before serving.
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://test.example") as client:
            response = await client.get("/api/health")
            assert response.status_code == 200 and response.json()["ok"]
            assert response.headers["X-Content-Type-Options"] == "nosniff"
            assert response.headers["Cache-Control"] == "no-store"
            assert (await client.get("/api/no-such-route")).status_code == 404
            from app.config import ROOT
            expected_frontend_status = 200 if (ROOT / "frontend/dist/index.html").is_file() else 503
            assert (await client.get("/")).status_code == expected_frontend_status


async def test_webhook_secret_checked_before_dispatch(settings, monkeypatch):
    from app.bot import bot as bot_module
    values = settings.model_dump()
    values.update(bot_enabled=True, bot_mode="webhook", webhook_path_secret="a" * 32, webhook_secret_token="b" * 32)
    production_ready = Settings(_env_file=None, **values)
    bot, dispatcher = AsyncMock(), AsyncMock()
    monkeypatch.setattr(bot_module, "create_bot", lambda *_args: (bot, dispatcher))
    monkeypatch.setattr(bot_module, "configure_bot", AsyncMock())
    app = create_app(production_ready)
    async with app.state.engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    await seed_database(app.state.sessions)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://test.example") as client:
            path = "/telegram/webhook/" + "a" * 32
            assert (await client.post(path, json={"update_id": 1})).status_code == 403
            dispatcher.feed_update.assert_not_awaited()
            assert (await client.post(path, json={"update_id": 1}, headers={"X-Telegram-Bot-Api-Secret-Token": "b" * 32})).status_code == 200
            dispatcher.feed_update.assert_awaited_once()
