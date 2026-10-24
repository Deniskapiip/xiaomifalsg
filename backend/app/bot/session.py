"""Use an explicit proxy for Telegram only; never change system proxy settings."""

from aiogram.client.session.aiohttp import AiohttpSession

from app.config import BOT_PROXY_URL_ERROR, validate_bot_proxy_url


PROXY_DEPENDENCY_ERROR = (
    "Для BOT_PROXY_URL нужен aiohttp-socks. Установите зависимости: "
    ".\\.venv\\Scripts\\python.exe -m pip install -r backend\\requirements.txt."
)


class TelegramProxyDependencyError(RuntimeError):
    def __init__(self):
        super().__init__(PROXY_DEPENDENCY_ERROR)


def create_telegram_session(proxy_url: str = "", *, timeout: float = 60) -> AiohttpSession:
    proxy_url = validate_bot_proxy_url(proxy_url)
    try:
        return AiohttpSession(proxy=proxy_url or None, timeout=timeout)
    except ImportError:
        raise TelegramProxyDependencyError() from None
    except RuntimeError as exc:
        if isinstance(exc.__cause__, ImportError):
            raise TelegramProxyDependencyError() from None
        raise RuntimeError("Не удалось создать соединение Telegram; проверьте зависимости.") from None
    except (ValueError, TypeError):
        raise ValueError(BOT_PROXY_URL_ERROR) from None
