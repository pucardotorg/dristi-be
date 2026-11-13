"""Drafting, editing, withdrawing and resolving flags (spec 0024 #3.2, #3.3, #3.5, #4.5).

Flags are drafted on the open scrutiny round only, which is locked first, so
two officers drafting on the same target get one flag and ``E09009`` (#9.4).
Nothing reaches the filer until the round is sent back.
"""

import uuid

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import NotFound

from apps.api.errors import BusinessError

from .. import errors, ports
from ..enums import CourtRole, FlagStatus, FlagTarget, RoundStage
from ..models import ScrutinyFlag
from .rounds import lock_open_round, require_role


def auto_note(source):
    """Return the note on a date marked because ``source`` was flagged (#3.3)."""
    return f"Marked because {source.target_label} was flagged"


def draft(case_id, actor, *, target_type, target_ref, note="", reason_code="", document_issue=None):
    """Draft a flag, and return every flag created (#8.1).

    ``document_issue`` (``document_id``, ``reason_code``, ``note``) drafts a
    linked document flag with a field flag (*Save both*). A field flag on a
    date marks every date downstream of it that applies to the case.
    """
    with transaction.atomic():
        round_ = lock_open_round(case_id, RoundStage.SCRUTINY)
        require_role(actor, round_, CourtRole.SCRUTINY_OFFICER)
        case = round_.case
        catalogue = ports.fields(case) if target_type == FlagTarget.FIELD else {}
        if document_issue and target_type != FlagTarget.FIELD:
            raise BusinessError(
                errors.FLAG_TARGET_UNKNOWN,
                "A document issue is saved together with a field flag only.",
                field="document_issue",
            )
        flag = _draft_one(round_, target_type, target_ref, note, reason_code, catalogue)
        created = [flag]
        if document_issue:
            issue = _draft_one(
                round_,
                FlagTarget.DOCUMENT,
                str(document_issue.get("document_id") or ""),
                document_issue.get("note") or "",
                document_issue.get("reason_code") or "",
                catalogue,
                prefix="document_issue.",
            )
            flag.linked_flag, issue.linked_flag = issue, flag
            flag.save()
            issue.save()
            created.append(issue)
        if target_type == FlagTarget.FIELD:
            created += _auto_mark(round_, flag, catalogue)
    return created


def _draft_one(round_, target_type, target_ref, note, reason_code, catalogue, prefix=""):
    ref_field = f"{prefix}document_id" if prefix else "target_ref"
    target_ref, label, section, value = _resolve_target(
        round_.case, target_type, target_ref, catalogue, ref_field
    )
    note = (note or "").strip()
    _check_note(target_type, note, reason_code, f"{prefix}note")
    if _live(round_, target_type, target_ref).exists():
        raise BusinessError(errors.FLAG_DUPLICATE, field=ref_field)
    return ScrutinyFlag.objects.create(
        round=round_,
        target_type=target_type,
        target_ref=target_ref,
        target_label=label,
        section_id=section,
        reason_code=reason_code or "",
        note=note,
        value_at_flag=value,
        status=FlagStatus.DRAFT,
    )


def _resolve_target(case, target_type, target_ref, catalogue, ref_field):
    """Return ``(ref, label, section, value)`` for a target on the case, or refuse it (#3.2)."""
    if target_type == FlagTarget.FIELD:
        field = catalogue.get(target_ref)
        if field is not None:
            return field.ref, field.label, field.section, field.value
    elif target_type == FlagTarget.SECTION:
        if target_ref in ports.SECTIONS:
            return target_ref, ports.SECTIONS[target_ref], target_ref, None
    elif target_type == FlagTarget.DOCUMENT:
        document = _document(case, target_ref)
        if document is not None:
            # The synopsis and complaint render from fields; flag those (DOC-01).
            if ports.is_generated(document):
                raise BusinessError(errors.GENERATED_DOCUMENT_NOT_FLAGGABLE, field=ref_field)
            label = document.get_document_type_display()
            return str(document.pk), label, ports.DOCUMENTS_SECTION, None
    elif target_type == FlagTarget.OATH:
        if not ports.oath_required(case):
            raise BusinessError(errors.OATH_NOT_REQUIRED, field=ref_field)
        for oath in ports.oaths(case):
            if str(oath["id"]) == target_ref:
                return target_ref, f"Oath of {oath['complainant']}", "", None
    raise BusinessError(errors.FLAG_TARGET_UNKNOWN, field=ref_field)


