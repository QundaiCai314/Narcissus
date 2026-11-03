#!/bin/sh
set -eu
dest=${1:?Usage: sh scripts/backup.sh backups/DATE}
mkdir -p "$dest"
chmod 700 "$dest"
dest=$(cd "$dest" && pwd)
docker compose stop web api worker beat
trap 'docker compose start api worker beat web' EXIT
docker compose exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > "$dest/database.dump"
docker compose run --rm --no-deps -v "$dest:/backup" --user root api python -m app.backup backup /backup/objects.tar.gz
printf '%s\n' 'Backup complete. Keep .env separately in encrypted storage.'
