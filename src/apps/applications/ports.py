"""Stand-ins for the contracts other modules do not offer yet (spec 0033 #1.2).

As ``apps.scrutiny.ports`` and ``apps.hearings.ports`` do, every call to a
contract that does not exist yet goes through this module, so each stand-in is
replaced here and only here:

* **Case access** (``apps.cases.selectors.case_access`` / ``advocate_access`` /
  ``participants`` / ``state_code``, #1.1) — built here on the case models.
* **Office access** — ``OfficeMembership`` (a placeholder model of this app):
  a clerk or junior works for an advocate on every case the advocate holds.
* **Court reading** (``apps.organizations.selectors.is_court_reader``, 0029) —
  Django groups named after the PRD roles at the configured establishment and
  its courtrooms.
* **Tasks** (0011 ``TaskService``) — no task rows; court lists and
  *Needs attention* are derived from statuses. The calls are no-ops so every
  call site exists for the day the engine lands.
* **Orders** (0025) — no live orders; ``live_items_targeting`` is empty and
  ``get_order`` returns only what the transition log knows.
* **Case effects of the type workflows** (#12.2) — not built; they raise
  ``PortNotAvailable`` and the workflow stays ``FAILED`` and retryable.
"""

import logging
import uuid
from dataclasses import dataclass, field

from django.conf import settings
from django.db.models import Q
from django.utils import timezone

from apps.cases.models import (
    CaseParticipant,
    CaseStatus,
    ParticipantRole,
    PoaMandate,
    Representation,
)
from apps.locations.models import Location
from apps.organizations.models import Organization
from apps.users.models import Role

from . import conf
from .enums import Side

logger = logging.getLogger(__name__)

# Participant role -> the side it stands on (a PoA holder for the complainant, #2.1).
ROLE_SIDE = {
    ParticipantRole.COMPLAINANT: Side.COMPLAINANT,
    ParticipantRole.POA_HOLDER: Side.COMPLAINANT,
    ParticipantRole.ACCUSED: Side.ACCUSED,
}
LITIGANT_ROLES = (ParticipantRole.COMPLAINANT, ParticipantRole.ACCUSED)
LITIGANT_SIDE = {
    ParticipantRole.COMPLAINANT: Side.COMPLAINANT,
    ParticipantRole.ACCUSED: Side.ACCUSED,
}

# PLACEHOLDER (0029): the PRD roles that make someone court staff of a courtroom.
COURT_STAFF_GROUPS = ("Order drafter", "Order data filler", "Order signer")
# The roles a review or decide task goes to (#16.1).
TASK_GROUPS = ("Order drafter", "Order signer")


class PortNotAvailable(Exception):  # noqa: N818 - names the missing contract
    """A contract this module needs is not built yet."""

    code = "CONTRACT_NOT_AVAILABLE"


def active_q(end_field):
    """Active now: not deactivated and not past its end date."""
    now = timezone.now()
    return Q(is_active=True) & (
        Q(**{f"{end_field}__isnull": True}) | Q(**{f"{end_field}__gt": now})
    )


# Case access (#1.1, #2.1) ----------------------------------------------------------


@dataclass(frozen=True)
class AdvocateOption:
    """Someone who may be *Raised by* on a side, with the litigants they represent."""

    user_id: uuid.UUID
    name: str
    kind: str  # ADVOCATE or PARTY_IN_PERSON
    litigant_ids: tuple[uuid.UUID, ...]


@dataclass(frozen=True)
class CaseAccess:
    """Who the caller is on a case (#2.1)."""

    side: str | None = None
    # Advocate with vakalatnama access on the side, or a party in person.
    is_advocate_or_pip: bool = False
    # A clerk or junior working for an advocate of the side (``OfficeMembership``).
    works_for: tuple[uuid.UUID, ...] = ()
    # Any active relationship on the side: advocate, PiP, clerk, litigant, PoA holder.
    is_on_side: bool = False
    # The litigants the caller represents (an advocate) or is (a PiP).
    represents: tuple[uuid.UUID, ...] = ()
    is_litigant: bool = False
    is_poa_holder: bool = False
    participant_ids: tuple[uuid.UUID, ...] = field(default=())

    @property
    def is_drafter(self):
        """Advocate with vakalatnama, PiP, or a clerk / junior for such an advocate (#2.1)."""
        return self.is_advocate_or_pip or bool(self.works_for)

    @property
    def is_case_reader(self):
        return self.side is not None


NO_ACCESS = CaseAccess()


def _litigants(case_id):
    return CaseParticipant.objects.filter(
        active_q("end_date"), case_id=case_id, role__in=LITIGANT_ROLES
    )


