#!/bin/sh
# Bothost entrypoint: один процесс, миграции при каждом старте.
# Bothost передаёт PORT, DOMAIN и токен бота через переменные окружения;
# постоянный диск платформы — /app/data.
set -eu

DATA_DIR="${DATA_DIR:-/app/data}"
mkdir -p "$DATA_DIR"

# По умолчанию база лежит на постоянном диске Bothost.
# Если DATABASE_URL задан в панели (например, PostgreSQL), он имеет приоритет.
if [ -z "${DATABASE_URL:-}" ]; then
  export DATABASE_URL="sqlite+aiosqlite:///$DATA_DIR/taoji.db"
fi

# Bothost выдаёт домен в DOMAIN; WEBAPP_URL можно не заполнять вручную.
if [ -z "${WEBAPP_URL:-}" ] && [ -n "${DOMAIN:-}" ]; then
  export WEBAPP_URL="https://${DOMAIN}"
fi

# На хостинге с HTTPS-доменом webhook — правильный режим по умолчанию.
export ENV="${ENV:-production}"
export BOT_MODE="${BOT_MODE:-webhook}"

cd /srv/taoji-cargo/backend

python -m alembic upgrade head
python -m app.seed

exec python -m app.main
