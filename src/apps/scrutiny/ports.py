"""What scrutiny needs from modules that are not built yet (spec 0024 #1.1, #2.2, #2.3).

Spec 0024 relies on the 0011 workflow engine and its tasks, on court roles
(``court-roles.md``) and on a contract ``apps.cases`` does not expose yet. Every
call scrutiny makes to them goes through this module, so each stand-in below
is replaced here, and only here, when the real one lands:

* Workflow — ``Case.status`` is moved directly, as ``apps.cases.services.filing``
  does (spec 0021 §7, option a). A round opens when a case is saved in a stage
  status (``receivers``), not on ``state_entered``.
* Tasks — none yet: a case is on a list while its round is open, and *start*
  is the claim.
* Roles — Django groups named after the role. Each deployment has one court
  establishment (``RLE-00``), so the establishment is not checked.
* Cases contract — the cheque-bounce field catalogue and date chain below, the
  correction scope and case title kept in the detail row's
  ``additional_details``, courtrooms as the establishment's child
  organizations, one registration type and no oath.
"""

import calendar
import datetime
import re
from dataclasses import dataclass

from django.utils import timezone

from apps.api.errors import define
from apps.cases.models import Case, CaseDocument, CaseEvidence, CaseStatus
from apps.cases.services.case_types import EvidenceType, get_config
from apps.cases.services.filing import get_viewable_case
from apps.organizations.models import Organization

from .enums import CourtRole, RoundStage

# Roles


def roles_held(user, establishment_id):
    """Return the court roles ``user`` holds at the establishment."""
    names = user.groups.filter(name__in=CourtRole.values).values_list("name", flat=True)
    return frozenset(CourtRole(name) for name in names)


# Workflow

# The case status of each stage's workflow state.
STAGE_STATUS = {
    RoundStage.SCRUTINY: CaseStatus.UNDER_SCRUTINY,
    RoundStage.REGISTRATION: CaseStatus.PENDING_REGISTRATION,
}
STATUS_STAGE = {status: stage for stage, status in STAGE_STATUS.items()}


def lock_case(case_id):
    """Return the case with its row locked until the transaction ends."""
    return Case.objects.select_for_update().get(pk=case_id)


# The 0011 engine's stale-version error (spec 0011 #9.5), defined here until
# apps.workflows exists and owns it; the code is the one 0011 allocates.
WORKFLOW_STALE = define(
    "E08005", "The case has changed since you loaded it. Reload and try again.", status=412
)


def workflow_version(case):
    """Return the case's version for ``If-Match``; 0011 will give its instance version."""
    return int(case.updated_at.timestamp() * 1_000_000)


def filing_side_case(case_id, user):
    """Return the case if ``user`` is on its filing side (``ROLE-01``–``ROLE-05``), or raise NotFound."""
    return get_viewable_case(case_id, user)


def move_case(case, status):
    """Move the locked ``case`` to ``status``."""
    case.status = status
    case.save()


# Court establishment and courtrooms (#2.5)


@dataclass(frozen=True)
class RegistrationType:
    """One way a state registers a case, with its own number series (``SCR-13``)."""

    code: str
    label: str


REGISTRATION_TYPES = (RegistrationType("CC", "Criminal complaint"),)


def establishment_id(case):
    """Return the court establishment the case was filed in, or None."""
    return case.court_id


def courtrooms(establishment_id):
    """Return the establishment's courtrooms; one with none of its own is its only courtroom."""
    rooms = list(Organization.objects.active().filter(parent_id=establishment_id).order_by("name"))
    return rooms or list(Organization.objects.filter(pk=establishment_id))


def registration_types(establishment_id):
    """Return the state's registration types."""
    return REGISTRATION_TYPES


def set_court(case, courtroom_id):
    """Store the courtroom the Scrutiny officer chose on the locked ``case``."""
    case.court_id = courtroom_id
    case.save()


def register_case(case, registration_type, actor):
    """Number the locked ``case`` from its type's series and move it on to cognizance.

    A stand-in series, ``{type}/{n}/{year}``; ``case-numbers.md`` will replace
    it. Raises ``IntegrityError`` when the number is taken, which rolls the
    whole decision back.
    """
    now = timezone.now()
    prefix, suffix = f"{registration_type}/", f"/{now.year}"
    taken = Case.objects.filter(
        case_number__startswith=prefix, case_number__endswith=suffix
    ).count()
    case.case_number = f"{prefix}{taken + 1}{suffix}"
    case.registered_at = now
    case.status = CaseStatus.REGISTERED
    case.save()


