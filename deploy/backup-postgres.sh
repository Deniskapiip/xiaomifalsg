#!/bin/sh
set -eu
umask 077
TAOJI_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
TAOJI_BACKUPS="$TAOJI_ROOT/backups/postgres"
mkdir -p "$TAOJI_BACKUPS"
exec 9>"$TAOJI_BACKUPS/.backup.lock"
flock -n 9 || { echo "Другая копия ещё выполняется." >&2; exit 1; }
TAOJI_TEMP=$(mktemp "$TAOJI_BACKUPS/.partial-XXXXXX")
trap 'rm -f "$TAOJI_TEMP"' EXIT HUP INT TERM
sh "$TAOJI_ROOT/deploy/compose.sh" exec -T postgres sh -c 'PGPASSWORD="$POSTGRES_PASSWORD" exec pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom --no-owner --no-acl' > "$TAOJI_TEMP"
[ -s "$TAOJI_TEMP" ]
sh "$TAOJI_ROOT/deploy/compose.sh" exec -T postgres pg_restore --list < "$TAOJI_TEMP" > /dev/null
TAOJI_FILENAME="taoji-$(date -u +%Y%m%d-%H%M%S)-$(basename "$TAOJI_TEMP" | cut -c10-).dump"
mv "$TAOJI_TEMP" "$TAOJI_BACKUPS/$TAOJI_FILENAME"
TAOJI_INDEX=0
for TAOJI_FILE in $(find "$TAOJI_BACKUPS" -maxdepth 1 -regextype posix-extended -type f -regex '.*/taoji-[0-9]{8}-[0-9]{6}-[A-Za-z0-9]{6}\.dump' -printf '%f\n' | LC_ALL=C sort -r); do
    TAOJI_INDEX=$((TAOJI_INDEX + 1))
    if [ "$TAOJI_INDEX" -gt 14 ]; then rm -f "$TAOJI_BACKUPS/$TAOJI_FILE"; fi
done
echo "Копия PostgreSQL сохранена и проверена: $TAOJI_FILENAME"
