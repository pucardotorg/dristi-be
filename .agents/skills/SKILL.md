# Dristi Skill

A skill for working with the Dristi Django + DRF + Dramatiq codebase.

## When to use

Use this skill when asked to:

- Add or modify Django apps, models, views, serializers, or admin configurations.
- Create or update Dramatiq background tasks.
- Change Docker, Docker Compose, or CI/CD configuration.
- Update settings, environment variables, or deployment documentation.

## Project map

- `src/config/settings/` — environment-specific Django settings.
- `src/apps/` — Django apps (`core`, `users`, `api`, plus future apps).
- `src/apps/core/models.py` — `BaseModel` to inherit from.
- `src/apps/core/tasks.py` — example Dramatiq actors.
- `docker/` — Dockerfile, compose files, entrypoint, nginx config.
- `.github/workflows/` — CI and Docker publishing actions.

## Workflow

1. Read `agents.md` and `docs/architecture.md` if you are making structural changes.
2. Make focused changes that preserve the existing app structure and style.
3. Update `.env.example` / `.env.prod.example`, `README.md`, and relevant docs under `docs/` when adding environment variables.
4. Run tests and linting before finishing:
   - `cd src && pytest`
   - `cd src && ruff check . && ruff format .`
5. For Docker-related changes, verify the image builds locally when possible:
   - `docker build -f docker/Dockerfile .`

## Constraints

- Do not commit `.env` files or real secrets.
- Keep business logic out of views when possible; prefer services, model methods, or Dramatiq actors.
- Use `apps.<appname>` as the full Python app path everywhere.
- Maintain test coverage for new features and bug fixes.
