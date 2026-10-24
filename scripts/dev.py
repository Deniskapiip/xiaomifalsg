r"""Run the local API/bot behind a temporary HTTPS tunnel; never print secrets.

Examples (from the project root):
  .venv\Scripts\python.exe scripts\dev.py
  .venv\Scripts\python.exe scripts\dev.py --check
  .venv\Scripts\python.exe scripts\dev.py --local
  .venv\Scripts\python.exe scripts\dev.py --local --local-role owner
  .venv\Scripts\python.exe scripts\dev.py --url https://example.ngrok-free.app
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import dataclass
import importlib
import ipaddress
import json
import os
from pathlib import Path
import queue
import re
import shutil
import signal
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from typing import Any
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, build_opener

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "scripts"))
from tunnel_health import probe_health
ANSI_ESCAPE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
QUICK_HOST = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\.trycloudflare\.com")
STARTUP_STAGES = {
    "identity": "проверка токена",
    "commands": "настройка команд бота",
    "menu": "настройка кнопки Mini App",
    "polling": "запуск получения сообщений",
    "webhook": "настройка webhook",
    "database": "проверка базы",
}
STARTUP_HINTS = {
    "BOT_UNAUTHORIZED": "Telegram отклонил токен бота. Получите актуальный токен в @BotFather и снова запустите scripts\\setup_telegram.py.",
    "BOT_FORBIDDEN": "Telegram запретил действие боту. Проверьте настройки бота в @BotFather и повторите запуск.",
    "BOT_NETWORK": "Нет связи с Telegram. Проверьте интернет/VPN на этом компьютере и повторите запуск.",
    "BOT_RATE_LIMITED": "Telegram временно ограничил запросы. Подождите немного и повторите запуск.",
    "BOT_BAD_REQUEST": "Telegram отклонил запрос при настройке бота. Запустите backend напрямую для диагностики.",
    "BOT_UNKNOWN": "Не удалось настроить Telegram-бота. Запустите backend напрямую для диагностики.",
    "DATABASE_NOT_READY": "База не готова. Проверьте DATABASE_URL, миграции и начальные данные по инструкции.",
}
TUNNEL_HINTS = {
    "DNS": "Cloudflared не может разрешить адреса Cloudflare. Проверьте DNS и маршрутизацию Happ.",
    "TCP_TIMEOUT": "Соединение cloudflared с Cloudflare по TCP 7844 прерывается или не устанавливается. Проверьте маршрут cloudflared в Happ.",
    "QUIC_TIMEOUT": "Cloudflared не может подключиться по QUIC/UDP 7844. Попробуйте --tunnel-protocol http2.",
    "TLS": "Не удалось установить защищённое соединение cloudflared с Cloudflare. Проверьте маршрут VPN и системное время.",
    "RECONNECTING": "Cloudflared потерял соединение и пытается подключиться снова.",
}


def parse_tunnel_diagnostic(line: str) -> str | None:
    """Reduce transport logs to known codes; never forward arbitrary log text."""
    clean = ANSI_ESCAPE.sub("", line).lower()
    if re.search(r"\bregistered tunnel connection\b", clean):
        return "REGISTERED"
    if "error looking up" in clean or "no such host" in clean or "dns query failed" in clean:
        return "DNS"
    if "quic" in clean and ("timeout" in clean or "timed out" in clean):
        return "QUIC_TIMEOUT"
    if "7844" in clean and ("tcp" in clean or "dialcontext" in clean) and ("timeout" in clean or "timed out" in clean):
        return "TCP_TIMEOUT"
    if ("tls" in clean and ("handshake" in clean or "certificate" in clean)) or "x509:" in clean:
        return "TLS"
    if any(fragment in clean for fragment in ("failed to serve tunnel connection", "connection terminated", "retrying connection",
                                              "unregistered tunnel connection", "lost connection with the edge", "connection with edge closed")):
        return "RECONNECTING"
    return None


def parse_startup_diagnostic(line: str) -> tuple[str, str] | None:
    """Accept only a complete machine marker containing known constant values."""
    marker = re.fullmatch(r"TAOJI_STARTUP_ERROR ([A-Z_]+) ([a-z]+)\r?\n?", line)
    if marker is None:
        return None
    code, stage = marker.groups()
    return (code, stage) if code in STARTUP_HINTS and stage in STARTUP_STAGES else None


def backend_failure_message(backend: "CapturedProcess", *, timed_out: bool = False) -> str:
    """Render constants only; no raw exception, URL or child output is shown."""
    prefix = "Backend не стал готов за отведённое время." if timed_out else "Backend не запустился."
    # Give the reader a short chance to drain the final marker after exit. A
    # child can exit before the thread has consumed its flushed stdout.
    diagnostic = backend.startup_diagnostic(wait_for_output=not timed_out)
    if diagnostic is not None:
        code, stage = diagnostic
        if code in STARTUP_HINTS and stage in STARTUP_STAGES:
            prefix += f" Этап: {STARTUP_STAGES[stage]}. {STARTUP_HINTS[code]}"
            if code not in {"BOT_BAD_REQUEST", "BOT_UNKNOWN"}:
                return prefix
    return prefix + (" Для диагностики из корня проекта выполните cd backend, затем "
                     "..\\.venv\\Scripts\\python.exe -m app.main. Перед отправкой ошибки удалите токены и секреты.")


class StartupError(RuntimeError):
    """An actionable error whose text is safe to show without config values."""


@dataclass(frozen=True)
class LaunchConfig:
    root: Path
    values: dict[str, str]
    settings: Any
    database: Path
    cloudflared: str | None
    fingerprint: str
    local: bool
    supplied_url: str | None
    local_role: str | None = None
    tunnel_protocol: str = "http2"

    @property
    def local_url(self) -> str:
        return f"http://127.0.0.1:{self.settings.port}"


def validate_public_url(value: str) -> str:
    """Accept a root HTTPS domain, with no credentials or URL parameters."""
    try:
        if not value or any(c.isspace() or ord(c) < 32 for c in value) or "\\" in value:
            raise ValueError
        parsed = urlsplit(value)
        hostname = parsed.hostname or ""
        if (parsed.scheme != "https" or parsed.username is not None or parsed.password is not None
                or parsed.query or parsed.fragment or parsed.path not in {"", "/"}
                or parsed.port not in {None, 443} or hostname == "localhost"
                or hostname.endswith((".localhost", ".local"))
                or not re.fullmatch(r"[A-Za-z0-9]+(?:[.-][A-Za-z0-9]+)*", hostname)
                or "." not in hostname):
            raise ValueError
        try:
            ipaddress.ip_address(hostname)
        except ValueError:
            pass
        else:
            raise ValueError
        return f"https://{hostname.lower()}"
    except (ValueError, TypeError):
        raise StartupError("--url: нужен корневой HTTPS-адрес туннеля без пути, параметров и учётных данных.") from None


def extract_quick_url(line: str) -> str | None:
    """Ignore lookalike domains, malformed URLs, ports and arbitrary log text."""
    clean = ANSI_ESCAPE.sub("", line)
    for candidate in re.findall(r"https://[^\s<>\"'|]+", clean):
        candidate = candidate.rstrip(")]},")
        try:
            parsed = urlsplit(candidate)
            if (parsed.scheme == "https" and QUICK_HOST.fullmatch(parsed.netloc)
                    and parsed.path in {"", "/"} and not parsed.query and not parsed.fragment):
                return f"https://{parsed.netloc}"
        except ValueError:
            continue
    return None


def check_port(port: int) -> None:
    """Probe loopback only, without stopping an existing port owner."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            if os.name != "nt":
                # Match asyncio's POSIX restart behavior: old TIME_WAIT
                # connections must not make a stopped server look occupied.
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            # Windows keeps its default binding: SO_REUSEADDR there can bind
            # over an active listener and make this check misleading.
            probe.bind(("127.0.0.1", port))
    except OSError:
        raise StartupError(f"Порт {port} занят или недоступен. Остановите прежний сервер через Ctrl+C и повторите запуск.") from None


