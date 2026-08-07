.PHONY: sync lint format typecheck test check web-check web-install

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

web-install:
	pnpm install

web-check:
	pnpm -r build
	pnpm -r lint
	pnpm -r test
	cd apps/edge-web && pnpm test:e2e

check: lint format typecheck test web-check
