#!/bin/sh
set -eu

project_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$project_root"

for required_path in .venv/bin/python .venv/bin/alembic .env; do
  if [ ! -e "$required_path" ]; then
    printf 'Missing required local development file: %s\n' "$required_path" >&2
    exit 1
  fi
done

set -a
. ./.env
set +a

if [ "${APP_ENV:-development}" = "production" ]; then
  printf 'Refusing to create development seed data with APP_ENV=production.\n' >&2
  exit 1
fi

if [ -z "${DATABASE_URL:-}" ]; then
  export DATABASE_URL="sqlite+pysqlite:///$project_root/data/newsday-dev.db"
  export NEWSDAY_LOCAL_SQLITE=1
  printf 'DATABASE_URL is unset; using local SQLite database at data/newsday-dev.db.\n'
fi

if [ "${NEWSDAY_LOCAL_SQLITE:-}" = "1" ]; then
  .venv/bin/python -m app.dev_database_cli
else
  .venv/bin/alembic upgrade head
fi
exec .venv/bin/python -m app.dev_seed_cli
