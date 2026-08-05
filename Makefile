.PHONY: sync lint typecheck test

sync:
	uv sync

lint:
	uv run ruff check apps

typecheck:
	uv run mypy apps/edge-service/src

test:
	uv run pytest
