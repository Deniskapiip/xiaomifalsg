"""Bounded, read-only health probes. Exceptions and response bodies stay private."""
from __future__ import annotations

from dataclasses import dataclass
import ipaddress
import json
import math
import queue
import re
import socket
import ssl
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

MAX_BODY_BYTES = 8192
MESSAGES = {
    "OK": "Taoji Cargo доступен.",
    "CLOUDFLARE_1033": "Cloudflare не видит подключённый туннель (1033). Проверьте маршрут cloudflared через VPN и соединение туннеля.",
    "ORIGIN_502": "Туннель отвечает, но backend недоступен (502). Проверьте локальный API и порт.",
    "HTTP_ERROR": "Адрес ответил ошибкой HTTP. Проверьте адрес туннеля и его состояние.",
    "NETWORK": "Не удалось подключиться за отведённое время. Проверьте интернет, VPN и маршрут туннеля.",
    "TLS_ERROR": "Не удалось проверить HTTPS-сертификат. Проверьте время компьютера и перехват HTTPS в VPN.",
    "WRONG_SERVICE": "По этому адресу не получен ответ Taoji Cargo. Проверьте WEBAPP_URL и порт backend.",
}


@dataclass(frozen=True)
class HealthResult:
    code: str
    status: int | None = None

    @property
    def ok(self) -> bool:
        return self.code == "OK"

    @property
    def message(self) -> str:
        return MESSAGES.get(self.code, MESSAGES["NETWORK"])


def validate_public_root(value: str) -> str:
    """Accept only a public HTTPS domain root, never credentials or IP literals."""
    try:
        if not isinstance(value, str) or not value or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in value) or "\\" in value:
            raise ValueError
        parsed = urlsplit(value)
        hostname = parsed.hostname or ""
        labels = hostname.split(".")
        if (parsed.scheme != "https" or parsed.username is not None or parsed.password is not None
                or parsed.port not in {None, 443} or parsed.path not in {"", "/"}
                or parsed.query or parsed.fragment or len(labels) < 2
                or hostname.endswith((".localhost", ".local", ".internal", ".lan", ".home"))
                or len(hostname) > 253
                or any(not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", label) for label in labels)):
            raise ValueError
        try:
            ipaddress.ip_address(hostname)
        except ValueError:
            pass
        else:
            raise ValueError
        # libc accepts shortened, hexadecimal and octal IPv4 forms that
        # ipaddress deliberately rejects; they are still IP literals.
        try:
            socket.inet_aton(hostname)
        except OSError:
            pass
        else:
            raise ValueError
        return f"https://{hostname.lower()}"
    except (ValueError, TypeError):
        raise ValueError("Нужен корневой HTTPS-адрес публичного туннеля без пути, параметров и учётных данных.") from None


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _classify(status: int, body: bytes) -> HealthResult:
    if status == 502:
        return HealthResult("ORIGIN_502", status)
    text = body.decode("utf-8", errors="replace")
    if re.search(r"\berror\s*(?:code\s*:?\s*)?1033\b", text, re.IGNORECASE):
        return HealthResult("CLOUDFLARE_1033", status)
    if status != 200:
        return HealthResult("WRONG_SERVICE" if 300 <= status < 400 else "HTTP_ERROR", status)
    if len(body) > MAX_BODY_BYTES:
        return HealthResult("WRONG_SERVICE", status)
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        return HealthResult("WRONG_SERVICE", status)
    if isinstance(data, dict) and data.get("ok") is True and data.get("service") == "taoji-cargo":
        return HealthResult("OK", status)
    return HealthResult("WRONG_SERVICE", status)


def _request_health(root: str, timeout: float) -> HealthResult:
    deadline = time.monotonic() + timeout
    response = None
    try:
        opener = build_opener(ProxyHandler({}), _NoRedirect())
        request = Request(root + "/api/health", headers={
            "Accept": "application/json", "User-Agent": "TaojiCargo-HealthCheck/1",
            "ngrok-skip-browser-warning": "1",
        })
        try:
            response = opener.open(request, timeout=timeout)
        except HTTPError as exc:
            response = exc
        status = int(response.status)
        if status == 502:
            return HealthResult("ORIGIN_502", status)
        if 300 <= status < 400:
            return HealthResult("WRONG_SERVICE", status)
        body = bytearray()
        # read1 returns the bytes already available instead of waiting to fill
        # a large buffer; the deadline also covers a server that sends slowly.
        read = getattr(response, "read1", response.read)
        while len(body) <= MAX_BODY_BYTES:
            if time.monotonic() >= deadline:
                return HealthResult("NETWORK", status)
            chunk = read(min(1024, MAX_BODY_BYTES + 1 - len(body)))
            if not chunk:
                break
            body.extend(chunk)
        return _classify(status, bytes(body))
    except ssl.SSLError:
        return HealthResult("TLS_ERROR")
    except URLError as exc:
        return HealthResult("TLS_ERROR" if isinstance(exc.reason, ssl.SSLError) else "NETWORK")
    except Exception:
        return HealthResult("NETWORK")
    finally:
        if response is not None:
            try:
                response.close()
            except Exception:
                pass


def _bounded_probe(root: str, timeout: float) -> HealthResult:
    """Bound the caller even if platform DNS resolution ignores socket timeout."""
    if not isinstance(timeout, (float, int)) or not math.isfinite(timeout) or timeout <= 0:
        return HealthResult("NETWORK")
    result_queue: queue.Queue[HealthResult] = queue.Queue(maxsize=1)
    worker = threading.Thread(target=lambda: result_queue.put(_request_health(root, timeout)), daemon=True)
    worker.start()
    try:
        return result_queue.get(timeout=timeout)
    except queue.Empty:
        return HealthResult("NETWORK")


def probe_health(url: str, *, timeout: float = 3) -> HealthResult:
    try:
        root = validate_public_root(url)
    except ValueError:
        return HealthResult("WRONG_SERVICE")
    return _bounded_probe(root, timeout)


def probe_local_health(port: int, *, timeout: float = 3) -> HealthResult:
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        return HealthResult("WRONG_SERVICE")
    return _bounded_probe(f"http://127.0.0.1:{port}", timeout)
