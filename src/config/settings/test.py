"""Test / CI settings.

These settings are used by pytest and the GitHub Actions CI workflow.
"""

from .base import *  # noqa: F401,F403
from .base import MESSAGING_BACKENDS, MIDDLEWARE, REST_FRAMEWORK, STORAGES, env  # noqa: F401

SECRET_KEY = "test-secret-key-not-for-production"
DEBUG = False

# CI sets DATABASE_URL to a PostgreSQL service, matching production. Without
# it, tests fall back to in-memory SQLite, which lacks some PostgreSQL-only
# lookups (for example JSONField `contains`).
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

# No scheduler lock URL: dramatiq-crontab falls back to an in-process lock, so
# tests never need Redis (spec 0026 #3.3).
DRAMATIQ_CRONTAB = {}

# Tests run on the dummy SMS backend; CDAC is exercised via override_settings.
MESSAGING_BACKENDS = {**MESSAGING_BACKENDS, "sms": "apps.messaging.senders.sms.DummySMSBackend"}

# eSign runs on the mock provider in tests; the CDAC addon is exercised
# directly with override_settings and a generated test keystore.
ESIGN_PROVIDER = "apps.esign.providers.mock.MockESignProvider"
# The public callback throttle shares the process cache across tests, so it
# is off by default and switched on by the test that asserts it.
ESIGN_CALLBACK_THROTTLE_RATE = ""
# Off by default; the test that asserts it switches it on.
ADVOCATE_SEARCH_THROTTLE_RATE = ""

# Payments run on the mock provider in tests; the public callback throttle is
# off by default for the same reason as eSign's.
PAYMENT_PROVIDERS = {"mock": "apps.payments.providers.mock.MockPaymentProvider"}
PAYMENT_DEFAULT_PROVIDER = "mock"
PAYMENT_CALLBACK_THROTTLE_RATE = ""

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

# The OTP code and its resend cooldown both live in the cache, so tests need a
# real one that requires no server and resets between runs.
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "dristi-tests",
    },
    "state": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "dristi-tests-state",
    },
}

EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

# Disable throttling in tests
REST_FRAMEWORK["DEFAULT_THROTTLE_CLASSES"] = []

# Use the default staticfiles storage in tests so no collectstatic is required
STORAGES["staticfiles"]["BACKEND"] = "django.contrib.staticfiles.storage.StaticFilesStorage"

# WhiteNoise is not needed in tests and would warn about a missing staticfiles directory
MIDDLEWARE = [m for m in MIDDLEWARE if m != "whitenoise.middleware.WhiteNoiseMiddleware"]

# A paid case needs an establishment to enter scrutiny (spec 0024 #2.5), or the
# submission is refused. Scrutiny's own tests set a real one; tests that only
# walk the filing flow get this placeholder.
SCRUTINY_ESTABLISHMENT_ID = env(
    "SCRUTINY_ESTABLISHMENT_ID", default="00000000-0000-0000-0000-000000000001"
)
