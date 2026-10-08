"""Version-aware regeneration avoidance (spec 0016 #7).

::

    reuse_key = sha256(tenant_id, key, entity_id, template_version.version,
                       canonical(significant request data))

Which parts of the request are significant is declared per template in
``data_config.significant_fields`` (a list of JSONPaths). Without it the whole
request is significant. Volatile fields (timestamps, nonces) are therefore
excluded simply by not listing them.
"""

from __future__ import annotations

import hashlib
import json

from ..models import PDFJob, PDFJobStatus
from .mapping.direct import find_all


def canonical(value) -> str:
    """Return a stable JSON encoding: sorted keys, no whitespace, unicode kept."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def significant_data(data_config: dict, request_data):
    """Return the part of ``request_data`` that identifies the document."""
    paths = (data_config or {}).get("significant_fields")
    if not paths:
        return request_data
    return {path: find_all(path, request_data) for path in paths}


def compute_reuse_key(
    *, tenant_id: str, key: str, entity_id: str, version: int, data_config: dict, request_data
) -> str:
    """Return the deterministic reuse hash for a request."""
    payload = canonical(
        [tenant_id, key, entity_id or "", int(version), significant_data(data_config, request_data)]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def find_reusable_job(reuse_key: str) -> PDFJob | None:
    """Return the newest completed, still-downloadable job with ``reuse_key``.

    ``CANCELLED``, ``FAILED`` and ``PARTIAL_SUCCESS`` jobs are never reused, nor
    are jobs whose documents have been deleted.
    """
    return (
        PDFJob.objects.filter(
            reuse_key=reuse_key,
            status=PDFJobStatus.COMPLETED,
            files_deleted_at__isnull=True,
        )
        .order_by("-completed_at", "-created_at")
        .first()
    )
