"""External API mapping (spec 0016 #5, ``ExternalAPIMapper``).

Fetches data from another service and extracts values from the response with
JSONPath. Mapping shape::

    {"type": "external_api", "target": "advocate",
     "method": "GET",                       # or POST
     "url": "https://hrms.internal/advocates/{{ data.advocate_id }}",
     "params": {"tenant": "{{ meta.tenant_id }}"},   # GET query / POST JSON body
     "credentials": "hrms",                 # key in PDF_SERVICE_CREDENTIALS
     "path": "$.advocate",                  # JSONPath into the JSON response
     "fields": {"name": "$.name", "bar_no": "$.barRegistrationNumber"},
     "many": false, "default": null}

``url`` and every ``params`` value are template strings, so parameters can be
built from request data, ``meta`` and earlier mapping targets. Responses are
cached per job for the duration of one ``DataMapper.map`` call, so mappings that
hit the same URL with the same parameters share one request.
"""

from __future__ import annotations

import json

from django.conf import settings

from ...exceptions import PDFDependencyError, PDFRequestDataError
from .. import http
from ..templating import render_text
from .direct import find_all, find_first


class ExternalAPIMapper:
    """Resolve ``external_api`` mappings."""

    type = "external_api"

    def __init__(self, context=None):
        self.context = context
        self._responses: dict[str, object] = {}
        self.calls = 0

    def map(self, spec: dict, variables: dict):
        """Return the value extracted from the external API response."""
        method = spec.get("method", "GET").upper()
        url = render_text(spec["url"], variables, escape_output=False)
        params = {
            name: render_text(value, variables, escape_output=False)
            if isinstance(value, str)
            else value
            for name, value in (spec.get("params") or {}).items()
        }

        body = self._fetch(method, url, params, spec)

        path = spec.get("path", "$")
        many = spec.get("many", False)
        value = find_all(path, body) if many else find_first(path, body, None)

        fields = spec.get("fields")
        if fields and value is not None:
            rows = value if many else [value]
            projected = [
                {name: find_first(field_path, row, None) for name, field_path in fields.items()}
                for row in rows
            ]
            value = projected if many else projected[0]

        if value is None or value == []:
            if "default" in spec:
                return spec["default"]
            if spec.get("required", True):
                raise PDFRequestDataError(
                    f"External API returned no value for {spec.get('target')!r}."
                )
        return value

    def _fetch(self, method: str, url: str, params: dict, spec: dict):
        """Return the decoded JSON response, sharing identical requests within a job."""
        cache_key = json.dumps([method, url, params, spec.get("credentials")], sort_keys=True)
        if cache_key in self._responses:
            return self._responses[cache_key]

        max_calls = settings.PDF_EXTERNAL_API_MAX_CALLS_PER_JOB
        if self.calls >= max_calls:
            raise PDFRequestDataError(
                f"Template exceeds the limit of {max_calls} external API calls per document."
            )
        self.calls += 1

        response = http.fetch(
            method,
            url,
            timeout=settings.PDF_EXTERNAL_API_TIMEOUT_SECONDS,
            max_retries=settings.PDF_EXTERNAL_API_MAX_RETRIES,
            context=self.context,
            params=params if method == "GET" else None,
            json=params if method != "GET" else None,
            headers=http.credential_headers(spec.get("credentials")),
            dependency="external_api",
        )
        try:
            body = response.json()
        except ValueError as exc:
            raise PDFDependencyError("External API returned a non-JSON response.") from exc
        self._responses[cache_key] = body
        return body
