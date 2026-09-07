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

export FRONTEND_DEV_MODE=true
export VITE_DEV_SERVER_URL="${VITE_DEV_SERVER_URL:-http://127.0.0.1:5173}"

.venv/bin/alembic upgrade head
exec .venv/bin/uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
