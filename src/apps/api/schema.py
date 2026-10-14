"""OpenAPI documentation of the response envelope (spec 0000 sections 8 and 10).

``ApiAutoSchema`` documents responses as ``MetaJSONRenderer`` actually sends
them:

- success bodies include ``meta``: objects gain a ``meta`` property, arrays and
  scalars are wrapped as ``{"data": ..., "meta": ...}``;
- error responses carry named examples, one per scenario, so Swagger shows
  what that endpoint actually returns rather than one generic sample.
  Scenarios come from business errors declared with ``error_responses()`` and
  from the view itself: a missing required field of its request serializer,
  authentication and coded permission failures, not-found for routes with
  path parameters, and throttling.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

from django.contrib.auth.models import AnonymousUser
from drf_spectacular.openapi import AutoSchema
from drf_spectacular.plumbing import force_instance
from drf_spectacular.utils import OpenApiResponse

from . import errors
from .errors import ErrorCode, ErrorExample, all_errors, get_error
from .meta import SPEC_VERSION
from .renderers import MetaJSONRenderer

ERROR_RESPONSE_REF = {"$ref": "#/components/schemas/ErrorResponse"}
META_REF = {"$ref": "#/components/schemas/ResponseMeta"}
HTTP_METHODS = {"get", "put", "post", "delete", "options", "head", "patch", "trace"}
BODY_METHODS = {"POST", "PUT", "PATCH"}
EXAMPLE_META = {
    "timestamp": "2026-09-16T12:34:56.123456+05:30",
    "app_version": "abc123def",
    "spec_version": SPEC_VERSION,
}


@dataclass(frozen=True)
class ErrorScenario:
    """One documented error: the code, the message shown and an optional field.

    ``status`` defaults to the code's registered status; it differs only where
    DRF decides it at runtime (not-authenticated is a 403 under session auth).
    """

    error: ErrorCode
    message: str
    field: str | None = None
    status: int | None = None

    @property
    def http_status(self) -> int:
        return self.status or self.error.status

    @classmethod
    def of(cls, item: ErrorCode | ErrorExample) -> ErrorScenario:
        if isinstance(item, ErrorExample):
            return cls(item.error, item.message, item.field)
        return cls(item, item.message)

    def body(self) -> dict:
        error = {"code": self.error.code, "message": self.message}
        if self.field:
            error["field"] = self.field
        return {"errors": [error], "meta": EXAMPLE_META}


class DeclaredErrors(OpenApiResponse):
    """An ``OpenApiResponse`` that remembers the error scenarios it documents."""

    def __init__(self, scenarios: list[ErrorScenario]):
        super().__init__(description=_describe(scenarios))
        self.scenarios = scenarios


def error_responses(*items: ErrorCode | ErrorExample) -> dict[int, OpenApiResponse]:
    """Document the errors an endpoint can return, keyed by status.

    Each code is listed under its own registered status, so the documented
    status cannot drift from the one returned, and becomes a named example.
    Use ``.example()`` for the field an error is reported on or the exact
    message the endpoint sends::

        @extend_schema(
            responses=error_responses(
                errors.OTP_INVALID,
                errors.EMAIL_TAKEN.example(field="email"),
                errors.INVALID.example("Must be a valid UUID.", field="parent_id"),
            )
        )

    On its own it keeps the inferred success response; merge it with an
    explicit one (``{201: Out, **error_responses(...)}``) when that differs.
    """
    by_status: dict[int, list[ErrorScenario]] = {}
    for item in items:
        scenario = ErrorScenario.of(item)
        by_status.setdefault(scenario.http_status, []).append(scenario)
    return {status: DeclaredErrors(scenarios) for status, scenarios in by_status.items()}


class ApiAutoSchema(AutoSchema):
    """``AutoSchema`` that documents the project's response envelope.

    Adds ``meta`` to success bodies and per-operation error examples, and
    fills in what views would otherwise repeat on every operation:

    - the tag is the owning app (``apps.<app>``), unless ``tags=`` is given;
    - custom actions named in the view's ``list_actions`` return a paginated
      list, those in ``unpaginated_actions`` a plain list;
    - ``responses=error_responses(...)`` with no success entry keeps the
      inferred success response.
    """

    def get_tags(self):
        app = _owning_app(self.view, self.method)
        return [app] if app else super().get_tags()

    def _is_list_view(self, serializer=None):
        action = getattr(self.view, "action", None)
        if action in getattr(self.view, "list_actions", ()) or action in getattr(
            self.view, "unpaginated_actions", ()
        ):
            return True
        return super()._is_list_view(serializer)

    def _get_paginator(self):
        if getattr(self.view, "action", None) in getattr(self.view, "unpaginated_actions", ()):
            return None
        return super()._get_paginator()

    def _get_response_bodies(self, direction="response"):
        responses = super()._get_response_bodies(direction)
        if direction != "response":
            return responses

        if self._declares_only_errors():
            responses = {**self._inferred_success(), **responses}

        if self._renders_meta():
            for status_code, response in responses.items():
                media = response.get("content", {}).get(MetaJSONRenderer.media_type)
                if str(status_code).startswith("2") and media and "schema" in media:
                    media["schema"] = with_meta(media["schema"])

        by_status: dict[int, list[ErrorScenario]] = {}
        for scenario in [*self._declared_scenarios(), *self._derived_scenarios()]:
            listed = by_status.setdefault(scenario.http_status, [])
            if scenario not in listed:
                listed.append(scenario)

        for status, scenarios in sorted(by_status.items()):
            responses[str(status)] = {
                "description": _describe(scenarios),
                "content": {
                    "application/json": {
                        "schema": ERROR_RESPONSE_REF,
                        "examples": _examples(scenarios),
                    }
                },
            }
        return responses

    def _declares_only_errors(self) -> bool:
        """Whether ``responses=`` lists error_responses() and no success response."""
        declared = self.get_response_serializers()
        return (
            isinstance(declared, dict)
            and bool(declared)
            and all(isinstance(response, DeclaredErrors) for response in declared.values())
        )

    def _inferred_success(self) -> dict:
        """The success response drf-spectacular infers when nothing is declared."""
        if self.method == "DELETE":
            return {"204": {"description": "No response body"}}
        code = "201" if self._is_create_operation() else "200"
        return {code: self._get_response_for_code(self._get_serializer(), code)}

    def _renders_meta(self) -> bool:
        """Whether this view's JSON goes through MetaJSONRenderer (the schema view does not)."""
        try:
            renderers = self.view.get_renderers()
        except Exception:  # noqa: BLE001 - documentation must never break the schema
            return False
        return any(isinstance(renderer, MetaJSONRenderer) for renderer in renderers)

    def _declared_scenarios(self) -> list[ErrorScenario]:
        declared = self.get_response_serializers()
        if not isinstance(declared, dict):
            return []
        return [
            scenario
            for response in declared.values()
            if isinstance(response, DeclaredErrors)
            for scenario in response.scenarios
        ]

    def _derived_scenarios(self) -> list[ErrorScenario]:
        return [
            *self._validation_scenarios(),
            *self._auth_scenarios(),
            *self._not_found_scenarios(),
            *self._throttle_scenarios(),
        ]

    def _validation_scenarios(self) -> list[ErrorScenario]:
        """A missing required field, named from the request serializer."""
        if self.method not in BODY_METHODS:
            return []
        serializer = force_instance(self.get_request_serializer())
        fields = getattr(serializer, "fields", None)
        if not fields:
            return []
        writable = [name for name, field in fields.items() if not field.read_only]
        required = [name for name in writable if fields[name].required]
        if required and self.method != "PATCH":
            return [ErrorScenario(errors.REQUIRED, errors.REQUIRED.message, required[0])]
        if writable:
            return [ErrorScenario(errors.INVALID, errors.INVALID.message, writable[0])]
        return []

    def _auth_scenarios(self) -> list[ErrorScenario]:
        """Not authenticated, plus any permission class carrying a registered code."""
        try:
            permissions = self.view.get_permissions()
        except Exception:  # noqa: BLE001 - documentation must never break the schema
            return []
        if self._anonymous_allowed(permissions):
            return []

        # Session authentication sends no challenge header, so DRF answers 403.
        try:
            challenge = self.view.get_authenticate_header(self.view.request)
        except Exception:  # noqa: BLE001
            challenge = None
        scenarios = [
            ErrorScenario(
                errors.NOT_AUTHENTICATED,
                errors.NOT_AUTHENTICATED.message,
                status=None if challenge else 403,
            )
        ]
        for permission in permissions:
            error = get_error(getattr(permission, "code", None))
            if error is not None:
                scenarios.append(
                    ErrorScenario(error, getattr(permission, "message", error.message))
                )
        return scenarios

    def _anonymous_allowed(self, permissions) -> bool:
        """Ask each permission whether an anonymous caller gets through.

        Covers AllowAny and method-dependent classes such as
        IsAuthenticatedOrReadOnly alike. Built here rather than taken from the
        generator's mock request, which carries the user viewing the docs. A
        permission that cannot answer from this minimal request is assumed to
        require authentication, matching the project's fail-closed defaults.
        """
        request = SimpleNamespace(
            method=self.method, user=AnonymousUser(), auth=None, query_params={}, data={}
        )
        for permission in permissions:
            try:
                if not permission.has_permission(request, self.view):
                    return False
            except Exception:  # noqa: BLE001
                return False
        return True

    def _not_found_scenarios(self) -> list[ErrorScenario]:
        """A detail route can name an object that does not exist."""
        if "{" not in self.path:
            return []
        message = errors.NOT_FOUND.message
        try:
            model = self.view.get_queryset().model
            message = f"No {model._meta.object_name} matches the given query."
        except Exception:  # noqa: BLE001 - views without a queryset keep the generic message
            pass
        return [ErrorScenario(errors.NOT_FOUND, message)]

    def _throttle_scenarios(self) -> list[ErrorScenario]:
        try:
            throttled = bool(self.view.get_throttles())
        except Exception:  # noqa: BLE001
            throttled = False
        if not throttled:
            return []
        message = "Request was throttled. Expected available in 60 seconds."
        return [ErrorScenario(errors.THROTTLED, message)]


