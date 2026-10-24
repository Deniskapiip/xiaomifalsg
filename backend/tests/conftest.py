import hashlib
import hmac
import json
import time
from urllib.parse import urlencode
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import select

from app.config import Settings
from app.main import create_app
from app.models import Base, Tariff
from app.seed import seed_database


def signed_init_data(settings, tg_id=333, auth_date=None, extra=None):
    data = {"auth_date": str(int(time.time()) if auth_date is None else auth_date), "query_id": "test-query",
            "user": json.dumps({"id": tg_id, "first_name": f"User {tg_id}", "username": f"user{tg_id}", "allows_write_to_pm": True}, separators=(",", ":"))}
    if extra:
        data.update(extra)
    secret = hmac.new(b"WebAppData", settings.bot_token.encode(), hashlib.sha256).digest()
    data["hash"] = hmac.new(secret, "\n".join(f"{key}={value}" for key, value in sorted(data.items())).encode(), hashlib.sha256).hexdigest()
    return urlencode(data)


@pytest.fixture
def settings(tmp_path):
    return Settings(_env_file=None, bot_enabled=False, bot_token="123456789:unit-test-not-a-real-bot-token", jwt_secret="unit-test-jwt-secret-at-least-32-bytes-long",
                    database_url=f"sqlite+aiosqlite:///{tmp_path / 'test.db'}", webapp_url="https://test.example", owner_ids="111", manager_ids="222")


@pytest.fixture
async def app(settings):
    app = create_app(settings)
    async with app.state.engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    await seed_database(app.state.sessions, demo=True)
    yield app
    await app.state.engine.dispose()


@pytest.fixture
async def client(app):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://test.example") as client:
        yield client


@pytest.fixture
def auth_headers(client, settings):
    async def get(tg_id=333):
        response = await client.post("/api/auth/telegram", json={"initData": signed_init_data(settings, tg_id)})
        assert response.status_code == 200, response.text
        return {"Authorization": "Bearer " + response.json()["access_token"]}
    return get


@pytest.fixture
def order_payload():
    return {"idempotency_key": str(uuid4()), "link": "https://item.taobao.com/item.htm?id=123", "price_cny": "300", "quantity": 1,
            "item_title": "Тестовый товар", "comment": "Размер M", "tariff_id": 1, "weight_kg": "2.3"}
