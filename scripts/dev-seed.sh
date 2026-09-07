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

.venv/bin/alembic upgrade head
exec .venv/bin/python -m app.dev_seed_cli
