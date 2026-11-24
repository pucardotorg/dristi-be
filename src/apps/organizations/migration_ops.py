"""Data-migration helpers for adding, splitting and removing court actions (spec 0029 #3.4).

For ``RunPython`` in the owning module's migrations::

    from apps.organizations.migration_ops import add_action_to_roles_with

    def forwards(apps, schema_editor):
        add_action_to_roles_with(apps, "orders.use_shortcuts", like="orders.edit_text")

The migration depends on ``("organizations", "0003_court_roles")`` (or later).

The helpers use the historical models from ``apps``, never the services or
the registry, so a migration still runs after the code changes again; they
take codes as strings for the same reason. Historical models fire no history
signals, so each helper writes the ``simple_history`` rows itself, with the
reason ``"migration <app>.<name>"``. None sends ``court_access_changed``: the
people who can do anything do not change.
"""

import inspect
import uuid

from django.utils import timezone

HISTORY_REASON_LENGTH = 100


def _models(apps):
    """Return the historical ``CourtRoleAction`` model and its history model."""
    return (
        apps.get_model("organizations", "CourtRoleAction"),
        apps.get_model("organizations", "HistoricalCourtRoleAction"),
    )


def _reason():
    """``migration <app>.<name>`` for the migration module that called the helper."""
    for frame in inspect.stack()[2:]:
        module = frame.frame.f_globals.get("__name__", "")
        parts = module.split(".")
        if "migrations" in parts:
            index = parts.index("migrations")
            if index >= 1 and index + 1 < len(parts):
                return f"migration {parts[index - 1]}.{parts[index + 1]}"[:HISTORY_REASON_LENGTH]
    return "migration"


def _record(history_model, row, history_type, reason):
    """Write one history row for ``row`` (``+`` created, ``~`` changed, ``-`` deleted)."""
    values = {field.attname: getattr(row, field.attname) for field in row._meta.concrete_fields}
    history_model.objects.create(
        **values,
        history_date=timezone.now(),
        history_type=history_type,
        history_change_reason=reason,
    )


def add_action_to_roles_with(apps, code, *, like):
    """Add ``code`` to every role, active or not, that holds ``like``, copying each row's scope.

    Idempotent: a role already holding ``code`` with that scope is left alone.
    Returns the number of rows added.
    """
    model, history_model = _models(apps)
    reason = _reason()
    added = 0
    for source in model.objects.filter(action=like).order_by("role_id", "created_at"):
        held = model.objects.filter(role_id=source.role_id, action=code)
        if any(row.scope == source.scope for row in held):
            continue
        now = timezone.now()
        row = model.objects.create(
            id=uuid.uuid4(),
            role_id=source.role_id,
            action=code,
            scope=source.scope,
            created_at=now,
            updated_at=now,
        )
        _record(history_model, row, "+", reason)
        added += 1
    return added


def remove_action_from_roles(apps, code):
    """Delete every ``CourtRoleAction`` row for ``code``. Returns the number removed."""
    model, history_model = _models(apps)
    reason = _reason()
    removed = 0
    for row in model.objects.filter(action=code):
        _record(history_model, row, "-", reason)
        row.delete()
        removed += 1
    return removed


def add_scope_code_with(apps, axis, code, *, like):
    """Add ``code`` to every scope list on ``axis`` that holds ``like``, in every role.

    ``axis`` is ``"process_types"`` or ``"channels"``. Rows with the axis
    missing already cover every code and are left alone. Idempotent. Returns
    the number of rows changed.
    """
    if axis not in ("process_types", "channels"):
        raise ValueError(f"Unknown scope axis {axis!r}.")
    model, history_model = _models(apps)
    reason = _reason()
    changed = 0
    for row in model.objects.filter(scope__isnull=False):
        codes = (row.scope or {}).get(axis)
        if not codes or like not in codes or code in codes:
            continue
        row.scope = {**row.scope, axis: sorted({*codes, code})}
        row.updated_at = timezone.now()
        row.save(update_fields=["scope", "updated_at"])
        _record(history_model, row, "~", reason)
        changed += 1
    return changed
