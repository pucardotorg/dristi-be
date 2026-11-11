"""Read functions other modules use instead of the case models (spec 0023 #1.1).

Return values are frozen dataclasses, so a caller never holds a case model
instance.
"""

from collections import defaultdict
from dataclasses import dataclass
from uuid import UUID

from .models import CaseParticipant, ParticipantRole, Representation

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
