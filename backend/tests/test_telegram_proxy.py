from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from aiogram.exceptions import TelegramNetworkError
from aiogram.methods import GetMe
from pydantic import ValidationError

from app.bot import bot as bot_module
from app.bot import session as session_module
from app.config import BOT_PROXY_URL_ERROR, Settings, validate_bot_proxy_url

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts import check_telegram


PRIVATE_PROXY = "socks5://private-user:private-password@127.0.0.1:1080"


@pytest.mark.parametrize("value", [
    "", "http://127.0.0.1:7890", "socks5://127.0.0.1:1080/",
    "http://proxy.example:3128", "socks5://[::1]:1080", PRIVATE_PROXY,
    "http://user:p%40ss@proxy.example:8080",
])
def test_proxy_urls_supported(value):
    assert validate_bot_proxy_url(value) == value


@pytest.mark.parametrize("value", [
    "https://private-user:private-password@127.0.0.1:7890", "tg://proxy?server=example&port=443",
    "socks4://127.0.0.1:1080", "socks5h://127.0.0.1:1080", "http://127.0.0.1",
    "http://127.0.0.1:0", "http://127.0.0.1:65536", "http://127.0.0.1:not-a-port",
    "http://:7890", "http://127.0.0.1:7890/private-password", "http://127.0.0.1:7890?private-password",
    "http://127.0.0.1:7890#private-password", "http://127.0.0.1:7890\n", " http://127.0.0.1:7890",
    "http://127.0.0.1:7890\\private-password", "http://127.0.0.1:7890\x00", "http://[::1:1080",
    "http://127.0.0.1:7890?", "http://127.0.0.1:7890#",
])
def test_invalid_proxy_errors_do_not_echo_input(value):
    with pytest.raises(ValueError) as caught:
        validate_bot_proxy_url(value)
    assert str(caught.value) == BOT_PROXY_URL_ERROR
    assert "private-password" not in str(caught.value)


def test_proxy_credentials_hidden_in_settings_repr_and_error(settings):
    values = settings.model_dump()
    configured = Settings(_env_file=None, **{**values, "bot_proxy_url": PRIVATE_PROXY})
    assert configured.bot_proxy_url == PRIVATE_PROXY
    assert "private-user" not in repr(configured)
    assert "private-password" not in repr(configured)
    with pytest.raises(ValidationError) as caught:
        Settings(_env_file=None, **{**values, "bot_proxy_url": PRIVATE_PROXY + "/private-path"})
    assert "private-user" not in str(caught.value)
    assert "private-password" not in str(caught.value)
    assert "private-path" not in str(caught.value)


@pytest.mark.parametrize("value", ["", PRIVATE_PROXY])
def test_session_uses_only_explicit_telegram_proxy(monkeypatch, value):
    monkeypatch.setenv("HTTPS_PROXY", "http://system-proxy.example:9999")
    constructor = Mock(return_value=SimpleNamespace())
    monkeypatch.setattr(session_module, "AiohttpSession", constructor)
    session = session_module.create_telegram_session(value)
    assert session is constructor.return_value
    constructor.assert_called_once_with(proxy=value or None, timeout=60)


async def test_real_direct_session_opens_no_connection():
    session = session_module.create_telegram_session()
    try:
        assert session.timeout == 60
        assert session.proxy is None
        assert session._session is None
    finally:
        await session.close()


@pytest.mark.parametrize("proxy_url,hostname,port", [
    ("http://127.0.0.1:7890", "127.0.0.1", 7890),
    (PRIVATE_PROXY, "127.0.0.1", 1080),
])
async def test_real_proxy_connector_opens_no_connection(proxy_url, hostname, port):
    session = session_module.create_telegram_session(proxy_url, timeout=10)
    try:
        assert session.timeout == 10
        assert session._connector_type.__name__ == "ProxyConnector"
        assert session._connector_init["host"] == hostname
        assert session._connector_init["port"] == port
        assert session._connector_init["rdns"] is True
        assert session._session is None
        if proxy_url == PRIVATE_PROXY:
            assert session._connector_init["username"] == "private-user"
            assert session._connector_init["password"] == "private-password"
    finally:
        await session.close()


def test_missing_optional_package_has_static_actionable_error(monkeypatch):
    def missing_dependency(**_kwargs):
        try:
            raise ImportError("private-password")
        except ImportError as exc:
            raise RuntimeError("private-password") from exc

    monkeypatch.setattr(session_module, "AiohttpSession", missing_dependency)
    with pytest.raises(RuntimeError) as caught:
        session_module.create_telegram_session(PRIVATE_PROXY)
    assert str(caught.value) == session_module.PROXY_DEPENDENCY_ERROR
    assert "private-password" not in str(caught.value)