def _owning_app(view, method: str) -> str | None:
    """``<app>`` for a view defined in ``apps.<app>``, else None."""
    module = type(view).__module__
    if module.startswith("rest_framework."):
        # @api_view builds its view class inside DRF; the handler is the function.
        module = getattr(getattr(view, method.lower(), None), "__module__", None) or ""
    parts = module.split(".")
    return parts[1] if len(parts) > 2 and parts[0] == "apps" else None


def with_meta(schema: dict) -> dict:
    """Return ``schema`` as MetaJSONRenderer sends it.

    Mirrors the renderer: an object gains a top-level ``meta`` (paginated
    bodies included, keeping their keys); anything else is wrapped as
    ``{"data": ..., "meta": ...}``. Serializer and pagination components are
    objects, so a ``$ref`` counts as one.
    """
    if "$ref" in schema or "allOf" in schema or schema.get("type") == "object":
        return {
            "allOf": [
                schema,
                {"type": "object", "properties": {"meta": META_REF}, "required": ["meta"]},
            ]
        }
    return {
        "type": "object",
        "properties": {"data": schema, "meta": META_REF},
        "required": ["data", "meta"],
    }


def _describe(scenarios: list[ErrorScenario]) -> str:
    return "; ".join(f"`{s.error.code}` {s.message}" for s in scenarios)