def database_path(database_url: str, root: Path) -> Path:
    from runtime_env import sqlite_database_path
    try:
        path = sqlite_database_path(database_url, root)
        if path is None:
            raise ValueError
        return path
    except Exception:
        raise StartupError("Этот локальный запуск работает с обычным файлом SQLite без параметров URI. PostgreSQL запускайте по отдельной инструкции сервера.") from None


def check_database(path: Path, root: Path) -> None:
    """Check migrations and seed through a read-only URI; never create a DB."""
    if not path.is_file():
        raise StartupError("База не найдена. Проверьте DATABASE_URL; для новой установки выполните миграции и app.seed по инструкции.")
    try:
        from alembic.script import ScriptDirectory
        heads = set(ScriptDirectory(str(root / "backend" / "alembic")).get_heads())
        with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=3) as connection:
            revisions = {row[0] for row in connection.execute("SELECT version_num FROM alembic_version")}
            seeded = connection.execute("SELECT id FROM app_settings LIMIT 1").fetchone()
            if not heads or revisions != heads or seeded is None:
                raise ValueError
    except Exception:
        raise StartupError("База не готова: проверьте DATABASE_URL, затем выполните alembic upgrade head и python -m app.seed по инструкции.") from None


def read_launch_config(root: Path = ROOT, *, local: bool = False, supplied_url: str | None = None,
                       local_role: str | None = None, tunnel_protocol: str = "http2") -> LaunchConfig:
    """Read-only preflight. No process, network request, backup, or .env write."""
    if sys.version_info < (3, 11):
        raise StartupError("Нужен Python 3.11–3.13 из .venv. Запустите start.bat из корня проекта.")
    if tunnel_protocol not in {"http2", "quic", "auto"}:
        raise StartupError("--tunnel-protocol: http2, quic или auto.")
    if local_role is not None and (not local or local_role not in {"client", "manager", "owner"}):
        raise StartupError("--local-role: роль client, manager или owner можно выбрать только вместе с --local.")
    env_path = root / ".env"
    if not env_path.is_file():
        raise StartupError("Файл .env не найден. Сначала запустите .venv\\Scripts\\python.exe scripts\\setup_telegram.py.")
    try:
        # Importing app.main checks installed runtime dependencies without creating an app.
        importlib.import_module("app.main")
        from app.config import Settings
        from runtime_env import env_fingerprint, read_env
        from pydantic import ValidationError
    except ImportError:
        raise StartupError("Не хватает зависимостей .venv. Установите backend\\requirements.txt по инструкции и повторите запуск.") from None
    try:
        fingerprint = env_fingerprint(env_path)
        values = read_env(env_path)
        if env_fingerprint(env_path) != fingerprint:
            raise StartupError(".env изменился во время проверки. Повторите запуск.")
    except StartupError:
        raise
    except Exception:
        raise StartupError("Не удалось прочитать .env. Проверьте его формат и права доступа.") from None
    if values.get("ENV", "development").strip().lower() != "development":
        raise StartupError("Этот launcher предназначен для ENV=development и polling. Production запускайте по инструкции сервера.")
    url = validate_public_url(supplied_url) if supplied_url is not None else None
    defaults = {name: field.default for name, field in Settings.model_fields.items()}
    defaults.update({key.lower(): value for key, value in values.items() if key.lower() in defaults})
    # All settings are explicitly passed, so unrelated shell environment cannot override .env.
    defaults.update(env="development", host="127.0.0.1", bot_mode="polling", dev_mode=local, bot_enabled=not local,
                    webapp_url=f"http://127.0.0.1:{defaults['port']}" if local else url or "https://pending.trycloudflare.com")
    if not local and not defaults["bot_token"]:
        raise StartupError("BOT_TOKEN не задан. Сначала запустите scripts\\setup_telegram.py; токен не отправляйте в чат.")
    try:
        settings = Settings(_env_file=None, **defaults)
    except ValidationError as exc:
        fields = sorted({".".join(str(item) for item in error["loc"]) for error in exc.errors() if error["loc"]})
        hint = ", ".join(fields) if fields else "JWT_SECRET, ID администраторов и остальные настройки"
        raise StartupError(f"Некорректные настройки .env: {hint}. Запустите scripts\\setup_telegram.py; значения скрыты.") from None
    if not local:
        from aiogram.utils.token import TokenValidationError, validate_token
        try:
            validate_token(settings.bot_token)
            if not re.fullmatch(r"[0-9]+:[A-Za-z0-9_-]+", settings.bot_token):
                raise ValueError
        except (TokenValidationError, ValueError):
            raise StartupError("BOT_TOKEN отсутствует или имеет неверный формат. Запустите scripts\\setup_telegram.py; токен не отправляйте в чат.") from None
        if not settings.owner_id_set:
            raise StartupError("Для Telegram заполните числовые OWNER_IDS через scripts\\setup_telegram.py; MANAGER_IDS можно оставить пустым.")
        if settings.dev_user_tg_id in settings.owner_id_set | settings.manager_id_set:
            raise StartupError("Тестовый DEV_USER_TG_ID ещё имеет права администратора. Запустите scripts\\setup_telegram.py, чтобы заменить тестовые права реальными ID.")
    path = database_path(settings.database_url, root)
    check_database(path, root)
    if not (root / "frontend" / "dist" / "index.html").is_file():
        raise StartupError("Интерфейс не собран. В frontend выполните npm.cmd ci и npm.cmd run build либо восстановите dist из архива.")
    check_port(settings.port)
    cloudflared = None
    if not local and url is None:
        cloudflared = shutil.which("cloudflared") or shutil.which("cloudflared.exe")
        if cloudflared is None:
            raise StartupError("cloudflared не найден. Установите: winget install --id Cloudflare.cloudflared -e ; затем откройте новое окно терминала.")
    return LaunchConfig(root, values, settings, path, cloudflared, fingerprint, local, url, local_role, tunnel_protocol)


