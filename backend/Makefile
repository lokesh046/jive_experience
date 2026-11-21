# Simple commands. Run `make` to see them.
.DEFAULT_GOAL := help
.PHONY: help setup dev worker token test check db stop migrate migration fmt clean

PY := .venv/bin/python

help:  ## Show this list
	@grep -E '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  make %-10s %s\n", $$1, $$2}'

setup:  ## First time: install everything, start the database, create tables
	uv venv --python 3.12 .venv
	uv pip install --python $(PY) -e ".[dev]"
	docker compose up -d
	$(PY) -m alembic upgrade head

# Override when 8000 is taken:  make dev PORT=8001
PORT ?= 8000

dev:  ## Run the API (PORT=8000 by default, override with PORT=8001)
	$(PY) -m uvicorn app.main:app --reload --port $(PORT)

worker:  ## Run the background worker (outbox + sweeper)
	$(PY) -m app.worker

token:  ## Print an access token for Swagger:  make token EMAIL=you@gmail.com
	@$(PY) -m app.cli dev-token --email $(EMAIL)

test:  ## Run all tests
	$(PY) -m pytest

check:  ## Lint, type-check and test — what CI runs
	$(PY) -m ruff check app tests
	$(PY) -m ruff format --check app tests
	$(PY) -m mypy app
	$(PY) -m pytest

db:  ## Start PostgreSQL and Redis
	docker compose up -d

stop:  ## Stop them (data is kept)
	docker compose down

migrate:  ## Apply database migrations
	$(PY) -m alembic upgrade head

migration:  ## Create a migration:  make migration m="add events"
	$(PY) -m alembic revision --autogenerate -m "$(m)"

fmt:  ## Format and auto-fix
	$(PY) -m ruff format app tests
	$(PY) -m ruff check --fix app tests

clean:  ## Remove caches
	rm -rf .pytest_cache .ruff_cache .mypy_cache .coverage
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