def _examples(scenarios: list[ErrorScenario]) -> dict:
    """Name each example by code and field, numbering repeats so none is overwritten."""
    examples = {}
    for scenario in scenarios:
        base = (
            f"{scenario.error.code} ({scenario.field})" if scenario.field else scenario.error.code
        )
        name, n = base, 1
        while name in examples:
            n += 1
            name = f"{base} #{n}"
        examples[name] = {"summary": scenario.message, "value": scenario.body()}
    return examples


def error_schema_hook(result, generator, request, public):
    """Postprocessing hook: error schemas, per-operation responses, code catalogue."""
    catalogue = all_errors()

    schemas = result.setdefault("components", {}).setdefault("schemas", {})
    schemas.update(_error_schemas([error.code for error in catalogue]))

    for path_item in result.get("paths", {}).values():
        for method, operation in path_item.items():
            if method in HTTP_METHODS:
                _attach_error_responses(operation.setdefault("responses", {}))

    info = result.setdefault("info", {})
    info["description"] = f"{info.get('description', '')}\n\n{_catalogue_markdown(catalogue)}"
    return result


def _attach_error_responses(responses: dict) -> None:
    """Give any 4xx/5xx still without a body the error schema; add a ``4XX`` catch-all.

    ``ApiAutoSchema`` already fills in the responses it documents; this
    covers views on another schema class.
    """
    for status_code, response in responses.items():
        if str(status_code)[0] in "45" and "content" not in response:
            response["content"] = {"application/json": {"schema": ERROR_RESPONSE_REF}}
    responses.setdefault(
        "4XX",
        {
            "description": "Any other client error. See the error code catalogue in the "
            "API description.",
            "content": {"application/json": {"schema": ERROR_RESPONSE_REF}},
        },
    )


