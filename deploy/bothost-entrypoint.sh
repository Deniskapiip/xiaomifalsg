#!/bin/sh
# Bothost entrypoint: один процесс, миграции и секреты при каждом старте.
# Bothost передаёт DOMAIN и токен бота через переменные окружения;
# постоянный диск платформы — /app/data.
set -eu

DATA_DIR="${DATA_DIR:-/app/data}"
mkdir -p "$DATA_DIR"
export DATA_DIR

# 1. Хостинг-контейнер обязан слушать 0.0.0.0 на порту платформы.
# Принудительно перекрываем значения из локального .env (HOST=127.0.0.1, PORT=8000),
# иначе Bothost получает 502: приложение слушает только внутри контейнера.
export HOST=0.0.0.0
: "${PORT:=8000}"
export PORT

# 2. На Bothost всегда есть HTTPS-домен в DOMAIN. Он — единственный правильный адрес
# Mini App. Старый ngrok/cloudflare-адрес из локального .env игнорируем, иначе
# Telegram открывает мёртвый туннель (ERR_NGROK_3200).
if [ -n "${DOMAIN:-}" ]; then
  export WEBAPP_URL="https://${DOMAIN}"
  export BOT_MODE=webhook
fi
export BOT_MODE="${BOT_MODE:-webhook}"
export ENV=production
# Публичный домен не должен включать локальный dev-вход.
export DEV_MODE=false

# 3. SQLite — только на постоянном диске Bothost. PostgreSQL сохраняется, если задан явно.
case "${DATABASE_URL:-}" in
  ""|sqlite*) export DATABASE_URL="sqlite+aiosqlite:///$DATA_DIR/taoji.db" ;;
esac

# 4. Секреты. Валидные значения из панели используются как есть. Пустые или
# невалидные (например, скопированные из локального .env) заменяются сгенерированными
# и сохраняются на постоянном диске, чтобы пережить перезапуск контейнера.
# Значения никогда не печатаются в лог.
SECRETS_FILE="$DATA_DIR/.taoji-secrets"
SECRETS_ENV="/tmp/taoji-secrets.sh"
python - "$SECRETS_FILE" "$SECRETS_ENV" <<'PY'
import os
import pathlib
import re
import secrets
import shlex
import sys

secrets_path = pathlib.Path(sys.argv[1])
env_path = pathlib.Path(sys.argv[2])

saved = {}
if secrets_path.is_file():
    for line in secrets_path.read_text(encoding="utf-8").splitlines():
        key, separator, value = line.partition("=")
        if separator:
            saved[key.strip()] = value.strip()


def webhook_ok(value):
    return bool(re.fullmatch(r"[A-Za-z0-9_-]{32,128}", value or ""))


def jwt_ok(value):
    return bool(value) and len(value.encode()) >= 32 and not value.lower().startswith("change")


def token(length):
    return secrets.token_urlsafe(length)


resolved = {}
for name, check, generate in (
    ("JWT_SECRET", jwt_ok, lambda: token(48)),
    ("WEBHOOK_PATH_SECRET", webhook_ok, lambda: token(32)),
    ("WEBHOOK_SECRET_TOKEN", webhook_ok, lambda: token(32)),
):
    current = os.environ.get(name, "")
    if check(current):
        resolved[name] = current
    elif check(saved.get(name, "")):
        resolved[name] = saved[name]
    else:
        resolved[name] = generate()

changed = [f"{name}={value}" for name, value in resolved.items() if os.environ.get(name) != value]
if changed:
    secrets_path.write_text("\n".join(changed) + "\n", encoding="utf-8")
    secrets_path.chmod(0o600)

with env_path.open("w", encoding="utf-8") as handle:
    for name, value in resolved.items():
        handle.write(f"export {name}={shlex.quote(value)}\n")
PY
. "$SECRETS_ENV"
rm -f "$SECRETS_ENV"

# Диагностика без секретов: помогает сверить порт с настройкой «внутренний порт» в панели.
echo "[bothost] HOST=${HOST} PORT=${PORT} WEBAPP_URL=${WEBAPP_URL:-unset} BOT_MODE=${BOT_MODE} ENV=${ENV} DATABASE_URL=${DATABASE_URL} secrets=${SECRETS_FILE}"

cd /srv/taoji-cargo/backend

python -m alembic upgrade head
python -m app.seed

exec python -m app.main
