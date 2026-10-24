"""Launch orchestration is tested with fake children and local SQLite only."""
from contextlib import contextmanager
from pathlib import Path
import os
import queue
import shutil
import socket
import sqlite3
import subprocess
import sys
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT / "scripts"))
import dev


@pytest.fixture
def launch_root(tmp_path, monkeypatch):
    root = tmp_path / "project with spaces"
    (root / "data").mkdir(parents=True)
    (root / "frontend/dist").mkdir(parents=True)
    (root / "frontend/dist/index.html").write_text("<!doctype html>", encoding="utf-8")
    shutil.copytree(PROJECT / "backend/alembic", root / "backend/alembic")
    # Use the real migration head instead of a hard-coded revision, so adding a
    # migration does not silently make the launcher fixture look outdated.
    from alembic.script import ScriptDirectory
    heads = sorted(ScriptDirectory(str(root / "backend/alembic")).get_heads())
    connection = sqlite3.connect(root / "data/taoji.db")
    try:
        connection.execute("CREATE TABLE alembic_version (version_num TEXT)")
        connection.executemany("INSERT INTO alembic_version VALUES (?)", [(head,) for head in heads])
        connection.execute("CREATE TABLE app_settings (id INTEGER)")
        connection.execute("INSERT INTO app_settings VALUES (1)")
        connection.commit()
    finally:
        # Windows keeps the file locked until the SQLite handle is closed.
        connection.close()
    (root / ".env").write_text("\n".join([
        "ENV=development", "DEV_MODE=true", "DEV_USER_TG_ID=900000001", "BOT_ENABLED=false",
        "BOT_TOKEN=123456789:unit_test_not_a_real_token", "BOT_MODE=polling",
        "WEBAPP_URL=http://127.0.0.1:8000", "DATABASE_URL=sqlite+aiosqlite:///./data/taoji.db",
        "OWNER_IDS=111", "MANAGER_IDS=222", "JWT_SECRET=unit-test-secret-with-at-least-thirty-two-bytes",
        "HOST=0.0.0.0", "PORT=8000", "",]), encoding="utf-8")
    monkeypatch.setattr(dev.shutil, "which", lambda _command: "/fake/cloudflared")
    monkeypatch.setattr(dev, "check_port", lambda _port: None)
    return root


def env_replace(root, old, new):
    path = root / ".env"
    path.write_text(path.read_text(encoding="utf-8").replace(old, new), encoding="utf-8")


@pytest.mark.parametrize("line,expected", [
    ("| https://little-blue-parcel.trycloudflare.com |", "https://little-blue-parcel.trycloudflare.com"),
    ("\x1b[32mhttps://a1-b2.trycloudflare.com\x1b[0m", "https://a1-b2.trycloudflare.com"),
    ('{"message":"https://abcd.trycloudflare.com"}', "https://abcd.trycloudflare.com"),
    ("https://a.trycloudflare.com.evil.test", None),
    ("https://trycloudflare.com", None),
    ("https://a.trycloudflare.com:444", None),
    ("https://user@a.trycloudflare.com", None),
    ("https://a.trycloudflare.com/path", None),
    ("https://a.trycloudflare.com?token=secret", None),
    ("http://a.trycloudflare.com", None),
])
def test_only_real_quick_url_extracted(line, expected):
    assert dev.extract_quick_url(line) == expected


@pytest.mark.parametrize("value", ["http://example.com", "https://localhost", "https://127.0.0.1", "https://a.example/x", "https://user:pass@a.example", "https://a.example?x=1", "https://a.example#x", "https://a.example:444", "https://a.example\\evil", "https://a.example\n"])
def test_manual_tunnel_url_rejected_without_echoing_value(value):
    with pytest.raises(dev.StartupError) as caught:
        dev.validate_public_url(value)
    assert value not in str(caught.value)


def test_manual_tunnel_url_normalized():
    assert dev.validate_public_url("https://Example.ngrok-free.app:443/") == "https://example.ngrok-free.app"


def test_public_preflight_is_read_only_and_overrides_dev_settings(launch_root, monkeypatch):
    original_env = (launch_root / ".env").read_bytes()
    original_db = (launch_root / "data/taoji.db").read_bytes()
    monkeypatch.setattr(dev.subprocess, "Popen", Mock(side_effect=AssertionError("must not spawn")))
    monkeypatch.setattr(dev, "build_opener", Mock(side_effect=AssertionError("must not contact network")))
    monkeypatch.setenv("BOT_TOKEN", "different_secret_from_shell")
    monkeypatch.setenv("PORT", "8222")
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///do-not-create/ambient.db")
    config = dev.read_launch_config(launch_root)
    assert config.settings.host == "127.0.0.1"
    assert config.settings.dev_mode is False
    assert config.settings.bot_enabled is True
    assert config.settings.port == 8000
    assert config.settings.bot_token == "123456789:unit_test_not_a_real_token"
    assert config.database == launch_root / "data/taoji.db"
    assert (launch_root / ".env").read_bytes() == original_env
    assert (launch_root / "data/taoji.db").read_bytes() == original_db
    assert not (launch_root / "backups").exists()
    assert not (launch_root / ".taoji-launch.lock").exists()


