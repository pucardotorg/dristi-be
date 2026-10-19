.PHONY: help build up down logs test lint format migrate superuser shell prod-up prod-down check-env

help:
	@echo "Available targets:"
	@echo "  build       Build the development Docker image"
	@echo "  up          Start the development stack"
	@echo "  down        Stop the development stack"
	@echo "  logs        Follow development logs"
	@echo "  test        Run pytest in the web container"
	@echo "  lint        Run ruff linter"
	@echo "  format      Run ruff formatter"
	@echo "  migrate     Run Django migrations in the web container"
	@echo "  superuser   Create a Django superuser"
	@echo "  shell       Open a Django shell"
	@echo "  prod-up     Start the production stack"
	@echo "  prod-down   Stop the production stack"

COMPOSE_DEV=docker compose --env-file .env -f docker/docker-compose.yml
COMPOSE_PROD=docker compose -f docker/docker-compose.prod.yml

check-env:
	@if [ ! -f .env ]; then \
		echo "Missing .env. Copy .env.example to .env." >&2; \
		exit 1; \
	fi

build: check-env
	$(COMPOSE_DEV) build

up: check-env
	$(COMPOSE_DEV) up -d

down: check-env
	$(COMPOSE_DEV) down

logs: check-env
	$(COMPOSE_DEV) logs -f

test: check-env
	$(COMPOSE_DEV) exec web pytest

lint:
	cd src && ruff check .

format:
	cd src && ruff format .

migrate: check-env
	$(COMPOSE_DEV) exec web python manage.py migrate

superuser: check-env
	$(COMPOSE_DEV) exec web python manage.py createsuperuser

shell: check-env
	$(COMPOSE_DEV) exec web python manage.py shell

prod-up:
	$(COMPOSE_PROD) up -d

prod-down:
	$(COMPOSE_PROD) down