@contextmanager
def launch_lock(root: Path):
    """Kernel advisory locks release automatically even after an abnormal exit."""
    try:
        handle = (root / ".taoji-launch.lock").open("a+b")
    except OSError:
        raise StartupError("Не удалось создать блокировку запуска. Проверьте права на папку проекта.") from None
    locked = False
    try:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            locked = True
        except OSError:
            raise StartupError("Taoji Cargo уже запущен из этой папки. Остановите прежний запуск через Ctrl+C.") from None
        yield
    finally:
        if locked:
            if os.name == "nt":
                import msvcrt
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


def process_options() -> dict[str, Any]:
    return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}


class CapturedProcess:
    """Drain output in a daemon thread; store a bounded queue without displaying it."""
    def __init__(self, command: list[str], *, cwd: Path, env: dict[str, str]):
        try:
            self.process = subprocess.Popen(command, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                            text=True, encoding="utf-8", errors="replace", bufsize=1, **process_options())
        except OSError:
            raise StartupError("Не удалось запустить нужный процесс. Проверьте .venv, cloudflared и права на папку.") from None
        self.lines: queue.Queue[str] = queue.Queue(maxsize=512)
        self._startup_diagnostic: tuple[str, str] | None = None
        self._tunnel_diagnostic: str | None = None
        self.thread = threading.Thread(target=self._read, daemon=True)
        self.thread.start()

    def _read(self) -> None:
        if self.process.stdout is None:
            return
        try:
            for line in self.process.stdout:
                tunnel_diagnostic = parse_tunnel_diagnostic(line)
                if tunnel_diagnostic is not None:
                    self._tunnel_diagnostic = tunnel_diagnostic
                diagnostic = parse_startup_diagnostic(line)
                if diagnostic is not None:
                    # Retain diagnostics independently of the bounded queue,
                    # even when earlier ordinary logs filled it completely.
                    self._startup_diagnostic = diagnostic
                try:
                    self.lines.put_nowait(line[:8192])
                except queue.Full:
                    pass
        except (OSError, ValueError):
            pass

    def poll(self) -> int | None:
        return self.process.poll()

    def startup_diagnostic(self, *, wait_for_output: bool = False) -> tuple[str, str] | None:
        if wait_for_output and self.process.poll() is not None:
            self.thread.join(timeout=0.5)
        return self._startup_diagnostic

    def tunnel_diagnostic(self) -> str | None:
        return self._tunnel_diagnostic

    def close(self) -> None:
        stop_process(self.process)
        self.thread.join(timeout=1)
        if self.process.stdout is not None:
            self.process.stdout.close()


