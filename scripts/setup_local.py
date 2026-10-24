"""Create .env without exposing secrets; --dev-owner explicitly enables LOCAL testing."""
import argparse
from pathlib import Path
import secrets
import shutil

from dotenv import dotenv_values, set_key

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description="Подготовка локального .env Taoji Cargo")
    parser.add_argument("--dev-owner", action="store_true", help="Локальный тестовый owner без связи с Telegram; запрещено в production")
    args = parser.parse_args()
    path = ROOT / ".env"
    if not path.exists():
        shutil.copyfile(ROOT / ".env.example", path)
    values = dotenv_values(path)
    if args.dev_owner and values.get("ENV") == "production":
        raise SystemExit("Тестовый вход нельзя включать в production")
    if not values.get("JWT_SECRET"):
        set_key(str(path), "JWT_SECRET", secrets.token_urlsafe(48), quote_mode="never")
    if args.dev_owner:
        test_id = values.get("DEV_USER_TG_ID") or "900000001"
        ids = [part.strip() for part in (values.get("OWNER_IDS") or "").split(",") if part.strip()]
        if test_id not in ids:
            ids.append(test_id)
        for key, value in {"ENV": "development", "DEV_MODE": "true", "BOT_ENABLED": "false", "WEBAPP_URL": "http://127.0.0.1:8000", "OWNER_IDS": ",".join(ids)}.items():
            set_key(str(path), key, value, quote_mode="never")
        print("Включён локальный тестовый owner. Бот отключён. Перед туннелем выключите DEV_MODE и удалите тестовый ID из OWNER_IDS.")
    print(".env подготовлен. Значения секретов не выводятся.")


if __name__ == "__main__":
    main()
