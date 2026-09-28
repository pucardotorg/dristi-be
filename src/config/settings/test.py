"""Test / CI settings.

These settings are used by pytest and the GitHub Actions CI workflow.
"""

from .base import *  # noqa: F401,F403
from .base import MIDDLEWARE, REST_FRAMEWORK, STORAGES, env  # noqa: F401

SECRET_KEY = "test-secret-key-not-for-production"
DEBUG = False

# Use an in-memory SQLite database for speed in CI. Override with DATABASE_URL
# if you prefer running tests against PostgreSQL.
DATABASES = {
    "default": env.db(
        var="DATABASE_URL",
        default="sqlite:///:memory:",
    ),
}

# Use an in-memory cache in tests so cachalot exercises real caching/
# invalidation behavior without depending on a Redis service in CI.
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "KEY_PREFIX": "dristi-test",
    },
}

# Dramatiq runs synchronously in tests so assertions are straightforward.
DRAMATIQ_BROKER = {
    "BROKER": "dramatiq.brokers.stub.StubBroker",
    "OPTIONS": {},
    "MIDDLEWARE": [
        "dramatiq.middleware.AgeLimit",
        "dramatiq.middleware.TimeLimit",
        "dramatiq.middleware.Callbacks",
        "dramatiq.middleware.Retries",
        "django_dramatiq.middleware.DbConnectionsMiddleware",
    ],
}

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

# The OTP code and its resend cooldown both live in the cache, so tests need a
# real one that requires no server and resets between runs.
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "dristi-tests",
    },
}

EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

# Disable throttling in tests
REST_FRAMEWORK["DEFAULT_THROTTLE_CLASSES"] = []

# Use the default staticfiles storage in tests so no collectstatic is required
STORAGES["staticfiles"]["BACKEND"] = "django.contrib.staticfiles.storage.StaticFilesStorage"

# WhiteNoise is not needed in tests and would warn about a missing staticfiles directory
MIDDLEWARE = [m for m in MIDDLEWARE if m != "whitenoise.middleware.WhiteNoiseMiddleware"]