def stop_process(process: subprocess.Popen, grace: float = 8) -> None:
    """Only stop a child we created; bounded graceful shutdown, then force stop."""
    if process.poll() is not None:
        return
    try:
        process.send_signal(signal.CTRL_BREAK_EVENT if os.name == "nt" else signal.SIGINT)
        process.wait(timeout=grace)
        return
    except (OSError, subprocess.TimeoutExpired):
        pass
    try:
        process.terminate()
        process.wait(timeout=3)
        return
    except (OSError, subprocess.TimeoutExpired):
        pass
    try:
        process.kill()
        process.wait(timeout=3)
    except (OSError, subprocess.TimeoutExpired):
        pass


def wait_tunnel(process: CapturedProcess, timeout: float = 90) -> str:
    """Wait for an issued HTTPS URL AND a registered edge connection."""
    deadline = time.monotonic() + timeout
    url = None
    connected = False
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise StartupError("Туннель завершился до подключения. Проверьте интернет, VPN и cloudflared; можно использовать --url с уже работающим HTTPS-туннелем.")
        try:
            line = process.lines.get(timeout=min(0.2, max(0.001, deadline - time.monotonic())))
        except queue.Empty:
            continue
        url = extract_quick_url(line) or url
        connected = connected or "Registered tunnel connection" in ANSI_ESCAPE.sub("", line)
        if url and connected:
            return url
    raise StartupError("Туннель не подключился за 90 секунд. Проверьте интернет/VPN или запустите свой туннель и используйте --url.")


