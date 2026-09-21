"""Development settings."""

import os
from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent.parent
environ.Env.read_env(BASE_DIR.parent / ".env")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.local")

from .base import *  # noqa: E402,F401,F403
from .base import INSTALLED_APPS, MIDDLEWARE, REST_FRAMEWORK, STORAGES, env  # noqa: E402,F401

DEBUG = env.bool("DEBUG", default=True)
SECRET_KEY = env("SECRET_KEY", default="local-dev-secret-key-not-for-production")
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=["localhost", "127.0.0.1", "0.0.0.0"])
CSRF_TRUSTED_ORIGINS = env.list(
    "CSRF_TRUSTED_ORIGINS",
    default=["http://localhost:8000", "http://127.0.0.1:8000"],
)
CORS_ALLOWED_ORIGINS = env.list(
    "CORS_ALLOWED_ORIGINS",
    default=["http://localhost:3000", "http://127.0.0.1:3000"],
)
CORS_ALLOW_CREDENTIALS = env.bool("CORS_ALLOW_CREDENTIALS", default=True)

# Development niceties
INSTALLED_APPS += ["django_extensions", "debug_toolbar"]
MIDDLEWARE += ["debug_toolbar.middleware.DebugToolbarMiddleware"]

from debug_toolbar.settings import PANELS_DEFAULTS  # noqa: E402

DEBUG_TOOLBAR_PANELS = [*PANELS_DEFAULTS, "cachalot.panels.CachalotPanel"]

# WhiteNoise is not needed when running the Django development server
MIDDLEWARE = [m for m in MIDDLEWARE if m != "whitenoise.middleware.WhiteNoiseMiddleware"]

INTERNAL_IPS = ["127.0.0.1"]

# Use Django's staticfiles storage in development so collectstatic is not needed
STORAGES["staticfiles"]["BACKEND"] = "django.contrib.staticfiles.storage.StaticFilesStorage"

# Disable HTTPS-only cookies in development
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
SECURE_SSL_REDIRECT = False

# Render the browsable API in development
REST_FRAMEWORK["DEFAULT_RENDERER_CLASSES"].append("rest_framework.renderers.BrowsableAPIRenderer")
