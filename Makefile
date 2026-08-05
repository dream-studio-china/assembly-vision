.PHONY: sync lint format typecheck test check

sync:
	uv sync

lint:
	uv run ruff check .

format:
	uv run ruff format --check .

typecheck:
	uv run mypy .

test:
	uv run pytest

check: lint format typecheck test
