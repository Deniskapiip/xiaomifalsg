"""Explicitly resume notification jobs paused during a database import."""
import argparse
import asyncio
import os
from pathlib import Path
import sys
from sqlalchemy import update
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT/"backend"))
from app.models import NotificationJob
from app.db_types import utcnow
from scripts.runtime_env import read_env


async def resume(url):
    if make_url(url).drivername != "postgresql+asyncpg":
        raise ValueError("PostgreSQL required")
    engine = create_async_engine(url,connect_args={"timeout":10,"command_timeout":30})
    try:
        async with engine.begin() as db:
            result = await db.execute(update(NotificationJob).where(NotificationJob.state == "paused_migration")
                .values(state="pending", next_attempt_at=utcnow()))
            return result.rowcount
    finally:
        await engine.dispose()


def main(argv=None):
    parser=argparse.ArgumentParser(description="Возобновить старую очередь: бот сможет отправлять исторические сообщения")
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--confirm-send-old-notifications", action="store_true", required=True)
    args=parser.parse_args(argv)
    try:
        path=args.env_file or ROOT/".env.production"
        url=read_env(path).get("DATABASE_URL", "") if args.env_file or path.exists() else os.environ.get("DATABASE_URL", "")
        count=asyncio.run(resume(url))
    except Exception:
        print("Не удалось возобновить очередь. Проверьте доступ к PostgreSQL; значения скрыты.")
        return 1
    print(f"Возобновлено заданий: {count}. Бот проверит разрешение пользователя перед отправкой.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
