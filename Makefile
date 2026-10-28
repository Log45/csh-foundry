.PHONY: sync db migrate dev test lint typecheck
sync:
	uv sync --frozen
db:
	docker compose --env-file .env -f infrastructure/compose.yaml up -d --wait postgres
migrate:
	uv run alembic upgrade head
dev:
	uv run uvicorn ontology_platform.main:create_app --factory --reload --host 127.0.0.1
test:
	uv run pytest -ra
lint:
	uv run ruff check .
	uv run ruff format --check .
typecheck:
	uv run mypy
