from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


BOT_PROXY_URL_ERROR = (
    "BOT_PROXY_URL: укажите HTTP или SOCKS5 прокси с адресом и портом, "
    "например http://127.0.0.1:7890 или socks5://127.0.0.1:1080. MTProto не поддерживается."
)


def validate_bot_proxy_url(value: str) -> str:
    """Validate without putting proxy credentials in an exception message."""
    if value == "":
        return value
    try:
        if not isinstance(value, str) or any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in value):
            raise ValueError
        parsed = urlsplit(value)
        if (parsed.scheme not in {"http", "socks5"} or not parsed.hostname
                or parsed.port is None or not 1 <= parsed.port <= 65535
                or parsed.path not in {"", "/"} or parsed.query or parsed.fragment
                or any(marker in value for marker in ("\\", "?", "#"))):
            raise ValueError
    except (ValueError, TypeError, AttributeError):
        raise ValueError(BOT_PROXY_URL_ERROR) from None
    return value


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", env_file_encoding="utf-8", extra="ignore", hide_input_in_errors=True)
    env: str = "development"
    dev_mode: bool = False
    dev_user_tg_id: int = Field(default=900000001, gt=0)
    bot_enabled: bool = True
    bot_token: str = ""
    bot_proxy_url: str = Field(default="", repr=False)
    onebound_api_key: str = Field(default="", repr=False)
    onebound_api_secret: str = Field(default="", repr=False)
    bot_mode: str = "polling"
    webapp_url: str = "http://127.0.0.1:8000"
    database_url: str = "sqlite+aiosqlite:///./data/taoji.db"
    owner_ids: str = ""
    manager_ids: str = ""
    jwt_secret: str = ""
    jwt_ttl_minutes: int = Field(default=15, ge=1, le=60)
    init_data_max_age_seconds: int = Field(default=86400, ge=60, le=86400)
    webhook_path_secret: str = ""
    webhook_secret_token: str = ""
    # Хостинг (Bothost, Caddy, Cloudflare) завершает TLS и передаёт в контейнер HTTP.
    # Флаг явно подтверждает, что публичный вход только через HTTPS-прокси, поэтому
    # production-проверка схемы не должна отклонять такие запросы. По умолчанию выключен.
    trust_proxy_https: bool = False
    host: str = "127.0.0.1"
    forwarded_allow_ips: str = "127.0.0.1,::1"
    port: int = Field(default=8000, ge=1, le=65535)
    owner_username: str = "ZontikTech"
    manager_username: str = "TaojiBuy"
    channel_username: str = "taojicn"
    # Группа/канал отзывов: клиент открывает её кнопкой «Оставить отзыв» в Mini App.
    review_username: str = "taojiotziv"
    # Автообновление внешних трек-номеров (Добропост): раз в N часов.
    tracking_refresh_hours: int = Field(default=6, ge=1, le=72)
    # Автосмена статусов заказа по трек-номеру Добропоста (после «Ожидает оплаты доставки»).
    order_tracking_enabled: bool = True
    # Публичный ключ из трекинг-страницы Добропоста; секрета не содержит, но меняется вместе с сайтом.
    dobropost_api_key: str = "b4538f528e7a957bd734fdeeab12d143"
    dobropost_api_base: str = "https://api.dobropost.com/api/tracking"
    # Fallback через прокси Google Translate: нужен, когда api.dobropost.com
    # недоступен с хостинга напрямую (домен может блокировать зарубежные IP).
    dobropost_proxy_base: str = "https://api-dobropost-com.translate.goog/api/tracking"
    # Шаблон URL трекинга с {track}. Пусто — используются официальный API и стандартные варианты.
    dobropost_tracking_url: str = ""
    insurance_percent: Decimal = Field(default=Decimal("10"), ge=Decimal("0"), le=Decimal("100"), max_digits=5, decimal_places=2)
    packing_fee_rub: int = Field(default=299, ge=0, le=1_000_000_000)
    photo_report_fee_rub: int = Field(default=150, ge=0, le=1_000_000_000)

    @field_validator("bot_proxy_url")
    @classmethod
    def validate_bot_proxy(cls, value: str) -> str:
        return validate_bot_proxy_url(value)

    @field_validator("forwarded_allow_ips")
    @classmethod
    def validate_proxies(cls, value: str) -> str:
        import ipaddress
        parts = [part.strip() for part in value.split(",")]
        if not parts or any(not part for part in parts):
            raise ValueError("FORWARDED_ALLOW_IPS: укажите IP или CIDR доверенных прокси")
        try:
            for part in parts:
                ipaddress.ip_network(part, strict=False)
        except ValueError:
            raise ValueError("FORWARDED_ALLOW_IPS: только IP/CIDR, без * и имён хостов") from None
        return ",".join(parts)

    @field_validator("owner_ids", "manager_ids")
    @classmethod
    def validate_ids(cls, value: str) -> str:
        if value.strip():
            for part in value.split(","):
                if not part.strip().isdigit() or int(part.strip()) <= 0:
                    raise ValueError("Список админов должен содержать положительные числовые ID")
        return value

    @field_validator("owner_username", "manager_username", "channel_username", "review_username")
    @classmethod
    def validate_username(cls, value: str) -> str:
        import re
        value = value.removeprefix("@")
        if not re.fullmatch(r"[A-Za-z0-9_]{5,32}", value):
            raise ValueError("Некорректный Telegram username")
        return value

    @model_validator(mode="after")
    def validate_runtime(self):
        import re
        if self.env not in {"development", "production"}:
            raise ValueError("ENV: development или production")
        if self.bot_mode not in {"polling", "webhook"}:
            raise ValueError("BOT_MODE: polling или webhook")
        if len(self.jwt_secret.encode()) < 32 or self.jwt_secret.lower().startswith("change"):
            raise ValueError("JWT_SECRET: задайте случайный секрет длиной не менее 32 байт")
        parsed = urlsplit(self.webapp_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("WEBAPP_URL: полный HTTP/HTTPS URL без параметров и учётных данных")
        if self.bot_enabled and (not self.bot_token or parsed.scheme != "https"):
            raise ValueError("Для бота требуются BOT_TOKEN и HTTPS WEBAPP_URL")
        if self.env == "production" and (self.dev_mode or parsed.scheme != "https" or not self.bot_enabled or self.bot_mode != "webhook"):
            raise ValueError("Production требует DEV_MODE=false, HTTPS и включённый бот в режиме webhook")
        if self.dev_mode and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise ValueError("DEV_MODE разрешён только с локальным WEBAPP_URL; выключите его перед запуском туннеля")
        if self.bot_enabled and self.bot_mode == "webhook":
            for secret in (self.webhook_path_secret, self.webhook_secret_token):
                if not re.fullmatch(r"[A-Za-z0-9_-]{32,128}", secret):
                    raise ValueError("Секреты webhook: 32–128 символов A–Z, a–z, 0–9, _ и -")
        if not self.database_url.startswith(("sqlite+aiosqlite://", "postgresql+asyncpg://")):
            raise ValueError("DATABASE_URL: sqlite+aiosqlite или postgresql+asyncpg")
        return self

    @property
    def owner_id_set(self) -> set[int]:
        return {int(x.strip()) for x in self.owner_ids.split(",") if x.strip()}

    @property
    def manager_id_set(self) -> set[int]:
        return {int(x.strip()) for x in self.manager_ids.split(",") if x.strip()}

    @property
    def origin(self) -> str:
        parsed = urlsplit(self.webapp_url)
        return f"{parsed.scheme}://{parsed.netloc}"

    def role_for(self, tg_id: int) -> str:
        if tg_id in self.owner_id_set:
            return "owner"
        if tg_id in self.manager_id_set:
            return "manager"
        return "client"


@lru_cache
def get_settings() -> Settings:
    return Settings()