def wait_backend(backend: CapturedProcess, port: int, tunnel: CapturedProcess | None, timeout: float = 45) -> None:
    deadline = time.monotonic() + timeout
    # Local health checks must bypass HTTP_PROXY; no external requests here.
    opener = build_opener(ProxyHandler({}))
    while time.monotonic() < deadline:
        if backend.poll() is not None:
            raise StartupError(backend_failure_message(backend))
        if tunnel is not None and tunnel.poll() is not None:
            raise StartupError("Туннель отключился при запуске. Оба процесса будут остановлены; повторите запуск.")
        try:
            with opener.open(f"http://127.0.0.1:{port}/api/health", timeout=0.8) as response:
                data = json.loads(response.read(4096))
                if response.status == 200 and isinstance(data, dict) and data.get("ok") is True and data.get("service") == "taoji-cargo":
                    return
        except (URLError, OSError, ValueError):
            pass
        time.sleep(0.2)
    raise StartupError(backend_failure_message(backend, timed_out=True))


def wait_public_backend(url: str, backend: CapturedProcess, tunnel: CapturedProcess | None,
                        timeout: float = 30) -> None:
    """Require the exact public health response before advertising readiness."""
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        if backend.poll() is not None:
            raise StartupError(backend_failure_message(backend))
        if tunnel is not None and tunnel.poll() is not None:
            raise StartupError("Туннель остановился при проверке публичного адреса. Повторите запуск.")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        last = probe_health(url, timeout=min(3, remaining))
        if last.ok:
            if backend.poll() is None and (tunnel is None or tunnel.poll() is None):
                return
            continue
        remaining = deadline - time.monotonic()
        if remaining > 0:
            time.sleep(min(1, remaining))
    detail = f" [{last.code}] {last.message}" if last is not None else ""
    diagnostic = tunnel.tunnel_diagnostic() if tunnel is not None else None
    hint = TUNNEL_HINTS.get(diagnostic, "")
    suffix = f" [{diagnostic}] {hint}" if hint else ""
    raise StartupError("Публичный адрес Mini App не прошёл проверку." + detail + suffix
                       + " Локальный API запустился, но доступ через этот адрес не подтверждён."
                       + " Запуск остановлен. Попробуйте другой транспорт: start.bat --tunnel-protocol auto."
                       + " Инструкция: TUNNEL-1033-WINDOWS.md.")


