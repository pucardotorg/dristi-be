"""``DataMapper`` facade (spec 0016 #5).

``data_config`` declares an ordered list of mappings; each produces one
``target`` in the render context::

    {
      "mappings": [
        {"type": "direct", "target": "case_number", "path": "$.case.number"},
        {"type": "external_api", "target": "judge", "url": "...", "path": "$.name"},
        {"type": "derived", "target": "accused_count", "expression": "accused | length"},
        {"type": "format", "target": "hearing", "source": "data.hearing_date",
         "format": "date", "pattern": "%d %B %Y"},
        {"type": "localization", "target": "title", "code": "SUMMONS"},
        {"type": "image", "target": "seal", "source": "data.seal", "source_type": "base64"},
        {"type": "qr", "target": "qr", "template": "https://x/{{ case_number }}"}
      ],
      "localization": {"module": "...", "messages": {...}},
      "significant_fields": ["$.case.number", "$.hearing_date"],
      "bulk": {"records_path": "$.records", "merge": true},
      "sync_render": true
    }

Mappings run in order, and each sees the request data as ``data``, the request
context as ``meta``, and every earlier target by name, so later mappings can
build on earlier ones. Each type is handled by exactly one sub-mapper.
"""

from __future__ import annotations

from ...exceptions import PDFConfigurationError
from ..context import RequestContext
from .derived import DerivedMapper
from .direct import DirectMapper
from .external_api import ExternalAPIMapper
from .formatting import FormattingMapper
from .image import ImageMapper
from .localization import LocalizationMapper, LocalizationService
from .qr import QRMapper

MAPPING_TYPES = (
    "direct",
    "external_api",
    "derived",
    "format",
    "localization",
    "image",
    "qr",
)

RESERVED_TARGETS = frozenset({"data", "meta", "record", "records"})


class DataMapper:
    """Build a render context from request data and a ``data_config``."""

    def __init__(self, context: RequestContext | None = None, data_config: dict | None = None):
        self.context = context or RequestContext(tenant_id="")
        data_config = data_config or {}
        self.localization = LocalizationService(data_config.get("localization"), self.context)
        self.external_api = ExternalAPIMapper(self.context)
        self._mappers = {
            "direct": DirectMapper(),
            "external_api": self.external_api,
            "derived": DerivedMapper(),
            "format": FormattingMapper(),
            "localization": LocalizationMapper(self.localization),
            "image": ImageMapper(self.context),
            "qr": QRMapper(),
        }

    def map(self, data_config: dict, request_data, context: dict | None = None) -> dict:
        """Return the render context: ``data``, ``meta`` and every mapping target."""
        variables = {
            "data": request_data,
            "meta": self.context.as_dict(),
            **(context or {}),
        }
        for spec in (data_config or {}).get("mappings", []):
            mapper = self._mappers.get(spec.get("type"))
            if mapper is None:
                raise PDFConfigurationError(f"Unknown mapping type {spec.get('type')!r}.")
            if spec["type"] == "direct":
                value = mapper.map(spec, request_data)
            else:
                value = mapper.map(spec, variables)
            variables[spec["target"]] = value
        return variables


__all__ = ["DataMapper", "MAPPING_TYPES", "RESERVED_TARGETS"]
