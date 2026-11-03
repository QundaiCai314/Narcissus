#!/bin/sh
set -eu
src=${1:?Usage: sh scripts/restore.sh backups/DATE}
src=$(cd "$src" && pwd)
test -s "$src/database.dump"
test -s "$src/objects.tar.gz"
printf '%s\n' 'This replaces the configured project database. Type RESTORE to continue:'
read -r confirmation
test "$confirmation" = RESTORE
docker compose stop web api worker beat
docker compose up -d db redis minio
docker compose exec -T db sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists --no-owner --exit-on-error' < "$src/database.dump"
docker compose run --rm --no-deps -v "$src:/backup:ro" --user root api python -m app.backup restore /backup/objects.tar.gz
docker compose run --rm migrate
docker compose up -d api worker beat web
