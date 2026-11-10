"""Writes to a case sent back for correction (spec 0024 #5).

The court stores what the filer may change as the case's correction scope:
``mode = ALL`` opens everything; ``MARKED`` opens only the flagged values
(``fields``, plus the ``required`` ones), whole sections (``sections``) and
flagged documents (``documents``), named by the court's refs (``CHQ-3[0]``,
``LDN``). The case type's ``correction_sections`` and ``correction_fields``
translate a write into those refs.

Every write path calls ``check_write`` (or ``check_replacement``) on the locked
case before it saves. Outside correction that does nothing. In correction it
refuses a write outside the scope with ``FIELD_NOT_OPEN_FOR_CORRECTION``,
records that the filer changed something, and sends ``case_field_changed``
(or ``case_document_replaced``) in the write's transaction.
"""

from dataclasses import dataclass

from apps.api.errors import BusinessError

from .. import errors, signals
from ..models import Case, CaseStatus
from .case_types import DOCUMENTS_PART, get_config

SCOPE_KEY = "correction"
ALL = "ALL"


# The scope, kept on the detail row until the case model has a place for it


def open_for_correction(case, scope, round_id):
    """Store what the filer may change while the case is in correction."""
    row = _detail_row(case)
    row.additional_details[SCOPE_KEY] = {**scope, "round_id": str(round_id)}
    row.save(update_fields=["additional_details", "updated_at"])


def close_correction(case):
    """Clear the correction scope."""
    row = _detail_row(case)
    if row.additional_details.pop(SCOPE_KEY, None) is not None:
        row.save(update_fields=["additional_details", "updated_at"])


def get_scope(case):
    """Return the stored correction scope, or None."""
    return _detail_row(case).additional_details.get(SCOPE_KEY)


def mark_changed(case):
    """Record that the filer changed something during correction."""
    row = _detail_row(case)
    scope = row.additional_details.get(SCOPE_KEY)
    if scope is not None and not scope.get("changed"):
        scope["changed"] = True
        row.save(update_fields=["additional_details", "updated_at"])


def _detail_row(case):
    model = get_config(case.case_type).get_detail_model()
    return model.objects.get_or_create(case=case)[0]


# Checking writes


@dataclass(frozen=True)
class Change:
    """One changed value: its court ref (None if it has none), its request field and values."""

    ref: str | None
    field: str
    old: object
    new: object


def changes(case, part, old, new, *, index=None, field=""):
    """Return a ``Change`` for each key whose value differs between the dicts ``old`` and ``new``.

    ``index`` is the record index of an evidence item, carried in its refs;
    ``field`` the request field the dicts were sent as.
    """
    field_ids = get_config(case.case_type).correction_fields
    old, new = old or {}, new or {}
    found = []
    for key in sorted(old.keys() | new.keys()):
        if old.get(key) == new.get(key):
            continue
        field_id = field_ids.get((part, key))
        ref = field_id if field_id is None or index is None else f"{field_id}[{index}]"
        found.append(Change(ref, f"{field}.{key}" if field else key, old.get(key), new.get(key)))
    return found


def check_write(case, actor, part, changed=(), *, whole=False, field=None):
    """Refuse a write to ``part`` of a case in correction that is outside its scope.

    ``changed`` are the values the write changes. ``whole`` is a write that
    adds or removes an item, or changes one with no fields of its own (a
    party), so needs its whole section open; ``field`` is the request field it
    is refused on. An item may also be added when the court flagged one of the
    values it fills (a missing return memo's dates): ``changed`` then holds
    the new item's values. A write that changes nothing passes, and so does
    anything outside correction.
    """
    if case.status != CaseStatus.PENDING_CORRECTION or not (whole or changed):
        return
    scope = get_scope(case) or {}
    section = get_config(case.case_type).correction_sections.get(part)
    if scope.get("mode") != ALL and section not in scope.get("sections", ()):
        open_refs = {*scope.get("fields", ()), *scope.get("required", ())}
        if whole:
            if not any(change.ref in open_refs for change in changed):
                raise BusinessError(errors.FIELD_NOT_OPEN_FOR_CORRECTION, field=field)
        else:
            for change in changed:
                if change.ref is None or change.ref not in open_refs:
                    raise BusinessError(errors.FIELD_NOT_OPEN_FOR_CORRECTION, field=change.field)
    mark_changed(case)
    if whole:
        # The item's own values answer their field flags; the item answers its section.
        changed = [change for change in changed if change.ref is not None]
        changed.append(Change(None, field, None, None))
    for change in changed:
        signals.case_field_changed.send(
            sender=Case,
            case_id=case.pk,
            field_ref=change.ref,
            section=section,
            old=change.old,
            new=change.new,
            actor=actor,
        )


def check_replacement(case, actor, old_document, new_document):
    """Refuse replacing a document the scope does not open; otherwise announce the replacement.

    A flagged document may be replaced; an unflagged one only when the
    documents section is open (spec 0024 #5.1).
    """
    if case.status != CaseStatus.PENDING_CORRECTION:
        return
    scope = get_scope(case) or {}
    section = get_config(case.case_type).correction_sections.get(DOCUMENTS_PART)
    if (
        scope.get("mode") != ALL
        and section not in scope.get("sections", ())
        and str(old_document.pk) not in scope.get("documents", ())
    ):
        raise BusinessError(
            errors.FIELD_NOT_OPEN_FOR_CORRECTION, "Only a flagged document may be replaced."
        )
    mark_changed(case)
    signals.case_document_replaced.send(
        sender=Case,
        case_id=case.pk,
        old_document_id=old_document.pk,
        new_document_id=new_document.pk,
        actor=actor,
    )
