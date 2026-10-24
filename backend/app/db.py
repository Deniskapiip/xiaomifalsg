from pathlib import Path

from sqlalchemy import event
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import ROOT


def normalize_database_url(value: str) -> str:
    url = make_url(value)
    if url.get_backend_name() == "sqlite" and url.database and url.database != ":memory:":
        path = Path(url.database)
        if not path.is_absolute():
            path = ROOT / path
        path.parent.mkdir(parents=True, exist_ok=True)
        url = url.set(database=str(path.resolve()))
    return url.render_as_string(hide_password=False)


def create_database(value: str):
    url = normalize_database_url(value)
    sqlite = url.startswith("sqlite")
    engine = create_async_engine(url, connect_args={"timeout": 15} if sqlite else {}, pool_pre_ping=True)
    if sqlite:
        @event.listens_for(engine.sync_engine, "connect")
        def sqlite_pragmas(connection, _record):
            cursor = connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=15000")
            cursor.close()
    return engine, async_sessionmaker(engine, expire_on_commit=False)