def advocate_options(case_id, side=None) -> list[AdvocateOption]:
    """Advocates with vakalatnama access and parties in person, per side (#3.3).

    The litigants each represents: an advocate, their clients; a party in
    person, themselves.
    """
    roles = [role for role, s in LITIGANT_SIDE.items() if side is None or s == side]
    by_user: dict[uuid.UUID, dict] = {}
    representations = (
        Representation.objects.filter(
            active_q("to_date"), case_id=case_id, case_participant__role__in=roles
        )
        .filter(case_participant__is_active=True)
        .select_related("advocate__user", "case_participant")
        .order_by("from_date")
    )
    for rep in representations:
        user = rep.advocate.user
        entry = by_user.setdefault(
            user.pk,
            {"name": f"Adv. {rep.advocate.name or user.name}", "kind": "ADVOCATE", "ids": []},
        )
        if rep.case_participant_id not in entry["ids"]:
            entry["ids"].append(rep.case_participant_id)
    pips = (
        _litigants(case_id)
        .filter(role__in=roles, is_party_in_person=True, person__user__isnull=False)
        .select_related("person__user")
        .order_by("role", "ordinal")
    )
    for party in pips:
        user = party.person.user
        entry = by_user.setdefault(
            user.pk,
            {"name": party.name_at_filing or user.name, "kind": "PARTY_IN_PERSON", "ids": []},
        )
        if party.pk not in entry["ids"]:
            entry["ids"].append(party.pk)
    return [
        AdvocateOption(
            user_id=user_id, name=v["name"], kind=v["kind"], litigant_ids=tuple(v["ids"])
        )
        for user_id, v in by_user.items()
    ]


def office_advocate_user_ids(user) -> list[uuid.UUID]:
    """PLACEHOLDER: the advocates (their user ids) ``user`` works for as clerk or junior."""
    from .models import OfficeMembership

    if not getattr(user, "is_authenticated", False):
        return []
    return list(
        OfficeMembership.objects.filter(member=user, is_active=True).values_list(
            "advocate__user_id", flat=True
        )
    )


def case_access(case_id, user) -> CaseAccess:
    """Who ``user`` is on the case, evaluated now (#2.1, "membership when the action is taken").

    A caller is never on both sides: an advocate cannot represent both
    (0020 §6), a person cannot be both complainant and accused. A clerk working
    for advocates of both sides is resolved to the first found, complainant first.
    """
    if not getattr(user, "is_authenticated", False):
        return NO_ACCESS
    options = advocate_options(case_id)
    own_option = next((o for o in options if o.user_id == user.pk), None)
    own_parties = list(
        CaseParticipant.objects.filter(
            active_q("end_date"), case_id=case_id, person__user=user, role__in=list(ROLE_SIDE)
        ).values_list("pk", "role")
    )
    side = None
    if own_option is not None:
        side = LITIGANT_SIDE[_role_of(own_option.litigant_ids[0])]
    elif own_parties:
        side = ROLE_SIDE[own_parties[0][1]]

    works_for = ()
    if own_option is None:
        bosses = set(office_advocate_user_ids(user))
        sided = [o for o in options if o.user_id in bosses and o.kind == "ADVOCATE"]
        if side is not None:
            sided = [o for o in sided if _option_side(o) == side]
        if sided:
            side = side or _option_side(sided[0])
            works_for = tuple(o.user_id for o in sided if _option_side(o) == side)

    if side is None:
        return NO_ACCESS
    roles = {role for _, role in own_parties}
    return CaseAccess(
        side=side,
        is_advocate_or_pip=own_option is not None,
        works_for=works_for,
        is_on_side=True,
        represents=own_option.litigant_ids if own_option else (),
        is_litigant=bool(roles & set(LITIGANT_ROLES)),
        is_poa_holder=ParticipantRole.POA_HOLDER in roles,
        participant_ids=tuple(pk for pk, _ in own_parties),
    )


def _role_of(participant_id):
    return CaseParticipant.objects.values_list("role", flat=True).get(pk=participant_id)


def _option_side(option):
    return LITIGANT_SIDE[_role_of(option.litigant_ids[0])]


def side_user_ids(case_id, side) -> set[uuid.UUID]:
    """Every user with an active relationship on ``side`` (#2.1 payer, #16.1 SAME_SIDE)."""
    roles = [role for role, s in ROLE_SIDE.items() if s == side]
    users = set(
        CaseParticipant.objects.filter(
            active_q("end_date"), case_id=case_id, role__in=roles, person__user__isnull=False
        ).values_list("person__user_id", flat=True)
    )
    lit_roles = [role for role, s in LITIGANT_SIDE.items() if s == side]
    advocates = set(
        Representation.objects.filter(
            active_q("to_date"),
            case_id=case_id,
            case_participant__role__in=lit_roles,
            case_participant__is_active=True,
        ).values_list("advocate__user_id", flat=True)
    )
    users |= advocates
    from .models import OfficeMembership

    users |= set(
        OfficeMembership.objects.filter(
            is_active=True, advocate__user_id__in=advocates
        ).values_list("member_id", flat=True)
    )
    return users


def case_user_ids(case_id) -> set[uuid.UUID]:
    """Every user on the case, either side (#2.1 case reader)."""
    return side_user_ids(case_id, Side.COMPLAINANT) | side_user_ids(case_id, Side.ACCUSED)


