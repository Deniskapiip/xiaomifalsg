"""Ежедневный бэкап SQLite без внешних сервисов.

Копия базы складывается в <папка_данных>/backups/taoji-YYYYMMDD-HHMMSS.db
через sqlite3 backup API (безопасно для WAL), хранится последние BACKUP_KEEP файлов.
"""

import asyncio
import logging
import sqlite3
from pathlib import Path

from app.db_types import utcnow

log = logging.getLogger("taoji")
PREFIXES = ("sqlite+aiosqlite:///", "sqlite:///")
DAY_SECONDS = 24 * 60 * 60


def sqlite_path(database_url: str) -> Path | None:
    for prefix in PREFIXES:
        if database_url.startswith(prefix):
            raw = database_url[len(prefix):]
            if raw in {"", ":memory:"} or raw.startswith(":memory:"):
                return None
            return Path(raw).expanduser()
    return None


def copy_sqlite(source: Path, target: Path) -> None:
    src = sqlite3.connect(str(source))
    dst = sqlite3.connect(str(target))
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()


def cleanup_backups(directory: Path, keep: int) -> None:
    files = sorted(directory.glob("taoji-*.db"), key=lambda path: path.stat().st_mtime, reverse=True)
    for old in files[max(1, keep):]:
        old.unlink(missing_ok=True)


class BackupWorker:
    def __init__(self, settings):
        self.settings = settings

    async def backup_once(self) -> Path | None:
        if not self.settings.backup_enabled:
            return None
        source = sqlite_path(self.settings.database_url)
        if source is None or not source.exists():
            return None
        directory = source.parent / "backups"
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / f"taoji-{utcnow().strftime('%Y%m%d-%H%M%S')}.db"
        await asyncio.to_thread(copy_sqlite, source, target)
        await asyncio.to_thread(cleanup_backups, directory, self.settings.backup_keep)
        log.info("backup_created name=%s", target.name)
        return target

    async def run(self) -> None:
        while True:
            try:
                await self.backup_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - фоновый бэкап не должен ронять приложение
                log.error("backup_error type=%s", type(exc).__name__)
            await asyncio.sleep(DAY_SECONDS)