@pytest.mark.parametrize("old,new,hint", [
    ("OWNER_IDS=111", "OWNER_IDS=111,900000001", "Тестовый"),
    ("OWNER_IDS=111", "OWNER_IDS=", "OWNER_IDS"),
    ("OWNER_IDS=111", "OWNER_IDS=not-numeric", "owner_ids"),
    ("ENV=development", "ENV=production", "Production"),
    ("BOT_TOKEN=123456789:unit_test_not_a_real_token", "BOT_TOKEN=", "BOT_TOKEN"),
    ("BOT_TOKEN=123456789:unit_test_not_a_real_token", "BOT_TOKEN=unit-secret-no-colon", "BOT_TOKEN"),
    ("JWT_SECRET=unit-test-secret-with-at-least-thirty-two-bytes", "JWT_SECRET=short-hidden-secret", "JWT_SECRET"),
])
def test_bad_config_does_not_echo_secrets_or_modify_files(launch_root, old, new, hint):
    env_replace(launch_root, old, new)
    original = (launch_root / ".env").read_bytes()
    with pytest.raises(dev.StartupError, match=hint) as caught:
        dev.read_launch_config(launch_root)
    assert "unit-secret" not in str(caught.value)
    assert "short-hidden-secret" not in str(caught.value)
    assert (launch_root / ".env").read_bytes() == original


def test_local_mode_keeps_public_env_and_preserves_configured_roles(launch_root, monkeypatch):
    original = (launch_root / ".env").read_bytes()
    monkeypatch.setattr(dev.shutil, "which", lambda _command: None)
    monkeypatch.setenv("owner_ids", "888")
    config = dev.read_launch_config(launch_root, local=True)
    environment = dev.child_environment(config, config.local_url)
    assert config.cloudflared is None
    assert environment["BOT_ENABLED"] == "false" and environment["DEV_MODE"] == "true"
    assert environment["OWNER_IDS"] == "111"
    assert environment["MANAGER_IDS"] == "222"
    assert environment["HOST"] == "127.0.0.1"
    assert "owner_ids" not in environment
    assert environment["WEBAPP_URL"] == "http://127.0.0.1:8000"
    assert (launch_root / ".env").read_bytes() == original


def test_public_preflight_accepts_owner_without_managers(launch_root):
    env_replace(launch_root, "MANAGER_IDS=222", "MANAGER_IDS=")
    config = dev.read_launch_config(launch_root)
    assert config.settings.owner_id_set == {111}
    assert config.settings.manager_id_set == set()
    assert dev.child_environment(config, "https://safe.trycloudflare.com")["MANAGER_IDS"] == ""


def test_local_default_keeps_existing_fake_user_admin_role(launch_root):
    env_replace(launch_root, "OWNER_IDS=111", "OWNER_IDS=111,900000001")
    env_replace(launch_root, "MANAGER_IDS=222", "MANAGER_IDS=222,900000001")
    config = dev.read_launch_config(launch_root, local=True)
    environment = dev.child_environment(config, config.local_url)
    assert environment["OWNER_IDS"] == "111,900000001"
    assert environment["MANAGER_IDS"] == "222,900000001"


@pytest.mark.parametrize("role,owners,managers", [
    ("client", "111", "222"),
    ("manager", "111", "222,900000001"),
    ("owner", "111,900000001", "222"),
])
def test_explicit_local_role_changes_only_child_environment(launch_root, role, owners, managers):
    env_replace(launch_root, "OWNER_IDS=111", "OWNER_IDS=111,900000001")
    env_replace(launch_root, "MANAGER_IDS=222", "MANAGER_IDS=222,900000001")
    original = (launch_root / ".env").read_bytes()
    config = dev.read_launch_config(launch_root, local=True, local_role=role)
    environment = dev.child_environment(config, config.local_url)
    assert environment["OWNER_IDS"] == owners
    assert environment["MANAGER_IDS"] == managers
    assert config.settings.owner_id_set == {111, 900000001}
    assert config.settings.manager_id_set == {222, 900000001}
    assert (launch_root / ".env").read_bytes() == original


def test_local_preflight_uses_configured_port_in_origin(launch_root):
    env_replace(launch_root, "PORT=8000", "PORT=8222")
    config = dev.read_launch_config(launch_root, local=True)
    assert config.settings.webapp_url == config.local_url == "http://127.0.0.1:8222"


