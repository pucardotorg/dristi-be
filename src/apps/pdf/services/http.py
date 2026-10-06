"""Outbound HTTP for mappings: external APIs, localization and images.

Every call uses ``requests`` with an explicit ``(connect, read)`` timeout and a
bounded number of in-call retries on timeouts, connection errors and 5xx
responses (spec 0016 #5, #10). Exhausted retries raise ``PDFDependencyError``,
which the worker retries again at job level with backoff. A 4xx response is a
problem with the request rather than the dependency and is not retried.

Tenant, locale and correlation context are forwarded as headers (#13). The
caller's own authorization is never forwarded; service credentials come from
``settings.PDF_SERVICE_CREDENTIALS`` and are referenced from configuration by
name only.
"""

from __future__ import annotations

import logging
import time
from urllib.parse import urlsplit

import requests
from django.conf import settings

from ..exceptions import PDFConfigurationError, PDFDependencyError, PDFRequestDataError
from .context import RequestContext

logger = logging.getLogger("apps.pdf")

RETRY_BACKOFF_SECONDS = 0.5
ALLOWED_SCHEMES = ("http", "https")


def context_headers(context: RequestContext | None) -> dict[str, str]:
    """Return the headers that propagate request context to a dependency."""
    if context is None:
        return {}
    headers = {
        "X-Tenant-Id": context.tenant_id,
        "Accept-Language": context.locale.replace("_", "-"),
    }
    if context.correlation_id:
        headers["X-Correlation-Id"] = context.correlation_id
    return {name: value for name, value in headers.items() if value}


def credential_headers(name: str | None) -> dict[str, str]:
    """Return the configured service-credential headers registered under ``name``."""
    if not name:
        return {}
    credentials = getattr(settings, "PDF_SERVICE_CREDENTIALS", {}) or {}
    try:
        headers = credentials[name]
    except KeyError as exc:
        raise PDFConfigurationError(f"Unknown service credentials {name!r}.") from exc
    return {str(key): str(value) for key, value in dict(headers).items()}


def validate_url(url: str) -> str:
    """Reject non-HTTP schemes and hosts outside ``PDF_FETCH_ALLOWED_HOSTS``.

    URLs may be built from request data (an image URL, say), so the scheme and
    host are checked before anything is fetched.
    """
    parts = urlsplit(url)
    if parts.scheme not in ALLOWED_SCHEMES or not parts.hostname:
        raise PDFRequestDataError("Only absolute http(s) URLs can be fetched.")
    allowed = [host.lower() for host in getattr(settings, "PDF_FETCH_ALLOWED_HOSTS", []) or []]
    if allowed and parts.hostname.lower() not in allowed:
        raise PDFRequestDataError("The URL host is not allowed for PDF generation.")
    return url


def fetch(
    method: str,
    url: str,
    *,
    timeout: float,
    max_retries: int,
    context: RequestContext | None = None,
    params: dict | None = None,
    json: dict | list | None = None,
    headers: dict | None = None,
    max_bytes: int | None = None,
    dependency: str = "external_api",
) -> requests.Response:
    """Perform one bounded, retried HTTP request and return the response.

    ``max_bytes`` caps the body size (checked against ``Content-Length`` and
    while streaming) so a dependency cannot exhaust worker memory.
    """
    validate_url(url)
    all_headers = {**context_headers(context), **(headers or {})}
    attempts = max(0, int(max_retries)) + 1
    started = time.monotonic()

    for attempt in range(1, attempts + 1):
        try:
            response = requests.request(
                method.upper(),
                url,
                params=params,
                json=json,
                headers=all_headers,
                timeout=(timeout, timeout),
                stream=max_bytes is not None,
            )
        except (requests.Timeout, requests.ConnectionError) as exc:
            failure = f"{type(exc).__name__}"
        except requests.RequestException as exc:
            raise PDFDependencyError(f"{dependency} request failed.") from exc
        else:
            if response.status_code >= 500:
                failure = f"HTTP {response.status_code}"
                response.close()
            elif response.status_code >= 400:
                response.close()
                raise PDFRequestDataError(
                    f"{dependency} rejected the request with HTTP {response.status_code}."
                )
            else:
                if max_bytes is not None:
                    _read_bounded(response, max_bytes, dependency)
                logger.info(
                    "event=PDF_DEPENDENCY_CALL dependency=%s status=%s attempt=%s duration_ms=%d",
                    dependency,
                    response.status_code,
                    attempt,
                    (time.monotonic() - started) * 1000,
                )
                return response

        if attempt < attempts:
            time.sleep(RETRY_BACKOFF_SECONDS * (2 ** (attempt - 1)))

    logger.warning(
        "event=PDF_DEPENDENCY_FAILED dependency=%s reason=%s attempts=%s",
        dependency,
        failure,
        attempts,
    )
    raise PDFDependencyError(f"{dependency} is unavailable ({failure}).")


def _read_bounded(response: requests.Response, max_bytes: int, dependency: str) -> None:
    """Read a streamed body into ``response._content`` without exceeding ``max_bytes``."""
    declared = response.headers.get("Content-Length")
    if declared and declared.isdigit() and int(declared) > max_bytes:
        response.close()
        raise PDFRequestDataError(f"{dependency} response exceeds {max_bytes} bytes.")

    chunks, total = [], 0
    for chunk in response.iter_content(chunk_size=64 * 1024):
        total += len(chunk)
        if total > max_bytes:
            response.close()
            raise PDFRequestDataError(f"{dependency} response exceeds {max_bytes} bytes.")
        chunks.append(chunk)
    response._content = b"".join(chunks)
