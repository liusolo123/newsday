PYTHON ?= .venv/bin/python
RUFF ?= .venv/bin/ruff

.PHONY: install install-dev deps test lint syntax frontend-build check dev dev-seed

install:
	uv pip sync --python $(PYTHON) requirements.lock

install-dev:
	uv pip sync --python $(PYTHON) requirements-dev.lock

deps:
	$(PYTHON) -m pip check

test:
	$(PYTHON) -m unittest discover -s tests -q

lint:
	$(RUFF) check app finnews tests

syntax:
	$(PYTHON) -m compileall -q app alembic finnews tests

frontend-build:
	npm run build

check: deps lint syntax test frontend-build

dev:
	npm run dev

dev-seed:
	npm run dev:seed
