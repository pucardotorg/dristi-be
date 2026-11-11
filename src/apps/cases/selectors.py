"""Read functions other modules use instead of the case models (spec 0023 #1.1).

Return values are frozen dataclasses, so a caller never holds a case model
instance.
"""

from collections import defaultdict
from dataclasses import dataclass
from uuid import UUID

from .models import Case, CaseParticipant, CaseStatus, ParticipantRole, Representation

# The parties on an attendance roll, in the order the roll lists them.
ROLL_PARTY_ROLES = (
    ParticipantRole.COMPLAINANT,
    ParticipantRole.ACCUSED,
    ParticipantRole.POA_HOLDER,
)

# The roll line an advocate takes under the party they represent. A PoA holder
# has no advocate line (spec 0023 #2.3, ``ATT-01``).
ADVOCATE_LINE_TYPES = {
    ParticipantRole.COMPLAINANT: "COMPLAINANT_ADVOCATE",
    ParticipantRole.ACCUSED: "ACCUSED_ADVOCATE",
}


@dataclass(frozen=True)
class RollEntry:
    """One line on a case's attendance roll.

    ``type`` is the party's role, or its advocate line type. For an advocate
    line, ``participant_id`` is the party it sits under and ``name`` lists the
    party's advocates.
    """

    participant_id: UUID
    name: str
    type: str


def _advocate_name(representation):
    profile = representation.advocate
    return f"Adv. {profile.name or profile.user.name}"


def get_attendance_roll(case_id) -> list[RollEntry]:
    """Return who a hearing of the case takes attendance of (spec 0023 #1.1, #6.5).

    Every active complainant, accused and PoA holder, and one advocate line
    under each complainant and accused that has an active advocate, however
    many advocates they have. A party in person has no advocate line.
    Complainants first, then accused, then PoA holders, each by ordinal.
    Two queries.
    """
    parties = sorted(
        CaseParticipant.objects.active().filter(case_id=case_id, role__in=ROLL_PARTY_ROLES),
        key=lambda party: (ROLL_PARTY_ROLES.index(party.role), party.ordinal),
    )
    advocates = defaultdict(list)
    representations = (
        Representation.objects.active()
        .filter(case_id=case_id, case_participant__role__in=list(ADVOCATE_LINE_TYPES))
        .select_related("advocate__user")
        .order_by("from_date")
    )
    for representation in representations:
        advocates[representation.case_participant_id].append(_advocate_name(representation))

    roll = []
    for party in parties:
        roll.append(RollEntry(participant_id=party.id, name=party.name_at_filing, type=party.role))
        if names := advocates.get(party.id):
            roll.append(
                RollEntry(
                    participant_id=party.id,
                    name=", ".join(dict.fromkeys(names)),
                    type=ADVOCATE_LINE_TYPES[party.role],
                )
            )
    return roll


# Listability (spec 0023 #1.1)

NOT_REGISTERED = "NOT_REGISTERED"
DISPOSED = "DISPOSED"
LONG_PENDING_REGISTER = "LONG_PENDING_REGISTER"
TRANSFERRED = "TRANSFERRED"


@dataclass(frozen=True)
class Listability:
    """Whether a case may be given a hearing date, and in which court.

    ``reason`` is empty when ``listable``. Disposal, the Long Pending Register
    and transfer are not modelled yet (``case-lifecycle.md``), so today a case
    is listable exactly when it is registered in a court.
    """

    listable: bool
    reason: str
    court_id: UUID | None


def get_listability(case_id) -> Listability:
    """Return whether the case can be listed (spec 0023 #7.1). One query."""
    row = Case.objects.filter(pk=case_id).values("status", "court_id").first()
    if row is None:
        return Listability(listable=False, reason=NOT_REGISTERED, court_id=None)
    if row["status"] != CaseStatus.REGISTERED or row["court_id"] is None:
        return Listability(listable=False, reason=NOT_REGISTERED, court_id=row["court_id"])
    return Listability(listable=True, reason="", court_id=row["court_id"])


