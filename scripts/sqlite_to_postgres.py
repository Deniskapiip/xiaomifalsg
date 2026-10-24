"""Copy a checked SQLite snapshot into an empty migrated PostgreSQL database."""
import argparse
import asyncio
import os
from pathlib import Path
import sys

from sqlalchemy import func, select, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import create_async_engine

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT))
from app.models import Base
from scripts.runtime_env import read_env

PAUSED_STATE = "paused_migration"


async def migrate(source: Path, target_url: str, *, include_pending: bool = False) -> dict[str, int]:
    source = Path(source).resolve(strict=True)
    if not source.is_file():
        raise ValueError("SQLite source must be a file")
    target = make_url(target_url)
    if target.drivername != "postgresql+asyncpg":
        raise ValueError("Target must be PostgreSQL asyncpg")
    from alembic.script import ScriptDirectory
    expected = set(ScriptDirectory(str(ROOT / "backend/alembic")).get_heads())
    reader = create_async_engine(URL.create("sqlite+aiosqlite", database=source.as_uri(), query={"mode":"ro", "uri":"true"}))
    writer = create_async_engine(target, connect_args={"timeout":10, "command_timeout":60,
                                                    "server_settings":{"lock_timeout":"10s"}})
    counts = {}
    try:
        async with reader.connect() as source_db:
            # An explicit BEGIN gives all pages one consistent SQLite snapshot.
            await source_db.exec_driver_sql("BEGIN")
            if (await source_db.exec_driver_sql("PRAGMA quick_check")).fetchall() != [("ok",)]:
                raise ValueError("Invalid SQLite snapshot")
            if (await source_db.exec_driver_sql("PRAGMA foreign_key_check")).fetchall():
                raise ValueError("SQLite foreign keys are inconsistent")
            revisions = set((await source_db.execute(text("SELECT version_num FROM alembic_version"))).scalars())
            if revisions != expected:
                raise ValueError("Source migration revision is not current")
            async with writer.begin() as target_db:
                target_revisions = set((await target_db.execute(text("SELECT version_num FROM alembic_version"))).scalars())
                if target_revisions != revisions:
                    raise ValueError("Run target Alembic migrations first")
                tables = list(Base.metadata.sorted_tables)
                names = ", ".join('"'+table.name+'"' for table in tables)
                await target_db.execute(text(f"LOCK TABLE {names} IN ACCESS EXCLUSIVE MODE"))
                for table in tables:
                    if await target_db.scalar(select(func.count()).select_from(table)):
                        raise ValueError("Target is not empty; no rows were copied")
                for table in tables:
                    rows = await source_db.stream(select(table).order_by(table.c.id))
                    count = 0
                    async for batch in rows.mappings().partitions(200):
                        values = [dict(row) for row in batch]
                        if table.name == "notification_jobs" and not include_pending:
                            for row in values:
                                if row["state"] in {"pending", "sending", "waiting_access"}:
                                    row["state"] = PAUSED_STATE
                        await target_db.execute(table.insert(), values)
                        count += len(values)
                    counts[table.name] = count
                    if await target_db.scalar(select(func.count()).select_from(table)) != count:
                        raise ValueError("Target count mismatch")
                # Explicit IDs must be followed by correctly advanced PostgreSQL sequences.
                for table in tables:
                    sequence = await target_db.scalar(text("SELECT pg_get_serial_sequence(:table_name, 'id')"), {"table_name":table.name})
                    if sequence:
                        maximum = await target_db.scalar(select(func.max(table.c.id)))
                        await target_db.execute(text("SELECT setval(CAST(:sequence AS regclass), :value, :called)"),
                            {"sequence":sequence, "value":max(maximum or 0, 1), "called":bool(maximum)})
        return counts
    finally:
        await reader.dispose()
        await writer.dispose()


def main(argv=None):
    parser = argparse.ArgumentParser(description="Перенести SQLite online backup в пустую PostgreSQL после миграций")
    parser.add_argument("--source", type=Path, required=True, help="Проверенная копия SQLite; исходная база не изменяется")
    parser.add_argument("--env-file", type=Path, help="По умолчанию .env.production; внутри Docker — DATABASE_URL окружения")
    parser.add_argument("--include-pending-notifications", action="store_true", help="Явно разрешить отправку старой очереди после запуска бота")
    args = parser.parse_args(argv)
    try:
        path = args.env_file or ROOT/".env.production"
        url = read_env(path).get("DATABASE_URL", "") if args.env_file or path.exists() else os.environ.get("DATABASE_URL", "")
        counts = asyncio.run(migrate(args.source, url, include_pending=args.include_pending_notifications))
    except Exception:
        print("Перенос не выполнен. Проверьте SQLite-копию, доступ, миграции и пустую PostgreSQL. Секреты и данные клиентов скрыты.", file=sys.stderr)
        return 1
    print("Перенос завершён; ID, даты, снимки расчётов и история сохранены.")
    for name, count in counts.items():
        print(f"{name}: {count}")
    if not args.include_pending_notifications:
        print("Неотправленная очередь приостановлена. Возобновляйте её только после проверки через resume_import_notifications.py.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