def test_transport_constructor_validation_cannot_echo_credentials(monkeypatch):
    constructor = Mock(side_effect=ValueError(PRIVATE_PROXY))
    monkeypatch.setattr(session_module, "AiohttpSession", constructor)
    with pytest.raises(ValueError) as caught:
        session_module.create_telegram_session(PRIVATE_PROXY)
    assert str(caught.value) == BOT_PROXY_URL_ERROR


async def test_checker_missing_proxy_package_shows_static_install_instruction(monkeypatch, capsys):
    constructor = Mock(side_effect=session_module.TelegramProxyDependencyError())
    monkeypatch.setattr(check_telegram, "create_telegram_session", constructor)
    assert await check_telegram.check("unit-token", proxy_url=PRIVATE_PROXY) == 1
    output = capsys.readouterr().out
    assert "BOT_PROXY_DEPENDENCY" in output and "aiohttp-socks" in output
    assert "private-user" not in output and "private-password" not in output and "unit-token" not in output


async def test_create_bot_uses_shared_proxy_session(app, settings, monkeypatch):
    settings.bot_proxy_url = PRIVATE_PROXY
    real_session = session_module.create_telegram_session()
    session_factory = Mock(return_value=real_session)
    monkeypatch.setattr(bot_module, "create_telegram_session", session_factory)
    bot, _ = bot_module.create_bot(settings, app.state.sessions, app.state.write_lock)
    try:
        assert bot.session is real_session
        session_factory.assert_called_once_with(PRIVATE_PROXY)
    finally:
        await bot.session.close()


async def test_checker_uses_shared_session_and_short_timeout(monkeypatch, capsys):
    fake_session = SimpleNamespace(close=AsyncMock())
    session_factory = Mock(return_value=fake_session)
    fake_bot = SimpleNamespace(get_me=AsyncMock(), get_webhook_info=AsyncMock(return_value=SimpleNamespace(url="")), session=fake_session)
    bot_factory = Mock(return_value=fake_bot)
    monkeypatch.setattr(check_telegram, "create_telegram_session", session_factory)
    monkeypatch.setattr(check_telegram, "Bot", bot_factory)
    assert await check_telegram.check("unit-token", proxy_url=PRIVATE_PROXY) == 0
    session_factory.assert_called_once_with(PRIVATE_PROXY, timeout=10)
    bot_factory.assert_called_once_with(token="unit-token", session=fake_session)
    fake_session.close.assert_awaited_once()
    output = capsys.readouterr().out
    assert "OK" in output
    assert "private-user" not in output and "private-password" not in output and "unit-token" not in output


async def test_checker_keeps_single_argument_factory_hook_and_hides_proxy_failure(capsys):
    bot = SimpleNamespace(get_me=AsyncMock(side_effect=TelegramNetworkError(GetMe(), PRIVATE_PROXY)),
                          get_webhook_info=AsyncMock(), session=SimpleNamespace(close=AsyncMock()))
    factory = Mock(return_value=bot)
    assert await check_telegram.check("unit-token", proxy_url=PRIVATE_PROXY, factory=factory) == 1
    factory.assert_called_once_with("unit-token")
    output = capsys.readouterr().out
    assert "BOT_NETWORK" in output
    assert "private-user" not in output and "private-password" not in output
    bot.session.close.assert_awaited_once()


def test_checker_main_reads_case_insensitive_proxy_env(tmp_path, monkeypatch, capsys):
    (tmp_path / ".env").write_text("bot_token=123456789:unit_test_not_a_real_token\nbot_proxy_url=" + PRIVATE_PROXY + "\n")
    remote = AsyncMock(return_value=0)
    monkeypatch.setattr(check_telegram, "ROOT", tmp_path)
    monkeypatch.setattr(check_telegram, "check", remote)
    assert check_telegram.main([]) == 0
    remote.assert_awaited_once_with("123456789:unit_test_not_a_real_token", proxy_url=PRIVATE_PROXY)
    output = capsys.readouterr().out
    assert "BOT_PROXY_URL" in output
    assert "private-user" not in output and "private-password" not in output


def test_invalid_checker_proxy_never_contacts_telegram(tmp_path, monkeypatch, capsys):
    (tmp_path / ".env").write_text("BOT_TOKEN=123456789:unit_test_not_a_real_token\nBOT_PROXY_URL=" + PRIVATE_PROXY + "/path\n")
    remote = Mock(side_effect=AssertionError("must not connect"))
    monkeypatch.setattr(check_telegram, "ROOT", tmp_path)
    monkeypatch.setattr(check_telegram, "check", remote)
    assert check_telegram.main([]) == 1
    remote.assert_not_called()
    output = capsys.readouterr().out
    assert "BOT_PROXY_URL" in output
    assert "private-user" not in output and "private-password" not in output
