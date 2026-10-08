"""Database-backed configuration loading with caching (spec 0016 #9).

Two cache entries are involved:

* ``pdf:cfg:version:<version_id>`` holds a version's configuration. Versions
  are immutable once used, so these entries never need invalidation.
* ``pdf:cfg:active:<key>`` maps a template key to its active version id. It is
  deleted whenever a template or version is saved (see ``apps.pdf.signals``),
  so activating a new version takes effect for the next job without a restart.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.conf import settings
from django.core.cache import cache

from ..exceptions import PDFTemplateNotFound
from ..models import PDFTemplateVersion

ACTIVE_PREFIX = "pdf:cfg:active:"
VERSION_PREFIX = "pdf:cfg:version:"


@dataclass(frozen=True)
class LoadedConfig:
    """A template version's configuration, detached from the ORM."""

    template_version_id: str
    key: str
    version: int
    format_config: dict
    data_config: dict


class PDFConfigLoader:
    """Resolve template configuration by key or by version id."""

    @staticmethod
    def _timeout() -> int:
        return settings.PDF_CONFIG_CACHE_TIMEOUT_SECONDS

    @classmethod
    def load(cls, key: str) -> tuple[dict, dict, LoadedConfig]:
        """Return ``(format_config, data_config, config)`` for the active version of ``key``."""
        version_id = cache.get(ACTIVE_PREFIX + key)
        if version_id is None:
            version_id = (
                PDFTemplateVersion.objects.filter(
                    template__key=key, template__is_active=True, is_active=True
                )
                .values_list("id", flat=True)
                .first()
            )
            if version_id is None:
                raise PDFTemplateNotFound(f"No active PDF template for key {key!r}.")
            version_id = str(version_id)
            cache.set(ACTIVE_PREFIX + key, version_id, cls._timeout())
        config = cls.load_version(version_id)
        return config.format_config, config.data_config, config

    @classmethod
    def load_version(cls, template_version_id) -> LoadedConfig:
        """Return the configuration of a specific version (cached forever per id)."""
        cache_key = VERSION_PREFIX + str(template_version_id)
        config = cache.get(cache_key)
        if config is not None:
            return config
        try:
            version = PDFTemplateVersion.objects.select_related("template").get(
                pk=template_version_id
            )
        except PDFTemplateVersion.DoesNotExist as exc:
            raise PDFTemplateNotFound("The PDF template version no longer exists.") from exc
        config = LoadedConfig(
            template_version_id=str(version.id),
            key=version.template.key,
            version=version.version,
            format_config=version.format_config,
            data_config=version.data_config or {},
        )
        cache.set(cache_key, config, cls._timeout())
        return config

    @staticmethod
    def invalidate_key(key: str) -> None:
        """Forget the ``key -> active version`` lookup."""
        cache.delete(ACTIVE_PREFIX + key)

    @staticmethod
    def invalidate_version(template_version_id) -> None:
        """Forget a cached version (only needed if an unused version was edited)."""
        cache.delete(VERSION_PREFIX + str(template_version_id))
