"""OpenAPI documentation of the standard error response (spec 0000 section 10)."""

from __future__ import annotations

from drf_spectacular.utils import OpenApiResponse

from .errors import ErrorCode, all_errors

ERROR_RESPONSE_REF = {"$ref": "#/components/schemas/ErrorResponse"}
HTTP_METHODS = {"get", "put", "post", "delete", "options", "head", "patch", "trace"}


def error_responses(*errors: ErrorCode) -> dict[int, OpenApiResponse]:
    """Document the business errors an endpoint can return, keyed by status.

    Each code is listed under its own registered status, so the documented
    status cannot drift from the one returned. The body schema is attached by
    ``error_schema_hook``::

        @extend_schema(responses={200: Out, **error_responses(errors.OTP_INVALID)})
    """
    by_status: dict[int, list[ErrorCode]] = {}
    for error in errors:
        by_status.setdefault(error.status, []).append(error)
    return {
        status_code: OpenApiResponse(
            description="; ".join(f"`{error.code}` {error.msg}" for error in grouped)
        )
        for status_code, grouped in by_status.items()
    }


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
    """Give every declared 4xx/5xx the error body and add a ``4XX`` catch-all."""
    for status_code, response in responses.items():
        if str(status_code)[0] in "45" and "content" not in response:
            response["content"] = {"application/json": {"schema": ERROR_RESPONSE_REF}}
    responses.setdefault(
        "4XX",
        {
            "description": "Error. See the error code catalogue in the API description.",
            "content": {"application/json": {"schema": ERROR_RESPONSE_REF}},
        },
    )


def _error_schemas(codes: list[str]) -> dict:
    return {
        "ErrorItem": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "enum": codes, "example": "E01001"},
                "msg": {"type": "string", "example": "Invalid or expired code."},
                "field": {
                    "type": "string",
                    "description": "Request field the error refers to; absent otherwise.",
                    "example": "profile.bar_number",
                },
            },
            "required": ["code", "msg"],
        },
        "ErrorResponse": {
            "type": "object",
            "properties": {
                "errors": {
                    "type": "array",
                    "items": {"$ref": "#/components/schemas/ErrorItem"},
                    "minItems": 1,
                },
                "meta": {
                    "type": "object",
                    "properties": {
                        "timestamp": {"type": "string", "format": "date-time"},
                        "app_version": {"type": "string"},
                        "spec_version": {"type": "string"},
                    },
                },
            },
            "required": ["errors", "meta"],
        },
    }


def _catalogue_markdown(catalogue: list[ErrorCode]) -> str:
    rows = [f"| `{e.code}` | {e.status} | {e.domain} | {e.msg} |" for e in catalogue]
    return "\n".join(
        [
            "## Error codes",
            "",
            "Every error response has the body "
            '`{"errors": [{"code": "...", "msg": "...", "field": "..."}], "meta": {...}}`. '
            "Branch on `code`; `msg` is for display and may vary. "
            "`field` is present only when the error refers to one request field.",
            "",
            "| Code | HTTP | Domain | Default message |",
            "| --- | --- | --- | --- |",
            *rows,
        ]
    )
