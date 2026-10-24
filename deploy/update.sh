#!/bin/sh
set -eu
TAOJI_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
# Run after replacing source files or a reviewed git pull. Never git-reset data.
exec 9>"$TAOJI_ROOT/.taoji-update.lock"
flock -n 9 || { echo "Обновление уже выполняется." >&2; exit 1; }
sh "$TAOJI_ROOT/deploy/backup-postgres.sh"
sh "$TAOJI_ROOT/deploy/compose.sh" build app
sh "$TAOJI_ROOT/deploy/compose.sh" stop app
sh "$TAOJI_ROOT/deploy/compose.sh" run --rm --no-deps app python -m alembic upgrade head
sh "$TAOJI_ROOT/deploy/compose.sh" up -d --no-deps --force-recreate --wait --wait-timeout 90 app
sh "$TAOJI_ROOT/deploy/compose.sh" ps
echo "Обновление завершено. Проверьте HTTPS /api/health, webhook и заказ в Telegram."
