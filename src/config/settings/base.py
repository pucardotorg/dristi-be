"""Shared base settings for all environments.

Environment-specific settings live in:
  - config.settings.local     (development)
  - config.settings.test      (CI / unit tests)
  - config.settings.production (production)
"""

from pathlib import Path

import environ

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# Read environment variables from a .env file in development / test.
env = environ.Env(
    DEBUG=(bool, False),
    ALLOWED_HOSTS=(list, []),
    CSRF_TRUSTED_ORIGINS=(list, []),
    CORS_ALLOWED_ORIGINS=(list, []),
)

# Version information (commit SHA injected at Docker build time).
from .version import GIT_COMMIT_SHA  # noqa: E402,F401

# Environment-specific modules are responsible for loading .env files.


# ---------------------------------------------------------------------------
# Core Django settings
# ---------------------------------------------------------------------------
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Third-party
    "rest_framework",
    "drf_spectacular",
    "corsheaders",
    "django_dramatiq",
    "health_check",
    "simple_history",
    "cachalot",
    # Project apps
    "apps.core",
    "apps.users",
    "apps.dristi_requests",
    "apps.api",
    "apps.messaging",
    "apps.organizations",
    "apps.locations",
    "apps.files",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "simple_history.middleware.HistoryRequestMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
DATABASES = {
    "default": env.db(
        var="DATABASE_URL",
        default="postgres://dristi:secret@localhost:5432/dristi",
    ),
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------
AUTH_USER_MODEL = "users.User"

# Django tries each backend in order until one returns a user, so mobile+password
# and mobile+OTP are one authenticate() call from the caller's side.
AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",  # mobile + password
    "apps.users.services.backend.OTPBackend",  # mobile + OTP
]

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
        # The default list is username/first_name/last_name/email, and this
        # User has none of the first three. Left at the default the validator
        # compares against nothing and silently passes everything.
        "OPTIONS": {"user_attributes": ("name", "email", "mobile_number")},
    },
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]


# ---------------------------------------------------------------------------
# Simple History
# ---------------------------------------------------------------------------
# Disable admin revert to prevent accidental restoration of historical records.
SIMPLE_HISTORY_REVERT_DISABLED = True


# ---------------------------------------------------------------------------
# Internationalization
# ---------------------------------------------------------------------------
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True


STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}


# ---------------------------------------------------------------------------
# Static / media files
# ---------------------------------------------------------------------------
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"


# ---------------------------------------------------------------------------
# S3-compatible media storage (optional)
# ---------------------------------------------------------------------------
S3_API_ENDPOINT = env("S3_API_ENDPOINT", default=None)
S3_BUCKET = env("S3_BUCKET", default=None)
S3_ACCESS_KEY = env("S3_ACCESS_KEY", default=None)
S3_SECRET_KEY = env("S3_SECRET_KEY", default=None)

if all([S3_API_ENDPOINT, S3_BUCKET, S3_ACCESS_KEY, S3_SECRET_KEY]):
    STORAGES["default"] = {
        "BACKEND": "storages.backends.s3boto3.S3Boto3Storage",
        "OPTIONS": {
            "bucket_name": S3_BUCKET,
            "endpoint_url": S3_API_ENDPOINT,
            "access_key": S3_ACCESS_KEY,
            "secret_key": S3_SECRET_KEY,
            "signature_version": "s3v4",
            "default_acl": "private",
            "querystring_auth": True,
            "location": "media",
        },
    }


# ---------------------------------------------------------------------------
# File storage module (apps.files)
# ---------------------------------------------------------------------------
# apps.files writes content through the "files" storage alias, which follows
# the default backend: the local filesystem in development, and the
# S3-compatible bucket above once S3_* is configured.
STORAGES["files"] = STORAGES["default"]

FILE_MAX_SIZE_BYTES = env.int("FILE_MAX_SIZE_BYTES", default=10 * 1024 * 1024)
FILE_MAX_COUNT_PER_UPLOAD = env.int("FILE_MAX_COUNT_PER_UPLOAD", default=10)


# ---------------------------------------------------------------------------
# Django REST Framework
# ---------------------------------------------------------------------------
REST_FRAMEWORK = {
    # Registration and login are cookie-based. TokenAuthentication is the
    # intended second mechanism but is not yet wired — see spec 0000 section 6.3.
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
    ],
    # Gates are defaults so that forgetting to think about access on a new
    # endpoint fails closed. Endpoints reachable earlier opt out explicitly.
    #
    # IsAuthenticated looks redundant — IsAuthenticatedAndRegistered checks
    # authentication too — but it is not. DRF stops at the first permission
    # that fails and reports that one's message. Listed first, an anonymous
    # caller is told their credentials are missing; drop it and they are told
    # their registration is incomplete, which is wrong and sends the client to
    # the wrong screen. Keep both, in this order.
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
        "apps.users.services.permissions.IsAuthenticatedAndRegistered",
    ],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 20,
    "DEFAULT_RENDERER_CLASSES": [
        "apps.api.renderers.MetaJSONRenderer",
    ],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
}

SPECTACULAR_SETTINGS = {
    "TITLE": "Dristi API",
    "DESCRIPTION": "OpenAPI schema for Dristi Django REST APIs.",
    "VERSION": "1.0.0",
}

# ---------------------------------------------------------------------------
# Registration (spec 0005)
# ---------------------------------------------------------------------------
# Incremented by one each time new terms are published. An account whose
# terms_version_accepted is lower than this must re-accept.
CURRENT_TERMS_VERSION = env.int("CURRENT_TERMS_VERSION", default=1)

OTP_LENGTH = env.int("OTP_LENGTH", default=6)
OTP_TTL_SECONDS = env.int("OTP_TTL_SECONDS", default=300)

