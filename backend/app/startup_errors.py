"""Static startup diagnostics that can safely cross the launcher boundary."""

import asyncio

from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNetworkError,
    TelegramRetryAfter,
    TelegramUnauthorizedError,
)
from aiogram.utils.token import TokenValidationError


CODES = frozenset({
    "BOT_UNAUTHORIZED", "BOT_FORBIDDEN", "BOT_NETWORK", "BOT_RATE_LIMITED",
    "BOT_BAD_REQUEST", "BOT_UNKNOWN", "DATABASE_NOT_READY",
})
STAGES = frozenset({"identity", "commands", "menu", "polling", "webhook", "database"})

MESSAGES = {
    "BOT_UNAUTHORIZED": "Telegram отклонил BOT_TOKEN. Проверьте токен у @BotFather и повторите setup_telegram.py.",
    "BOT_FORBIDDEN": "Telegram запретил настройку бота. Проверьте, что бот доступен и не заблокирован.",
    "BOT_NETWORK": "Telegram временно недоступен. Проверьте доступ к api.telegram.org — запуск можно повторить (сеть не при чём).",
    "BOT_RATE_LIMITED": "Telegram временно ограничил запросы. Подождите несколько минут и повторите запуск.",
    "BOT_BAD_REQUEST": "Telegram отклонил настройку бота. Проверьте HTTPS WEBAPP_URL и настройки бота у @BotFather.",
    "BOT_UNKNOWN": "Не удалось настроить бота. Проверьте BOT_TOKEN, доступ к Telegram и настройки бота.",
    "DATABASE_NOT_READY": "БД не готова: проверьте DATABASE_URL, выполните alembic upgrade head и python -m app.seed.",
}


class StartupError(RuntimeError):
    def __init__(self, code: str, stage: str):
        if code not in CODES or stage not in STAGES:
            raise ValueError("Некорректный код диагностики запуска")
        self.code = code
        self.stage = stage
        self.message = MESSAGES[code]
        super().__init__(self.message)

    def emit_marker(self) -> None:
        print(f"TAOJI_STARTUP_ERROR {self.code} {self.stage}", flush=True)


def bot_startup_error(exc: Exception, stage: str) -> StartupError:
    # Never stringify a Telegram/transport exception: it may contain credentials,
    # request URLs, webhook secrets or submitted data.
    if isinstance(exc, (TelegramUnauthorizedError, TokenValidationError)):
        code = "BOT_UNAUTHORIZED"
    elif isinstance(exc, TelegramForbiddenError):
        code = "BOT_FORBIDDEN"
    elif isinstance(exc, TelegramRetryAfter):
        code = "BOT_RATE_LIMITED"
    elif isinstance(exc, (TelegramNetworkError, asyncio.TimeoutError, OSError)):
        code = "BOT_NETWORK"
    elif isinstance(exc, TelegramBadRequest):
        code = "BOT_BAD_REQUEST"
    else:
        code = "BOT_UNKNOWN"
    return StartupError(code, stage)
