"""Rounds and the decisions that close them (spec 0024 #4, #6).

Each decision locks the open round, checks the actor's court role, then locks
the case and moves it, in one transaction (#9.4). Roles are read when the
action is taken, never snapshotted (#2.2).
"""

import logging
import uuid

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.api.errors import BusinessError
from apps.cases.models import CaseStatus

from .. import errors, ports
from ..enums import CourtRole, FlagStatus, FlagTarget, RoundDecision, RoundStage, RoutingReason
from ..models import ScrutinyFlag, ScrutinyRound

logger = logging.getLogger(__name__)

# The role a stage's actions need at the establishment (#2.2).
STAGE_ROLE = {
    RoundStage.SCRUTINY: CourtRole.SCRUTINY_OFFICER,
    RoundStage.REGISTRATION: CourtRole.CASE_REGISTERER,
}
# Sent to the filer and not yet resolved; carried into the next round (#4.1).
UNRESOLVED = (FlagStatus.RAISED, FlagStatus.RESPONDED)


def open_round(case, visit_id=None, routing_reason=""):
    """Open the round for the stage ``case`` has just entered (#4.1), or return the open one.

    Numbered by visit of that stage. A scrutiny round after a send back is
    ``RESUBMITTED``; a registration round keeps the courtroom and type chosen
    at Forward. Every unresolved flag of the previous round is carried over as
    a draft, and the correction scope is closed. Returns None when the case is
    in no stage, or has no court establishment to be scrutinised at.
    """
    stage = ports.STATUS_STAGE.get(case.status)
    if stage is None:
        return None
    with transaction.atomic():
        current = ScrutinyRound.objects.filter(case=case, decision="").first()
        if current is not None:
            return current
        previous = ScrutinyRound.objects.filter(case=case).order_by("-created_at").first()
        establishment_id = previous.establishment_id if previous else ports.establishment_id(case)
        if establishment_id is None:
            logger.error("event=SCRUTINY_ROUND_NOT_OPENED case=%s reason=no court", case.pk)
            return None
        fields = {}
        if stage == RoundStage.REGISTRATION and previous is not None:
            fields = {
                "courtroom_id": previous.courtroom_id,
                "registration_type": previous.registration_type,
            }
        elif previous is not None and previous.decision == RoundDecision.SENT_BACK:
            routing_reason = RoutingReason.RESUBMITTED
        round_ = ScrutinyRound.objects.create(
            case=case,
            stage=stage,
            number=ScrutinyRound.objects.filter(case=case, stage=stage).count() + 1,
            visit_id=visit_id or uuid.uuid4(),
            establishment_id=establishment_id,
            routing_reason=routing_reason,
            **fields,
        )
        if previous is not None:
            _carry_forward(previous, round_)
        ports.close_correction(case)
    return round_


def _carry_forward(previous, round_):
    """Copy each unresolved flag of ``previous`` into ``round_`` as a draft; mark it ``CARRIED``.

    Unresolved: raised or responded, or a carried draft that travelled with a
    forwarded case. Date-chain and field–document links are kept between copies.
    """
    carried = list(
        previous.flags.filter(
            Q(status__in=UNRESOLVED) | Q(status=FlagStatus.DRAFT, carried_from__isnull=False)
        ).order_by("created_at")
    )
    copies = {}
    for flag in carried:
        copies[flag.pk] = ScrutinyFlag.objects.create(
            round=round_,
            target_type=flag.target_type,
            target_ref=flag.target_ref,
            target_label=flag.target_label,
            section_id=flag.section_id,
            reason_code=flag.reason_code,
            note=flag.note,
            value_at_flag=flag.value_at_flag,
            carried_from=flag,
            status=FlagStatus.DRAFT,
        )
        flag.status = FlagStatus.CARRIED
        flag.save()
    for flag in carried:
        copy = copies[flag.pk]
        copy.auto_marked_by = copies.get(flag.auto_marked_by_id)
        copy.linked_flag = copies.get(flag.linked_flag_id)
        if copy.auto_marked_by or copy.linked_flag:
            copy.save()


def lock_open_round(case_id, stage):
    """Return the case's open round of ``stage``, locked; ``E09001`` when there is none."""
    round_ = (
        ScrutinyRound.objects.select_for_update()
        .select_related("case")
        .filter(case_id=case_id, decision="")
        .first()
    )
    if round_ is None or round_.stage != stage:
        raise BusinessError(errors.ROUND_NOT_OPEN)
    return round_