# Oath and documents


def oath_required(case):
    """Whether the state requires an oath; none does until per-state configuration lands."""
    return False


def oaths(case):
    """Return the case's oaths, one per complainant."""
    return []


def is_generated(document):
    """Whether ``document`` is generated (synopsis, complaint); none is a ``CaseDocument`` yet."""
    return False


def active_document(case, document_id):
    """Return the active document ``document_id`` of the case, or None."""
    return CaseDocument.objects.active().filter(case=case, pk=document_id).first()


# The case-type plugin: fields, sections and the date chain (#3.2, #3.3, #3.4)

SECTIONS = {
    "LIT": "Litigant details",
    "ADV": "Advocate details",
    "ACC": "Accused details",
    "CHQ": "Cheque details",
    "LDN": "Legal demand notice",
    "JUR": "Jurisdiction and limitation",
    "PRY": "Prayer",
    "WIT": "Witnesses",
    "DCM": "Documents",
}
DOCUMENTS_SECTION = "DCM"


@dataclass(frozen=True)
class Field:
    """One flaggable field of a case, at one record index."""

    ref: str
    label: str
    section: str
    value: object = None
    # The case document the value was read from.
    document_id: object = None


# PRD field id -> (label, the evidence type it is read from and its key). One
# record per evidence item, matched by ordinal: cheque 1, its return memo, its notice.
_EVIDENCE_FIELDS = {
    "CHQ-1": ("Date on cheque", EvidenceType.CHEQUE, "cheque_date"),
    "CHQ-3": ("Cheque amount", EvidenceType.CHEQUE, "amount"),
    "CHQ-8": ("Date of presentation", EvidenceType.RETURN_MEMO, "presentation_date"),
    "CHQ-9": ("Date of return", EvidenceType.RETURN_MEMO, "return_date"),
    "LDN-2": ("Dispatch of demand notice", EvidenceType.LEGAL_DEMAND_NOTICE, "dispatch_date"),
    "LDN-6": ("Delivery of demand notice", EvidenceType.LEGAL_DEMAND_NOTICE, "delivery_date"),
    "LDN-7": ("Return of demand notice", EvidenceType.LEGAL_DEMAND_NOTICE, None),
}
DELAY_FIELDS = ("JUR-11", "JUR-12")

# Each date and the dates that must follow it (VAL-01/02). LDN-6 applies to a
# delivered notice and LDN-7 to an undelivered one, never both.
DATE_CHAIN = {
    "CHQ-1": ("CHQ-8",),
    "CHQ-8": ("CHQ-9",),
    "CHQ-9": ("LDN-2",),
    "LDN-2": ("LDN-6", "LDN-7"),
    "LDN-6": ("JUR-9",),
    "LDN-7": ("JUR-9",),
    "JUR-9": ("JUR-10",),
    "JUR-10": ("JUR-11",),
}
_REF = re.compile(r"^(?P<id>[A-Z]{3}-\d+)(?:\[(?P<index>\d+)\])?$")
# A complaint is filed within a month of the cause of action (S.142(1)(b)).
_FILING_WINDOW_MONTHS = 1


def split_ref(ref):
    """Return ``(field id, record index or None)`` for a field ref, or None if malformed."""
    match = _REF.match(ref)
    if match is None:
        return None
    index = match.group("index")
    return match.group("id"), None if index is None else int(index)


def detail(case):
    """Return the case-type detail row, created empty if missing."""
    model = get_config(case.case_type).get_detail_model()
    return model.objects.get_or_create(case=case)[0]