# Minimum gap between two codes sent to the same number. An operational dial:
# it trades SMS cost and abuse resistance against how long a user whose first
# message never arrived has to wait. Validated at startup by
# apps.users.services.checks.
OTP_RESEND_COOLDOWN_SECONDS = env.int("OTP_RESEND_COOLDOWN_SECONDS", default=30)


# ---------------------------------------------------------------------------
# Cache (Redis)
# ---------------------------------------------------------------------------
CACHES = {
    "default": env.cache(
        var="CACHE_REDIS_URL",
        default="redis://localhost:6379/1",
    ),
}

CACHE_ENABLED = env.bool("CACHE_ENABLED", default=True)
CACHE_KEY_PREFIX = env("CACHE_KEY_PREFIX", default="dristi")
CACHES["default"]["KEY_PREFIX"] = CACHE_KEY_PREFIX

if not CACHE_ENABLED:
    CACHES["default"] = {"BACKEND": "django.core.cache.backends.dummy.DummyCache"}

# ---------------------------------------------------------------------------
# django-cachalot (automatic ORM query caching, Redis-backed)
# ---------------------------------------------------------------------------
CACHALOT_ENABLED = env.bool("CACHALOT_ENABLED", default=CACHE_ENABLED)
CACHALOT_CACHE = "default"
CACHALOT_TIMEOUT = env.int("CACHALOT_TIMEOUT", default=120)

# Phase 1: allow-list only low-churn, non-user-scoped reference data.
CACHALOT_ONLY_CACHABLE_APPS = ("locations",)
CACHALOT_UNCACHABLE_TABLES = (
    "users_user",
    "authtoken_token",
    "django_session",
)


# ---------------------------------------------------------------------------
# Dramatiq (Redis broker)
# ---------------------------------------------------------------------------
DRAMATIQ_BROKER = {
    "BROKER": "dramatiq.brokers.redis.RedisBroker",
    "OPTIONS": {
        "url": env("DRAMATIQ_BROKER_URL", default="redis://localhost:6379/2"),
    },
    "MIDDLEWARE": [
        "dramatiq.middleware.AgeLimit",
        "dramatiq.middleware.TimeLimit",
        "dramatiq.middleware.Callbacks",
        "dramatiq.middleware.Retries",
        "django_dramatiq.middleware.DbConnectionsMiddleware",
        "django_dramatiq.middleware.AdminMiddleware",
    ],
}

DRAMATIQ_TASKS_DATABASE = "default"


# ---------------------------------------------------------------------------
# Messaging
# ---------------------------------------------------------------------------
MESSAGING_TEMPLATE_ENGINE = env("MESSAGING_TEMPLATE_ENGINE", default="jinja2")
# Sender classes can be overridden or extended via MESSAGING_SENDERS.
# Built-in defaults are email/sms/push; external Django apps can register
# custom channels by providing a BaseMessageSender subclass import path.
# Default mapping (uncomment and edit to override):
# MESSAGING_SENDERS = {
#     "email": "apps.messaging.senders.email.EmailSender",
#     "sms": "apps.messaging.senders.sms.SMSSender",
#     "push": "apps.messaging.senders.push.PushSender",
# }
MESSAGING_SENDERS = {}
# Concrete delivery backends for each channel (used by ConfiguredBackendSender).
# Defaults ship with the built-in SMTP email and dummy SMS backends.
MESSAGING_BACKENDS = {
    "email": "apps.messaging.senders.email.SMTPEmailBackend",
    "sms": "apps.messaging.senders.sms.DummySMSBackend",
}
MESSAGING_DUMMY_SMS_ENDPOINT = env("MESSAGING_DUMMY_SMS_ENDPOINT", default=None)
MESSAGING_DUMMY_SMS_TIMEOUT = env.int("MESSAGING_DUMMY_SMS_TIMEOUT", default=30)
MESSAGING_EMAIL_BACKEND = env("MESSAGING_EMAIL_BACKEND", default="django")
MESSAGING_EMAIL_HOST = env("MESSAGING_EMAIL_HOST", default=None)
MESSAGING_EMAIL_PORT = env.int("MESSAGING_EMAIL_PORT", default=587)
MESSAGING_EMAIL_HOST_USER = env("MESSAGING_EMAIL_HOST_USER", default=None)
MESSAGING_EMAIL_HOST_PASSWORD = env("MESSAGING_EMAIL_HOST_PASSWORD", default=None)
MESSAGING_EMAIL_USE_TLS = env.bool("MESSAGING_EMAIL_USE_TLS", default=True)
MESSAGING_EMAIL_USE_SSL = env.bool("MESSAGING_EMAIL_USE_SSL", default=False)
MESSAGING_EMAIL_DEFAULT_FROM = env("MESSAGING_EMAIL_DEFAULT_FROM", default=None)
MESSAGING_EMAIL_TIMEOUT = env.int("MESSAGING_EMAIL_TIMEOUT", default=30)
MESSAGING_RETRY_DELAY_BASE = env.int("MESSAGING_RETRY_DELAY_BASE", default=60)
MESSAGING_RETRY_DELAY_MAX = env.int("MESSAGING_RETRY_DELAY_MAX", default=3600)


# ---------------------------------------------------------------------------
# Email
# ---------------------------------------------------------------------------
EMAIL_CONFIG = env.email_url("EMAIL_URL", default="consolemail://")
vars().update(EMAIL_CONFIG)
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="noreply@example.com")


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "standard": {
            "format": "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "standard",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": "INFO",
    },
    "loggers": {
        "django": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
        "dramatiq": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
        "cachalot": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
    },
}
