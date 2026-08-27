.PHONY: help build up down logs test lint format migrate superuser shell prod-up prod-down

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

COMPOSE_DEV=docker compose -f docker/docker-compose.yml
COMPOSE_PROD=docker compose -f docker/docker-compose.prod.yml

build:
	$(COMPOSE_DEV) build

up:
	$(COMPOSE_DEV) up -d

down:
	$(COMPOSE_DEV) down

logs:
	$(COMPOSE_DEV) logs -f

test:
	$(COMPOSE_DEV) exec web pytest

lint:
	cd src && ruff check .

format:
	cd src && ruff format .

migrate:
	$(COMPOSE_DEV) exec web python manage.py migrate

superuser:
	$(COMPOSE_DEV) exec web python manage.py createsuperuser

shell:
	$(COMPOSE_DEV) exec web python manage.py shell

prod-up:
	$(COMPOSE_PROD) up -d

prod-down:
	$(COMPOSE_PROD) down
