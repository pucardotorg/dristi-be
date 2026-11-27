"""PoA Change, Production of Documents, Addition of Witness, Warrant by Hand (spec 0033 #3.4)."""

from apps.api import errors as api_errors
from apps.cases.models import ParticipantRole
from apps.cases.serializers import CaseParticipantSerializer

from .. import ports
from .base import ApplicationTypeSpec, Problems, is_uuid
from .common import ADDRESS_SCHEMA, ADDRESSES_SCHEMA, address_problems, address_text, phone_problem

MAX_ITEMS = 50


class PoaChange(ApplicationTypeSpec):
    """Raised and signed by the incoming PoA holder. Not offered until ``Q-16`` (#6.1).

    The seeded row is inactive; this spec exists so the type validates and
    renders the day the row is switched on.
    """

    code = "POA_CHANGE"
    label = "PoA Change"
    has_workflow = True
    document_fields = {"authorizations[].document_id": "Authorization document"}
    data_schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "participant_ids": {
                "type": "array",
                "maxItems": MAX_ITEMS,
                "items": {"type": "string", "format": "uuid"},
            },
            "authorizations": {
                "type": "array",
                "maxItems": MAX_ITEMS,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "participant_id": {"type": "string", "format": "uuid"},
                        "document_id": {"type": "string"},
                    },
                },
            },
        },
    }

    def unavailable_reason(self, ctx):
        return "Who raises and signs a PoA Change is not decided yet (Q-16)."

    def form_context(self, ctx):
        return {
            "litigants": [
                {
                    "participant_id": str(p.pk),
                    "name": p.name_at_filing or p.entity_name_at_filing,
                    "role": p.role,
                    "has_poa_holder": ports.has_poa_holder(ctx.case_id, p.pk),
                }
                for p in ports.participants(ctx.case_id)
            ]
        }

    def validate(self, app, *, complete):
        problems = Problems()
        selected = app.data.get("participant_ids") or []
        for index, pid in enumerate(selected):
            if not is_uuid(pid) or ports.participant(app.case_id, pid) is None:
                problems.add(f"data.participant_ids[{index}]", api_errors.DOES_NOT_EXIST)
        if complete:
            if not selected:
                problems.missing("data.participant_ids")
            given = [a.get("participant_id") for a in app.data.get("authorizations") or []]
            if sorted(given) != sorted(selected) or any(
                not a.get("document_id") for a in app.data.get("authorizations") or []
            ):
                problems.missing(
                    "data.authorizations", "Attach one authorization for each litigant chosen."
                )
        return problems.items

    def render_entries(self, app):
        names = []
        for pid in app.data.get("participant_ids") or []:
            party = ports.participant(app.case_id, pid)
            if party is not None:
                names.append(party.name_at_filing or party.entity_name_at_filing or "")
        return [{"term": "Litigants appointing the applicant", "value": ", ".join(names)}]

    def on_accept(self, app, *, order_id, values):
        ports.appoint_poa(
            app.case_id,
            app.raised_by_id,
            app.data.get("participant_ids", []),
            [a["document_id"] for a in app.data.get("authorizations", [])],
            source=app,
        )
        return {"summary": "PoA holder appointed"}


class ProductionOfDocuments(ApplicationTypeSpec):
    """Documents to add to the case file, PDF or JPEG only (#3.4, #6.4)."""

    code = "PRODUCTION_OF_DOCUMENTS"
    label = "Production of Documents"
    has_workflow = True
    document_formats = ("application/pdf", "image/jpeg")
    document_fields = {"documents[].document_id": "Document"}
    data_schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "documents": {
                "type": "array",
                "maxItems": MAX_ITEMS,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "document_type": {"type": "string", "maxLength": 128},
                        "document_id": {"type": "string"},
                    },
                },
            }
        },
    }

    def validate(self, app, *, complete):
        problems = Problems()
        documents = app.data.get("documents") or []
        if complete:
            if not documents:
                problems.missing("data.documents")
            for index, document in enumerate(documents):
                for key in ("document_type", "document_id"):
                    if not document.get(key):
                        problems.missing(f"data.documents[{index}].{key}")
        return problems.items

    def render_entries(self, app):
        return [
            {"term": f"Document {index}", "value": document.get("document_type", "")}
            for index, document in enumerate(app.data.get("documents") or [], start=1)
        ]

    def on_accept(self, app, *, order_id, values):
        ports.add_documents_from_application(app.case_id, app.data.get("documents", []), source=app)
        return {"summary": "Documents added to the case file"}


