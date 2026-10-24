import sqlite3
from pathlib import Path

from app.services.maintenance import BackupWorker, cleanup_backups, sqlite_path


def make_database(path: Path) -> None:
    connection = sqlite3.connect(str(path))
    try:
        connection.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, value TEXT)")
        connection.execute("INSERT INTO t (value) VALUES ('taoji')")
        connection.commit()
    finally:
        connection.close()


def test_sqlite_path_parsing():
    assert sqlite_path("sqlite+aiosqlite:///D:/data/taoji.db") == Path("D:/data/taoji.db")
    assert sqlite_path("sqlite:///./data/taoji.db") == Path("./data/taoji.db")
    assert sqlite_path("postgresql+asyncpg://user:pass@db/app") is None
    assert sqlite_path("sqlite+aiosqlite:///:memory:") is None


async def test_backup_creates_copy_and_rotates(tmp_path, settings):
    database = tmp_path / "taoji.db"
    make_database(database)
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    for index in range(5):
        stale = backup_dir / f"taoji-2020010{index}-000000.db"
        stale.write_bytes(b"old")
    updated = settings.model_copy(update={"database_url": f"sqlite+aiosqlite:///{database.as_posix()}", "backup_keep": 3})
    worker = BackupWorker(updated)
    created = await worker.backup_once()
    assert created is not None and created.exists()
    connection = sqlite3.connect(str(created))
    try:
        assert connection.execute("SELECT value FROM t").fetchone()[0] == "taoji"
    finally:
        connection.close()
    remaining = sorted(backup_dir.glob("taoji-*.db"))
    assert len(remaining) == 3


def test_cleanup_keeps_newest(tmp_path):
    for index in range(6):
        (tmp_path / f"taoji-{index}.db").write_bytes(b"x")
    cleanup_backups(tmp_path, 2)
    assert len(list(tmp_path.glob("taoji-*.db"))) == 2


async def test_backup_disabled(tmp_path, settings):
    updated = settings.model_copy(update={"database_url": "sqlite+aiosqlite:///" + (tmp_path / "taoji.db").as_posix(),
                                          "backup_enabled": False})
    worker = BackupWorker(updated)
    assert await worker.backup_once() is None
