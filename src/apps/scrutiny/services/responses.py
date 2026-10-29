"""The filer's answers to raised flags, and resubmission (spec 0024 #5.2, #5.3).

Corrections and re-uploads are recorded from ``apps.cases`` changes, never
reported by the filer; *explain* is the only answer given directly.
"""

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import NotFound

from apps.api.errors import BusinessError
from apps.cases.models import Case, CaseStatus

from .. import errors, ports
from ..enums import FlagStatus, FlagTarget, ResponseKind
from ..models import ScrutinyFlagResponse, ScrutinyRound
from .rounds import UNRESOLVED


def _correction_round(case_id, quiet=False):
    """Return the locked case in correction and the round that sent it back.

    A case not in correction is refused, or with ``quiet`` gives ``(None, None)``.
    """
    try:
        case = ports.lock_case(case_id)
    except Case.DoesNotExist as exc:
        if quiet:
            return None, None
        raise NotFound("Case not found.") from exc
    if case.status != CaseStatus.PENDING_CORRECTION:
        if quiet:
            return None, None
        raise BusinessError(errors.ROUND_NOT_OPEN, "This case is not open for correction.")
    return case, ScrutinyRound.objects.filter(case=case).order_by("-created_at").first()


def _respond(flag, actor, kind, **fields):
    response = ScrutinyFlagResponse.objects.create(
        flag=flag, kind=kind, responded_by=actor, responded_at=timezone.now(), **fields
    )
    flag.status = FlagStatus.RESPONDED
    flag.save()
    return response


def record_field_change(case_id, field_ref, old, new, actor):
    """Record a correction of ``field_ref`` against its raised flag, or the section flag holding it.

    Receiver of ``case_field_changed``. A change outside correction is ignored.
    """
    with transaction.atomic():
        case, round_ = _correction_round(case_id, quiet=True)
        if case is None:
            return None
        ports.mark_correction_changed(case)
        open_flags = round_.flags.filter(status__in=UNRESOLVED)
        flag = open_flags.filter(target_type=FlagTarget.FIELD, target_ref=field_ref).first()
        parts = ports.split_ref(field_ref)
        if flag is None and parts is not None:
            section = parts[0].split("-")[0]
            flag = open_flags.filter(target_type=FlagTarget.SECTION, target_ref=section).first()
        if flag is None:
            return None
        return _respond(flag, actor, ResponseKind.CORRECTED, value_after=new)


def record_document_replaced(case_id, old_document_id, new_document_id, actor):
    """Record a re-upload against the flag on the replaced document.

    Receiver of ``case_document_replaced``. A replacement outside correction is ignored.
    """
    with transaction.atomic():
        case, round_ = _correction_round(case_id, quiet=True)
        if case is None:
            return None
        ports.mark_correction_changed(case)
        flag = (
            round_.flags.filter(status__in=UNRESOLVED)
            .filter(target_type=FlagTarget.DOCUMENT, target_ref=str(old_document_id))
            .first()
        )
        if flag is None:
            return None
        return _respond(flag, actor, ResponseKind.REUPLOADED, document_id=new_document_id)


def explain(case_id, flag_id, actor, note):
    """Answer a raised flag without changing anything; the court sees it as contested."""
    note = (note or "").strip()
    if not note:
        raise BusinessError(errors.EXPLANATION_REQUIRED, field="note")
    with transaction.atomic():
        _case, round_ = _correction_round(case_id)
        flag = round_.flags.filter(pk=flag_id, status__in=UNRESOLVED).first()
        if flag is None:
            raise NotFound("Flag not found.")
        return _respond(flag, actor, ResponseKind.EXPLAINED, note=note)


def submit_correction(case_id, actor):
    """Send the corrected case on to be signed again (#5.3).

    Needs at least one answered flag, or for a registration send back at least
    one change (``E09012``). Unanswered flags travel to re-scrutiny as they are.
    """
    with transaction.atomic():
        case, round_ = _correction_round(case_id)
        scope = ports.correction_scope(case) or {}
        if scope.get("mode") == "ALL":
            answered = bool(scope.get("changed"))
        else:
            answered = ScrutinyFlagResponse.objects.filter(flag__round=round_).exists()
        if not answered:
            raise BusinessError(errors.NOTHING_TO_RESUBMIT)
        ports.move_case(case, CaseStatus.PENDING_SIGN)
    return case
