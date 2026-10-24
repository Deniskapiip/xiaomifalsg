"""Optional manual tunnel; auth token stays in .env and the child environment."""
import argparse
import getpass
import os
from pathlib import Path
import shutil
import subprocess
import sys
import warnings

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.runtime_env import env_fingerprint, read_env, update_env


def hidden_prompt(prompt: str) -> str:
    with warnings.catch_warnings():
        warnings.simplefilter("error", getpass.GetPassWarning)
        return getpass.getpass(prompt)


def stop_child(process: subprocess.Popen) -> None:
    """Close only the ngrok process that this command created."""
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def main() -> int:
    argparse.ArgumentParser(description="Запустить резервный туннель ngrok без токена в командной строке").parse_args()
    process = None
    try:
        values = read_env(ROOT / ".env")
        executable = shutil.which("ngrok")
        if not executable:
            print("ngrok не найден. Установите его с ngrok.com, откройте новое окно терминала и повторите.")
            return 1
        token = values.get("NGROK_AUTHTOKEN", "")
        if not token:
            stamp = env_fingerprint(ROOT / ".env")
            token = hidden_prompt("Authtoken из личного кабинета ngrok (ввод скрыт): ").strip()
            if not token or any(char.isspace() for char in token):
                print("Authtoken пуст или содержит пробелы. Его значение не выводится.")
                return 1
            if input("Сохранить authtoken в .env? [да/нет]: ").strip().lower() in {"да", "д", "yes", "y"}:
                update_env(ROOT / ".env", {"NGROK_AUTHTOKEN": token}, expected_fingerprint=stamp)
        if not token or any(char.isspace() for char in token):
            raise ValueError("NGROK_AUTHTOKEN")
        port = int(values.get("PORT", "8000"))
        if not 1 <= port <= 65535:
            raise ValueError("PORT")
        print("Оставьте это окно открытым. Возьмите HTTPS-адрес из ngrok и в другом окне запустите:")
        print(r".\.venv\Scripts\python.exe scripts\dev.py --url https://ВАШ-АДРЕС")
        process = subprocess.Popen([executable, "http", f"http://127.0.0.1:{port}"], env={**os.environ, "NGROK_AUTHTOKEN": token}, cwd=ROOT)
        return process.wait()
    except KeyboardInterrupt:
        return 0
    except Exception:
        print("Не удалось запустить ngrok. Проверьте установку, .env, authtoken и подключение; секреты не выводятся.")
        return 1
    finally:
        if process is not None:
            try:
                stop_child(process)
            except (OSError, subprocess.TimeoutExpired):
                print("Не удалось остановить запущенный ngrok; закройте его окно или процесс.")


if __name__ == "__main__":
    raise SystemExit(main())
