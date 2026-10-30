"""Production settings."""

from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F401,F403
from .base import CDAC_SMS_USE_DEFAULT_NUMBER, CDAC_SMS_VERIFY_SSL, env  # noqa: F401

# In production, rely on environment variables injected by Docker / secrets manager.
# Do NOT read .env files by default.

DEBUG = env.bool("DEBUG", default=False)
SECRET_KEY = env("SECRET_KEY")
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS")
CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=[])
CORS_ALLOWED_ORIGINS = env.list("CORS_ALLOWED_ORIGINS", default=[])
CORS_ALLOW_CREDENTIALS = env.bool("CORS_ALLOW_CREDENTIALS", default=True)

# Security hardening
SECURE_SSL_REDIRECT = env.bool("SECURE_SSL_REDIRECT", default=True)
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_SECURE = env.bool("SESSION_COOKIE_SECURE", default=True)
CSRF_COOKIE_SECURE = env.bool("CSRF_COOKIE_SECURE", default=True)
SECURE_HSTS_SECONDS = env.int("SECURE_HSTS_SECONDS", default=31536000)
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_BROWSER_XSS_FILTER = True
X_FRAME_OPTIONS = "DENY"


# ---------------------------------------------------------------------------
# Addon guards
# ---------------------------------------------------------------------------
# The CDAC recipient override and disabled TLS verification are test-only
# affordances and must never reach production.
if CDAC_SMS_USE_DEFAULT_NUMBER:
    raise ImproperlyConfigured("CDAC_SMS_USE_DEFAULT_NUMBER must be disabled in production.")
if not CDAC_SMS_VERIFY_SSL:
    raise ImproperlyConfigured("CDAC_SMS_VERIFY_SSL must be enabled in production.")


# ---------------------------------------------------------------------------
# Payments (spec 0017)
# ---------------------------------------------------------------------------
# The mock provider is never registered in production (a system check enforces
# it). A provider is a settings change (spec 0017 #9), so the gateway is enabled
# from the environment: set PAYMENT_DEFAULT_PROVIDER=egras to register e-GRAS and
# turn on its system checks (which then require the EGRAS_* block). Until a
# deployment is onboarded with NIC, leave PAYMENT_DEFAULT_PROVIDER empty — no
# provider is registered, the addon's checks stay silent, and the web container
# boots so the rest of the app runs.
PAYMENT_DEFAULT_PROVIDER = env("PAYMENT_DEFAULT_PROVIDER", default="")
PAYMENT_PROVIDERS = {}
if PAYMENT_DEFAULT_PROVIDER == "egras":
    PAYMENT_PROVIDERS = {"egras": "addon.egras_payment_gateway.provider.EGRASPaymentProvider"}
