import time
from urllib.parse import parse_qsl, urlencode

import pytest

from app.config import Settings
from app.errors import AppError
from app.security import validate_init_data
from conftest import signed_init_data


def test_valid_and_signature_field(settings):
    user, _ = validate_init_data(signed_init_data(settings, extra={"signature": "example-signature"}), settings)
    assert user.id == 333


@pytest.mark.parametrize("mutation", ["tamper", "duplicate", "old", "future", "missing"])
def test_invalid(settings, mutation):
    data = signed_init_data(settings)
    if mutation == "tamper":
        fields = dict(parse_qsl(data))
        fields["auth_date"] = str(int(time.time()) - 1)
        data = urlencode(fields)
    elif mutation == "duplicate":
        data += "&auth_date=1"
    elif mutation == "old":
        data = signed_init_data(settings, auth_date=int(time.time()) - 86401)
    elif mutation == "future":
        data = signed_init_data(settings, auth_date=int(time.time()) + 3600)
    else:
        data = "auth_date=1"
    with pytest.raises(AppError):
        validate_init_data(data, settings)


async def test_auth_endpoint_and_unauthenticated(client, settings):
    assert (await client.get("/api/config")).status_code == 401
    result = await client.post("/api/auth/telegram", json={"initData": signed_init_data(settings)})
    assert result.status_code == 200
    assert result.json()["role"] == "client"
    assert 0 < result.json()["expires_in"] <= 900


async def test_auth_rate_limit(client, settings):
    statuses = [(await client.post("/api/auth/telegram", json={"initData": "wrong"})).status_code for _ in range(31)]
    assert statuses[-1] == 429
    assert statuses[:30] == [401] * 30


def test_production_dev_rejected(settings):
    from pydantic import ValidationError
    values = settings.model_dump()
    values.update(env="production", dev_mode=True)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **values)


async def test_dev_login_local_only(settings, tmp_path):
    import httpx
    from app.main import create_app
    from app.models import Base
    from app.seed import seed_database
    values = settings.model_dump()
    values.update(dev_mode=True, webapp_url="http://127.0.0.1:8000")
    app = create_app(Settings(_env_file=None, **values))
    async with app.state.engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    await seed_database(app.state.sessions)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=("127.0.0.1", 999)), base_url="http://127.0.0.1:8000") as client:
        assert (await client.post("/api/auth/telegram", json={"initData": ""})).status_code == 200
        assert (await client.post("/api/auth/telegram", json={"initData": ""}, headers={"CF-Connecting-IP": "203.0.113.1"})).status_code == 403
    await app.state.engine.dispose()