@pytest.mark.parametrize("value", [
    "sqlite+aiosqlite:///:memory:",
    "sqlite+aiosqlite:///file:taoji.db?uri=true",
    "sqlite+aiosqlite:///./data/taoji.db?mode=ro",
    "sqlite+aiosqlite://user:secret@host/data/taoji.db",
    "sqlite+aiosqlite://host/data/taoji.db",
    "postgresql+asyncpg://user:secret@host/database",
])
def test_launcher_rejects_uri_memory_host_or_remote_database_without_echoing_url(tmp_path, value):
    with pytest.raises(dev.StartupError, match="обычным файлом SQLite") as caught:
        dev.database_path(value, tmp_path)
    assert value not in str(caught.value)
    assert not any(tmp_path.iterdir())


def test_existing_url_does_not_require_cloudflared(launch_root, monkeypatch):
    monkeypatch.setattr(dev.shutil, "which", lambda _command: None)
    config = dev.read_launch_config(launch_root, supplied_url="https://qa.ngrok-free.app")
    assert config.cloudflared is None
    assert config.supplied_url == "https://qa.ngrok-free.app"


def test_missing_database_never_created(launch_root):
    path = launch_root / "data/taoji.db"
    path.unlink()
    with pytest.raises(dev.StartupError, match="База не найдена"):
        dev.read_launch_config(launch_root)
    assert not path.exists()


def test_wrong_schema_fails_before_launch(launch_root):
    with sqlite3.connect(launch_root / "data/taoji.db") as connection:
        connection.execute("UPDATE alembic_version SET version_num='0000'")
    with pytest.raises(dev.StartupError, match="База не готова"):
        dev.read_launch_config(launch_root)


def test_unseeded_database_fails_before_launch(launch_root):
    with sqlite3.connect(launch_root / "data/taoji.db") as connection:
        connection.execute("DELETE FROM app_settings")
    with pytest.raises(dev.StartupError, match="База не готова"):
        dev.read_launch_config(launch_root)


def test_busy_port_fails_without_stopping_owner(monkeypatch):
    fake_socket = Mock()
    fake_socket.__enter__ = Mock(return_value=fake_socket)
    fake_socket.__exit__ = Mock(return_value=False)
    fake_socket.bind.side_effect = OSError("busy")
    monkeypatch.setattr(dev.socket, "socket", lambda *_args: fake_socket)
    with pytest.raises(dev.StartupError, match="занят"):
        dev.check_port(8000)
    fake_socket.bind.assert_called_once_with(("127.0.0.1", 8000))


def test_port_probe_rejects_real_active_listener():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        if os.name != "nt":
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        port = listener.getsockname()[1]
        with pytest.raises(dev.StartupError, match="занят"):
            dev.check_port(port)
        # The probe must leave the existing server reachable.
        with socket.create_connection(("127.0.0.1", port), timeout=1) as client:
            accepted, _address = listener.accept()
            accepted.close()


@pytest.mark.skipif(os.name == "nt", reason="SO_REUSEADDR safely permits POSIX TIME_WAIT reuse only")
def test_posix_port_probe_allows_restart_after_server_closes_connection_first():
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    port = listener.getsockname()[1]
    client = socket.create_connection(("127.0.0.1", port), timeout=1)
    accepted, _address = listener.accept()
    accepted.settimeout(1)
    try:
        # The server initiates FIN, leaving its port in TIME_WAIT once the
        # client's FIN arrives. A plain bind would fail during a quick restart.
        accepted.shutdown(socket.SHUT_WR)
        assert client.recv(1) == b""
        client.close()
        assert accepted.recv(1) == b""
    finally:
        client.close()
        accepted.close()
        listener.close()
    dev.check_port(port)


def test_windows_port_probe_keeps_default_binding_without_reuse(monkeypatch):
    fake_socket = Mock()
    fake_socket.__enter__ = Mock(return_value=fake_socket)
    fake_socket.__exit__ = Mock(return_value=False)
    monkeypatch.setattr(dev.socket, "socket", lambda *_args: fake_socket)
    # Patch only the launcher module's os binding, without changing pathlib's
    # platform for the remainder of the test process.
    monkeypatch.setattr(dev, "os", SimpleNamespace(name="nt"))
    dev.check_port(8000)
    fake_socket.setsockopt.assert_not_called()
    fake_socket.bind.assert_called_once_with(("127.0.0.1", 8000))


def test_launch_lock_blocks_second_launch_and_releases(tmp_path):
    with dev.launch_lock(tmp_path):
        with pytest.raises(dev.StartupError, match="уже запущен"):
            with dev.launch_lock(tmp_path):
                pytest.fail("second lock must fail")
    with dev.launch_lock(tmp_path):
        pass


