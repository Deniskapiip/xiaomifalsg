from pathlib import Path
import subprocess
import sys
import warnings

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts import ngrok_tunnel
from scripts.runtime_env import read_env

SECRET = "ngrok-private-authtoken-never-a-command-argument"


class FakeProcess:
    def __init__(self, wait_results=None):
        self.returncode = None
        self.wait_results = list(wait_results or [0])
        self.terminated = False
        self.killed = False

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        result = self.wait_results.pop(0)
        if isinstance(result, BaseException):
            raise result
        self.returncode = result
        return result

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.killed = True


def configure(tmp_path, monkeypatch, token=SECRET):
    monkeypatch.setattr(ngrok_tunnel, "ROOT", tmp_path)
    monkeypatch.setattr(sys, "argv", ["ngrok_tunnel.py"])
    monkeypatch.setattr(ngrok_tunnel.shutil, "which", lambda _name: "C:/ngrok/ngrok.exe")
    path = tmp_path / ".env"
    path.write_text(f"PORT=8123\nNGROK_AUTHTOKEN={token}\n", encoding="utf-8")
    return path


def test_token_only_in_child_environment_and_exit_code_preserved(tmp_path, monkeypatch, capsys):
    configure(tmp_path, monkeypatch)
    child = FakeProcess([7])
    calls = []

    def popen(command, **options):
        calls.append((command, options))
        return child

    monkeypatch.setattr(ngrok_tunnel.subprocess, "Popen", popen)
    assert ngrok_tunnel.main() == 7
    command, options = calls[0]
    assert command == ["C:/ngrok/ngrok.exe", "http", "http://127.0.0.1:8123"]
    assert options["env"]["NGROK_AUTHTOKEN"] == SECRET
    assert options["cwd"] == tmp_path
    assert SECRET not in str(command)
    assert SECRET not in capsys.readouterr().out
    assert not child.terminated


def test_ctrl_c_stops_only_own_child(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch)
    child = FakeProcess([KeyboardInterrupt(), -15])
    monkeypatch.setattr(ngrok_tunnel.subprocess, "Popen", lambda *_args, **_options: child)
    assert ngrok_tunnel.main() == 0
    assert child.terminated
    assert not child.killed


def test_unresponsive_child_is_killed_after_termination_timeout():
    child = FakeProcess([subprocess.TimeoutExpired("ngrok", 5), -9])
    ngrok_tunnel.stop_child(child)
    assert child.terminated and child.killed


def test_hidden_prompt_may_persist_token_without_placing_it_in_command(tmp_path, monkeypatch, capsys):
    path = configure(tmp_path, monkeypatch, token="")
    monkeypatch.setattr(ngrok_tunnel.getpass, "getpass", lambda _prompt: SECRET)
    monkeypatch.setattr("builtins.input", lambda _prompt: "да")
    child = FakeProcess()
    commands = []
    monkeypatch.setattr(ngrok_tunnel.subprocess, "Popen", lambda command, **_options: commands.append(command) or child)
    assert ngrok_tunnel.main() == 0
    assert read_env(path)["NGROK_AUTHTOKEN"] == SECRET
    assert SECRET not in str(commands)
    assert SECRET not in capsys.readouterr().out


def test_transient_token_not_saved_when_user_declines(tmp_path, monkeypatch):
    path = configure(tmp_path, monkeypatch, token="")
    original = path.read_bytes()
    monkeypatch.setattr(ngrok_tunnel.getpass, "getpass", lambda _prompt: SECRET)
    monkeypatch.setattr("builtins.input", lambda _prompt: "нет")
    monkeypatch.setattr(ngrok_tunnel.subprocess, "Popen", lambda *_args, **_options: FakeProcess())
    assert ngrok_tunnel.main() == 0
    assert path.read_bytes() == original


@pytest.mark.parametrize("port", ["0", "65536", "invalid"])
def test_invalid_port_never_starts_child(tmp_path, monkeypatch, port):
    path = configure(tmp_path, monkeypatch)
    path.write_text(f"PORT={port}\nNGROK_AUTHTOKEN={SECRET}\n")
    monkeypatch.setattr(ngrok_tunnel.subprocess, "Popen", lambda *_args, **_options: pytest.fail("Invalid port must not launch anything"))
    assert ngrok_tunnel.main() == 1


def test_invalid_saved_token_never_starts_child(tmp_path, monkeypatch, capsys):
    configure(tmp_path, monkeypatch, token="bad token with spaces")
    monkeypatch.setattr(ngrok_tunnel.subprocess, "Popen", lambda *_args, **_options: pytest.fail("Invalid token must not launch anything"))
    assert ngrok_tunnel.main() == 1
    assert "bad token with spaces" not in capsys.readouterr().out


def test_missing_ngrok_and_launch_failure_do_not_disclose_secret(tmp_path, monkeypatch, capsys):
    configure(tmp_path, monkeypatch)
    monkeypatch.setattr(ngrok_tunnel.shutil, "which", lambda _name: None)
    assert ngrok_tunnel.main() == 1
    monkeypatch.setattr(ngrok_tunnel.shutil, "which", lambda _name: "ngrok")

    def fail_launch(*_args, **_options):
        raise OSError(SECRET)

    monkeypatch.setattr(ngrok_tunnel.subprocess, "Popen", fail_launch)
    assert ngrok_tunnel.main() == 1
    assert SECRET not in capsys.readouterr().out


def test_help_requires_neither_env_nor_ngrok(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(ngrok_tunnel, "ROOT", tmp_path)
    monkeypatch.setattr(sys, "argv", ["ngrok_tunnel.py", "--help"])
    with pytest.raises(SystemExit) as result:
        ngrok_tunnel.main()
    assert result.value.code == 0
    assert "ngrok" in capsys.readouterr().out


def test_cli_aborts_before_echoing_getpass_fallback(tmp_path, monkeypatch):
    path = configure(tmp_path, monkeypatch, token="")
    original = path.read_bytes()

    def unavailable_hidden_input(_prompt):
        warnings.warn("Hidden input is unavailable", ngrok_tunnel.getpass.GetPassWarning)
        pytest.fail("Echoing fallback must never read the token")

    monkeypatch.setattr(ngrok_tunnel.getpass, "getpass", unavailable_hidden_input)
    assert ngrok_tunnel.main() == 1
    assert path.read_bytes() == original
