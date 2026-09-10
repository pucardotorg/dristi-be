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
    "rest_framework.authtoken",
    "corsheaders",
    "django_dramatiq",
    "health_check",
    # Project apps
    "apps.core",
    "apps.users",
    "apps.api",
    "apps.messaging",
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

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]


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
# Django REST Framework
# ---------------------------------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
        "rest_framework.authentication.TokenAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticatedOrReadOnly",
    ],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 20,
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
    ],
}


# ---------------------------------------------------------------------------
# Cache (Redis)
# ---------------------------------------------------------------------------
CACHES = {
    "default": env.cache(
        var="CACHE_URL",
        default="redis://localhost:6379/1",
    ),
}


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
MESSAGING_EMAIL_HOST_PASSWORD = env(
    "MESSAGING_EMAIL_HOST_PASSWORD", default=None
)
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
    },
}