# Contacts (spec 0023 #11.1)

COMPLAINANT_SIDE = "COMPLAINANT"
ACCUSED_SIDE = "ACCUSED"
PARTY_SIDES = {
    ParticipantRole.COMPLAINANT: COMPLAINANT_SIDE,
    ParticipantRole.POA_HOLDER: COMPLAINANT_SIDE,
    ParticipantRole.ACCUSED: ACCUSED_SIDE,
}


@dataclass(frozen=True)
class Contact:
    """Someone to notify about a case: a party or an advocate.

    ``kind`` is the party's role, or ``ADVOCATE``. ``phone`` and ``email`` are
    empty when unknown.
    """

    name: str
    phone: str
    email: str
    side: str
    kind: str


def get_case_contacts(case_id) -> list[Contact]:
    """Return the case's active parties and advocates with how to reach them. Two queries.

    A party's current phone and email come from its person, falling back to
    the phone given at filing. Witnesses are not parties and are left out.
    """
    contacts = []
    parties = (
        CaseParticipant.objects.active()
        .filter(case_id=case_id, role__in=list(PARTY_SIDES))
        .select_related("person")
        .order_by("role", "ordinal")
    )
    for party in parties:
        person = party.person
        contacts.append(
            Contact(
                name=party.name_at_filing,
                phone=(person.phone_number if person else "") or party.phone_number_at_filing or "",
                email=(person.email_address if person else "") or "",
                side=PARTY_SIDES[party.role],
                kind=party.role,
            )
        )
    representations = (
        Representation.objects.active()
        .filter(case_id=case_id, case_participant__role__in=list(PARTY_SIDES))
        .select_related("advocate__user", "case_participant")
        .order_by("from_date")
    )
    seen = set()
    for representation in representations:
        user = representation.advocate.user
        side = PARTY_SIDES[representation.case_participant.role]
        if (user.pk, side) in seen:
            continue
        seen.add((user.pk, side))
        contacts.append(
            Contact(
                name=_advocate_name(representation),
                phone=user.mobile_number or "",
                email=user.email or "",
                side=side,
                kind="ADVOCATE",
            )
        )
    return contacts


# Summaries (spec 0023 #1.1)


@dataclass(frozen=True)
class CaseSummary:
    """What a hearing shows of its case.

    ``display_number`` is the case number, else the filing number. ``title``
    is "first complainant v. first accused". ``stage`` is None until case
    stages are modelled (``case-lifecycle.md``).
    """

    id: UUID
    display_number: str
    title: str
    case_type: str
    court_id: UUID | None
    stage: dict | None
    filed_at: object
    registered_at: object


def get_case_summaries(case_ids) -> dict[UUID, CaseSummary]:
    """Return ``{case_id: CaseSummary}`` for the cases. Two queries, however many cases."""
    case_ids = list(case_ids)
    first_party = {}
    parties = (
        CaseParticipant.objects.active()
        .filter(
            case_id__in=case_ids, role__in=(ParticipantRole.COMPLAINANT, ParticipantRole.ACCUSED)
        )
        .order_by("ordinal")
        .values_list("case_id", "role", "name_at_filing")
    )
    for case_id, role, name in parties:
        first_party.setdefault((case_id, role), name)
    summaries = {}
    for case in Case.objects.filter(pk__in=case_ids):
        complainant = first_party.get((case.pk, ParticipantRole.COMPLAINANT), "")
        accused = first_party.get((case.pk, ParticipantRole.ACCUSED), "")
        summaries[case.pk] = CaseSummary(
            id=case.pk,
            display_number=case.case_number or case.filing_number or "",
            title=f"{complainant} v. {accused}"
            if complainant and accused
            else complainant or accused,
            case_type=case.case_type,
            court_id=case.court_id,
            stage=None,
            filed_at=case.filed_at,
            registered_at=case.registered_at,
        )
    return summaries