def _document(case, document_id):
    try:
        document_id = uuid.UUID(document_id)
    except ValueError:
        return None
    return ports.active_document(case, document_id)


def _check_note(target_type, note, reason_code, field):
    """A field, section or oath flag needs a note; a document flag a reason or a note (``E09004``)."""
    if note or (target_type == FlagTarget.DOCUMENT and reason_code):
        return
    raise BusinessError(errors.FLAG_NOTE_REQUIRED, field=field)


def _live(round_, target_type, target_ref):
    return round_.flags.filter(target_type=target_type, target_ref=target_ref).exclude(
        status=FlagStatus.WITHDRAWN
    )


def _auto_mark(round_, source, catalogue):
    """Draft a flag on each date downstream of ``source`` that has none yet (#3.3)."""
    created = []
    for ref in ports.downstream(round_.case, source.target_ref, catalogue):
        if _live(round_, FlagTarget.FIELD, ref).exists():
            continue
        field = catalogue[ref]
        created.append(
            ScrutinyFlag.objects.create(
                round=round_,
                target_type=FlagTarget.FIELD,
                target_ref=ref,
                target_label=field.label,
                section_id=field.section,
                note=auto_note(source),
                value_at_flag=field.value,
                auto_marked_by=source,
                status=FlagStatus.DRAFT,
            )
        )
    return created


def edit(case_id, flag_id, actor, *, note=None, reason_code=None):
    """Change a draft's note or reason. An auto-marked date given its own note is kept on withdrawal."""
    with transaction.atomic():
        flag = _draft_for_update(case_id, flag_id, actor)
        if note is not None:
            flag.note = note.strip()
        if reason_code is not None:
            flag.reason_code = reason_code
        _check_note(flag.target_type, flag.note, flag.reason_code, "note")
        flag.save()
    return flag


def withdraw(case_id, flag_id, actor):
    """Withdraw a draft, with the dates it marked that the officer did not edit (#3.3).

    A linked field flag or document issue stays (*"Flag removed. The document
    issue … stays."*).
    """
    with transaction.atomic():
        flag = _draft_for_update(case_id, flag_id, actor)
        flag.status = FlagStatus.WITHDRAWN
        flag.save()
        for child in flag.auto_marked_flags.filter(status=FlagStatus.DRAFT, note=auto_note(flag)):
            child.status = FlagStatus.WITHDRAWN
            child.save()
    return flag


def _draft_for_update(case_id, flag_id, actor):
    round_ = lock_open_round(case_id, RoundStage.SCRUTINY)
    require_role(actor, round_, CourtRole.SCRUTINY_OFFICER)
    flag = _flag_of_case(case_id, flag_id)
    if flag.round_id != round_.pk or flag.status != FlagStatus.DRAFT:
        raise BusinessError(errors.FLAG_NOT_DRAFT)
    return flag


def _flag_of_case(case_id, flag_id):
    flag = ScrutinyFlag.objects.filter(pk=flag_id, round__case_id=case_id).first()
    if flag is None:
        raise NotFound("Flag not found.")
    return flag


def resolve(case_id, flag_id, actor):
    """Resolve an item carried from an earlier round, with its whole ``carried_from`` chain (#4.5)."""
    with transaction.atomic():
        round_ = lock_open_round(case_id, RoundStage.SCRUTINY)
        require_role(actor, round_, CourtRole.SCRUTINY_OFFICER)
        flag = _flag_of_case(case_id, flag_id)
        carried_draft = (
            flag.round_id == round_.pk
            and flag.status == FlagStatus.DRAFT
            and flag.carried_from_id is not None
        )
        if not carried_draft:
            raise BusinessError(
                errors.FLAG_NOT_DRAFT, "Only an item carried from an earlier round can be resolved."
            )
        now, item = timezone.now(), flag
        while item is not None:
            item.status, item.resolved_by, item.resolved_at = FlagStatus.RESOLVED, actor, now
            item.save()
            item = item.carried_from
    return flag
