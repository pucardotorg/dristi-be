.PHONY: help build up down logs test lint format migrate superuser shell prod-up prod-down check-env prepare-volumes

# Container engine: auto-detected (podman if installed, otherwise docker).
# Override per invocation, e.g. `make up CONTAINER_ENGINE=docker`, or export it.
CONTAINER_ENGINE ?= $(shell command -v podman >/dev/null 2>&1 && echo podman || echo docker)

COMPOSE_DEV=$(CONTAINER_ENGINE) compose --env-file .env -f docker/docker-compose.yml
COMPOSE_PROD=$(CONTAINER_ENGINE) compose -f docker/docker-compose.prod.yml

# Recovery for a podman-compose quirk: containers whose depends_on chain
# passes through an already-exited one-shot service (rustfs_perms,
# rustfs-init) are left in "Created" ("not found in input list"). Starting
# every non-running container of the stack in a single `podman start` call
# lets podman resolve the --requires graph. The config_files label matches
# the compose file exactly as passed to -f from the repo root. Not needed on
# docker, where a failed `compose up` should simply fail.
recover-stuck = \
	if [ "$(CONTAINER_ENGINE)" = "podman" ]; then \
		echo "compose up left containers behind; starting them (podman-compose dependency-graph workaround)"; \
		$(CONTAINER_ENGINE) ps -a \
			--filter label=com.docker.compose.project.config_files=$(1) \
			--filter status=created --filter status=exited \
			--format '{{.Names}}' | xargs -r $(CONTAINER_ENGINE) start; \
	else \
		exit 1; \
	fi

help:
	@echo "Available targets:"
	@echo "  build       Build the development image"
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
	@echo ""
	@echo "Container engine: $(CONTAINER_ENGINE) (override with CONTAINER_ENGINE=docker)"

check-env:
	@if [ ! -f .env ]; then \
		echo "Missing .env. Copy .env.example to .env." >&2; \
		exit 1; \
	fi

# Rootless podman cannot create the rustfs bind-mount sources once
# rustfs_volumes is owned by the container user (10001), so create and chown
# them from inside the user namespace. Docker's daemon creates missing bind
# sources itself and the rustfs_perms one-shot then chowns them, so there is
# nothing to fix beyond a best-effort mkdir.
prepare-volumes:
ifeq ($(CONTAINER_ENGINE),podman)
	podman unshare sh -c 'mkdir -p docker/rustfs_volumes/data docker/rustfs_volumes/logs && chown -R 10001:10001 docker/rustfs_volumes'
else
	@mkdir -p docker/rustfs_volumes/data docker/rustfs_volumes/logs 2>/dev/null || true
endif

build: check-env
	$(COMPOSE_DEV) build

up: check-env prepare-volumes
	@$(COMPOSE_DEV) up -d || { $(call recover-stuck,docker/docker-compose.yml); }

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
	@$(COMPOSE_PROD) up -d || { $(call recover-stuck,docker/docker-compose.prod.yml); }

prod-down:
	$(COMPOSE_PROD) down
