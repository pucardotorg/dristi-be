"""Error codes and the standard error response (spec 0000 section 9).

Every error an API returns is rendered as::

    {"errors": [{"code": "E01001", "msg": "Invalid or expired code."}], "meta": {...}}

``code`` is a stable, registered identifier clients branch on; ``msg`` is the
human-readable text and may vary (it can carry the offending value). Errors
tied to one request field also carry ``field``.

Codes are ``E`` + a two-digit domain + a three-digit sequence. Each domain app
declares its own in ``<app>/errors.py``; ``ApiConfig.ready()`` imports those
modules so the full catalogue is known before the first request or schema
build.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass

from django.core.exceptions import ImproperlyConfigured
from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import Http404, JsonResponse
from django.views import defaults
from rest_framework import exceptions
from rest_framework.fields import get_error_detail
from rest_framework.settings import api_settings

from .meta import build_response_meta

ERROR_CODE_PATTERN = re.compile(r"^E(\d{2})\d{3}$")

# Two-digit domain prefix -> owning app. Allocate a new prefix here before an
# app defines its first code, so two apps can never claim the same range.
DOMAINS = {
    "00": "common",
    "01": "users",
    "02": "dristi_requests",
}


@dataclass(frozen=True)
class ErrorCode:
    """A registered error: its code, default message and HTTP status."""

    code: str
    msg: str
    status: int

    @property
    def domain(self) -> str:
        """Return the owning domain, derived from the code's prefix."""
        return DOMAINS[self.code[1:3]]

    def validation_error(self, detail=None) -> exceptions.ValidationError:
        """Return a DRF ``ValidationError`` carrying this code.

        For serializer ``validate``/``validate_<field>`` methods, where DRF
        only collects ``ValidationError``: there it attributes the error to the
        field being validated, which ``BusinessError`` cannot do. ``detail``
        defaults to this code's message and may be a string, list or dict::

            raise errors.EMAIL_TAKEN.validation_error()
            raise errors.INVALID_DOCUMENTS.validation_error({"documents": problems})
        """
        return exceptions.ValidationError(self.msg if detail is None else detail, code=self.code)

    def __str__(self) -> str:
        return self.code


_REGISTRY: dict[str, ErrorCode] = {}


def define(code: str, msg: str, *, status: int = 400) -> ErrorCode:
    """Register and return an error code.

    Raises ``ImproperlyConfigured`` at import time for a malformed code, an
    unallocated domain prefix or a code already taken, so a clash fails the
    build rather than silently reusing a number clients already rely on.
    """
    match = ERROR_CODE_PATTERN.match(code)
    if match is None:
        raise ImproperlyConfigured(f"Error code {code!r} must match E<domain:2><seq:3>.")
    if match.group(1) not in DOMAINS:
        raise ImproperlyConfigured(f"Error code {code!r} uses unallocated domain prefix.")
    if code in _REGISTRY:
        raise ImproperlyConfigured(f"Error code {code} is already defined.")

    error = ErrorCode(code=code, msg=msg, status=status)
    _REGISTRY[code] = error
    return error


def get_error(code: str | None) -> ErrorCode | None:
    """Return the registered error for ``code``, if any."""
    return _REGISTRY.get(code) if code else None


def all_errors() -> list[ErrorCode]:
    """Return every registered error, ordered by code."""
    return sorted(_REGISTRY.values(), key=lambda error: error.code)


# ---------------------------------------------------------------------------
# Common codes (domain 00)
# ---------------------------------------------------------------------------
# E00001-E00099: field validation. Mapped from DRF's built-in error codes, so
# plain serializer validation needs no extra wiring.
INVALID = define("E00001", "Invalid value.")
REQUIRED = define("E00002", "This field is required.")
NULL = define("E00003", "This field may not be null.")
BLANK = define("E00004", "This field may not be blank.")
INVALID_CHOICE = define("E00005", "Not a valid choice.")
MAX_LENGTH = define("E00006", "Value is too long.")
MIN_LENGTH = define("E00007", "Value is too short.")
MAX_VALUE = define("E00008", "Value is too large.")
MIN_VALUE = define("E00009", "Value is too small.")
UNIQUE = define("E00010", "Value must be unique.")
DOES_NOT_EXIST = define("E00011", "Referenced object does not exist.")
INCORRECT_TYPE = define("E00012", "Value has the wrong type.")
EMPTY = define("E00013", "This field may not be empty.")
TOO_MANY_DIGITS = define("E00014", "Number has too many digits.")

