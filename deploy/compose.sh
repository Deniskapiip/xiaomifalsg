#!/bin/sh
set -eu
TAOJI_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
exec docker compose --env-file "$TAOJI_ROOT/.env.production" -f "$TAOJI_ROOT/deploy/docker-compose.yml" "$@"
