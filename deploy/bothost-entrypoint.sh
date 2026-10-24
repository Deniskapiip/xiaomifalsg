#!/bin/sh
# Bothost entrypoint: один процесс, миграции при каждом старте.
# Bothost передаёт PORT, DOMAIN и токен бота через переменные окружения;
# постоянный диск платформы — /app/data.
set -eu

DATA_DIR="${DATA_DIR:-/app/data}"
mkdir -p "$DATA_DIR"

# Хостинг-контейнер обязан слушать 0.0.0.0 на порту платформы.
# Принудительно перекрываем значения из локального .env (HOST=127.0.0.1, PORT=8000),
# иначе Bothost получает 502: приложение слушает только внутри контейнера.
export HOST=0.0.0.0
: "${PORT:=8000}"
export PORT

# На Bothost всегда есть HTTPS-домен в DOMAIN. Он — единственный правильный адрес
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

# SQLite — только на постоянном диске Bothost. PostgreSQL сохраняется, если задан явно.
case "${DATABASE_URL:-}" in
  ""|sqlite*) export DATABASE_URL="sqlite+aiosqlite:///$DATA_DIR/taoji.db" ;;
esac

# Диагностика без секретов: помогает сверить порт с настройкой «внутренний порт» в панели.
echo "[bothost] HOST=${HOST} PORT=${PORT} WEBAPP_URL=${WEBAPP_URL:-unset} BOT_MODE=${BOT_MODE} ENV=${ENV} DATABASE_URL=${DATABASE_URL}"

cd /srv/taoji-cargo/backend

python -m alembic upgrade head
python -m app.seed

exec python -m app.main