# E00100-E00199: request-level failures raised by DRF itself.
SERVER_ERROR = define("E00100", "A server error occurred.", status=500)
MALFORMED_REQUEST = define("E00101", "Malformed request.")
NOT_AUTHENTICATED = define("E00102", "Authentication credentials were not provided.", status=401)
AUTHENTICATION_FAILED = define("E00103", "Incorrect authentication credentials.", status=401)
PERMISSION_DENIED = define(
    "E00104", "You do not have permission to perform this action.", status=403
)
NOT_FOUND = define("E00105", "Not found.", status=404)
METHOD_NOT_ALLOWED = define("E00106", "Method not allowed.", status=405)
NOT_ACCEPTABLE = define("E00107", "Could not satisfy the request Accept header.", status=406)
CONFLICT = define("E00108", "The request conflicts with the current state.", status=409)
UNSUPPORTED_MEDIA_TYPE = define("E00109", "Unsupported media type in request.", status=415)
THROTTLED = define("E00110", "Request was throttled.", status=429)

# DRF's own error codes (ErrorDetail.code) -> registered code.
DRF_CODE_MAP: dict[str, ErrorCode] = {
    "invalid": INVALID,
    "required": REQUIRED,
    "null": NULL,
    "blank": BLANK,
    "invalid_choice": INVALID_CHOICE,
    "max_length": MAX_LENGTH,
    "min_length": MIN_LENGTH,
    "max_value": MAX_VALUE,
    "min_value": MIN_VALUE,
    "unique": UNIQUE,
    "does_not_exist": DOES_NOT_EXIST,
    "incorrect_type": INCORRECT_TYPE,
    "not_a_list": INCORRECT_TYPE,
    "not_a_dict": INCORRECT_TYPE,
    "empty": EMPTY,
    "max_digits": TOO_MANY_DIGITS,
    "max_decimal_places": TOO_MANY_DIGITS,
    "max_whole_digits": TOO_MANY_DIGITS,
    "error": SERVER_ERROR,
    "parse_error": MALFORMED_REQUEST,
    "not_authenticated": NOT_AUTHENTICATED,
    "authentication_failed": AUTHENTICATION_FAILED,
    "permission_denied": PERMISSION_DENIED,
    "not_found": NOT_FOUND,
    "method_not_allowed": METHOD_NOT_ALLOWED,
    "not_acceptable": NOT_ACCEPTABLE,
    "unsupported_media_type": UNSUPPORTED_MEDIA_TYPE,
    "throttled": THROTTLED,
}

# Last resort for an exception whose code is neither registered nor a DRF
# built-in: pick by status so the client still gets the right category.
STATUS_FALLBACK: dict[int, ErrorCode] = {
    400: INVALID,
    401: NOT_AUTHENTICATED,
    403: PERMISSION_DENIED,
    404: NOT_FOUND,
    405: METHOD_NOT_ALLOWED,
    406: NOT_ACCEPTABLE,
    409: CONFLICT,
    415: UNSUPPORTED_MEDIA_TYPE,
    429: THROTTLED,
}


class BusinessError(exceptions.APIException):
    """A business-rule failure carrying a registered error code.

    Raise from views and services. The status comes from the error code.
    ``msg`` overrides the default message, typically to include specifics;
    ``field`` attributes the error to one request field. Inside serializer
    validation use ``ErrorCode.validation_error()`` instead::

        raise BusinessError(errors.OTP_INVALID)
        raise BusinessError(errors.EMAIL_TAKEN, field="email")
    """

    def __init__(self, error: ErrorCode, msg: str | None = None, *, field: str | None = None):
        self.error = error
        self.status_code = error.status
        message = error.msg if msg is None else msg
        super().__init__(detail={field: [message]} if field else message, code=error.code)


def resolve_error(code: str | None, status_code: int) -> ErrorCode:
    """Return the registered error for a DRF error-detail code."""
    return (
        get_error(code)
        or DRF_CODE_MAP.get(code or "")
        or STATUS_FALLBACK.get(status_code, SERVER_ERROR)
    )


