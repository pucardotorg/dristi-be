"""Edit Litigant Details (spec 0033 #3.4, #3.5).

One application edits one litigant. ``details`` takes the e-filing litigant
fields for the participant's role and type with the 0021 keys; the form
endpoint pre-fills them with the current values. The diff against the current
values is computed at *Proceed to sign* into ``data.changes`` (``prepare``), so
the template and the court see what changes.
"""

from apps.cases.models import CaseContact, ContactType, ParticipantRole, Representation
from apps.cases.serializers import CaseParticipantSerializer

from .. import conf, errors, ports
from .base import ApplicationTypeSpec, Problems
from .common import ADDRESSES_SCHEMA, address_problems, phone_problem

LITIGANT_TYPES = {"INDIVIDUAL": "Individual", "INSTITUTION": "Institution"}

DETAILS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        # Person (LIT-3..9, ACC-2..13)
        "name": {"type": "string", "maxLength": 256},
        "age": {"type": ["integer", "null"], "minimum": 1, "maximum": 150},
        "gender": {"type": ["string", "null"], "maxLength": 32},
        "disability_status": {"type": ["boolean", "null"]},
        "designation": {"type": ["string", "null"], "maxLength": 128},
        "phone_number": {"type": ["string", "null"], "maxLength": 16},
        "email": {"type": ["string", "null"], "maxLength": 254},
        "addresses": ADDRESSES_SCHEMA,
        # Institution (LIT-17..26, ACC-4..5)
        "entity_type": {"type": ["string", "null"], "maxLength": 64},
        "entity_name": {"type": ["string", "null"], "maxLength": 256},
        "cin_or_pan": {"type": ["string", "null"], "maxLength": 32},
        "representative": {
            "type": ["object", "null"],
            "additionalProperties": False,
            "properties": {
                "name": {"type": "string", "maxLength": 256},
                "phone_number": {"type": "string", "maxLength": 16},
                "age": {"type": ["integer", "null"], "minimum": 1, "maximum": 150},
                "gender": {"type": ["string", "null"], "maxLength": 32},
                "disability_status": {"type": ["boolean", "null"]},
                "email": {"type": ["string", "null"], "maxLength": 254},
                "designation": {"type": "string", "maxLength": 128},
                "addresses": ADDRESSES_SCHEMA,
            },
        },
    },
}

# Mandatory keys by role and type (PRD LIT-*, ACC-*).
REQUIRED = {
    (ParticipantRole.COMPLAINANT, "INDIVIDUAL"): ("phone_number", "name", "age", "addresses"),
    (ParticipantRole.COMPLAINANT, "INSTITUTION"): (
        "entity_type",
        "entity_name",
        "addresses",
        "representative",
    ),
    (ParticipantRole.ACCUSED, "INDIVIDUAL"): ("name", "phone_number", "email", "addresses"),
    (ParticipantRole.ACCUSED, "INSTITUTION"): (
        "entity_type",
        "entity_name",
        "phone_number",
        "email",
        "addresses",
    ),
}
REPRESENTATIVE_REQUIRED = ("phone_number", "name", "age", "designation", "addresses")


