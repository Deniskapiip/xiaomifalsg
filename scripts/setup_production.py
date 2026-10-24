"""Create a separate server configuration locally, without exposing secrets."""
import argparse
import os
from pathlib import Path
import re
import secrets
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.runtime_env import read_env
from scripts.setup_telegram import hidden_prompt, parse_ids, valid_token


def prepare(values, domain, email, token, owners, managers):
    domain = domain.strip().lower()
    if not re.fullmatch(r"(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}", domain):
        raise ValueError("Нужен домен без https://, пути и порта")
    if not re.fullmatch(r"[^\s@{}]+@[^\s@{}]+\.[^\s@{}]+", email):
        raise ValueError("Укажите email для уведомлений о сертификате")
    if not valid_token(token):
        raise ValueError("Неверный формат токена BotFather")
    owners, managers = parse_ids(owners, required=True), parse_ids(managers)
    if values.get("ENV") == "production" and values.get("POSTGRES_PASSWORD"):
        raise ValueError("Production уже настроен. Не меняйте пароль существующей БД этим мастером")
    password = secrets.token_hex(32)
    return {"DOMAIN":domain, "ACME_EMAIL":email, "ENV":"production", "DEV_MODE":"false",
            "BOT_ENABLED":"true", "BOT_MODE":"webhook", "BOT_TOKEN":token,
            "WEBAPP_URL":"https://"+domain, "OWNER_IDS":owners, "MANAGER_IDS":managers,
            "JWT_SECRET":secrets.token_urlsafe(48), "WEBHOOK_PATH_SECRET":secrets.token_urlsafe(36),
            "WEBHOOK_SECRET_TOKEN":secrets.token_urlsafe(36), "POSTGRES_PASSWORD":password,
            "DATABASE_URL":f"postgresql+asyncpg://taoji:{password}@postgres:5432/taoji",
            "HOST":"0.0.0.0", "PORT":"8000", "FORWARDED_ALLOW_IPS":"127.0.0.1,::1,172.30.0.2"}


def main(argv=None):
    argparse.ArgumentParser(description="Подготовить отдельный .env.production для VPS").parse_args(argv)
    path = ROOT / ".env.production"
    try:
        if path.exists():
            print(".env.production уже существует. Сохраняем его; мастер не заменяет серверные секреты.")
            return 1
        domain = input("Домен Mini App, например cargo.example.com: ").strip()
        email = input("Email для сертификата: ").strip()
        token = hidden_prompt("Токен BotFather (скрытый ввод): ").strip()
        owners = input("Реальные числовые ID владельцев через запятую: ")
        managers = input("Числовые ID менеджеров (можно оставить пустым): ")
        updates = prepare({}, domain, email, token, owners, managers)
        if input("Создать .env.production? [да/нет]: ").strip().lower() not in {"да","д","y","yes"}:
            print("Создание отменено.")
            return 0
        values=read_env(ROOT / ".env.production.example")
        values.update(updates)
        # Exclusive creation prevents a second setup from replacing these secrets.
        descriptor=os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
                for key,value in values.items():
                    escaped=value.replace('\\', '\\\\').replace("'", "\\'")
                    stream.write(f"{key}='{escaped}'\n")
                stream.flush()
                os.fsync(stream.fileno())
        except Exception:
            path.unlink(missing_ok=True)
            raise
        print(".env.production создан; локальный .env не изменён. Секреты скрыты.")
        return 0
    except (KeyboardInterrupt, EOFError):
        print("Настройка отменена.")
        return 1
    except Exception:
        print("Не удалось подготовить серверные настройки. Проверьте домен, email, токен, ID и права; значения скрыты.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
