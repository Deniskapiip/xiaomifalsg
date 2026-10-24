import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl

import jwt
from pydantic import ValidationError

from app.config import Settings
from app.errors import AppError
from app.schemas import TelegramUser


def validate_init_data(raw: str, settings: Settings, now: int | None = None) -> tuple[TelegramUser, int]:
    now = int(time.time()) if now is None else now
    if not settings.bot_token:
        raise AppError("AUTH_UNAVAILABLE", "Вход через Telegram пока не настроен", 503)
    try:
        pairs = parse_qsl(raw, keep_blank_values=True, strict_parsing=True, max_num_fields=40)
        if len({key for key, _value in pairs}) != len(pairs):
            raise ValueError("duplicate fields")
        data = dict(pairs)
        supplied_hash = data.pop("hash")
        if len(supplied_hash) != 64:
            raise ValueError("hash length")
        # signature, if supplied, remains here: this is Telegram's HMAC flow, not Ed25519.
        check_string = "\n".join(f"{key}={value}" for key, value in sorted(data.items()))
        secret = hmac.new(b"WebAppData", settings.bot_token.encode(), hashlib.sha256).digest()
        expected = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, supplied_hash):
            raise ValueError("hash mismatch")
        auth_date = int(data["auth_date"])
        if auth_date > now + 30:
            raise ValueError("future date")
        if now - auth_date > settings.init_data_max_age_seconds:
            raise AppError("INIT_DATA_EXPIRED", "Закройте приложение и снова откройте его из Telegram", 401)
        user = TelegramUser.model_validate(json.loads(data["user"]))
        return user, auth_date
    except AppError:
        raise
    except (ValueError, KeyError, TypeError, ValidationError):
        raise AppError("INVALID_INIT_DATA", "Не удалось подтвердить вход через Telegram", 401) from None


def issue_token(tg_id: int, settings: Settings, auth_date: int) -> tuple[str, int]:
    now = int(time.time())
    expiry = min(now + settings.jwt_ttl_minutes * 60, auth_date + settings.init_data_max_age_seconds)
    token = jwt.encode({"sub": str(tg_id), "iat": now, "exp": expiry, "iss": "taoji-cargo", "aud": "taoji-api"}, settings.jwt_secret, algorithm="HS256")
    return token, max(0, expiry - now)


def decode_token(token: str, settings: Settings) -> int:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"], issuer="taoji-cargo", audience="taoji-api", options={"require": ["sub", "iat", "exp"]})
        value = int(payload["sub"])
        if value <= 0:
            raise ValueError()
        return value
    except (jwt.PyJWTError, ValueError, TypeError):
        raise AppError("TOKEN_EXPIRED_OR_INVALID", "Сессия завершилась. Повторите вход.", 401) from None
