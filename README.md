# Dristi

A Django-based API project template using:

- **Django 5** + **Django REST Framework** for the API
- **Dramatiq** for background jobs (Redis broker)
- **Redis** for cache and the task queue
- **PostgreSQL** for the database
- **Docker & Docker Compose** for local development and production deployment
- **GitHub Actions** for CI, testing, and publishing Docker images to GHCR

## Quick start

1. Clone the repository and copy the example environment file:

   ```bash
   cp .env.example .env
   ```

2. Start the development stack with Docker Compose (the `web` service uses Django's runserver for hot-reload):

   ```bash
   docker compose -f docker/docker-compose.yml up -d --build
   ```

3. Create a superuser:

   ```bash
   docker compose -f docker/docker-compose.yml exec web python manage.py createsuperuser
   ```

4. Open the API in your browser:

   - API root: http://localhost:8000/api/v1/
   - Admin: http://localhost:8000/admin/
   - Health check: http://localhost:8000/health/

## Project structure

```
.
├── .github/workflows/      # GitHub Actions
├── docker/                 # Dockerfile, compose files, nginx config
├── src/                    # Django project source
│   ├── config/             # Django settings split by environment
│   ├── apps/
│   │   ├── core/           # Shared utilities, base model, example tasks
│   │   ├── users/          # Custom user model
│   │   └── api/            # DRF API views, serializers, routes
│   ├── requirements/
│   └── manage.py
├── .env.example
├── .env.prod.example
├── pyproject.toml
├── README.md
├── agents.md
├── architecture.md
└── skills/
```

## Environment variables

Copy `.env.example` to `.env` for local development. See `.env.prod.example` for production variables.

| Variable | Description | Example |
| --- | --- | --- |
| `DJANGO_SETTINGS_MODULE` | Settings module to use | `config.settings.local` |
| `SECRET_KEY` | Django secret key | long random string |
| `ALLOWED_HOSTS` | Comma-separated list of allowed hosts | `localhost,api.example.com` |
| `DATABASE_URL` | PostgreSQL connection URL | `postgres://user:pass@db:5432/dristi` |
| `REDIS_URL` | Redis connection for general use | `redis://redis:6379/0` |
| `CACHE_URL` | Redis connection for Django cache | `redis://redis:6379/1` |
| `DRAMATIQ_BROKER_URL` | Redis connection for Dramatiq | `redis://redis:6379/2` |
| `EMAIL_URL` | Email backend URL | `smtp://user:pass@smtp:587` |
| `SENTRY_DSN` | Optional Sentry DSN | `https://...@sentry.io/...` |

## Running locally without Docker

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

## Linting and formatting

This project uses [Ruff](https://docs.astral.sh/ruff/).

```bash
cd src
ruff check .
ruff format .
```

## Production deployment

1. Prepare production environment variables (see `.env.prod.example`) and export them on the target host. At minimum you need `SECRET_KEY`, `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS`, `DB_PASSWORD`, plus any email/Sentry variables you configure.
2. Deploy using the production compose file:

   ```bash
   docker compose -f docker/docker-compose.prod.yml up -d
   ```

3. Run migrations manually if needed:

   ```bash
   docker compose -f docker/docker-compose.prod.yml exec web python manage.py migrate
   ```

> The production image runs as a non-root user and is built to be stateless: static files are collected into a shared volume on startup and media uploads should be backed by the `media` volume (or an object-store such as S3).

Images are built and pushed to `ghcr.io/<owner>/dristi` automatically on every push to `main`.

## CI/CD

- `.github/workflows/ci.yml` runs linting, Django system checks, and pytest on every push/PR.
- `.github/workflows/docker-publish.yml` builds and pushes the Docker image to GitHub Container Registry on every push to `main`.