def child_environment(config: LaunchConfig, url: str) -> dict[str, str]:
    from app.config import Settings
    environment = dict(os.environ)
    # Remove case variants on Unix too; Windows environment keys are case-insensitive.
    names = {name.upper() for name in Settings.model_fields}
    environment = {key: value for key, value in environment.items() if key.upper() not in names}
    for name, value in config.settings.model_dump().items():
        environment[name.upper()] = str(value).lower() if isinstance(value, bool) else str(value)
    environment.update(PYTHONUTF8="1", PYTHONUNBUFFERED="1", WEBAPP_URL=url,
                       HOST="127.0.0.1", ENV="development", BOT_MODE="polling",
                       BOT_ENABLED="false" if config.local else "true", DEV_MODE="true" if config.local else "false")
    if config.local and config.local_role is not None:
        owners = config.settings.owner_id_set - {config.settings.dev_user_tg_id}
        managers = config.settings.manager_id_set - {config.settings.dev_user_tg_id}
        if config.local_role == "owner":
            owners.add(config.settings.dev_user_tg_id)
        elif config.local_role == "manager":
            managers.add(config.settings.dev_user_tg_id)
        environment["OWNER_IDS"] = ",".join(str(item) for item in sorted(owners))
        environment["MANAGER_IDS"] = ",".join(str(item) for item in sorted(managers))
    return environment


def cloudflared_environment(*, telegram_proxy: bool = False) -> dict[str, str]:
    # An existing shell tunnel token/name must not turn an anonymous quick tunnel
    # into a different user's configured tunnel. With a Telegram-only proxy,
    # keep the tunnel off shell proxies. OS TUN routing still needs VPN setup.
    excluded = {"NO_AUTOUPDATE", "BOT_TOKEN", "BOT_PROXY_URL", "JWT_SECRET", "ONEBOUND_API_KEY", "ONEBOUND_API_SECRET"}
    if telegram_proxy:
        excluded.update({"HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"})
    return {key: value for key, value in os.environ.items()
            if not key.upper().startswith("TUNNEL_") and key.upper() not in excluded}