def _error_schemas(codes: list[str]) -> dict:
    # No property-level examples here: Swagger would assemble them into one
    # sample shared by every endpoint, pairing unrelated codes and fields.
    # Examples live on each operation's responses instead.
    return {
        "ErrorItem": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "enum": codes},
                "message": {"type": "string"},
                "field": {
                    "type": "string",
                    "description": "Request field the error refers to; absent otherwise.",
                },
            },
            "required": ["code", "message"],
        },
        "ResponseMeta": {
            "type": "object",
            "description": "Added to every JSON response (spec 0000 section 8).",
            "properties": {
                "timestamp": {
                    "type": "string",
                    "format": "date-time",
                    "description": "Server time in IST (Asia/Kolkata).",
                    "example": EXAMPLE_META["timestamp"],
                },
                "app_version": {
                    "type": "string",
                    "description": "Git commit of the running build.",
                    "example": EXAMPLE_META["app_version"],
                },
                "spec_version": {
                    "type": "string",
                    "description": "API coding spec version.",
                    "example": SPEC_VERSION,
                },
            },
            "required": ["timestamp", "app_version", "spec_version"],
        },
        "ErrorResponse": {
            "type": "object",
            "properties": {
                "errors": {
                    "type": "array",
                    "items": {"$ref": "#/components/schemas/ErrorItem"},
                    "minItems": 1,
                },
                "meta": META_REF,
            },
            "required": ["errors", "meta"],
            "example": {
                "errors": [{"code": "E00001", "message": "Invalid value."}],
                "meta": EXAMPLE_META,
            },
        },
    }


def _catalogue_markdown(catalogue: list[ErrorCode]) -> str:
    rows = [f"| `{e.code}` | {e.status} | {e.domain} | {e.message} |" for e in catalogue]
    return "\n".join(
        [
            "## Error codes",
            "",
            "Every error response has the body "
            '`{"errors": [{"code": "...", "message": "...", "field": "..."}], "meta": {...}}`. '
            "Branch on `code`; `message` is for display and may vary. "
            "`field` is present only when the error refers to one request field.",
            "",
            "| Code | HTTP | Domain | Default message |",
            "| --- | --- | --- | --- |",
            *rows,
        ]
    )