def require_role(actor, round_, role):
    """Refuse ``actor`` unless they hold ``role`` at the round's establishment (``E09008``)."""
    if role not in ports.roles_held(actor, round_.establishment_id):
        raise BusinessError(errors.ROLE_REQUIRED)


def lock_case(case_id, expected_version=None):
    """Lock the case after its round (#9.4); ``412 E08005`` when ``If-Match`` is stale."""
    case = ports.lock_case(case_id)
    if expected_version is not None and expected_version != ports.workflow_version(case):
        raise BusinessError(ports.WORKFLOW_STALE)
    return case


def unresolved_count(round_):
    """Return how many flags of the open round are still unresolved: its carried drafts."""
    return round_.flags.filter(status=FlagStatus.DRAFT, carried_from__isnull=False).count()


def start(case_id, actor, stage):
    """Record who first started the stage's open round (#4.2). Repeat calls change nothing."""
    with transaction.atomic():
        round_ = lock_open_round(case_id, stage)
        require_role(actor, round_, STAGE_ROLE[stage])
        if round_.started_by_id is None:
            round_.started_by, round_.started_at = actor, timezone.now()
            round_.save()
    return round_


def send_back(case_id, actor, *, expected_version=None):
    """Raise every draft flag and send the case to the filer for correction (#4.3)."""
    with transaction.atomic():
        round_ = lock_open_round(case_id, RoundStage.SCRUTINY)
        require_role(actor, round_, CourtRole.SCRUTINY_OFFICER)
        case = lock_case(case_id, expected_version)
        drafts = list(round_.flags.filter(status=FlagStatus.DRAFT))
        if not drafts:
            raise BusinessError(errors.NOTHING_TO_SEND_BACK)
        for flag in drafts:
            flag.status = FlagStatus.RAISED
            flag.save()
        ports.open_for_correction(case, _marked_scope(case, drafts), round_.id)
        _decide(round_, actor, RoundDecision.SENT_BACK)
        ports.move_case(case, CaseStatus.PENDING_CORRECTION)
    return round_


def _marked_scope(case, flags):
    """Return what a scrutiny send back opens: the flagged targets and the delay fields (#5.1)."""

    def targets(target_type):
        return [flag.target_ref for flag in flags if flag.target_type == target_type]

    return {
        "mode": "MARKED",
        "fields": targets(FlagTarget.FIELD),
        "sections": targets(FlagTarget.SECTION),
        "documents": targets(FlagTarget.DOCUMENT),
        "oaths": targets(FlagTarget.OATH),
        "required": _delay_fields(case),
    }


def _delay_fields(case):
    # Required whether or not they were flagged (REF-05, REF-06).
    return list(ports.DELAY_FIELDS) if ports.delay_alert(case) else []


def forward(
    case_id,
    actor,
    *,
    courtroom_id=None,
    registration_type="",
    acknowledge_open_items=False,
    expected_version=None,
):
    """Forward the case to the Case registerer (#4.4); for a Scrutiny officer who does not register."""
    return _decide_at_scrutiny(
        case_id,
        actor,
        False,
        courtroom_id,
        registration_type,
        acknowledge_open_items,
        expected_version,
    )


def register_at_scrutiny(
    case_id,
    actor,
    *,
    courtroom_id=None,
    registration_type="",
    acknowledge_open_items=False,
    expected_version=None,
):
    """Register the case at Scrutiny (#4.4); for a Scrutiny officer who is also a Case registerer."""
    return _decide_at_scrutiny(
        case_id,
        actor,
        True,
        courtroom_id,
        registration_type,
        acknowledge_open_items,
        expected_version,
    )


def _decide_at_scrutiny(
    case_id, actor, register, courtroom_id, registration_type, acknowledge, expected_version
):
    with transaction.atomic():
        round_ = lock_open_round(case_id, RoundStage.SCRUTINY)
        roles = ports.roles_held(actor, round_.establishment_id)
        if CourtRole.SCRUTINY_OFFICER not in roles:
            raise BusinessError(errors.ROLE_REQUIRED)
        # Roles decide which of the two a person gets (SCR-11).
        if register != (CourtRole.CASE_REGISTERER in roles):
            raise BusinessError(errors.ACTION_NOT_FOR_ROLES)
        case = lock_case(case_id, expected_version)
        courtroom = _choose_courtroom(round_.establishment_id, courtroom_id)
        type_code, stored_type = _choose_registration_type(
            round_.establishment_id, registration_type
        )
        open_items = _acknowledged_open_items(round_, acknowledge)
        for flag in round_.flags.filter(status=FlagStatus.DRAFT, carried_from__isnull=True):
            flag.status = FlagStatus.WITHDRAWN
            flag.save()
        ports.set_court(case, courtroom.pk)
        round_.courtroom_id, round_.registration_type = courtroom.pk, stored_type
        decision = RoundDecision.REGISTERED if register else RoundDecision.FORWARDED
        _decide(
            round_,
            actor,
            decision,
            open_items_acknowledged=bool(open_items),
            open_items_at_decision=open_items,
        )
        if register:
            ports.register_case(case, type_code, actor)
        else:
            ports.move_case(case, CaseStatus.PENDING_REGISTRATION)
    return round_


