"""Consistent local SQLite backups, including databases with an active WAL."""
from __future__ import annotations

import argparse
from contextlib import closing
from datetime import datetime, timezone
import os
from pathlib import Path
import re
import secrets
import sqlite3
import sys
import tempfile
import time


ROOT = Path(__file__).resolve().parents[1]
_BACKUP_TIMEOUT_SECONDS = 30.0
_SQLITE_TIMEOUT_SECONDS = 1.0
_OWNED_NAME = re.compile(r"taoji-[0-9]{8}-[0-9]{6}-[0-9]{6}-[0-9a-f]{8}\.db\Z")


class _ConfigurationError(ValueError):
    """A controlled user-facing message that contains no environment values."""


def _check_integrity(connection: sqlite3.Connection, deadline: float) -> None:
    """Bound verification time as well as time spent waiting on SQLite locks."""
    connection.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1000)
    try:
        if time.monotonic() >= deadline:
            raise TimeoutError("SQLite backup exceeded its time limit")
        result = connection.execute("PRAGMA quick_check").fetchall()
        if result != [("ok",)]:
            raise sqlite3.DatabaseError("SQLite backup integrity check failed")
    except sqlite3.OperationalError as error:
        if time.monotonic() >= deadline:
            raise TimeoutError("SQLite backup exceeded its time limit") from error
        raise
    finally:
        connection.set_progress_handler(None, 0)


def _rotate(backups: Path, source: Path, latest: Path, keep: int) -> None:
    candidates: list[tuple[int, str, Path]] = []
    for path in backups.iterdir():
        if not _OWNED_NAME.fullmatch(path.name) or path.is_symlink() or path == latest:
            continue
        try:
            if not path.is_file() or path.resolve() == source:
                continue
            candidates.append((path.stat().st_mtime_ns, path.name, path))
        except FileNotFoundError:
            # Another backup invocation may already have rotated this file.
            continue
    candidates.sort(reverse=True)
    # Always retain the new verified backup, even if an older file has a future mtime.
    for _, _, path in candidates[keep - 1 :]:
        try:
            path.unlink()
        except FileNotFoundError:
            pass


def create_backup(database_path: Path, backup_dir: Path, keep: int = 14) -> Path:
    """Publish a checked standalone .db atomically, then rotate only owned backups.

    The source is opened with SQLite's read-only URI mode. The online backup API
    reads committed pages from the database and its WAL; copying the main file
    alone would miss recent committed changes. No source database is created.
    """
    if isinstance(keep, bool) or not isinstance(keep, int) or not 1 <= keep <= 100:
        raise ValueError("keep must be an integer between 1 and 100")
    source = Path(database_path).expanduser().resolve(strict=True)
    if not source.is_file():
        raise ValueError("The SQLite database must be an existing regular file")
    with source.open("rb") as stream:
        if stream.read(16) != b"SQLite format 3\x00":
            raise sqlite3.DatabaseError("The source is not a SQLite database")
    backups = Path(backup_dir).expanduser().resolve()
    if backups == source or (backups.exists() and not backups.is_dir()):
        raise ValueError("The backup destination must be a directory")
    backups.mkdir(parents=True, exist_ok=True)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    latest = backups / f"taoji-{stamp}-{secrets.token_hex(4)}.db"
    while latest.exists():
        latest = backups / f"taoji-{stamp}-{secrets.token_hex(4)}.db"
    descriptor, filename = tempfile.mkstemp(prefix=".taoji-backup-", suffix=".tmp", dir=backups)
    os.close(descriptor)
    temporary = Path(filename)
    deadline = time.monotonic() + _BACKUP_TIMEOUT_SECONDS

    def progress(_status: int, _remaining: int, _total: int) -> None:
        if time.monotonic() >= deadline:
            raise TimeoutError("SQLite backup exceeded its time limit")

    try:
        if os.name != "nt":
            temporary.chmod(0o600)
        # as_uri() correctly quotes spaces, Unicode, '%' and '#' in file names.
        with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True,
                                     timeout=_SQLITE_TIMEOUT_SECONDS)) as source_connection:
            with closing(sqlite3.connect(temporary, timeout=_SQLITE_TIMEOUT_SECONDS)) as target:
                source_connection.backup(target, pages=64, progress=progress, sleep=0.01)
                # A backup is one independent file, with no required WAL sidecar.
                target.execute("PRAGMA journal_mode=DELETE").fetchone()
                _check_integrity(target, deadline)
        # Both SQLite handles must be closed before replacement on Windows.
        os.replace(temporary, latest)
    finally:
        # Only this invocation's unpublished file and SQLite sidecars are removed.
        for path in (temporary, Path(str(temporary) + "-journal"),
                     Path(str(temporary) + "-wal"), Path(str(temporary) + "-shm")):
            try:
                path.unlink()
            except FileNotFoundError:
                pass
    _rotate(backups, source, latest, keep)
    return latest


def _keep_argument(value: str) -> int:
    try:
        keep = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("Введите целое число от 1 до 100") from error
    if not 1 <= keep <= 100:
        raise argparse.ArgumentTypeError("Введите целое число от 1 до 100")
    return keep


def _configured_database() -> Path:
    env_path = ROOT / ".env"
    if not env_path.is_file():
        raise _ConfigurationError("Не найден .env. Подготовьте проект или задайте путь через --database.")
    if __package__:
        from .runtime_env import read_env, sqlite_database_path
    else:
        from runtime_env import read_env, sqlite_database_path

    values = read_env(env_path)
    database = sqlite_database_path(values.get("DATABASE_URL", ""), ROOT)
    if database is None:
        raise _ConfigurationError("Этот скрипт поддерживает только файловую базу SQLite.")
    return database


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Проверенная резервная копия SQLite Taoji Cargo")
    parser.add_argument("--database", type=Path, help="Файл SQLite; по умолчанию DATABASE_URL из .env проекта")
    parser.add_argument("--output", type=Path, default=ROOT / "backups", help="Папка копий; по умолчанию backups проекта")
    parser.add_argument("--keep", type=_keep_argument, default=14, help="Количество сохраняемых копий (1–100), по умолчанию 14")
    args = parser.parse_args(argv)
    try:
        database = args.database if args.database is not None else _configured_database()
        path = create_backup(database, args.output, args.keep)
    except FileNotFoundError:
        print("Ошибка: файл базы не найден. Запустите подготовку базы или проверьте --database.", file=sys.stderr)
        return 1
    except TimeoutError:
        print("Ошибка: база занята дольше 30 секунд. Повторите копирование позднее.", file=sys.stderr)
        return 1
    except sqlite3.DatabaseError:
        print("Ошибка: не удалось прочитать SQLite или проверить целостность копии. Исходная база не изменена.", file=sys.stderr)
        return 1
    except _ConfigurationError as error:
        print(f"Ошибка: {error}", file=sys.stderr)
        return 1
    except (OSError, ValueError):
        # Do not echo DATABASE_URL, SQL contents, or configuration secrets.
        print("Ошибка: проверьте файловую базу SQLite, папку копий, права записи и наличие .env. Можно задать --database явно.", file=sys.stderr)
        return 1
    print(f"Резервная копия проверена: {path}")
    print(f"Сохраняются последние {args.keep} копий Taoji Cargo.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
