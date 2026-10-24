import os
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts import runtime_env


def test_atomic_edit_preserves_comments_and_literal_secrets(tmp_path, capsys):
    path = tmp_path / ".env"
    path.write_bytes(b"\xef\xbb\xbf# Private configuration\nPORT=8001\nBOT_TOKEN=old\n")
    secret = "123456:$SHELL's-private-token"
    runtime_env.update_env(path, {"BOT_TOKEN": secret, "JWT_SECRET": "literal-${HOME}"},
                           expected_fingerprint=runtime_env.env_fingerprint(path))
    assert runtime_env.read_env(path) == {"PORT": "8001", "BOT_TOKEN": secret, "JWT_SECRET": "literal-${HOME}"}
    assert "# Private configuration" in path.read_text()
    assert not path.read_bytes().startswith(b"\xef\xbb\xbf")
    assert list(tmp_path.iterdir()) == [path]
    assert capsys.readouterr().out == ""
    if os.name != "nt":
        assert path.stat().st_mode & 0o777 == 0o600


def test_stale_fingerprint_leaves_user_changes_intact(tmp_path):
    path = tmp_path / ".env"
    path.write_text("PORT=8000\n")
    old_stamp = runtime_env.env_fingerprint(path)
    path.write_text("PORT=8008\n")
    with pytest.raises(runtime_env.EnvConflict):
        runtime_env.update_env(path, {"PORT": "9000"}, expected_fingerprint=old_stamp)
    assert path.read_text() == "PORT=8008\n"
    assert list(tmp_path.iterdir()) == [path]


def test_edit_detects_changes_during_preparation(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    path.write_text("PORT=8000\n")
    fingerprint = runtime_env.env_fingerprint

    def concurrent_writer(target):
        target.write_text("PORT=8008\n")
        return fingerprint(target)

    monkeypatch.setattr(runtime_env, "env_fingerprint", concurrent_writer)
    with pytest.raises(runtime_env.EnvConflict):
        runtime_env.update_env(path, {"PORT": "9000"})
    assert path.read_text() == "PORT=8008\n"
    assert list(tmp_path.iterdir()) == [path]


def test_failed_publish_preserves_original_and_removes_temporary(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    original = b"BOT_TOKEN=original-secret\n"
    path.write_bytes(original)

    def deny_replace(*_args):
        raise PermissionError("Destination is locked")

    monkeypatch.setattr(runtime_env.os, "replace", deny_replace)
    with pytest.raises(PermissionError):
        runtime_env.update_env(path, {"BOT_TOKEN": "new-secret"})
    assert path.read_bytes() == original
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.parametrize("updates", [{1: "value"}, {"BAD-KEY": "value"}, {"PORT": 8000},
                                   {"BOT_TOKEN": "line\nsecret"}, {"BOT_TOKEN": "line\rsecret"},
                                   {"BOT_TOKEN": "null\x00secret"}])
def test_invalid_updates_are_rejected_before_any_write(tmp_path, updates):
    path = tmp_path / ".env"
    path.write_text("PORT=8000\n")
    with pytest.raises(ValueError):
        runtime_env.update_env(path, updates)
    assert path.read_text() == "PORT=8000\n"
    assert list(tmp_path.iterdir()) == [path]


def test_ensure_env_never_replaces_existing_and_cleans_failed_creation(tmp_path):
    path = tmp_path / ".env"
    example = tmp_path / ".env.example"
    example.write_text("PORT=8000\n")
    runtime_env.ensure_env(path, example)
    path.write_text("PORT=8123\n")
    runtime_env.ensure_env(path, tmp_path / "missing-example")
    assert path.read_text() == "PORT=8123\n"
    failed = tmp_path / "failed.env"
    with pytest.raises(FileNotFoundError):
        runtime_env.ensure_env(failed, tmp_path / "missing-example")
    assert not failed.exists()


def test_read_env_does_not_expand_ambient_secrets(tmp_path, monkeypatch):
    monkeypatch.setenv("PRIVATE", "ambient-secret")
    path = tmp_path / ".env"
    path.write_text("TOKEN=${PRIVATE}\nUNSET\n", encoding="utf-8")
    assert runtime_env.read_env(path) == {"TOKEN": "${PRIVATE}", "UNSET": ""}


@pytest.mark.parametrize("url", ["sqlite:///:memory:", "sqlite+aiosqlite:///file:orders.db?mode=ro",
                               "sqlite://user:password@localhost/orders.db", "sqlite://", "not-a-url"])
def test_database_path_rejects_memory_uri_and_invalid_urls(tmp_path, url):
    with pytest.raises(ValueError):
        runtime_env.sqlite_database_path(url, tmp_path)


def test_database_path_resolves_file_and_leaves_non_sqlite_to_caller(tmp_path):
    assert runtime_env.sqlite_database_path("sqlite+aiosqlite:///./data/База #100%.db", tmp_path) == (tmp_path / "data/База #100%.db").resolve()
    assert runtime_env.sqlite_database_path(f"sqlite:///{tmp_path / 'absolute.db'}", tmp_path) == tmp_path / "absolute.db"
    assert runtime_env.sqlite_database_path("postgresql+asyncpg://user:secret@host/database", tmp_path) is None
