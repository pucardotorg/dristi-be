# Dristi

A Django-based API project template using:

- **Django 5** + **Django REST Framework** for the API
- **Dramatiq** for background jobs (Redis broker)
- **Redis** for cache and the task queue
- **PostgreSQL** for the database
- **Docker & Docker Compose** for local development and production deployment
- **GitHub Actions** for CI, testing, and publishing Docker images to GHCR

## Quick start

1. **Clone and configure environment:**

   ```bash
   git clone https://github.com/pucardotorg/dristi-be.git
   cd dristi-be
   cp .env.example .env
   ```

2. **Start all services:**

   ```bash
   make up
   ```

   Or without Make:
   ```bash
   docker compose -f docker/docker-compose.yml up -d --build
   ```

   This starts: PostgreSQL, Redis, Django dev server, Dramatiq workers, Rustfs (S3-compatible storage), MailHog, Adminer, and monitoring dashboards.

3. **Create an admin user** (first time only):

   ```bash
   make superuser
   ```

   Or without Make:
   ```bash
   docker compose -f docker/docker-compose.yml exec web python manage.py createsuperuser
   ```

4. **Access the application:**

   | Service | URL | Notes |
   |---------|-----|-------|
   | 🌐 API Root | http://localhost:8000/api/v1/ | Main API endpoint |
   | 📚 Swagger UI | http://localhost:8000/api/docs/ | Interactive API docs |
   | 📋 OpenAPI Schema | http://localhost:8000/api/schema/ | API specification |
   | 🔐 Admin Panel | http://localhost:8000/admin/ | Use superuser from step 3 |
   | ✅ Health Check | http://localhost:8000/health/ | Service status |

5. **Development tools:**

   | Service | URL | Credentials | Purpose |
   |---------|-----|-------------|---------|
   | 📧 MailHog | http://localhost:8025 | - | View test emails |
   | 🗄️ Adminer | http://localhost:9090 | See `.env` postgres credentials | Database UI |
   | 📦 Rustfs Console | http://localhost:9001 | `admin` / `admin123` | S3 storage browser |
   | 🔄 Dramatiq Dashboard | http://localhost:8080 | - | Background jobs monitor |

## Common commands

The project includes a [Makefile](Makefile) with shortcuts for common tasks:

```bash
make up          # Start all services
make down        # Stop all services
make logs        # View logs (press Ctrl+C to exit)
make test        # Run tests
make superuser   # Create Django superuser
make shell       # Open Django shell
make migrate     # Run migrations (rarely needed - runs automatically on startup)
make lint        # Check code quality with ruff
make format      # Format code with ruff
```

Run `make help` to see all available commands.

## Documentation