class FakeChild:
    def __init__(self, lines=(), exit_code=None, diagnostic=None, tunnel_diagnostic=None):
        self.lines = queue.Queue()
        for line in lines:
            self.lines.put(line)
        self.exit_code = exit_code
        self.closed = False
        self.diagnostic = diagnostic
        self.transport_diagnostic = tunnel_diagnostic

    def poll(self):
        return self.exit_code

    def close(self):
        self.closed = True

    def startup_diagnostic(self, *, wait_for_output=False):
        return self.diagnostic

    def tunnel_diagnostic(self):
        return self.transport_diagnostic


def test_tunnel_waits_for_url_and_connection():
    child = FakeChild(["https://good-words.trycloudflare.com", "Registered tunnel connection connIndex=0"])
    assert dev.wait_tunnel(child, timeout=1) == "https://good-words.trycloudflare.com"


def test_tunnel_missing_connection_times_out():
    child = FakeChild(["https://good-words.trycloudflare.com"])
    with pytest.raises(dev.StartupError, match="не подключился"):
        dev.wait_tunnel(child, timeout=0.02)


def test_tunnel_early_exit_fails():
    child = FakeChild(exit_code=1)
    with pytest.raises(dev.StartupError, match="завершился"):
        dev.wait_tunnel(child, timeout=1)


@pytest.mark.parametrize("line,expected", [
    ("Registered tunnel connection connIndex=0", "REGISTERED"),
    ("Unregistered tunnel connection connIndex=0 private-secret", "RECONNECTING"),
    ("ERR Lost connection with the edge private-secret", "RECONNECTING"),
    ("ERR error looking up Cloudflare edge IPs private-secret", "DNS"),
    ("ERR DialContext error dial tcp 1.2.3.4:7844: i/o timeout private-secret", "TCP_TIMEOUT"),
    ("ERR QUIC handshake timeout private-secret", "QUIC_TIMEOUT"),
    ("ERR TLS handshake x509: certificate signed by unknown authority private-secret", "TLS"),
    ("ordinary output containing private-secret", None),
])
def test_transport_log_reduced_to_safe_code(line, expected):
    assert dev.parse_tunnel_diagnostic(line) == expected


def test_stop_process_escalates_only_its_child():
    child = Mock()
    child.poll.return_value = None
    child.wait.side_effect = [subprocess.TimeoutExpired("fake", 0), subprocess.TimeoutExpired("fake", 0), 0]
    dev.stop_process(child, grace=0.01)
    child.send_signal.assert_called_once()
    child.terminate.assert_called_once()
    child.kill.assert_called_once()
    assert [call.kwargs["timeout"] for call in child.wait.call_args_list] == [0.01, 3, 3]


