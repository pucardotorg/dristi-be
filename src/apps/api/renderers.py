"""Custom DRF renderers for API responses."""

from __future__ import annotations

from rest_framework.renderers import JSONRenderer

from .meta import build_response_meta


class MetaJSONRenderer(JSONRenderer):
    """JSON renderer that injects a standard ``meta`` object into responses."""

    def render(self, data, accepted_media_type=None, renderer_context=None):
        """Render payload while appending response metadata."""

        if data is not None:
            meta = build_response_meta()
            if isinstance(data, dict):
                if "meta" not in data:
                    data = {**data, "meta": meta}
            elif isinstance(data, list):
                data = {"data": data, "meta": meta}
            else:
                data = {"data": data, "meta": meta}

        return super().render(
            data, accepted_media_type=accepted_media_type, renderer_context=renderer_context
        )
