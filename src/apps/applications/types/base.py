"""The contract every application type implements (spec 0033 #3.2).

A type is code: what it may hold in ``data``, when it is offered, what the form
pre-fills, what makes it complete, what its PDF prints and what acceptance
does. ``ApplicationType`` rows only switch types on (#4.1).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, ClassVar
from uuid import UUID

import jsonschema

from .. import errors

if TYPE_CHECKING:  # pragma: no cover
    from ..models import Application
    from ..ports import CaseAccess

EMPTY_SCHEMA = {"type": "object", "maxProperties": 0}


@dataclass(frozen=True)
class FilerContext:
    """Who is asking, on which case (#3.2)."""

    case_id: UUID
    user: object
    access: CaseAccess

    @property
    def side(self):
        """The caller's side as a drafter, or None."""
        return self.access.side if self.access.is_drafter else None


@dataclass(frozen=True)
class FieldProblem:
    """One thing wrong with an application, on its path (#3.2)."""

    field: str
    code: str
    message: str


@dataclass
class Problems:
    """Collects problems, so every one is reported, not only the first."""

    items: list[FieldProblem] = field(default_factory=list)

    def add(self, path, error, message=None):
        self.items.append(FieldProblem(path, error.code, message or error.message))

    def missing(self, path, message=None):
        self.add(path, errors.APPLICATION_INCOMPLETE, message)

    def __bool__(self):
        return bool(self.items)


class ApplicationTypeSpec:
    """One application type (#3.1, #3.2). Subclasses set ``code`` and override the hooks they need."""

    code: ClassVar[str]
    label: ClassVar[str]
    expires_with_hearing: ClassVar[bool] = False
    needs_hearing: ClassVar[bool] = False
    has_workflow: ClassVar[bool] = False
    runs_on_reject: ClassVar[bool] = False
    # ``data`` paths whose values are document ids, with the label the server
    # names the attached file by (``DSB-23``). A path ending in ``[]`` is a list.
    document_fields: ClassVar[dict[str, str]] = {}
    data_schema: ClassVar[dict] = EMPTY_SCHEMA
    # Content types an upload to this type may be; None takes every accepted format (#6.4).
    document_formats: ClassVar[tuple[str, ...] | None] = None

    def unavailable_reason(self, ctx: FilerContext) -> str | None:
        """Why the type is not offered to the caller, or None (``ALC-26``)."""
        return None

    def form_context(self, ctx: FilerContext) -> dict:
        """The type's system fields and prefills for the form (#6.2)."""
        return {}

    def schema_problems(self, data) -> list[FieldProblem]:
        """Shape problems against ``data_schema`` (#3.2): unknown keys are ``E13009``."""
        problems = Problems()
        validator = jsonschema.Draft202012Validator(self.data_schema)
        for error in sorted(validator.iter_errors(data), key=lambda e: list(e.path)):
            path = _path(["data", *error.path])
            if error.validator == "additionalProperties":
                known = set(error.schema.get("properties", {}))
                for key in sorted(set(error.instance) - known):
                    problems.add(f"{path}.{key}", errors.FIELD_NOT_FOR_TYPE)
            elif error.validator == "maxProperties" and not error.path:
                for key in sorted(error.instance):
                    problems.add(f"data.{key}", errors.FIELD_NOT_FOR_TYPE)
            else:
                from apps.api import errors as api_errors

                problems.add(path, api_errors.INVALID, error.message)
        return problems.items

    def validate(self, app: Application, *, complete: bool) -> list[FieldProblem]:
        """Rules beyond shape. ``complete`` adds mandatory fields (#3.2, ``ALC-27``)."""
        return []

    def document_refs(self, data: dict) -> list[tuple[str, str]]:
        """``(field_path, document_id)`` for every document ``data`` references."""
        refs = []
        for path in self.document_fields:
            refs.extend(_collect(data, path.split("."), ["data"]))
        return refs

    def render_entries(self, app: Application) -> list[dict]:
        """The type's fields as term and value, labels resolved (#6.5a)."""
        return []

    def render_title(self, app: Application) -> str:
        """The application's heading on paper."""
        return app.application_type.label

    def prepare(self, app: Application) -> None:
        """Computed fields stored at *Proceed to sign* (Edit Litigant Details' ``changes``)."""

    def on_accept(self, app: Application, *, order_id, values: dict) -> dict:
        """The type's workflow on acceptance (``ALC-16``); idempotent; returns what it made."""
        return {}

    def on_reject(self, app: Application, *, order_id) -> None:
        """Only where the type needs it (Delay Condonation)."""

    def decision_hint(self, app: Application) -> str | None:
        """A line for the court's decision screen (#14.4), or None."""
        return None

    def document_label(self, field_path: str) -> str:
        """The name the server gives a file attached to ``field_path`` (``DSB-23``)."""
        pattern = _pattern(field_path)
        for path, label in self.document_fields.items():
            if _pattern(path) == pattern:
                return label
        return ""

    def declares_document_field(self, field_path: str) -> bool:
        return bool(self.document_label(field_path))


def _pattern(path):
    """``sureties[1].id_proof_document_ids`` -> ``sureties[].id_proof_document_ids``."""
    import re

    return re.sub(r"\[\d+\]", "[]", path).removeprefix("data.")


def _path(parts):
    path = ""
    for part in parts:
        path += f"[{part}]" if isinstance(part, int) else (f".{part}" if path else str(part))
    return path


def _collect(value, parts, prefix):
    """Walk ``value`` along ``parts`` (``a[]``, ``b``) and return ``(path, id)`` pairs."""
    if not parts:
        if isinstance(value, list):
            return [(_path(prefix), str(item)) for item in value if item is not None]
        return [(_path(prefix), str(value))] if value else []
    head, rest = parts[0], parts[1:]
    is_list = head.endswith("[]")
    key = head.removesuffix("[]")
    if not isinstance(value, dict) or key not in value:
        return []
    child = value[key]
    if is_list:
        if not isinstance(child, list):
            return []
        found = []
        for index, item in enumerate(child):
            found.extend(_collect(item, rest, [*prefix, key, index]))
        return found
    return _collect(child, rest, [*prefix, key])


def is_uuid(value) -> bool:
    try:
        UUID(str(value))
    except (TypeError, ValueError):
        return False
    return True