def is_clerk(user) -> bool:
    return getattr(user, "role", None) == Role.CLERK


def participant(case_id, participant_id):
    """An active complainant or accused of the case, or None."""
    if participant_id is None:
        return None
    return _litigants(case_id).filter(pk=participant_id).select_related("person").first()


def participants(case_id, role=None):
    """The case's active litigants (and their current details), in role order."""
    queryset = _litigants(case_id).select_related("person", "institution")
    if role:
        queryset = queryset.filter(role=role)
    return list(queryset.order_by("role", "ordinal"))


def has_poa_holder(case_id, participant_id) -> bool:
    return PoaMandate.objects.filter(
        is_active=True, case_id=case_id, represented_participant_id=participant_id
    ).exists()


def is_on_file(case) -> bool:
    """Registered, with a courtroom (#3.1)."""
    return case.status == CaseStatus.REGISTERED and case.court_id is not None


def state_code(case) -> str:
    """The state the case's court sits in, as a location code (``IN_KL``), else the default.

    Read from the court's (or its parent establishment's) jurisdictions: a
    ``state`` location, or the state above a ``district`` one.
    """
    court = case.court if case is not None else None
    seen = 0
    while court is not None and seen < 3:
        for location in court.jurisdictions.all():
            found = _state_of(location)
            if found:
                return found
        court = court.parent
        seen += 1
    return conf.default_state_code()


def _state_of(location):
    hops = 0
    while location is not None and hops < 4:
        if location.location_type == Location.LocationType.STATE:
            return location.code
        location = location.parent
        hops += 1
    return ""


# Court reading (0029) ---------------------------------------------------------------


def configured_establishment():
    try:
        return uuid.UUID(str(settings.SCRUTINY_ESTABLISHMENT_ID))
    except ValueError:
        return None


def _in_establishment(court_id):
    establishment = configured_establishment()
    if establishment is None or court_id is None:
        return False
    if str(court_id) == str(establishment):
        return True
    return Organization.objects.filter(pk=court_id, parent_id=establishment).exists()


def is_court_reader(user, court_id) -> bool:
    """PLACEHOLDER: staff of ``court_id`` read every submitted application of its cases (#2.2)."""
    if not getattr(user, "is_authenticated", False) or not _in_establishment(court_id):
        return False
    return user.groups.filter(name__in=COURT_STAFF_GROUPS).exists()


def can_draft_order(user, court_id) -> bool:
    """PLACEHOLDER for ``orders.edit_text`` (0025, ``RLE-07``)."""
    return _in_establishment(court_id) and user.groups.filter(name="Order drafter").exists()


# Tasks (0011) -----------------------------------------------------------------------


class TaskPort:
    """PLACEHOLDER for ``apps.workflows.TaskService`` (#16.1): records nothing.

    Court lists and *Needs attention* are derived from statuses and dates until
    the engine lands. Every call site already passes what the engine will need.
    """

    def open(self, task_key, application, *, users=None, due_date=None):
        logger.debug(
            "event=APPLICATION_TASK_OPEN task=%s application=%s due=%s",
            task_key,
            application.pk,
            due_date,
        )

    def complete(self, task_key, application):
        logger.debug(
            "event=APPLICATION_TASK_COMPLETE task=%s application=%s", task_key, application.pk
        )

    def expire(self, task_key, application, *, reason=""):
        logger.debug(
            "event=APPLICATION_TASK_EXPIRE task=%s application=%s reason=%s",
            task_key,
            application.pk,
            reason,
        )

    def reschedule(self, task_key, application, *, due_date):
        logger.debug(
            "event=APPLICATION_TASK_RESCHEDULE task=%s application=%s due=%s",
            task_key,
            application.pk,
            due_date,
        )


tasks = TaskPort()


def dispatch_case_event(case_id, event):
    """PLACEHOLDER for ``CaseWorkflowService.dispatch`` (0011 #10.4)."""
    raise PortNotAvailable(f"CaseWorkflowService.dispatch({event})")


# Orders (0025) ----------------------------------------------------------------------


def live_items_targeting(application_ids) -> dict:
    """PLACEHOLDER for ``apps.orders.selectors.live_items_targeting`` (#13, #14.4).

    ``{application_id: {id, status, answers}}`` of live orders carrying an
    *Application action* item. Empty until orders exist.
    """
    return {}


# Case effects of the type workflows (#12.2) ----------------------------------------


def apply_litigant_edit(case_id, participant_id, changes, *, source):
    raise PortNotAvailable("apps.cases.services.participants.apply_litigant_edit")


def add_witnesses(case_id, called_by, witnesses, *, source):
    raise PortNotAvailable("apps.cases.services.participants.add_witnesses")


def appoint_poa(case_id, holder_user_id, participant_ids, documents, *, source):
    raise PortNotAvailable("apps.cases.services.poa.appoint")


def add_documents_from_application(case_id, documents, *, source):
    raise PortNotAvailable("apps.cases.services.documents.add_from_application")
