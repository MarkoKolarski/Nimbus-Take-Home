.PHONY: up test migrate reset

up:
	docker compose up --build

test:
	docker compose exec -T api pytest -q

migrate:
	docker compose exec api alembic upgrade head

reset:
	docker compose down -v && docker compose up --build