def error_items(exc: exceptions.APIException, *, field: str | None = None) -> list[dict]:
    """Flatten an APIException's detail into standard error items.

    ``field`` prefixes every field path, for errors raised while handling one
    element of a larger payload. Never empty: a detail with no messages (for
    example ``ValidationError({})``) still yields one item for its status, so
    ``errors`` always tells the client something.
    """
    items = list(_flatten(exc.detail, field, exc.status_code))
    if not items:
        error = resolve_error(None, exc.status_code)
        items = [{"code": error.code, "msg": error.msg, **({"field": field} if field else {})}]
    return items


def error_body(*errors: ErrorCode) -> dict:
    """Return a complete error body, ``meta`` included, for non-DRF responses."""
    return {
        "errors": [{"code": error.code, "msg": error.msg} for error in errors],
        "meta": build_response_meta(),
    }


def _flatten(detail, field: str | None, status_code: int) -> Iterator[dict]:
    if isinstance(detail, dict):
        for key, value in detail.items():
            yield from _flatten(value, _join(field, key), status_code)
    elif isinstance(detail, list):
        for index, value in enumerate(detail):
            # A list of messages belongs to the field itself; a list of
            # objects (many=True) is addressed element by element.
            child = _join(field, index) if isinstance(value, dict | list) else field
            yield from _flatten(value, child, status_code)
    else:
        error = resolve_error(getattr(detail, "code", None), status_code)
        item = {"code": error.code, "msg": str(detail)}
        if field:
            item["field"] = field
        yield item


def _join(parent: str | None, key) -> str | None:
    """Build a field path: ``profile.bar_number``, ``documents[0]``."""
    if isinstance(key, int):
        return f"{parent or ''}[{key}]"
    if key == api_settings.NON_FIELD_ERRORS_KEY:
        return parent
    return f"{parent}.{key}" if parent else str(key)


def as_api_exception(exc: Exception) -> Exception:
    """Translate Django exceptions into their DRF equivalents.

    404 and 403 mirror DRF's own handler, done up front so the detail keeps
    its error code. Django's ``ValidationError`` goes further than DRF, which
    leaves it to become a 500: models that validate in ``save()`` (for example
    ``BaseExtendableModel``) raise it from any write path, and it is the
    client's input that is wrong. Its messages, field keys and codes are kept.
    """
    if isinstance(exc, Http404):
        return exceptions.NotFound(*exc.args)
    if isinstance(exc, DjangoPermissionDenied):
        return exceptions.PermissionDenied(*exc.args)
    if isinstance(exc, DjangoValidationError):
        return exceptions.ValidationError(detail=get_error_detail(exc))
    return exc


def api_exception_handler(exc, context):
    """Project exception handler: DRF's handling, standard error body.

    DRF's handler still decides status, headers (``WWW-Authenticate``,
    ``Retry-After``) and transaction rollback; only the body is replaced.
    Anything DRF does not handle is left to propagate as a 500.
    """
    # Imported here: rest_framework.views resolves the default permission
    # classes at import time, and those import their error codes from here.
    from rest_framework.views import exception_handler as drf_exception_handler

    exc = as_api_exception(exc)
    response = drf_exception_handler(exc, context)
    if response is None:
        return None

    response.data = {"errors": error_items(exc)}
    return response


# Django-level handlers, wired in config.urls. They cover what never reaches a
# DRF view: an /api/ URL that matches no route, and an unhandled exception
# (logged by Django before the handler runs). Neither is used while DEBUG is
# on, when Django shows its technical pages instead.
API_PATH_PREFIX = "/api/"


def handler404(request, exception):
    """404 in the standard error shape under /api/, Django's page elsewhere."""
    if request.path.startswith(API_PATH_PREFIX):
        return JsonResponse(error_body(NOT_FOUND), status=404)
    return defaults.page_not_found(request, exception)


def handler500(request):
    """500 in the standard error shape under /api/, Django's page elsewhere.

    The message is the generic one: exception details never reach the client.
    """
    if request.path.startswith(API_PATH_PREFIX):
        return JsonResponse(error_body(SERVER_ERROR), status=500)
    return defaults.server_error(request)
