#!/bin/sh
set -eu

project_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$project_root"

for required_path in .venv/bin/python .venv/bin/alembic .venv/bin/uvicorn .env; do
  if [ ! -e "$required_path" ]; then
    printf 'Missing required local development file: %s\n' "$required_path" >&2
    exit 1
  fi
done

set -a
. ./.env
set +a

if [ "${APP_ENV:-development}" = "production" ]; then
  printf 'Refusing to start the local development server with APP_ENV=production.\n' >&2
  exit 1
fi

if [ -z "${DATABASE_URL:-}" ]; then
  export DATABASE_URL="sqlite+pysqlite:///$project_root/data/newsday-dev.db"
  export NEWSDAY_LOCAL_SQLITE=1
  printf 'DATABASE_URL is unset; using local SQLite database at data/newsday-dev.db.\n'
fi

export FRONTEND_DEV_MODE=true
export VITE_DEV_SERVER_URL="${VITE_DEV_SERVER_URL:-http://127.0.0.1:5173}"

if [ "${NEWSDAY_LOCAL_SQLITE:-}" = "1" ]; then
  .venv/bin/python -m app.dev_database_cli
else
  .venv/bin/alembic upgrade head
fi
exec .venv/bin/uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
