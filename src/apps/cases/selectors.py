"""Read functions other modules use instead of the case models (spec 0023 #1.1).

Return values are frozen dataclasses, so a caller never holds a case model
instance.
"""

from collections import defaultdict
from dataclasses import dataclass
from uuid import UUID

from django.db.models import Exists, OuterRef, Q

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


# Advocates (spec 0023 #1.1, the Advocates column)


@dataclass(frozen=True)
class AdvocateRef:
    """An active advocate of a case and the side they appear for.

    ``id`` is the advocate's profile id, the value the board's advocate filter
    takes (``CLS-07``).
    """

    id: UUID
    name: str
    side: str


def get_case_advocates(case_ids) -> dict[UUID, list[AdvocateRef]]:
    """Return ``{case_id: [AdvocateRef]}`` for the cases. One query, however many cases.

    One entry per advocate and side, complainant side first, each in the order
    they were engaged. An advocate of a PoA holder appears for the complainant.
    A case with no advocate has an empty list.
    """
    case_ids = list(case_ids)
    advocates = {case_id: [] for case_id in case_ids}
    seen = set()
    representations = (
        Representation.objects.active()
        .filter(case_id__in=case_ids, case_participant__role__in=list(PARTY_SIDES))
        .select_related("advocate__user", "case_participant")
        .order_by("from_date")
    )
    for representation in representations:
        side = PARTY_SIDES[representation.case_participant.role]
        key = (representation.case_id, representation.advocate_id, side)
        if key in seen:
            continue
        seen.add(key)
        advocates.setdefault(representation.case_id, []).append(
            AdvocateRef(
                id=representation.advocate_id,
                name=_advocate_name(representation),
                side=side,
            )
        )
    for refs in advocates.values():
        refs.sort(key=lambda ref: ref.side != COMPLAINANT_SIDE)
    return advocates


# Access and search (spec 0023 #1.1, #10.3, #10.5)

# The parties a case shows its hearings to; a witness is not one.
PARTY_ROLES = tuple(PARTY_SIDES)


def case_ids_visible_to(user):
    """Return the ids of the cases ``user`` has an active relationship with (spec 0023 #10.5).

    The filer; an active complainant, accused or PoA holder who is the user;
    and an active advocate of any party. Advocate clerks are not linked to
    cases or advocates yet, so they see none. A lazy ``QuerySet`` of ids, to
    use inside another query.
    """
    if not user or not user.is_authenticated:
        return Case.objects.none().values_list("pk", flat=True)
    party = CaseParticipant.objects.active().filter(
        case=OuterRef("pk"), role__in=PARTY_ROLES, person__user=user
    )
    advocate = Representation.objects.active().filter(case=OuterRef("pk"), advocate__user=user)
    return Case.objects.filter(Q(created_by=user) | Exists(party) | Exists(advocate)).values_list(
        "pk", flat=True
    )


def search_case_ids(text, court_id=None):
    """Return the ids of cases matching ``text`` (spec 0023 #10.3, ``?search=``).

    Case-insensitive, anywhere in the case number, filing number, an active
    party's name (which covers the "A v. B" title) or an active advocate's
    name. ``court_id`` limits it to one court. A lazy ``QuerySet`` of ids.
    """
    text = (text or "").strip()
    cases = Case.objects.all()
    if court_id is not None:
        cases = cases.filter(court_id=court_id)
    if not text:
        return cases.values_list("pk", flat=True)
    party = CaseParticipant.objects.active().filter(
        case=OuterRef("pk"), role__in=PARTY_ROLES, name_at_filing__icontains=text
    )
    advocate = Representation.objects.active().filter(
        Q(advocate__name__icontains=text) | Q(advocate__user__name__icontains=text),
        case=OuterRef("pk"),
    )
    return cases.filter(
        Q(case_number__icontains=text)
        | Q(filing_number__icontains=text)
        | Exists(party)
        | Exists(advocate)
    ).values_list("pk", flat=True)


def cases_awaiting_hearing(court_id):
    """Return the ids of the court's registered, live cases (spec 0023 #10.4.8).

    The scheduling queue is these minus the cases with a live hearing, which
    hearings subtracts. Disposal, transfer and the Long Pending Register are
    not modelled yet, so today every registered case of the court is live,
    matching ``get_listability``. A lazy ``QuerySet`` of ids.
    """
    return Case.objects.filter(court_id=court_id, status=CaseStatus.REGISTERED).values_list(
        "pk", flat=True
    )


def case_ids_represented_by(advocate_ids):
    """Return the ids of cases where any of the advocates is active for a party (spec 0023 #10.3).

    ``advocate_ids`` are advocate profile ids, as ``AdvocateRef.id`` gives
    them. A lazy ``QuerySet`` of ids, for the board's ``advocate`` filter.
    """
    return (
        Representation.objects.active()
        .filter(advocate_id__in=list(advocate_ids), case_participant__role__in=PARTY_ROLES)
        .values_list("case_id", flat=True)
    )


def case_ids_filed_before(moment):
    """Return the ids of cases filed before ``moment`` (spec 0023 #11.2, ``beyond_trial_target``).

    A lazy ``QuerySet`` of ids; a case not yet filed is not in it.
    """
    return Case.objects.filter(filed_at__lt=moment).values_list("pk", flat=True)
