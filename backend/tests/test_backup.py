import importlib.util
import os
from pathlib import Path
import sqlite3
import time

import pytest


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("taoji_backup", ROOT / "scripts" / "backup.py")
backup = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(backup)


def make_database(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE orders (id INTEGER PRIMARY KEY, title TEXT)")
        connection.execute("INSERT INTO orders (title) VALUES (?)", ("Тестовый заказ",))


@pytest.mark.parametrize("filename", ["orders.db", "База заказов #100%.db"])
def test_checked_backup_supports_spaces_unicode_and_uri_characters(tmp_path, filename):
    source = tmp_path / filename
    make_database(source)
    path = backup.create_backup(source, tmp_path / "Копии базы")

    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA quick_check").fetchall() == [("ok",)]
        assert connection.execute("SELECT title FROM orders").fetchall() == [("Тестовый заказ",)]
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
    assert list(path.parent.iterdir()) == [path]
    if os.name != "nt":
        assert path.stat().st_mode & 0o777 == 0o600


def test_backup_includes_uncheckpointed_wal_and_only_committed_rows(tmp_path):
    source = tmp_path / "live.db"
    writer = sqlite3.connect(source)
    try:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("PRAGMA wal_autocheckpoint=0")
        writer.execute("CREATE TABLE orders (id INTEGER PRIMARY KEY, title TEXT)")
        writer.executemany("INSERT INTO orders (title) VALUES (?)", [(f"Заказ {i}",) for i in range(80)])
        writer.commit()
        assert Path(str(source) + "-wal").stat().st_size > 0
        writer.execute("INSERT INTO orders (title) VALUES ('Ещё не сохранён')")

        path = backup.create_backup(source, tmp_path / "backups")
        with sqlite3.connect(path) as connection:
            assert connection.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 80
            assert connection.execute("SELECT title FROM orders ORDER BY id DESC LIMIT 1").fetchone()[0] == "Заказ 79"
        assert not Path(str(path) + "-wal").exists()
        assert not Path(str(path) + "-shm").exists()
        assert writer.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 81
    finally:
        writer.close()


def test_missing_source_is_never_created(tmp_path):
    source = tmp_path / "missing.db"
    output = tmp_path / "backups"
    with pytest.raises(FileNotFoundError):
        backup.create_backup(source, output)
    assert not source.exists()
    assert not output.exists()


def test_directory_source_is_rejected(tmp_path):
    with pytest.raises(ValueError):
        backup.create_backup(tmp_path, tmp_path / "backups")
    assert not (tmp_path / "backups").exists()


def test_non_sqlite_source_is_not_modified(tmp_path):
    source = tmp_path / "wrong.db"
    original = b"This is not SQLite."
    source.write_bytes(original)
    with pytest.raises(sqlite3.DatabaseError):
        backup.create_backup(source, tmp_path / "backups")
    assert source.read_bytes() == original
    assert not (tmp_path / "backups").exists()


@pytest.mark.parametrize("keep", [0, 101, -1, True, 1.5])
def test_invalid_retention_is_rejected_before_any_write(tmp_path, keep):
    source = tmp_path / "source.db"
    make_database(source)
    with pytest.raises(ValueError):
        backup.create_backup(source, tmp_path / "backups", keep)
    assert not (tmp_path / "backups").exists()


def test_rotation_keeps_fourteen_and_leaves_unrelated_files(tmp_path):
    source = tmp_path / "source.db"
    make_database(source)
    output = tmp_path / "backups"
    output.mkdir()
    unrelated = [output / "other-project.db", output / "taoji-latest.db", output / "README.txt",
                 output / ".taoji-backup-sentinel.tmp"]
    for path in unrelated:
        path.write_bytes(b"Do not remove this file")
    paths = [backup.create_backup(source, output) for _ in range(16)]

    assert len(set(paths)) == 16
    assert not paths[0].exists()
    assert not paths[1].exists()
    assert all(path.exists() for path in paths[2:])
    assert all(path.read_bytes() == b"Do not remove this file" for path in unrelated)
    assert source.exists()
    assert len(list(output.iterdir())) == 18


def test_source_with_backup_name_is_not_rotated(tmp_path):
    source = tmp_path / "taoji-20000101-000000-000000-12345678.db"
    make_database(source)
    first = backup.create_backup(source, tmp_path, keep=1)
    second = backup.create_backup(source, tmp_path, keep=1)
    assert source.exists()
    assert not first.exists()
    assert second.exists()
    with sqlite3.connect(source) as connection:
        assert connection.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 1


def test_rotation_keeps_latest_even_with_old_future_mtime(tmp_path):
    source = tmp_path / "source.db"
    make_database(source)
    first = backup.create_backup(source, tmp_path / "backups", keep=1)
    future = time.time() + 86400
    os.utime(first, (future, future))
    latest = backup.create_backup(source, first.parent, keep=1)
    assert latest.exists()
    assert not first.exists()


def test_integrity_failure_does_not_publish_or_rotate(tmp_path, monkeypatch):
    source = tmp_path / "source.db"
    make_database(source)
    output = tmp_path / "backups"
    original = backup.create_backup(source, output, keep=1)

    def fail_verification(_connection, _deadline):
        raise sqlite3.DatabaseError("Simulated damaged backup")

    monkeypatch.setattr(backup, "_check_integrity", fail_verification)
    with pytest.raises(sqlite3.DatabaseError):
        backup.create_backup(source, output, keep=1)
    assert list(output.iterdir()) == [original]
    with sqlite3.connect(source) as connection:
        assert connection.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 1


def test_publish_failure_removes_partial_and_preserves_previous_backup(tmp_path, monkeypatch):
    source = tmp_path / "source.db"
    make_database(source)
    output = tmp_path / "backups"
    original = backup.create_backup(source, output, keep=1)

    def deny_replace(_source, _destination):
        raise PermissionError("Simulated destination access denial")

    monkeypatch.setattr(backup.os, "replace", deny_replace)
    with pytest.raises(PermissionError):
        backup.create_backup(source, output, keep=1)
    assert list(output.iterdir()) == [original]


def test_owned_name_symlink_is_not_rotated(tmp_path):
    source = tmp_path / "source.db"
    make_database(source)
    output = tmp_path / "backups"
    output.mkdir()
    sentinel = tmp_path / "unrelated.db"
    sentinel.write_bytes(b"Keep this unrelated database")
    link = output / "taoji-20000101-000000-000000-12345678.db"
    try:
        link.symlink_to(sentinel)
    except (OSError, NotImplementedError):
        pytest.skip("Symlink creation is unavailable on this platform")
    latest = backup.create_backup(source, output, keep=1)
    assert latest.exists()
    assert link.is_symlink()
    assert sentinel.read_bytes() == b"Keep this unrelated database"


def test_busy_database_times_out_and_removes_partial_file(tmp_path, monkeypatch):
    source = tmp_path / "source.db"
    make_database(source)
    output = tmp_path / "backups"
    monkeypatch.setattr(backup, "_BACKUP_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(backup, "_SQLITE_TIMEOUT_SECONDS", 0.05)
    blocker = sqlite3.connect(source)
    try:
        blocker.execute("BEGIN EXCLUSIVE")
        blocker.execute("INSERT INTO orders (title) VALUES ('Не сохранён')")
        started = time.monotonic()
        with pytest.raises(TimeoutError):
            backup.create_backup(source, output)
        assert time.monotonic() - started < 2
        assert not list(output.iterdir())
    finally:
        blocker.close()


def test_backup_destination_cannot_be_source_file(tmp_path):
    source = tmp_path / "source.db"
    make_database(source)
    with pytest.raises(ValueError):
        backup.create_backup(source, source)


def test_cli_explicit_source_does_not_require_environment(tmp_path, capsys):
    source = tmp_path / "source.db"
    make_database(source)
    assert backup.main(["--database", str(source), "--output", str(tmp_path / "backups"), "--keep", "2"]) == 0
    captured = capsys.readouterr()
    assert "Резервная копия проверена:" in captured.out
    assert not captured.err


def test_cli_invalid_configuration_does_not_echo_secrets(monkeypatch, capsys):
    def invalid_configuration():
        raise ValueError("postgresql://user:private-password@db.example/db")

    monkeypatch.setattr(backup, "_configured_database", invalid_configuration)
    assert backup.main([]) == 1
    captured = capsys.readouterr()
    assert "private-password" not in captured.err
    assert "db.example" not in captured.err
    assert "SQLite" in captured.err


def test_cli_missing_environment_has_a_clear_error(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(backup, "ROOT", tmp_path)
    assert backup.main([]) == 1
    assert "Не найден .env" in capsys.readouterr().err
