# Developer Setup Guide

This document explains how to set up and run Dristi for local development.

## Docker-based development

The easiest way to develop is with the provided Docker Compose file. It starts PostgreSQL, Redis, the Django dev server, and Dramatiq workers.

```bash
# Copy environment variables
cp .env.example .env

# Build and start all services
docker compose -f docker/docker-compose.yml up -d --build

# View logs
docker compose -f docker/docker-compose.yml logs -f

# Run a management command
docker compose -f docker/docker-compose.yml exec web python manage.py <command>
```

Common management commands:

```bash
# Run migrations
docker compose -f docker/docker-compose.yml exec web python manage.py migrate

# Create a superuser
docker compose -f docker/docker-compose.yml exec web python manage.py createsuperuser

# Open a Django shell
docker compose -f docker/docker-compose.yml exec web python manage.py shell

# Make migrations after model changes
docker compose -f docker/docker-compose.yml exec web python manage.py makemigrations
```

Once the stack is running:

- API root: http://localhost:8000/api/v1/
- Admin: http://localhost:8000/admin/
- Health check: http://localhost:8000/health/

## Local development without Docker

1. Create a virtual environment and install dependencies:

   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -r src/requirements/local.txt
   ```

2. Copy `.env.example` to `.env` and start PostgreSQL + Redis locally.

3. Run migrations and start the dev server:

   ```bash
   cd src
   python manage.py migrate
   python manage.py runserver
   ```

## Running tests

Tests use pytest with the `config.settings.test` settings module (SQLite in-memory by default).

```bash
cd src
pytest
```

To run with coverage:

```bash
pytest --cov --cov-report=html
```

## Linting and formatting

This project uses [Ruff](https://docs.astral.sh/ruff/).

```bash
cd src
ruff check .
ruff format .
```

## Background jobs

Dramatiq workers run as a separate `worker` service. Example tasks are defined in `src/apps/core/tasks.py`.

Enqueue a task from code:

```python
from apps.core.tasks import send_welcome_email

send_welcome_email.send("user@example.com")
```

Monitor the worker logs:

```bash
docker compose -f docker/docker-compose.yml logs -f worker
```
