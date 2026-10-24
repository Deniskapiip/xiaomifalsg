from pathlib import Path
import sys
import warnings

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts import setup_telegram
from scripts.runtime_env import read_env

TOKEN = "123456789:abcdefghijklmnopqrstuvwxyz_123456"
JWT = "preserved-existing-private-jwt-secret-of-48-bytes"


def test_preparation_disables_preview_and_preserves_independent_configuration():
    values = {"ENV": "development", "DEV_USER_TG_ID": "000111", "JWT_SECRET": JWT,
              "DATABASE_URL": "sqlite+aiosqlite:///./data/taoji.db", "PORT": "8123"}
    updates = setup_telegram.prepare_updates(values, TOKEN, " 222,111,222 ", "333")
    assert updates["OWNER_IDS"] == "111,222"
    assert updates["MANAGER_IDS"] == "333"
    assert updates["DEV_USER_TG_ID"] not in {"111", "222", "333"}
    assert updates["DEV_MODE"] == "false"
    assert updates["BOT_ENABLED"] == "true"
    assert updates["BOT_MODE"] == "polling"
    assert updates["JWT_SECRET"] == JWT
    assert updates["WEBAPP_URL"] == "https://setup-pending.invalid"
    assert "DATABASE_URL" not in updates and "PORT" not in updates
    assert values["DEV_USER_TG_ID"] == "000111"


def test_preview_identity_skips_all_real_administrators_and_invalid_previous_id():
    updates = setup_telegram.prepare_updates({"DEV_USER_TG_ID": "bad", "JWT_SECRET": "change-this-secret"}, TOKEN,
                                            "900000001", "900000002")
    assert updates["DEV_USER_TG_ID"] == "900000003"
    assert len(updates["JWT_SECRET"].encode()) >= 32
    assert not updates["JWT_SECRET"].startswith("change")


@pytest.mark.parametrize("value", ["@someone", "123,", "0", "-1", "123.0", "١٢٣", "9223372036854775808"])
def test_ids_require_ascii_positive_int64_values(value):
    with pytest.raises(ValueError):
        setup_telegram.parse_ids(value, required=True)


def test_owner_required_and_manager_optional():
    with pytest.raises(ValueError):
        setup_telegram.parse_ids("", required=True)
    assert setup_telegram.parse_ids(" ") == ""
    assert setup_telegram.prepare_updates({"JWT_SECRET": JWT}, TOKEN, "111", "")["MANAGER_IDS"] == ""


@pytest.mark.parametrize("token", ["", "12345:short", "abcde:abcdefghijklmnopqrstuvwxyz", TOKEN + "\n"])
def test_token_format_rejected_without_exposing_token(token):
    with pytest.raises(ValueError) as error:
        setup_telegram.prepare_updates({"JWT_SECRET": JWT}, token, "111", "222")
    assert token not in str(error.value) if token else True


def configured_main(tmp_path, monkeypatch, answers, token=TOKEN):
    monkeypatch.setattr(setup_telegram, "ROOT", tmp_path)
    monkeypatch.setattr(sys, "argv", ["setup_telegram.py"])
    monkeypatch.setattr(setup_telegram.getpass, "getpass", lambda _prompt: token)
    responses = iter(answers)
    monkeypatch.setattr("builtins.input", lambda _prompt: next(responses))
    path = tmp_path / ".env"
    path.write_text(f"ENV=development\nDEV_MODE=true\nBOT_TOKEN={TOKEN}\nJWT_SECRET={JWT}\nPORT=8123\n", encoding="utf-8")
    return path


def test_cli_saves_hidden_token_without_echo_and_reuses_it_on_enter(tmp_path, monkeypatch, capsys):
    path = configured_main(tmp_path, monkeypatch, ["111", "", "да"], token="")
    assert setup_telegram.main() == 0
    result = read_env(path)
    assert result["BOT_TOKEN"] == TOKEN
    assert result["JWT_SECRET"] == JWT
    assert result["PORT"] == "8123"
    assert result["DEV_MODE"] == "false"
    assert result["MANAGER_IDS"] == ""
    output = capsys.readouterr().out
    assert TOKEN not in output and JWT not in output


def test_cli_cancel_never_writes_values(tmp_path, monkeypatch):
    path = configured_main(tmp_path, monkeypatch, ["111", "222", "нет"])
    original = path.read_bytes()
    assert setup_telegram.main() == 0
    assert path.read_bytes() == original


def test_cli_rejects_production_without_prompting_or_changing_it(tmp_path, monkeypatch):
    path = configured_main(tmp_path, monkeypatch, [])
    path.write_text("ENV=production\nBOT_TOKEN=production-private-token\n")
    original = path.read_bytes()
    monkeypatch.setattr(setup_telegram.getpass, "getpass", lambda _prompt: pytest.fail("Production must not prompt for secrets"))
    assert setup_telegram.main() == 1
    assert path.read_bytes() == original


def test_cli_conflict_does_not_overwrite_concurrent_user_change_or_echo_secrets(tmp_path, monkeypatch, capsys):
    path = configured_main(tmp_path, monkeypatch, [])
    answers = iter(["111", "222", "да"])

    def input_with_edit(_prompt):
        answer = next(answers)
        if answer == "да":
            path.write_text("ENV=development\nPORT=8555\nBOT_TOKEN=other-private-token\n")
        return answer

    monkeypatch.setattr("builtins.input", input_with_edit)
    assert setup_telegram.main() == 1
    assert read_env(path)["PORT"] == "8555"
    assert read_env(path)["BOT_TOKEN"] == "other-private-token"
    output = capsys.readouterr().out
    assert TOKEN not in output and JWT not in output and "other-private-token" not in output


def test_cli_keyboard_interrupt_preserves_configuration(tmp_path, monkeypatch):
    path = configured_main(tmp_path, monkeypatch, [])
    original = path.read_bytes()

    def interrupt(_prompt):
        raise KeyboardInterrupt

    monkeypatch.setattr(setup_telegram.getpass, "getpass", interrupt)
    assert setup_telegram.main() == 1
    assert path.read_bytes() == original


def test_cli_aborts_before_echoing_getpass_fallback(tmp_path, monkeypatch):
    path = configured_main(tmp_path, monkeypatch, [])
    original = path.read_bytes()

    def unavailable_hidden_input(_prompt):
        warnings.warn("Hidden input is unavailable", setup_telegram.getpass.GetPassWarning)
        pytest.fail("Echoing fallback must never read the token")

    monkeypatch.setattr(setup_telegram.getpass, "getpass", unavailable_hidden_input)
    assert setup_telegram.main() == 1
    assert path.read_bytes() == original
