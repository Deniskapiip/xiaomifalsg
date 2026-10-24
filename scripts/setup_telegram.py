"""Interactive local Telegram configuration. Secrets never enter command arguments."""
import argparse
import getpass
from pathlib import Path
import re
import secrets
import sys
import warnings

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.runtime_env import ensure_env, env_fingerprint, read_env, update_env


def hidden_prompt(prompt: str) -> str:
    # Fail before getpass's echoing fallback in redirected terminals or IDE consoles.
    with warnings.catch_warnings():
        warnings.simplefilter("error", getpass.GetPassWarning)
        return getpass.getpass(prompt)


def valid_token(value: str) -> bool:
    return bool(re.fullmatch(r"[0-9]{5,20}:[A-Za-z0-9_-]{20,100}", value))


def parse_ids(value: str, *, required: bool = False) -> str:
    if not value.strip():
        if required:
            raise ValueError("Укажите хотя бы один числовой ID владельца")
        return ""
    items = value.split(",")
    if any(not re.fullmatch(r"[0-9]+", item.strip()) or not 0 < int(item.strip()) <= 9223372036854775807 for item in items):
        raise ValueError("Нужны положительные числовые Telegram ID через запятую, без @username")
    return ",".join(str(value) for value in sorted({int(item.strip()) for item in items}))


def prepare_updates(values: dict[str, str], token: str, owner_ids: str, manager_ids: str) -> dict[str, str]:
    if values.get("ENV", "development").strip().lower() == "production":
        raise ValueError("Этот мастер предназначен для локального теста; production .env не изменён")
    if not valid_token(token):
        raise ValueError("Токен имеет неверный формат. Скопируйте его у @BotFather")
    owners = parse_ids(owner_ids, required=True)
    managers = parse_ids(manager_ids)
    real_ids = set((owners + "," + managers).split(","))
    # Keep the local preview identity distinct from every real administrator.
    preview_id = values.get("DEV_USER_TG_ID", "900000001").strip()
    if not re.fullmatch(r"[0-9]+", preview_id) or not 0 < int(preview_id) <= 9223372036854775807:
        preview_id = "900000001"
    preview_id = str(int(preview_id))
    if preview_id in real_ids:
        candidate = 900000001
        while str(candidate) in real_ids:
            candidate += 1
        preview_id = str(candidate)
    jwt_secret = values.get("JWT_SECRET", "")
    if len(jwt_secret.encode()) < 32 or jwt_secret.lower().startswith("change"):
        jwt_secret = secrets.token_urlsafe(48)
    return {"ENV": "development", "DEV_MODE": "false", "DEV_USER_TG_ID": preview_id,
            "BOT_ENABLED": "true", "BOT_MODE": "polling", "BOT_TOKEN": token,
            "OWNER_IDS": owners, "MANAGER_IDS": managers, "JWT_SECRET": jwt_secret,
            "HOST": "127.0.0.1", "WEBAPP_URL": "https://setup-pending.invalid"}


def main() -> int:
    argparse.ArgumentParser(description="Подготовить .env для Telegram на вашем ПК без вывода секретов").parse_args()
    path = ROOT / ".env"
    try:
        ensure_env(path, ROOT / ".env.example")
        stamp = env_fingerprint(path)
        values = read_env(path)
        if values.get("ENV", "").strip().lower() == "production":
            print("Этот мастер не изменяет production .env. Для локального теста используйте отдельную папку проекта.")
            return 1
        print("Настройка Telegram. Токен скрыт при вводе и сохраняется только в .env.")
        print("Получите реальный токен у @BotFather, числовые ID — у @userinfobot.")
        token = hidden_prompt("Токен бота (Enter — оставить текущий): ").strip() or values.get("BOT_TOKEN", "")
        while not valid_token(token):
            print("Токен имеет неверный формат. Его значение не выводится.")
            token = hidden_prompt("Скопируйте токен бота ещё раз: ").strip()
        owners = input("Реальные ID владельцев через запятую: ").strip()
        while True:
            try:
                owners = parse_ids(owners, required=True)
                break
            except ValueError as error:
                print(error)
                owners = input("ID владельцев: ").strip()
        managers = input("Реальные ID менеджеров через запятую (Enter — пока без менеджеров): ").strip()
        while True:
            try:
                managers = parse_ids(managers)
                break
            except ValueError as error:
                print(error)
                managers = input("ID менеджеров: ").strip()
        updates = prepare_updates(values, token, owners, managers)
        print("Владельцы:", owners)
        print("Менеджеры:", managers or "пока не заданы")
        print("Эти списки заменят прежние ID администраторов. Введите все реальные ID, которые хотите сохранить.")
        print("Локальный тестовый вход будет отключён; база и настройки расчёта сохраняются.")
        print("Адрес HTTPS установит start.bat при запуске туннеля.")
        if input("Сохранить настройки? [да/нет]: ").strip().lower() not in {"да", "д", "yes", "y"}:
            print("Настройки не изменены.")
            return 0
        update_env(path, updates, expected_fingerprint=stamp)
        print("Готово. Запустите start.bat. Каждый владелец и менеджер должен нажать /start у бота.")
        return 0
    except (EOFError, KeyboardInterrupt):
        print("\nНастройка отменена. Введённые значения не сохранены.")
        return 1
    except Exception:
        print("Не удалось сохранить настройки. Проверьте доступ к .env и повторите настройку; секреты не выводятся.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
