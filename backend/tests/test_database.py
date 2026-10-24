import os
from pathlib import Path
import subprocess
import sys

from sqlalchemy import select, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from app.models import AppSettings, Base, Tariff
from app.seed import seed_database


async def test_seed_idempotent_and_sqlite_pragmas(app):
    await seed_database(app.state.sessions)
    async with app.state.sessions() as db:
        tariffs = (await db.scalars(select(Tariff))).all()
        assert len(tariffs) == 4
        assert (await db.get(AppSettings, 1)).commission_min_rub == 650
        assert await db.scalar(text("PRAGMA foreign_keys")) == 1
        assert await db.scalar(text("PRAGMA journal_mode")) == "wal"


def test_migration_upgrade_check_downgrade(tmp_path):
    env = {**os.environ, "BOT_ENABLED": "false", "DEV_MODE": "false", "ENV": "development", "WEBAPP_URL": "http://127.0.0.1:8000",
           "JWT_SECRET": "migration-unit-test-secret-at-least-32-bytes", "DATABASE_URL": f"sqlite+aiosqlite:///{tmp_path / 'migration.db'}"}
    cwd = Path(__file__).resolve().parents[1]
    for command in (("alembic", "upgrade", "head"), ("app.seed",), ("alembic", "check"), ("alembic", "downgrade", "base"), ("alembic", "upgrade", "head")):
        result = subprocess.run([sys.executable, "-m", *command], cwd=cwd, env=env, text=True, capture_output=True)
        assert result.returncode == 0, result.stdout + result.stderr


def test_postgres_schema_compiles_without_sqlite_storage():
    dialect = postgresql.dialect()
    all_sql = "\n".join(str(CreateTable(table).compile(dialect=dialect)) for table in Base.metadata.sorted_tables)
    assert "NUMERIC(12, 4)" in all_sql
    assert "NUMERIC(8, 3)" in all_sql
    assert "TIMESTAMP WITH TIME ZONE" in all_sql
    assert "goods_rub BIGINT" in all_sql