class EditLitigantDetails(ApplicationTypeSpec):
    code = "EDIT_LITIGANT_DETAILS"
    label = "Edit Litigant Details"
    has_workflow = True
    data_schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "participant_id": {"type": "string", "format": "uuid"},
            "litigant_type": {"enum": list(LITIGANT_TYPES)},
            "details": DETAILS_SCHEMA,
            # Computed at Proceed to sign; refused from the client (``prepare``).
            "changes": {"type": "object"},
        },
    }

    def editable_ids(self, case_id, side, raised_by_litigants):
        """The litigants the control lets this side edit (#3.5)."""
        control = conf.edit_litigant_details()
        if side not in control.get("raised_by_sides", []):
            return []
        mode = control.get("editable", "OWN_LITIGANTS")
        litigants = ports.participants(case_id)
        if mode == "ANY":
            return [p.pk for p in litigants]
        if mode == "OWN_SIDE":
            return [p.pk for p in litigants if ports.LITIGANT_SIDE[p.role] == side]
        return [p.pk for p in litigants if p.pk in raised_by_litigants]

    def _own_litigants(self, ctx):
        if ctx.access.represents:
            return set(ctx.access.represents)
        options = ports.advocate_options(ctx.case_id, ctx.side)
        return {pid for o in options if o.user_id in ctx.access.works_for for pid in o.litigant_ids}

    def unavailable_reason(self, ctx):
        if ctx.side is None or not self.editable_ids(
            ctx.case_id, ctx.side, self._own_litigants(ctx)
        ):
            return "There is no litigant whose details you may edit."
        return None

    def form_context(self, ctx):
        ids = set(self.editable_ids(ctx.case_id, ctx.side, self._own_litigants(ctx)))
        return {
            "editable_litigants": [
                {
                    "participant_id": str(p.pk),
                    "role": p.role,
                    "litigant_type": "INSTITUTION" if p.institution_id else "INDIVIDUAL",
                    "current": current_details(p),
                }
                for p in ports.participants(ctx.case_id)
                if p.pk in ids
            ]
        }

    def validate(self, app, *, complete):
        problems = Problems()
        data = app.data
        details = data.get("details") or {}
        participant = None
        if data.get("participant_id"):
            participant = ports.participant(app.case_id, data["participant_id"])
            raised_by_litigants = set()
            if app.raised_by_id:
                options = ports.advocate_options(app.case_id, app.side)
                raised_by_litigants = {
                    pid for o in options if o.user_id == app.raised_by_id for pid in o.litigant_ids
                }
            if participant is None or participant.pk not in self.editable_ids(
                app.case_id, app.side, raised_by_litigants or {app.raised_on_behalf_of}
            ):
                problems.add("data.participant_id", errors.LITIGANT_NOT_EDITABLE)
                participant = None
        for key in ("phone_number",):
            problem = phone_problem(details.get(key), f"data.details.{key}")
            if problem:
                problems.items.append(problem)
        for index, address in enumerate(details.get("addresses") or []):
            problems.items.extend(address_problems(address, f"data.details.addresses[{index}]"))
        if (
            participant is not None
            and participant.role == ParticipantRole.COMPLAINANT
            and details.get("phone_number")
            and phone_taken(app.case_id, participant.pk, details["phone_number"])
        ):
            problems.add("data.details.phone_number", errors.PHONE_IN_USE)
        if participant is not None and participant.role == ParticipantRole.ACCUSED:
            for index, address in enumerate(details.get("addresses") or []):
                if complete and not (address.get("police_station") or "").strip():
                    problems.missing(f"data.details.addresses[{index}].police_station")
        if not complete:
            return problems.items
        for key in ("participant_id", "litigant_type"):
            if not data.get(key):
                problems.missing(f"data.{key}")
        if participant is not None and data.get("litigant_type"):
            for key in REQUIRED[(participant.role, data["litigant_type"])]:
                if details.get(key) in (None, "", [], {}):
                    problems.missing(f"data.details.{key}")
            representative = details.get("representative") or {}
            if (participant.role, data["litigant_type"]) == (
                ParticipantRole.COMPLAINANT,
                "INSTITUTION",
            ) and representative:
                for key in REPRESENTATIVE_REQUIRED:
                    if representative.get(key) in (None, "", []):
                        problems.missing(f"data.details.representative.{key}")
            if not problems and not compute_changes(participant, data):
                problems.missing("data.details", "This application changes nothing.")
        return problems.items

    def prepare(self, app):
        """Store the diff at *Proceed to sign* (#3.4)."""
        participant = ports.participant(app.case_id, app.data.get("participant_id"))
        app.data = {**app.data, "changes": compute_changes(participant, app.data)}

    def render_entries(self, app):
        participant = ports.participant(app.case_id, app.data.get("participant_id"))
        entries = [
            {"term": "Litigant", "value": _name(participant)},
            {
                "term": "Type of litigant",
                "value": LITIGANT_TYPES.get(app.data.get("litigant_type"), ""),
            },
        ]
        for key, change in (app.data.get("changes") or {}).items():
            entries.append(
                {
                    "term": key.replace("_", " ").capitalize(),
                    "value": f"{_show(change.get('from'))} → {_show(change.get('to'))}",
                }
            )
        return entries

    def on_accept(self, app, *, order_id, values):
        ports.apply_litigant_edit(
            app.case_id, app.data["participant_id"], app.data.get("changes", {}), source=app
        )
        return {"participant_id": app.data["participant_id"], "summary": "Litigant details updated"}


def _name(participant):
    if participant is None:
        return ""
    return participant.name_at_filing or participant.entity_name_at_filing or ""


def _show(value):
    if isinstance(value, list):
        return "; ".join(str(v) for v in value)
    return "" if value is None else str(value)


def current_details(participant) -> dict:
    """The participant's current values under the ``details`` keys (#3.4 prefill)."""
    data = CaseParticipantSerializer(participant).data
    addresses = [
        {
            key: address.get(key) or ""
            for key in ("line1", "city", "district", "state", "pincode", "police_station")
        }
        for address in data.get("addresses") or []
    ]
    details = {
        "name": participant.name_at_filing,
        "age": participant.age_at_filing,
        "gender": participant.gender_at_filing,
        "designation": participant.designation_at_filing,
        "phone_number": (data.get("mobile_numbers") or [None])[0],
        "email": (data.get("email_addresses") or [None])[0],
        "addresses": addresses,
    }
    institution = data.get("institution")
    if institution:
        details.update(
            entity_type=institution.get("entity_type"),
            entity_name=participant.entity_name_at_filing or institution.get("entity_name"),
            cin_or_pan=institution.get("cin") or institution.get("pan"),
        )
    return details


def compute_changes(participant, data) -> dict:
    """``{key: {from, to}}`` for every ``details`` key that differs from the current value."""
    if participant is None:
        return {}
    current = current_details(participant)
    changes = {}
    current_type = "INSTITUTION" if participant.institution_id else "INDIVIDUAL"
    if data.get("litigant_type") and data["litigant_type"] != current_type:
        changes["litigant_type"] = {"from": current_type, "to": data["litigant_type"]}
    for key, value in (data.get("details") or {}).items():
        if current.get(key) != value and not (
            current.get(key) in (None, "") and value in (None, "")
        ):
            changes[key] = {"from": current.get(key), "to": value}
    return changes


def phone_taken(case_id, participant_id, phone) -> bool:
    """The number belongs to another complainant, accused, PoA holder or advocate (``LIT-3``)."""
    others = CaseContact.objects.filter(
        case_id=case_id,
        is_active=True,
        contact_type=ContactType.MOBILE_NUMBER,
        value=phone,
        case_participant__is_active=True,
    ).exclude(case_participant_id=participant_id)
    if others.exists():
        return True
    return Representation.objects.filter(
        case_id=case_id, is_active=True, advocate__user__mobile_number=phone
    ).exists()
