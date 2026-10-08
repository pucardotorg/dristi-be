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
   | API Root | http://localhost:8000/api/v1/ | Main API endpoint |
   | Swagger UI | http://localhost:8000/api/docs/ | Interactive API docs |
   | OpenAPI Schema | http://localhost:8000/api/schema/ | API specification |
   | Admin Panel | http://localhost:8000/admin/ | Use superuser from step 3 |
   | Health Check | http://localhost:8000/health/ | Service status |

5. **Development tools:**

   | Service | URL | Credentials | Purpose |
   |---------|-----|-------------|---------|
   | MailHog | http://localhost:8025 | - | View test emails |
   | Adminer | http://localhost:9090 | See `.env` postgres credentials | Database UI |
   | Rustfs Console | http://localhost:9001 | `admin` / `admin123` | S3 storage browser |
   | Dramatiq Dashboard | http://localhost:8080 | - | Background jobs monitor |

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

## Pre-commit hooks

The repo uses [pre-commit](https://pre-commit.com/) to run Ruff (lint with auto-fix, then format) automatically on every `git commit`. The hooks are defined in [.pre-commit-config.yaml](.pre-commit-config.yaml).

One-time setup after cloning:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r src/requirements/local.txt   # includes pre-commit
pre-commit install                          # installs the git hook
```

From then on, each commit runs Ruff on the staged files. If Ruff fixes or reformats anything, the commit is stopped so you can review the changes. Run `git add` and commit again.


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
| `MESSAGING_TASK_TIME_LIMIT` | Dramatiq time limit for `send_message` in milliseconds; must exceed any gateway timeout | `600000` |
| `CDAC_SMS_URL` | CDAC gateway endpoint (required when the CDAC backend is active) | `https://msdgweb.mgov.gov.in/esms/sendsmsrequestDLT` |
| `CDAC_SMS_USERNAME` | CDAC username | `dristi` |
| `CDAC_SMS_PASSWORD` | CDAC password; hashed (SHA-1) before transmission, never sent in plaintext | secret |
| `CDAC_SMS_SENDER_ID` | Registered DLT sender ID | `DRISTI` |
| `CDAC_SMS_SECURE_KEY` | Signature key for the SHA-512 request key; never logged | secret |
| `CDAC_SMS_TEMPLATE_ID` | Fallback DLT template ID when the template has none | `1234567890` |
| `CDAC_SMS_MOBILE_PREFIX` | Prefix applied to the recipient number at request time | `91` |
| `CDAC_SMS_ENABLED` | Master kill-switch; `False` marks messages `filtered` without contacting the gateway | `True` |
| `CDAC_SMS_TIMEOUT` | Gateway connect/read timeout in seconds | `30` |
| `CDAC_SMS_VERIFY_SSL` | Verify gateway TLS certificates (rejected in production when `False`) | `True` |
| `CDAC_SMS_SUCCESS_CODES` | Allowed HTTP statuses | `200,201,202` |
| `CDAC_SMS_ERROR_CODES` | Disallowed HTTP statuses | empty |
| `CDAC_SMS_VERIFY_RESPONSE` | Enable the response body substring check | `False` |
| `CDAC_SMS_VERIFY_RESPONSE_CONTAINS` | Literal the gateway body must contain | `MsgID` |
| `CDAC_SMS_PRINT_RESPONSE` | Log the gateway status and body (secrets redacted) | `True` |
| `CDAC_SMS_WHITELIST_NUMBERS` | Allowed recipient patterns (`X` = one digit, `*` = remaining digits); empty allows all | `98765XXXXX` |
| `CDAC_SMS_BLACKLIST_NUMBERS` | Suppressed recipient patterns | `9876*` |
| `CDAC_SMS_USE_DEFAULT_NUMBER` | Redirect every SMS to `CDAC_SMS_DEFAULT_NUMBER` (rejected in production) | `False` |
| `CDAC_SMS_DEFAULT_NUMBER` | 10-digit test recipient used by the override | `9000000000` |
| `S3_API_ENDPOINT` | S3-compatible API endpoint for media uploads | `http://rustfs:9000` |
| `S3_BUCKET` | S3 bucket for media uploads | `dristi-media` |
| `S3_ACCESS_KEY` | S3 access key | `minioadmin` |
| `S3_SECRET_KEY` | S3 secret key | `minioadmin` |
| `FILE_MAX_SIZE_BYTES` | Largest single file `apps.files` will accept | `10485760` |
| `FILE_MAX_COUNT_PER_UPLOAD` | Most files allowed in one `upload_file` call | `10` |
| `FILE_MAX_READ_BYTES` | Largest file `get_file_content()` will open into memory. Defaults to `FILE_MAX_SIZE_BYTES`. | `10485760` |

## Services included

The Docker Compose stack includes:

- **PostgreSQL 16** - Primary database
- **Redis 7** - Cache and message broker for Dramatiq
- **Rustfs** - S3-compatible object storage for media files
- **MailHog** - Email testing (catches all outgoing emails)
- **Adminer** - Database management UI
- **Dramatiq Dashboard** - Background job monitoring
- **httpbin** - HTTP testing service (for dummy SMS backend)
| `ESIGN_PROVIDER` | Dotted path of the active eSign provider. The mock provider needs no C-DAC credentials and is the local/CI default. | `addon.cdac_esign.provider.CDACESignProvider` |
| `ESIGN_ENABLED` | Kill switch; initiation returns 503 when disabled | `True` |
| `ESIGN_TRANSACTION_TTL` | Seconds a transaction waits for the ESP callback | `900` |
| `ESIGN_CALLBACK_GRACE_PERIOD` | Seconds a late callback is still accepted | `300` |
| `ESIGN_SIGNING_STUCK_TIMEOUT` | Seconds before a row stuck in `SIGNING` is reconciled | `300` |
| `ESIGN_MAX_ATTEMPTS` | Maximum signing attempts per document | `3` |
| `ESIGN_PLACEHOLDER_RETENTION` | Days a prepared (placeholder) PDF is kept after a transaction ends | `7` |
| `ESIGN_UI_REDIRECT_URL` | Server-side redirect target the ESP callback sends the browser to. Required and `https://` in production. | `https://app.example.com/esign/return` |
| `ESIGN_CALLBACK_THROTTLE_RATE` | Per-IP throttle for the public callback; blank disables it | `60/min` |
| `ESIGN_CALLBACK_MAX_BODY_BYTES` | Largest callback body accepted | `262144` |
| `ESIGN_SYSTEM_ACTOR_ID` | Actor recorded for callback-leg uploads when a transaction has no signer | `system` |
| `CDAC_ESIGN_URL` | C-DAC ESP endpoint the browser posts the signing form to | `https://esign.cdac.gov.in/...` |
| `CDAC_ESIGN_ASP_ID` | ASP identifier issued by C-DAC | `ASP-123` |
| `CDAC_ESIGN_RESPONSE_URL` | Absolute `https://` callback URL registered with C-DAC | `https://api.example.com/api/v1/esign/_signed` |
| `CDAC_ESIGN_KEYSTORE_PATH` | PKCS#12 keystore holding the ASP key and certificate | `/run/secrets/asp-keystore.p12` |
| `CDAC_ESIGN_KEYSTORE_PASSWORD` | Keystore password; never logged or persisted | secret |
| `CDAC_ESIGN_RESPONSE_CERT` | C-DAC certificate the response signature is verified against (required in production) | PEM or base64 |
| `CDAC_ESIGN_VERSION` | eSign API version | `2.1` |
| `CDAC_ESIGN_AUTH_MODE` | Authentication mode (`1` = Aadhaar OTP) | `1` |
| `CDAC_ESIGN_HASH_ALGORITHM` | Digest algorithm declared to the ESP; must match `PDF_SIGNATURE_HASH_ALGORITHM` | `SHA256` |
| `CDAC_ESIGN_EKYC_ID_TYPE` | eKYC id type | `A` |
| `CDAC_ESIGN_CONSENT` | Consent flag sent as `sc` | `Y` |
| `CDAC_ESIGN_TXN_TEMPLATE` | Template for the ESP correlation id; must keep `{transaction_id}` | `{module}-{transaction_id}` |
| `CDAC_ESIGN_RESPONSE_MAX_SKEW` | Seconds of clock skew allowed on the response `ts` | `900` |
| `CDAC_ESIGN_VERIFY_RESPONSE_SIGNATURE` | Verify the response XMLDSig; rejected as `False` in production | `True` |
| `CDAC_ESIGN_RESPONSE_FIELD` | Form field the ESP delivers the response document under, when it is not one of the known names | `msg` |
| `PDF_SIGNATURE_HASH_ALGORITHM` | Digest the PDF service computes over the signing ByteRange | `SHA256` |
| `PDF_SIGNATURE_CONTAINER_BYTES` | Bytes reserved for the PKCS#7 signature container | `16384` |
| `PDF_MAX_SIGN_INPUT_BYTES` | Largest PDF accepted for in-process signing | `20971520` |

## Docker dependency profiles

The Docker image supports selecting which requirements file to install via the `REQUIREMENTS_FILE` build arg:

- Local compose (`docker/docker-compose.yml`) builds with `requirements/local.txt` (includes dev tools)
- Production compose (`docker/docker-compose.prod.yml`) builds with `requirements/production.txt`
- GitHub image publishing (`.github/workflows/docker-publish.yml`) also builds with `requirements/production.txt`

If you run `docker build` directly without setting `REQUIREMENTS_FILE`, it defaults to `requirements/production.txt`.

## CI/CD

- `.github/workflows/ci.yml` runs linting, Django system checks, and pytest on every push/PR.
- `.github/workflows/docker-publish.yml` builds and pushes the Docker image to GitHub Container Registry on every push to `main`.