def _choose_courtroom(establishment_id, courtroom_id):
    """Return the chosen courtroom of the establishment; nothing is pre-selected (``SCR-16``)."""
    rooms = ports.courtrooms(establishment_id)
    if courtroom_id is None and len(rooms) == 1:
        return rooms[0]
    for room in rooms:
        if courtroom_id is not None and str(room.pk) == str(courtroom_id):
            return room
    raise BusinessError(errors.COURTROOM_REQUIRED, field="courtroom_id")


def _choose_registration_type(establishment_id, code, preselected=""):
    """Return ``(type to number from, type to store on the round)`` (``SCR-13``).

    With one type the choice is not shown and nothing is stored; with several,
    one must be chosen, or kept from Forward when registering.
    """
    types = ports.registration_types(establishment_id)
    code = code or preselected
    if len(types) == 1 and code in ("", types[0].code):
        return types[0].code, ""
    if len(types) > 1 and code in {kind.code for kind in types}:
        return code, code
    raise BusinessError(errors.REGISTRATION_TYPE_REQUIRED, field="registration_type")


def _acknowledged_open_items(round_, acknowledged):
    """Return the round's unresolved items, refusing ``E09006`` unless they are acknowledged."""
    count = unresolved_count(round_)
    if count and not acknowledged:
        raise BusinessError(
            errors.OPEN_ITEMS_NOT_ACKNOWLEDGED,
            f"The case has {count} open item{'s' if count != 1 else ''}; "
            "acknowledge them to continue.",
        )
    return count


def register(
    case_id, actor, *, registration_type="", acknowledge_open_items=False, expected_version=None
):
    """Register a forwarded case (#6.1): the type chosen at Forward may be changed, and is final."""
    with transaction.atomic():
        round_ = lock_open_round(case_id, RoundStage.REGISTRATION)
        require_role(actor, round_, CourtRole.CASE_REGISTERER)
        case = lock_case(case_id, expected_version)
        type_code, stored_type = _choose_registration_type(
            round_.establishment_id, registration_type, preselected=round_.registration_type
        )
        open_items = _acknowledged_open_items(round_, acknowledge_open_items)
        round_.registration_type = stored_type
        _decide(
            round_,
            actor,
            RoundDecision.REGISTERED,
            open_items_acknowledged=bool(open_items),
            open_items_at_decision=open_items,
        )
        ports.register_case(case, type_code, actor)
    return round_


def registration_send_back(case_id, actor, comment, *, expected_version=None):
    """Send a forwarded case to the filer with one comment, everything but the oath open (#6.2)."""
    with transaction.atomic():
        round_ = lock_open_round(case_id, RoundStage.REGISTRATION)
        require_role(actor, round_, CourtRole.CASE_REGISTERER)
        case = lock_case(case_id, expected_version)
        comment = (comment or "").strip()
        if not comment:
            raise BusinessError(errors.SEND_BACK_COMMENT_REQUIRED, field="comment")
        scope = {"mode": "ALL", "required": _delay_fields(case)}
        ports.open_for_correction(case, scope, round_.id)
        _decide(round_, actor, RoundDecision.SENT_BACK, comment=comment)
        ports.move_case(case, CaseStatus.PENDING_CORRECTION)
    return round_


def set_title(case_id, actor, *, complainant, accused):
    """Change the parties' display names (*Edit case title*, #4.6) at either stage."""
    with transaction.atomic():
        round_ = (
            ScrutinyRound.objects.select_for_update().filter(case_id=case_id, decision="").first()
        )
        if round_ is None:
            raise BusinessError(errors.ROUND_NOT_OPEN)
        require_role(actor, round_, STAGE_ROLE[round_.stage])
        ports.set_case_title(ports.lock_case(case_id), complainant, accused, actor)
    return round_


def _decide(round_, actor, decision, **fields):
    round_.decision, round_.decided_by, round_.decided_at = decision, actor, timezone.now()
    for name, value in fields.items():
        setattr(round_, name, value)
    round_.save()
