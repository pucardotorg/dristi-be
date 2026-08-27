# Agent Instructions

This document helps AI coding assistants work effectively inside the **Dristi** Django repository.

## Project conventions

- **Python version:** 3.11+
- **Code style:** [Ruff](https://docs.astral.sh/ruff/) (replaces flake8, black, isort)
- **Django settings:** split by environment under `src/config/settings/`
  - `local.py` — development, reads `.env`
  - `test.py` — CI / unit tests, uses SQLite by default
  - `production.py` — production, relies on injected environment variables
- **Apps:** live under `src/apps/<app>/`. Always use the full Python path (`apps.<app>`) in `INSTALLED_APPS`, imports, and `AppConfig.name`.
- **Models:** inherit from `apps.core.models.BaseModel` unless you have a strong reason not to.
- **Background jobs:** use Dramatiq. Define actors in `<app>/tasks.py` and import them where needed.
- **APIs:** use Django REST Framework. Keep views thin; business logic belongs in services / models / tasks.

## Before committing changes

1. Run the test suite:

   ```bash
   cd src && DJANGO_SETTINGS_MODULE=config.settings.test pytest
   ```

2. Run the linter and formatter:

   ```bash
   cd src && ruff check . && ruff format .
   ```

3. Run Django system checks for the target environment:

   ```bash
   cd src && python manage.py check
   ```

## Adding a new Django app

1. Create the package under `src/apps/<appname>/`.
2. Add `apps/<appname>/apps.py` with `name = "apps.<appname>"`.
3. Add the app to `src/config/settings/base.py` in `INSTALLED_APPS`.
4. Create tests in `<app>/tests.py` or a `tests/` package.
5. Register models in `<app>/admin.py` if they need admin access.

## Adding a new environment variable

1. Add it to `.env.example` with a sensible default/placeholder.
2. Add it to `.env.prod.example` if it is required in production.
3. Read it in the appropriate settings module (`base.py` for shared, `production.py` for prod-only overrides).
4. Document it in `README.md`.

## Adding a Dramatiq task

1. Create or edit `<app>/tasks.py`.
2. Use the `@actor` decorator from `dramatiq`.
3. Keep actors idempotent and transactional when possible.
4. Add a test that enqueues the message using the stub broker (`config.settings.test`).

## Docker notes

- The `web` service runs Gunicorn and executes migrations + static collection on startup.
- The `worker` service runs Dramatiq workers.
- Do not commit `.env` files. The `.env.example` files are the source of truth for local development.
- The production compose file expects exported environment variables; do not bake secrets into the image.

## Common commands

```bash
# Build and start the full dev stack
docker compose -f docker/docker-compose.yml up -d --build

# Run a management command in the web container
docker compose -f docker/docker-compose.yml exec web python manage.py <command>

# View logs
docker compose -f docker/docker-compose.yml logs -f

# Run tests in the web container
docker compose -f docker/docker-compose.yml exec web pytest
```
