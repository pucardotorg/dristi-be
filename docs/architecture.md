# Architecture

## Overview

Dristi is a containerized Django API platform. It separates synchronous web traffic from asynchronous background work, uses Redis as both cache and message broker, and persists data in PostgreSQL.

## Components

```
┌─────────────┐      ┌─────────────┐      ┌─────────────────┐
│   Client    │──────▶│    Nginx    │──────▶│  Django (Gunicorn)
│  (Browser)  │      │   (reverse  │      │      Web        │
└─────────────┘      │   proxy)    │      └─────────────────┘
                     └─────────────┘                │
                            │                       │
                            ▼                       ▼
                     ┌─────────────┐      ┌─────────────────┐
                     │  Static /   │      │   PostgreSQL    │
                     │  Media vol  │      │   (persistent)  │
                     └─────────────┘      └─────────────────┘
                                                   ▲
                                                   │
┌─────────────────┐      ┌─────────────┐          │
│ Dramatiq Worker │◀─────│    Redis    │──────────┘
│   (background)  │      │ cache/queue │
└─────────────────┘      └─────────────┘
```

## Django application layout

### `config`

The `config` package is the Django project configuration. Settings are split by environment:

- `base.py` — shared settings (installed apps, middleware, DRF, cache, Dramatiq broker, logging).
- `local.py` — development settings; loads `.env`, enables debug toolbar, browsable API.
- `test.py` — CI settings; uses an in-memory SQLite database and the Dramatiq stub broker.
- `production.py` — production settings; security hardening, optional Sentry integration.

### `apps.core`

Shared foundation:

- `BaseModel` with UUID primary key and timestamps.
- Example Dramatiq actors (`send_welcome_email`, `process_long_running_job`).
- Placeholder for cross-cutting utilities.

### `apps.users`

Custom user model using `email` as the primary identifier. Admin is registered in `admin.py`.

### `apps.api`

DRF API layer:

- `urls.py` — routes using `DefaultRouter`.
- `views.py` — viewsets and function-based views.
- `serializers.py` — DRF serializers.
- `tests.py` — API tests using `APITestCase`.

## Data flow

### HTTP request

1. Nginx terminates TLS and forwards HTTP requests to the Gunicorn/Django web service.
2. Django middleware handles CORS, sessions, CSRF, and security headers.
3. DRF routes the request to the appropriate view/serializer.
4. Views interact with models backed by PostgreSQL.
5. Static files are served by WhiteNoise (or Nginx in production); media files are served by Nginx.

### Background job

1. Application code calls `task.send(...)` which pushes a message to Redis via Dramatiq.
2. The `worker` service consumes messages from Redis.
3. Actors execute business logic; database connections are managed by `django_dramatiq` middleware.
4. Results (if requested) are stored back in Redis or ignored for fire-and-forget tasks.

### Caching

Django’s cache framework is configured to use a dedicated Redis database. Views and tasks can use `django.core.cache` for low-latency reads.

## Scalability and operations

- **Web tier:** horizontally scalable by increasing Gunicorn workers or running multiple `web` containers behind a load balancer.
- **Worker tier:** horizontally scalable by adding more `worker` containers; Dramatiq uses Redis as the shared broker.
- **Database:** use PostgreSQL connection pooling (e.g. PgBouncer) and read replicas at scale.
- **Observability:** structured logging to stdout and health check endpoints (`/health/`, `/api/v1/health/`).

## Security

- Production settings enforce HTTPS-only cookies, HSTS, secure redirects, and strict framing.
- Secrets are supplied via environment variables or Docker secrets, never committed.
- The Docker image runs as a non-root user (`appuser`).
- GitHub Actions build provenance attestations are generated for every image pushed to GHCR.