- [docs/development.md](docs/development.md) — developer setup, running tests, linting, and background jobs.
- [docs/production.md](docs/production.md) — production deployment guide.
- [docs/architecture.md](docs/architecture.md) — system architecture and component overview.
- [agents.md](agents.md) — conventions and workflows for AI coding assistants.

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
├── docs/
│   ├── architecture.md
│   ├── development.md
│   └── production.md
├── .agents/
│   └── skills/
│       └── SKILL.md
```

## Environment variables

Copy `.env.example` to `.env` for local development. See `.env.prod.example` for production variables.

| Variable | Description | Example |
| --- | --- | --- |
| `DJANGO_SETTINGS_MODULE` | Settings module to use | `config.settings.local` |
| `SECRET_KEY` | Django secret key | long random string |
| `ALLOWED_HOSTS` | Comma-separated list of allowed hosts | `localhost,api.example.com` |
| `CSRF_TRUSTED_ORIGINS` | Comma-separated trusted origins for CSRF-protected requests | `https://api.example.com` |
| `CORS_ALLOWED_ORIGINS` | Comma-separated frontend origins allowed by CORS (local `:3000` is a common default; use your actual frontend port if different) | `https://app.example.com` |
| `CORS_ALLOW_CREDENTIALS` | Allow cross-origin cookies/credentials for browser API calls | `True` |
| `DATABASE_URL` | PostgreSQL connection URL | `postgres://user:pass@db:5432/dristi` |
| `CACHE_REDIS_URL` | Redis connection for Django cache | `redis://redis:6379/1` |
| `CACHE_ENABLED` | Enable or disable Django's cache backend. When disabled, Django uses the dummy cache backend. | `True` |
| `CACHE_KEY_PREFIX` | Prefix added to Django cache keys to namespace cached data. | `dristi-dev` |
| `CACHALOT_ENABLED` | Enable or disable django-cachalot automatic ORM query caching. Defaults to `CACHE_ENABLED`. | `True` |
| `CACHALOT_TIMEOUT` | Default lifetime of django-cachalot cached ORM query results, in seconds. | `120` |
| `DRAMATIQ_BROKER_URL` | Redis connection for Dramatiq | `redis://redis:6379/2` |
| `EMAIL_URL` | Email backend URL | `smtp://user:pass@smtp:587` |
| `MESSAGING_TEMPLATE_ENGINE` | Template engine for message rendering (`jinja2` or `mustache`) | `jinja2` |
| `MESSAGING_DUMMY_SMS_ENDPOINT` | HTTP endpoint for the dummy SMS backend | `http://httpbin:8080/post` |
| `MESSAGING_EMAIL_BACKEND` | Email backend mode (`smtp` or `django`) | `smtp` |
| `MESSAGING_EMAIL_HOST` | SMTP host for the messaging email backend | `smtp.example.com` |
| `MESSAGING_EMAIL_PORT` | SMTP port for the messaging email backend | `587` |
| `MESSAGING_EMAIL_HOST_USER` | SMTP username for the messaging email backend | `notifications@example.com` |
| `MESSAGING_EMAIL_HOST_PASSWORD` | SMTP password for the messaging email backend | secret |
| `MESSAGING_EMAIL_USE_TLS` | Enable TLS for the messaging SMTP backend | `True` |
| `MESSAGING_EMAIL_USE_SSL` | Enable SSL for the messaging SMTP backend | `False` |
| `MESSAGING_EMAIL_DEFAULT_FROM` | Default sender for messaging emails | `Dristi <notifications@example.com>` |
| `MESSAGING_EMAIL_TIMEOUT` | SMTP connection timeout in seconds | `30` |
| `MESSAGING_RETRY_DELAY_BASE` | Base retry delay in seconds (exponential backoff) | `60` |
| `MESSAGING_RETRY_DELAY_MAX` | Maximum retry delay in seconds | `3600` |
| `S3_API_ENDPOINT` | S3-compatible API endpoint for media uploads | `http://rustfs:9000` |
| `S3_BUCKET` | S3 bucket for media uploads | `dristi-media` |
| `S3_ACCESS_KEY` | S3 access key | `minioadmin` |
| `S3_SECRET_KEY` | S3 secret key | `minioadmin` |

## Services included

The Docker Compose stack includes:

- **PostgreSQL 16** - Primary database
- **Redis 7** - Cache and message broker for Dramatiq
- **Rustfs** - S3-compatible object storage for media files
- **MailHog** - Email testing (catches all outgoing emails)
- **Adminer** - Database management UI
- **Dramatiq Dashboard** - Background job monitoring
- **httpbin** - HTTP testing service (for dummy SMS backend)

## Docker dependency profiles

The Docker image supports selecting which requirements file to install via the `REQUIREMENTS_FILE` build arg:

- Local compose (`docker/docker-compose.yml`) builds with `requirements/local.txt` (includes dev tools)
- Production compose (`docker/docker-compose.prod.yml`) builds with `requirements/production.txt`
- GitHub image publishing (`.github/workflows/docker-publish.yml`) also builds with `requirements/production.txt`

If you run `docker build` directly without setting `REQUIREMENTS_FILE`, it defaults to `requirements/production.txt`.

## CI/CD

- `.github/workflows/ci.yml` runs linting, Django system checks, and pytest on every push/PR.
- `.github/workflows/docker-publish.yml` builds and pushes the Docker image to GitHub Container Registry on every push to `main`.