WITNESS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "name": {"type": "string", "maxLength": 256},
        "age": {"type": ["integer", "null"], "minimum": 1, "maximum": 150},
        "what_will_prove": {"type": ["string", "null"], "maxLength": 2000},
        "designation": {"type": ["string", "null"], "maxLength": 128},
        "mobile": {"type": ["string", "null"], "maxLength": 16},
        "email": {"type": ["string", "null"], "maxLength": 254},
        "addresses": ADDRESSES_SCHEMA,
    },
}


class AdditionOfWitness(ApplicationTypeSpec):
    """Witnesses with the e-filing witness fields (§13, ``WIT-1``..``WIT-7``)."""

    code = "ADDITION_OF_WITNESS"
    label = "Addition of Witness"
    has_workflow = True
    data_schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "witnesses": {"type": "array", "maxItems": MAX_ITEMS, "items": WITNESS_SCHEMA}
        },
    }

    def validate(self, app, *, complete):
        problems = Problems()
        witnesses = app.data.get("witnesses") or []
        for index, witness in enumerate(witnesses):
            base = f"data.witnesses[{index}]"
            problem = phone_problem(witness.get("mobile"), f"{base}.mobile")
            if problem:
                problems.items.append(problem)
            for a_index, address in enumerate(witness.get("addresses") or []):
                problems.items.extend(address_problems(address, f"{base}.addresses[{a_index}]"))
            if complete:
                if (
                    not (witness.get("name") or "").strip()
                    and not (witness.get("designation") or "").strip()
                ):
                    problems.missing(f"{base}.name", "Enter the witness's name or designation.")
                if not witness.get("addresses"):
                    problems.missing(f"{base}.addresses")
        if complete and not witnesses:
            problems.missing("data.witnesses")
        return problems.items

    def render_entries(self, app):
        entries = []
        for index, witness in enumerate(app.data.get("witnesses") or [], start=1):
            entries.append(
                {
                    "term": f"Witness {index}",
                    "value": witness.get("name") or witness.get("designation") or "",
                }
            )
            if witness.get("what_will_prove"):
                entries.append(
                    {"term": "What they will prove", "value": witness["what_will_prove"]}
                )
            for address in witness.get("addresses") or []:
                entries.append({"term": "Address", "value": address_text(address)})
        return entries

    def on_accept(self, app, *, order_id, values):
        ports.add_witnesses(
            app.case_id, app.raised_on_behalf_of, app.data.get("witnesses", []), source=app
        )
        return {
            "summary": "Witness added"
            if len(app.data.get("witnesses", [])) == 1
            else "Witnesses added"
        }


class WarrantByHand(ApplicationTypeSpec):
    """Nothing runs on acceptance; the court is told to issue a warrant by hand (#12.2)."""

    code = "WARRANT_BY_HAND"
    label = "Warrant by Hand"
    data_schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "accused_participant_id": {"type": "string", "format": "uuid"},
            "delivery_address": ADDRESS_SCHEMA,
        },
    }

    def form_context(self, ctx):
        return {
            "accused": [
                {
                    "participant_id": str(p.pk),
                    "name": p.name_at_filing or p.entity_name_at_filing,
                    "addresses": CaseParticipantSerializer(p).data.get("addresses") or [],
                }
                for p in ports.participants(ctx.case_id, role=ParticipantRole.ACCUSED)
            ]
        }

    def validate(self, app, *, complete):
        problems = Problems()
        accused_id = app.data.get("accused_participant_id")
        if accused_id:
            party = ports.participant(app.case_id, accused_id)
            if party is None or party.role != ParticipantRole.ACCUSED:
                problems.add(
                    "data.accused_participant_id",
                    api_errors.INVALID,
                    "Choose an accused of the case.",
                )
        problems.items.extend(
            address_problems(app.data.get("delivery_address"), "data.delivery_address")
        )
        if complete:
            if not accused_id:
                problems.missing("data.accused_participant_id")
            if not app.data.get("delivery_address"):
                problems.missing("data.delivery_address")
        return problems.items

    def render_entries(self, app):
        party = ports.participant(app.case_id, app.data.get("accused_participant_id"))
        return [
            {
                "term": "Accused",
                "value": (party.name_at_filing or party.entity_name_at_filing or "")
                if party
                else "",
            },
            {"term": "Delivery address", "value": address_text(app.data.get("delivery_address"))},
        ]

    def decision_hint(self, app):
        return "Issue a warrant with the channel By hand."
