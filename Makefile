.PHONY: sync lint typecheck test

sync:
	uv sync

lint:
	uv run ruff check apps

typecheck:
	uv run mypy apps/edge-service/src packages/python/domain/src packages/python/vision-core/src training/src

test:
	uv run pytest
