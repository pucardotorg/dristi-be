"""Localization lookups (spec 0016 #5, ``LocalizationMapper``; design decision 9).

Messages are resolved through ``LocalizationService``, an internal abstraction
over two sources, consulted in order:

1. Inline messages declared in the template's ``data_config``::

       "localization": {"module": "pdf-summons",
                        "messages": {"en_IN": {"SUMMONS": "Summons"},
                                     "ml_IN": {"SUMMONS": "സമൻസ്"}}}

2. The localization service at ``PDF_LOCALIZATION_BASE_URL`` (when set),
   queried as ``GET {base}?tenant_id=..&module=..&locale=..`` and expected to
   return either ``{"CODE": "message", ...}`` or
   ``{"messages": [{"code": "CODE", "message": "..."}, ...]}``. Results are
   cached per tenant/module/locale for ``PDF_LOCALIZATION_CACHE_TIMEOUT_SECONDS``.

Mapping shape::

    {"type": "localization", "target": "title", "code": "SUMMONS"}
    {"type": "localization", "target": "court", "source": "data.court_code",
     "module": "common-masters", "locale": "ml_IN", "default": "{code}"}

``code`` is a literal; ``source`` is an expression whose value (or list of
values) is the code. When no message exists the ``default`` is used, with
``{code}`` substituted; without a default the code itself is returned so a
missing translation degrades visibly rather than failing the document.
"""

from __future__ import annotations

import hashlib

from django.conf import settings
from django.core.cache import cache

from ...exceptions import PDFDependencyError
from .. import http
from ..templating import evaluate

CACHE_PREFIX = "pdf:l10n:"


class LocalizationService:
    """Resolve localized messages for a tenant, module and locale."""

    def __init__(self, inline: dict | None = None, context=None):
        inline = inline or {}
        self.default_module = inline.get("module", "")
        self.inline_messages = inline.get("messages", {}) or {}
        self.context = context
        self._loaded: dict[tuple, dict] = {}

    def translate(self, code: str, *, module: str = "", locale: str = "", tenant_id: str = ""):
        """Return the message for ``code`` or ``None`` when there is none."""
        locale = locale or (self.context.locale if self.context else "")
        tenant_id = tenant_id or (self.context.tenant_id if self.context else "")
        module = module or self.default_module

        inline = self.inline_messages.get(locale, {})
        if code in inline:
            return inline[code]
        return self.messages(tenant_id, module, locale).get(code)

    def messages(self, tenant_id: str, module: str, locale: str) -> dict:
        """Return every remote message for the tenant/module/locale (cached)."""
        base_url = getattr(settings, "PDF_LOCALIZATION_BASE_URL", "")
        if not base_url or not locale:
            return {}

        key = (tenant_id, module, locale)
        if key in self._loaded:
            return self._loaded[key]

        digest = hashlib.sha256("|".join(key).encode()).hexdigest()[:32]
        cache_key = f"{CACHE_PREFIX}{digest}"
        messages = cache.get(cache_key)
        if messages is None:
            messages = self._fetch(base_url, tenant_id, module, locale)
            cache.set(cache_key, messages, settings.PDF_LOCALIZATION_CACHE_TIMEOUT_SECONDS)
        self._loaded[key] = messages
        return messages

    def _fetch(self, base_url: str, tenant_id: str, module: str, locale: str) -> dict:
        response = http.fetch(
            "GET",
            base_url,
            timeout=settings.PDF_EXTERNAL_API_TIMEOUT_SECONDS,
            max_retries=settings.PDF_EXTERNAL_API_MAX_RETRIES,
            context=self.context,
            params={"tenant_id": tenant_id, "module": module, "locale": locale},
            dependency="localization",
        )
        try:
            body = response.json()
        except ValueError as exc:
            raise PDFDependencyError("Localization service returned a non-JSON response.") from exc
        return self._normalize(body)

    @staticmethod
    def _normalize(body) -> dict:
        if isinstance(body, dict) and isinstance(body.get("messages"), list):
            return {
                str(item["code"]): str(item.get("message", ""))
                for item in body["messages"]
                if isinstance(item, dict) and "code" in item
            }
        if isinstance(body, dict):
            return {str(code): str(message) for code, message in body.items()}
        raise PDFDependencyError("Localization service returned an unexpected payload.")


class LocalizationMapper:
    """Resolve ``localization`` mappings."""

    type = "localization"

    def __init__(self, service: LocalizationService):
        self.service = service

    def map(self, spec: dict, variables: dict):
        """Return the localized message(s)."""
        code = spec["code"] if "code" in spec else evaluate(spec["source"], variables)
        if isinstance(code, list):
            return [self._one(item, spec) for item in code]
        return self._one(code, spec)

    def _one(self, code, spec):
        if code in (None, ""):
            return ""
        code = str(code)
        message = self.service.translate(
            code, module=spec.get("module", ""), locale=spec.get("locale", "")
        )
        if message is not None:
            return message
        if "default" in spec:
            default = spec["default"]
            return default.replace("{code}", code) if isinstance(default, str) else default
        return code