def run(config: LaunchConfig) -> None:
    from backup import create_backup
    from runtime_env import env_fingerprint, update_env
    backend = None
    tunnel = None
    env_path = config.root / ".env"
    with launch_lock(config.root), tempfile.TemporaryDirectory(prefix="taoji-tunnel-") as private_dir:
        try:
            # Recheck after taking the lock, before backup or public network access.
            if env_fingerprint(env_path) != config.fingerprint:
                raise StartupError(".env изменился после проверки. Повторите запуск.")
            check_port(config.settings.port)
            try:
                create_backup(config.database, config.root / "backups", keep=14)
            except Exception:
                raise StartupError("Не удалось сохранить резервную копию базы. Проверьте свободное место и права на папку backups.") from None
            print("Резервная копия базы сохранена.", flush=True)
            url = config.local_url if config.local else config.supplied_url
            if not config.local and url is None:
                isolated_config = Path(private_dir) / "config.yml"
                isolated_config.write_text("{}\n", encoding="utf-8")
                print("Подключаю временный HTTPS-туннель…", flush=True)
                tunnel = CapturedProcess([str(config.cloudflared), "tunnel", "--config", str(isolated_config),
                                          "--no-autoupdate", "--url", config.local_url, "--protocol", config.tunnel_protocol],
                                         cwd=config.root, env=cloudflared_environment(
                                             telegram_proxy=bool(config.settings.bot_proxy_url)))
                url = wait_tunnel(tunnel)
            if not config.local:
                # Atomically change ONLY WEBAPP_URL after a connected tunnel has
                # issued a validated hostname; never persist a localhost dev mode.
                update_env(env_path, {"WEBAPP_URL": str(url)}, expected_fingerprint=config.fingerprint)
            elif env_fingerprint(env_path) != config.fingerprint:
                raise StartupError(".env изменился после проверки. Повторите запуск.")
            print("Запускаю API" + (" и Telegram-бота…" if not config.local else " для локальной проверки…"), flush=True)
            backend = CapturedProcess([sys.executable, "-m", "app.main"], cwd=config.root / "backend",
                                      env=child_environment(config, str(url)))
            wait_backend(backend, config.settings.port, tunnel)
            if not config.local:
                print("Проверяю публичный адрес Mini App…", flush=True)
                wait_public_backend(str(url), backend, tunnel)
            print(f"Готово: {url}", flush=True)
            if config.local:
                role = config.local_role or config.settings.role_for(config.settings.dev_user_tg_id)
                label = {"client": "клиент", "manager": "менеджер", "owner": "владелец"}[role]
                print(f"Роль локального тестового пользователя: {label}. Настройки Telegram в .env сохранены.", flush=True)
            else:
                print("Кнопка меню бота обновлена. Откройте личный чат с ботом, отправьте /start и нажмите «Открыть приложение».", flush=True)
                if tunnel is not None:
                    print("При следующем запуске адрес изменится. После перезапуска закройте старую Mini App и откройте её через бота.", flush=True)
            print("Оставьте окно открытым. Ctrl+C останавливает этот backend и его туннель.", flush=True)
            last_tunnel_diagnostic = tunnel.tunnel_diagnostic() if tunnel is not None else None
            while True:
                if backend.poll() is not None:
                    raise StartupError("Backend остановился. Его туннель будет закрыт. Проверьте интернет и повторите запуск.")
                if tunnel is not None and tunnel.poll() is not None:
                    raise StartupError("Туннель остановился. Backend и бот будут выключены, чтобы не оставлять устаревший адрес. Повторите запуск.")
                if tunnel is not None:
                    diagnostic = tunnel.tunnel_diagnostic()
                    if diagnostic != last_tunnel_diagnostic:
                        if diagnostic in TUNNEL_HINTS:
                            print(f"Cloudflare [{diagnostic}]: " + TUNNEL_HINTS[diagnostic], flush=True)
                        elif diagnostic == "REGISTERED" and last_tunnel_diagnostic is not None:
                            print("Cloudflare: соединение повторно зарегистрировано. Проверка адреса: python scripts\\check_tunnel.py.", flush=True)
                        last_tunnel_diagnostic = diagnostic
                time.sleep(0.3)
        finally:
            try:
                if backend is not None:
                    backend.close()
            finally:
                if tunnel is not None:
                    tunnel.close()


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Taoji Cargo: API + Telegram-бот + временный HTTPS-туннель. Ctrl+C останавливает запущенные процессы.")
    modes = result.add_mutually_exclusive_group()
    modes.add_argument("--local", action="store_true", help="Локальный браузер без Telegram/туннеля. Роли из .env сохраняются.")
    modes.add_argument("--url", help="Корневой HTTPS-адрес уже запущенного вручную туннеля (например, ngrok); cloudflared не запускать.")
    result.add_argument("--local-role", choices=("client", "manager", "owner"), help="Только с --local: выбрать роль DEV_USER_TG_ID в этом процессе без изменения .env.")
    result.add_argument("--tunnel-protocol", choices=("http2", "quic", "auto"), default="http2",
                        help="Транспорт cloudflared: http2 (TCP), quic (UDP) или auto. По умолчанию http2.")
    result.add_argument("--check", action="store_true", help="Только проверить настройки, базу, сборку, порт и cloudflared. Без сети, процессов, резервных копий и изменения .env.")
    return result


def main(argv: list[str] | None = None) -> int:
    argument_parser = parser()
    arguments = argument_parser.parse_args(argv)
    if arguments.local_role is not None and not arguments.local:
        argument_parser.error("--local-role можно использовать только вместе с --local")
    try:
        config = read_launch_config(local=arguments.local, supplied_url=arguments.url, local_role=arguments.local_role,
                                   tunnel_protocol=arguments.tunnel_protocol)
        if arguments.check:
            print("Проверка пройдена: настройки, SQLite, сборка и локальный порт готовы. Секреты скрыты.")
            print("Связь с Telegram и Cloudflare не проверялась. Запустите без --check для подключения.")
            return 0
        run(config)
    except KeyboardInterrupt:
        print("\nЗапуск остановлен; его процессы закрыты.")
        return 0
    except StartupError as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 1
    except Exception:
        # Exception representations can contain config values or HTTP URLs with
        # bot tokens. Keep unexpected failures generic and preserve user files.
        print("Ошибка запуска. Проверьте .env через scripts\\setup_telegram.py и инструкцию STAGE-4-WINDOWS.md; значения скрыты.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