def test_windows_process_options_create_an_own_signal_group(monkeypatch):
    monkeypatch.setattr(dev, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(dev, "subprocess", SimpleNamespace(CREATE_NEW_PROCESS_GROUP=0x200))
    assert dev.process_options() == {"creationflags": 0x200}


def test_posix_process_options_create_an_own_session(monkeypatch):
    monkeypatch.setattr(dev, "os", SimpleNamespace(name="posix"))
    assert dev.process_options() == {"start_new_session": True}


def test_windows_stop_requests_ctrl_break_before_force_stop(monkeypatch):
    monkeypatch.setattr(dev, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(dev, "signal", SimpleNamespace(CTRL_BREAK_EVENT=21))
    child = Mock()
    child.poll.return_value = None
    child.wait.return_value = 0
    dev.stop_process(child, grace=0.01)
    child.send_signal.assert_called_once_with(21)
    child.wait.assert_called_once_with(timeout=0.01)
    child.terminate.assert_not_called()
    child.kill.assert_not_called()


def test_stop_does_not_signal_already_exited_child():
    child = Mock()
    child.poll.return_value = 0
    dev.stop_process(child)
    child.send_signal.assert_not_called()
    child.terminate.assert_not_called()
    child.kill.assert_not_called()


@pytest.fixture
def run_mocks(launch_root, monkeypatch):
    import backup
    import runtime_env
    config = dev.read_launch_config(launch_root)
    events = []
    tunnel, backend = FakeChild(), FakeChild()

    def captured(command, **kwargs):
        kind = "backend" if "app.main" in command else "tunnel"
        events.append((kind, command, kwargs))
        return backend if kind == "backend" else tunnel

    monkeypatch.setattr(dev, "CapturedProcess", captured)
    monkeypatch.setattr(backup, "create_backup", Mock(side_effect=lambda *_args, **_kwargs: events.append(("backup",))))
    monkeypatch.setattr(dev, "wait_tunnel", Mock(side_effect=lambda *_args: events.append(("connected",)) or "https://new-safe.trycloudflare.com"))
    real_update = runtime_env.update_env

    def update(*args, **kwargs):
        events.append(("update", args, kwargs))
        return real_update(*args, **kwargs)

    monkeypatch.setattr(runtime_env, "update_env", update)
    monkeypatch.setattr(dev, "wait_backend", Mock(side_effect=lambda *_args: events.append(("ready",))))
    monkeypatch.setattr(dev, "wait_public_backend", Mock(side_effect=lambda *_args: events.append(("public_ready",))))
    monkeypatch.setattr(dev.time, "sleep", Mock(side_effect=KeyboardInterrupt))
    return config, events, tunnel, backend


def test_full_run_orders_backup_connection_url_then_backend_and_cleans_up(run_mocks):
    from runtime_env import read_env
    config, events, tunnel, backend = run_mocks
    before = (config.root / ".env").read_text(encoding="utf-8")
    with pytest.raises(KeyboardInterrupt):
        dev.run(config)
    assert [item[0] for item in events] == ["backup", "tunnel", "connected", "update", "backend", "ready", "public_ready"]
    after = (config.root / ".env").read_text(encoding="utf-8")
    assert [line for line in after.splitlines() if not line.startswith("WEBAPP_URL=")] == [
        line for line in before.splitlines() if not line.startswith("WEBAPP_URL=")]
    assert read_env(config.root / ".env")["WEBAPP_URL"] == "https://new-safe.trycloudflare.com"
    backend_env = next(item[2]["env"] for item in events if item[0] == "backend")
    assert backend_env["DEV_MODE"] == "false" and backend_env["BOT_ENABLED"] == "true"
    assert backend_env["WEBAPP_URL"] == "https://new-safe.trycloudflare.com"
    assert backend_env["OWNER_IDS"] == "111"
    cf_command = next(item[1] for item in events if item[0] == "tunnel")
    assert "--config" in cf_command and "--no-autoupdate" in cf_command
    assert cf_command[-2:] == ["--protocol", "http2"]
    assert tunnel.closed and backend.closed


def test_full_run_sends_proxy_only_to_backend(run_mocks, monkeypatch):
    config, events, _tunnel, _backend = run_mocks
    proxy = "socks5://127.0.0.1:1080"
    with (config.root / ".env").open("a", encoding="utf-8") as stream:
        stream.write(f"BOT_PROXY_URL={proxy}\n")
    config = dev.read_launch_config(config.root)
    monkeypatch.setenv("HTTPS_PROXY", "http://ambient.invalid:8080")
    with pytest.raises(KeyboardInterrupt):
        dev.run(config)
    backend_env = next(item[2]["env"] for item in events if item[0] == "backend")
    tunnel_env = next(item[2]["env"] for item in events if item[0] == "tunnel")
    assert backend_env["BOT_PROXY_URL"] == proxy
    assert "BOT_PROXY_URL" not in tunnel_env
    assert not any(key.upper() in {"HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"} for key in tunnel_env)


def test_failed_tunnel_never_updates_env_or_starts_backend(run_mocks, monkeypatch):
    config, events, tunnel, backend = run_mocks
    before = (config.root / ".env").read_bytes()
    monkeypatch.setattr(dev, "wait_tunnel", Mock(side_effect=dev.StartupError("fake timeout")))
    with pytest.raises(dev.StartupError, match="fake timeout"):
        dev.run(config)
    assert [item[0] for item in events] == ["backup", "tunnel"]
    assert (config.root / ".env").read_bytes() == before
    assert tunnel.closed and not backend.closed


def test_changed_env_stops_before_backup_or_any_child(run_mocks):
    config, events, tunnel, backend = run_mocks
    with (config.root / ".env").open("a", encoding="utf-8") as stream:
        stream.write("# changed by user\n")
    with pytest.raises(dev.StartupError, match="изменился"):
        dev.run(config)
    assert events == []
    assert not tunnel.closed and not backend.closed


def test_backup_failure_stops_before_tunnel_or_env_update(run_mocks, monkeypatch):
    import backup
    config, events, tunnel, backend = run_mocks
    before = (config.root / ".env").read_bytes()
    monkeypatch.setattr(backup, "create_backup", Mock(side_effect=OSError("disk full")))
    with pytest.raises(dev.StartupError, match="резервную копию"):
        dev.run(config)
    assert events == []
    assert (config.root / ".env").read_bytes() == before
    assert not tunnel.closed and not backend.closed


def test_backend_startup_failure_stops_both_owned_children(run_mocks, monkeypatch):
    config, events, tunnel, backend = run_mocks
    monkeypatch.setattr(dev, "wait_backend", Mock(side_effect=dev.StartupError("startup failure")))
    with pytest.raises(dev.StartupError, match="startup failure"):
        dev.run(config)
    assert backend.closed and tunnel.closed


def test_public_failure_never_prints_ready_and_closes_both_children(run_mocks, monkeypatch, capsys):
    config, _events, tunnel, backend = run_mocks
    monkeypatch.setattr(dev, "wait_public_backend", Mock(side_effect=dev.StartupError("CLOUDFLARE_1033")))
    with pytest.raises(dev.StartupError, match="CLOUDFLARE_1033"):
        dev.run(config)
    output = capsys.readouterr().out
    assert "Проверяю публичный адрес" in output
    assert "Готово:" not in output
    assert backend.closed and tunnel.closed


@pytest.mark.parametrize("protocol", ["auto", "quic"])
def test_selected_protocol_reaches_owned_tunnel_command(run_mocks, protocol):
    original, events, _tunnel, _backend = run_mocks
    config = dev.read_launch_config(original.root, tunnel_protocol=protocol)
    with pytest.raises(KeyboardInterrupt):
        dev.run(config)
    command = next(item[1] for item in events if item[0] == "tunnel")
    assert command[-2:] == ["--protocol", protocol]


def test_invalid_transport_rejected_before_reading_env(tmp_path):
    with pytest.raises(dev.StartupError, match="--tunnel-protocol"):
        dev.read_launch_config(tmp_path, tunnel_protocol="private-secret")


def test_public_health_retries_transient_1033_then_succeeds(monkeypatch):
    from tunnel_health import HealthResult
    check = Mock(side_effect=[HealthResult("CLOUDFLARE_1033", 530), HealthResult("OK", 200)])
    monkeypatch.setattr(dev, "probe_health", check)
    monkeypatch.setattr(dev.time, "sleep", Mock())
    dev.wait_public_backend("https://safe.trycloudflare.com", FakeChild(), FakeChild(), timeout=1)
    assert check.call_count == 2
    assert all(0 < call.kwargs["timeout"] <= 1 for call in check.call_args_list)


def test_public_health_failure_is_bounded_and_keeps_transport_hint(monkeypatch):
    from tunnel_health import HealthResult
    clock = SimpleNamespace(now=0)
    monkeypatch.setattr(dev.time, "monotonic", lambda: clock.now)
    monkeypatch.setattr(dev.time, "sleep", lambda seconds: setattr(clock, "now", clock.now + seconds))
    check = Mock(return_value=HealthResult("CLOUDFLARE_1033", 530))
    monkeypatch.setattr(dev, "probe_health", check)
    with pytest.raises(dev.StartupError, match="CLOUDFLARE_1033") as caught:
        dev.wait_public_backend("https://safe.trycloudflare.com", FakeChild(),
                                FakeChild(tunnel_diagnostic="TCP_TIMEOUT"), timeout=2)
    assert clock.now == 2
    assert check.call_count == 2
    assert "TCP 7844" in str(caught.value)


def test_public_health_rechecks_owned_children_after_successful_http(monkeypatch):
    from tunnel_health import HealthResult
    tunnel = FakeChild()
    def disappear(*_args, **_kwargs):
        tunnel.exit_code = 1
        return HealthResult("OK", 200)
    monkeypatch.setattr(dev, "probe_health", disappear)
    with pytest.raises(dev.StartupError, match="Туннель остановился"):
        dev.wait_public_backend("https://safe.trycloudflare.com", FakeChild(), tunnel, timeout=1)


def test_tunnel_cleanup_still_runs_if_backend_cleanup_fails(run_mocks, monkeypatch):
    config, events, tunnel, backend = run_mocks
    monkeypatch.setattr(backend, "close", Mock(side_effect=OSError("child cleanup failure")))
    with pytest.raises(OSError, match="child cleanup failure"):
        dev.run(config)
    assert tunnel.closed


def test_local_run_never_updates_env_or_creates_tunnel(run_mocks):
    original_config, events, tunnel, backend = run_mocks
    config = dev.read_launch_config(original_config.root, local=True, local_role="manager")
    before = (config.root / ".env").read_bytes()
    with pytest.raises(KeyboardInterrupt):
        dev.run(config)
    assert [item[0] for item in events] == ["backup", "backend", "ready"]
    assert (config.root / ".env").read_bytes() == before
    backend_env = next(item[2]["env"] for item in events if item[0] == "backend")
    assert backend_env["BOT_ENABLED"] == "false" and backend_env["DEV_MODE"] == "true"
    assert backend_env["OWNER_IDS"] == "111" and backend_env["MANAGER_IDS"] == "222,900000001"
    assert backend.closed and not tunnel.closed


def test_manual_tunnel_run_changes_url_without_spawning_another_tunnel(run_mocks):
    from runtime_env import read_env
    original_config, events, tunnel, backend = run_mocks
    config = dev.read_launch_config(original_config.root, supplied_url="https://manual.ngrok-free.app")
    with pytest.raises(KeyboardInterrupt):
        dev.run(config)
    assert [item[0] for item in events] == ["backup", "update", "backend", "ready", "public_ready"]
    assert read_env(config.root / ".env")["WEBAPP_URL"] == "https://manual.ngrok-free.app"
    assert backend.closed and not tunnel.closed


def test_dead_tunnel_stops_running_backend(run_mocks, monkeypatch):
    config, events, tunnel, backend = run_mocks
    monkeypatch.setattr(dev, "wait_backend", Mock(side_effect=lambda *_args: setattr(tunnel, "exit_code", 1)))
    with pytest.raises(dev.StartupError, match="Туннель остановился"):
        dev.run(config)
    assert backend.closed and tunnel.closed


def test_cloudflared_does_not_inherit_named_tunnel_or_bot_secrets(monkeypatch):
    monkeypatch.setenv("TUNNEL_TOKEN", "not-a-real-tunnel-token")
    monkeypatch.setenv("TUNNEL_NAME", "other-project")
    monkeypatch.setenv("BOT_TOKEN", "fake-secret")
    monkeypatch.setenv("BOT_PROXY_URL", "http://user:fake-secret@localhost:8080")
    monkeypatch.setenv("ONEBOUND_API_KEY", "fake-product-key")
    monkeypatch.setenv("ONEBOUND_API_SECRET", "fake-product-secret")
    monkeypatch.setenv("JWT_SECRET", "fake-secret")
    monkeypatch.setenv("PATH", "/kept/path")
    monkeypatch.setenv("HTTPS_PROXY", "http://kept.proxy")
    environment = dev.cloudflared_environment()
    assert environment["PATH"] == "/kept/path"
    assert environment["HTTPS_PROXY"] == "http://kept.proxy"
    assert not any(key in environment for key in ["TUNNEL_TOKEN", "TUNNEL_NAME", "BOT_TOKEN", "BOT_PROXY_URL", "JWT_SECRET", "ONEBOUND_API_KEY", "ONEBOUND_API_SECRET"])


def test_telegram_proxy_keeps_tunnel_off_shell_proxies(monkeypatch):
    for key in ["HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"]:
        monkeypatch.setenv(key, "http://proxy.invalid:8080")
    monkeypatch.setenv("NO_PROXY", "localhost")
    monkeypatch.setenv("SSL_CERT_FILE", "/kept/ca.pem")
    environment = dev.cloudflared_environment(telegram_proxy=True)
    assert not any(key.upper() in {"HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"} for key in environment)
    assert environment["NO_PROXY"] == "localhost"
    assert environment["SSL_CERT_FILE"] == "/kept/ca.pem"


def test_check_cli_never_runs_or_backs_up(launch_root, monkeypatch, capsys):
    config = dev.read_launch_config(launch_root)
    monkeypatch.setattr(dev, "read_launch_config", Mock(return_value=config))
    runner = Mock(side_effect=AssertionError("check must not start"))
    monkeypatch.setattr(dev, "run", runner)
    assert dev.main(["--check"]) == 0
    assert "Секреты скрыты" in capsys.readouterr().out
    runner.assert_not_called()


@pytest.mark.parametrize("arguments", [
    ["--local-role", "owner"],
    ["--url", "https://safe.trycloudflare.com", "--local-role", "manager"],
])
def test_cli_rejects_local_role_without_local_before_reading_config(arguments, monkeypatch, capsys):
    preflight = Mock(side_effect=AssertionError("must fail before preflight"))
    monkeypatch.setattr(dev, "read_launch_config", preflight)
    with pytest.raises(SystemExit) as caught:
        dev.main(arguments)
    assert caught.value.code == 2
    assert "только вместе с --local" in capsys.readouterr().err
    preflight.assert_not_called()


@pytest.mark.parametrize("local,role", [(False, "owner"), (True, "admin")])
def test_preflight_rejects_invalid_local_role_before_config_read(tmp_path, local, role):
    with pytest.raises(dev.StartupError, match="--local-role"):
        dev.read_launch_config(tmp_path, local=local, local_role=role)


def test_cli_error_never_prints_unexpected_exception_secrets(monkeypatch, capsys):
    monkeypatch.setattr(dev, "read_launch_config", Mock(side_effect=RuntimeError("very-private-token")))
    assert dev.main(["--check"]) == 1
    assert "very-private-token" not in capsys.readouterr().err


@pytest.mark.parametrize("line", [
    "prefix TAOJI_STARTUP_ERROR BOT_UNAUTHORIZED identity\n",
    " TAOJI_STARTUP_ERROR BOT_UNAUTHORIZED identity\n",
    "TAOJI_STARTUP_ERROR BOT_UNAUTHORIZED identity private-secret\n",
    "TAOJI_STARTUP_ERROR BOT_NOT_REAL identity\n",
    "TAOJI_STARTUP_ERROR BOT_NETWORK arbitrary-stage\n",
    "TAOJI_STARTUP_ERROR BOT_NETWORK IDENTITY\n",
    "\x1b[31mTAOJI_STARTUP_ERROR BOT_NETWORK identity\x1b[0m\n",
    "TAOJI_STARTUP_ERROR BOT_NETWORK identity\nextra",
])
def test_only_exact_known_startup_marker_is_accepted(line):
    assert dev.parse_startup_diagnostic(line) is None


def test_real_child_error_retained_when_log_queue_is_full(tmp_path, capsys):
    script = (
        "for i in range(600): print('hidden-private-token http://api.invalid/bot-secret/' + str(i))\n"
        "print('TAOJI_STARTUP_ERROR BOT_NETWORK menu', flush=True)\n"
        "print('Unregistered tunnel connection hidden-private-token', flush=True)\n"
        "print('TAOJI_STARTUP_ERROR BOT_NOT_REAL identity', flush=True)\n"
        "raise SystemExit(1)\n"
    )
    child = dev.CapturedProcess([sys.executable, "-c", script], cwd=tmp_path, env=dict(os.environ))
    try:
        child.process.wait(timeout=5)
        with pytest.raises(dev.StartupError, match="Нет связи с Telegram") as caught:
            dev.wait_backend(child, 8000, None, timeout=1)
        message = str(caught.value)
        assert "настройка кнопки Mini App" in message
        assert "hidden-private-token" not in message and "bot-secret" not in message
        assert "BOT_NOT_REAL" not in message
        assert child.lines.qsize() == 512
        assert child.tunnel_diagnostic() == "RECONNECTING"
    finally:
        child.close()
    output = capsys.readouterr()
    assert output.out == "" and output.err == ""


def test_exited_child_waits_briefly_for_pending_reader_marker(tmp_path, monkeypatch):
    release_reader = threading.Event()
    real_read = dev.CapturedProcess._read

    def delayed_read(child):
        release_reader.wait(timeout=2)
        real_read(child)

    monkeypatch.setattr(dev.CapturedProcess, "_read", delayed_read)
    child = dev.CapturedProcess(
        [sys.executable, "-c", "print('TAOJI_STARTUP_ERROR BOT_UNAUTHORIZED identity', flush=True)"],
        cwd=tmp_path, env=dict(os.environ),
    )
    timer = None
    try:
        child.process.wait(timeout=5)
        assert child.startup_diagnostic() is None
        timer = threading.Timer(0.02, release_reader.set)
        timer.start()
        with pytest.raises(dev.StartupError, match="Telegram отклонил токен") as caught:
            dev.wait_backend(child, 8000, None, timeout=1)
        assert "проверка токена" in str(caught.value)
    finally:
        release_reader.set()
        if timer is not None:
            timer.cancel()
        child.close()


def test_unknown_real_child_trace_shows_diagnostic_command_without_echoing_secrets(tmp_path, capsys):
    script = (
        "print('Traceback: https://api.telegram.org/bot-private-token/getMe', flush=True)\n"
        "print('TAOJI_STARTUP_ERROR BOT_UNKNOWN identity private-secret', flush=True)\n"
        "raise SystemExit(1)\n"
    )
    child = dev.CapturedProcess([sys.executable, "-c", script], cwd=tmp_path, env=dict(os.environ))
    try:
        child.process.wait(timeout=5)
        with pytest.raises(dev.StartupError) as caught:
            dev.wait_backend(child, 8000, None, timeout=1)
        message = str(caught.value)
        assert "..\\.venv\\Scripts\\python.exe -m app.main" in message
        assert "private-token" not in message and "private-secret" not in message
        assert "второго polling" not in message
    finally:
        child.close()
    output = capsys.readouterr()
    assert output.out == "" and output.err == ""


def test_backend_timeout_preserves_safe_diagnostic_without_echoing_network_exception(monkeypatch):
    child = FakeChild(diagnostic=("BOT_RATE_LIMITED", "commands"))
    opener = Mock()
    opener.open.side_effect = dev.URLError("private-token from HTTP proxy")
    monkeypatch.setattr(dev, "build_opener", Mock(return_value=opener))
    with pytest.raises(dev.StartupError, match="Telegram временно ограничил") as caught:
        dev.wait_backend(child, 8000, None, timeout=0.001)
    message = str(caught.value)
    assert "за отведённое время" in message and "настройка команд бота" in message
    assert "private-token" not in message
