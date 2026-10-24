"""Read-only diagnosis of local API and the current public Mini App URL."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.runtime_env import read_env
from scripts.tunnel_health import HealthResult, probe_health, probe_local_health, validate_public_root


def _print_result(label: str, result: HealthResult) -> None:
    status = f" HTTP {result.status}." if result.status is not None else ""
    print(f"{label}: {result.code}.{status} {result.message}")


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(description="Проверить локальный API и публичный туннель без изменения .env или бота").parse_args(argv)
    try:
        values = {key.upper(): value for key, value in read_env(ROOT / ".env").items()}
        try:
            port_value = values.get("PORT", "8000")
            if not port_value.isdecimal():
                raise ValueError
            port = int(port_value)
            if not 1 <= port <= 65535:
                raise ValueError
        except (ValueError, TypeError):
            print("PORT имеет неверный формат. Нужен номер порта от 1 до 65535.")
            return 1
        try:
            url = validate_public_root(values.get("WEBAPP_URL", ""))
        except ValueError:
            print("WEBAPP_URL имеет неверный формат. Нужен корневой HTTPS-адрес текущего туннеля.")
            return 1
        print("Оставьте start.bat работающим. Проверка ничего не меняет и не выводит секреты.")
        local = probe_local_health(port)
        _print_result("Локальный API", local)
        print(f"Текущий адрес: {url}")
        public = probe_health(url)
        _print_result("Публичный туннель", public)
        if local.ok and public.code == "CLOUDFLARE_1033":
            print("Backend работает локально, но Cloudflare не видит туннель. Проверьте cloudflared и его маршрут в Happ; новая ссылка сама по себе это не исправляет.")
        print("Проверка завершена. .env, настройки бота и процессы не изменялись.")
        return 0 if local.ok and public.ok else 1
    except KeyboardInterrupt:
        print("Проверка отменена.")
        return 1
    except Exception:
        print("Не удалось прочитать .env или выполнить проверку. Значения настроек и секретов скрыты.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