def fields(case, today=None):
    """Return every flaggable field of the case that applies to it, by ref."""
    catalogue = {}
    evidence = CaseEvidence.objects.active().filter(case=case).order_by("ordinal")
    for item in evidence:
        info = item.evidence_info
        for field_id, (label, evidence_type, key) in _EVIDENCE_FIELDS.items():
            if item.evidence_type != evidence_type:
                continue
            delivered = info.get("is_delivered")
            if (field_id == "LDN-6" and delivered is False) or (
                field_id == "LDN-7" and delivered is not False
            ):
                continue
            ref = f"{field_id}[{item.ordinal - 1}]"
            section = field_id[:3]
            value = info.get(key) if key else None
            catalogue[ref] = Field(ref, label, section, value, item.case_document_id)
    jurisdiction = getattr(detail(case), "jurisdiction_limitation", {}) or {}
    catalogue["JUR-9"] = Field(
        "JUR-9", "Cause of action", "JUR", jurisdiction.get("cause_of_action_date")
    )
    filed_on = case.filed_at and timezone.localdate(case.filed_at).isoformat()
    catalogue["JUR-10"] = Field("JUR-10", "Filing date", "JUR", filed_on)
    if delay_applicable(case, today):
        catalogue["JUR-11"] = Field("JUR-11", "Delay", "JUR")
    catalogue["JUR-12"] = Field("JUR-12", "Delay condonation prayer", "JUR")
    return catalogue


def downstream(case, ref, catalogue):
    """Return the refs that follow ``ref`` in the date chain and apply to the case.

    A cheque's dates follow their own cheque: ``CHQ-8[1]`` leads to
    ``CHQ-9[1]`` and that cheque's notice; the jurisdiction dates are the case's.
    A date the case does not have is passed through, not a dead end, so the
    dates after it are still marked.
    """
    parts = split_ref(ref)
    if parts is None:
        return []
    found, seen, queue = [], {parts}, [parts]
    while queue:
        field_id, index = queue.pop(0)
        for child in DATE_CHAIN.get(field_id, ()):
            child_index = None if child.startswith("JUR") else index
            if (child, child_index) in seen:
                continue
            seen.add((child, child_index))
            queue.append((child, child_index))
            child_ref = child if child_index is None else f"{child}[{child_index}]"
            if child_ref in catalogue:
                found.append(child_ref)
    return found


def delay_applicable(case, today=None):
    """Whether the filing month after the cause of action has passed, against today (``REF-04``)."""
    today = today or timezone.localdate()
    jurisdiction = getattr(detail(case), "jurisdiction_limitation", {}) or {}
    cause = jurisdiction.get("cause_of_action_date")
    if not cause:
        return False
    return today > add_months(datetime.date.fromisoformat(cause), _FILING_WINDOW_MONTHS)


def delay_prayer_present(case):
    """Whether the filing prays for condonation of delay; the form has no such field yet."""
    return False


def delay_alert(case, today=None):
    """Whether delay applies and no condonation is prayed for (#3.4)."""
    return delay_applicable(case, today) and not delay_prayer_present(case)


def add_months(day, months):
    """Return ``day`` moved by ``months``, clamped to the end of a shorter month."""
    index = day.month - 1 + months
    year, month = day.year + index // 12, index % 12 + 1
    return day.replace(
        year=year, month=month, day=min(day.day, calendar.monthrange(year, month)[1])
    )


# Correction scope and title, kept on the detail row until apps.cases owns them (#5.1, #4.6)

_CORRECTION_KEY = "correction"


def open_for_correction(case, scope, round_id):
    """Store what the filer may change while the case is in correction."""
    row = detail(case)
    row.additional_details[_CORRECTION_KEY] = {**scope, "round_id": str(round_id)}
    row.save(update_fields=["additional_details", "updated_at"])


def close_correction(case):
    """Clear the correction scope."""
    row = detail(case)
    if row.additional_details.pop(_CORRECTION_KEY, None) is not None:
        row.save(update_fields=["additional_details", "updated_at"])


def correction_scope(case):
    """Return the stored correction scope, or None."""
    return detail(case).additional_details.get(_CORRECTION_KEY)


def mark_correction_changed(case):
    """Record that the filer changed something during correction."""
    row = detail(case)
    scope = row.additional_details.get(_CORRECTION_KEY)
    if scope is not None and not scope.get("changed"):
        scope["changed"] = True
        row.save(update_fields=["additional_details", "updated_at"])


def set_case_title(case, complainant, accused, actor):
    """Store the display names the court gave the parties (*Edit case title*)."""
    row = detail(case)
    row.additional_details["case_title"] = {"complainant": complainant, "accused": accused}
    row.save(update_fields=["additional_details", "updated_at"])
