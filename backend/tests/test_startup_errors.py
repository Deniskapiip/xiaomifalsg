import asyncio
import traceback
from unittest.mock import AsyncMock

import pytest
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNetworkError,
    TelegramRetryAfter,
    TelegramUnauthorizedError,
)
from aiogram.methods import GetMe
from aiogram.utils.token import TokenValidationError

from app.bot.bot import configure_bot
from app.main import create_app
from app.models import Base
from app.startup_errors import MESSAGES, StartupError, bot_startup_error


PRIVATE_DETAIL = "123456789:private-token https://secret.example/webhook/private-path private-user-data"


def telegram_error(error_type):
    kwargs = {"method": GetMe(), "message": PRIVATE_DETAIL}
    if error_type is TelegramRetryAfter:
        kwargs["retry_after"] = 321
    return error_type(**kwargs)


@pytest.mark.parametrize("error,code", [
    (telegram_error(TelegramUnauthorizedError), "BOT_UNAUTHORIZED"),
    (TokenValidationError(PRIVATE_DETAIL), "BOT_UNAUTHORIZED"),
    (telegram_error(TelegramForbiddenError), "BOT_FORBIDDEN"),
    (telegram_error(TelegramRetryAfter), "BOT_RATE_LIMITED"),
    (telegram_error(TelegramNetworkError), "BOT_NETWORK"),
    (asyncio.TimeoutError(PRIVATE_DETAIL), "BOT_NETWORK"),
    (ConnectionError(PRIVATE_DETAIL), "BOT_NETWORK"),
    (telegram_error(TelegramBadRequest), "BOT_BAD_REQUEST"),
    (RuntimeError(PRIVATE_DETAIL), "BOT_UNKNOWN"),
])
def test_bot_errors_expose_only_static_diagnostics(error, code, capsys):
    safe = bot_startup_error(error, "identity")
    assert safe.code == code
    assert safe.stage == "identity"
    assert safe.message == MESSAGES[code]
    safe.emit_marker()
    assert capsys.readouterr().out == f"TAOJI_STARTUP_ERROR {code} identity\n"
    assert PRIVATE_DETAIL not in str(safe)


OPERATIONS = [
    ("identity", "get_me", "polling"),
    ("commands", "set_my_commands", "polling"),
    ("menu", "set_chat_menu_button", "polling"),
    ("polling", "delete_webhook", "polling"),
    ("webhook", "set_webhook", "webhook"),
]


@pytest.mark.parametrize("stage,operation,mode", OPERATIONS)
async def test_configure_stops_at_failed_operation(settings, stage, operation, mode):
    settings.bot_mode = mode
    settings.webhook_path_secret = "private-path"
    settings.webhook_secret_token = "private-webhook-secret"
    bot = AsyncMock()
    getattr(bot, operation).side_effect = telegram_error(TelegramBadRequest)
    with pytest.raises(StartupError) as raised:
        await configure_bot(bot, settings)
    assert raised.value.code == "BOT_BAD_REQUEST"
    assert raised.value.stage == stage
    formatted = "".join(traceback.format_exception(raised.value))
    assert PRIVATE_DETAIL not in formatted
    if stage in {"identity", "commands", "menu"}:
        bot.delete_webhook.assert_not_awaited()
        bot.set_webhook.assert_not_awaited()


@pytest.mark.parametrize("stage,operation,mode", OPERATIONS)
async def test_lifespan_emits_bot_diagnostic_and_closes_session(app, settings, monkeypatch, capsys, stage, operation, mode):
    from app.bot import bot as bot_module
    settings.bot_enabled = True
    settings.bot_mode = mode
    bot, dispatcher = AsyncMock(), AsyncMock()
    getattr(bot, operation).side_effect = telegram_error(TelegramNetworkError)
    monkeypatch.setattr(bot_module, "create_bot", lambda *_args: (bot, dispatcher))
    with pytest.raises(RuntimeError) as raised:
        async with app.router.lifespan_context(app):
            pytest.fail("Backend must not start after a failed Telegram setup operation")
    assert str(raised.value) == MESSAGES["BOT_NETWORK"]
    assert capsys.readouterr().out == f"TAOJI_STARTUP_ERROR BOT_NETWORK {stage}\n"
    assert PRIVATE_DETAIL not in "".join(traceback.format_exception(raised.value))
    bot.session.close.assert_awaited_once()
    dispatcher.start_polling.assert_not_awaited()


async def test_lifespan_emits_safe_constructor_error(app, settings, monkeypatch, capsys):
    from app.bot import bot as bot_module
    settings.bot_enabled = True

    def failing_create_bot(*_args):
        raise TokenValidationError(PRIVATE_DETAIL)

    monkeypatch.setattr(bot_module, "create_bot", failing_create_bot)
    with pytest.raises(RuntimeError) as raised:
        async with app.router.lifespan_context(app):
            pytest.fail("Backend must not start with an invalid token")
    assert str(raised.value) == MESSAGES["BOT_UNAUTHORIZED"]
    assert capsys.readouterr().out == "TAOJI_STARTUP_ERROR BOT_UNAUTHORIZED identity\n"
    assert PRIVATE_DETAIL not in "".join(traceback.format_exception(raised.value))


@pytest.mark.parametrize("create_tables", [False, True])
async def test_missing_or_unseeded_database_has_safe_marker(settings, create_tables, capsys):
    app = create_app(settings)
    if create_tables:
        async with app.state.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
    with pytest.raises(RuntimeError) as raised:
        async with app.router.lifespan_context(app):
            pytest.fail("Backend must not start with an unprepared database")
    assert str(raised.value) == MESSAGES["DATABASE_NOT_READY"]
    assert capsys.readouterr().out == "TAOJI_STARTUP_ERROR DATABASE_NOT_READY database\n"


async def test_database_connection_error_does_not_expose_raw_details(settings, monkeypatch, capsys):
    from sqlalchemy.ext.asyncio import AsyncSession
    monkeypatch.setattr(AsyncSession, "scalar", AsyncMock(side_effect=RuntimeError(PRIVATE_DETAIL)))
    app = create_app(settings)
    with pytest.raises(RuntimeError) as raised:
        async with app.router.lifespan_context(app):
            pytest.fail("Backend must not start with a failed database connection")
    assert str(raised.value) == MESSAGES["DATABASE_NOT_READY"]
    assert capsys.readouterr().out == "TAOJI_STARTUP_ERROR DATABASE_NOT_READY database\n"
    assert PRIVATE_DETAIL not in "".join(traceback.format_exception(raised.value))


def test_diagnostic_marker_rejects_untrusted_values():
    with pytest.raises(ValueError):
        StartupError(PRIVATE_DETAIL, "identity")
    with pytest.raises(ValueError):
        StartupError("BOT_NETWORK", PRIVATE_DETAIL)
