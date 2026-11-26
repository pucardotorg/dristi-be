"""Bail (spec 0033 #3.4); surety fields follow Form No. 37."""

from decimal import Decimal, InvalidOperation

from ..enums import Side
from ..signals import bail_bond_requested
from .base import ApplicationTypeSpec, Problems
from .common import ADDRESS_SCHEMA, address_problems, address_text, format_rupees
from .simple import side_only

MAX_SURETIES = 10
BAIL_TYPES = {"CASH": "Cash", "SURETY": "Surety"}

SURETY_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "name": {"type": "string", "maxLength": 255},
        "parent_name": {"type": "string", "maxLength": 255},
        "phone": {"type": "string", "maxLength": 16},
        "email": {"type": ["string", "null"], "maxLength": 254},
        "address": ADDRESS_SCHEMA,
        "id_proof_document_ids": {"type": "array", "items": {"type": "string"}},
        "solvency_document_ids": {"type": "array", "items": {"type": "string"}},
    },
}


class Bail(ApplicationTypeSpec):
    code = "BAIL"
    label = "Bail"
    has_workflow = True
    document_fields = {
        "sureties[].id_proof_document_ids": "Surety ID proof",
        "sureties[].solvency_document_ids": "Proof of solvency",
    }
    data_schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "bail_type": {"enum": list(BAIL_TYPES)},
            "bail_amount": {"type": "string", "maxLength": 20},
            "number_of_sureties": {"type": "integer", "minimum": 1, "maximum": MAX_SURETIES},
            "sureties": {"type": "array", "maxItems": MAX_SURETIES, "items": SURETY_SCHEMA},
        },
    }

    def unavailable_reason(self, ctx):
        return side_only(Side.ACCUSED)(ctx)

    def validate(self, app, *, complete):
        data = app.data
        problems = Problems()
        bail_type = data.get("bail_type")
        if bail_type == "CASH":
            from .. import errors

            for key in ("number_of_sureties", "sureties"):
                if key in data:
                    problems.add(f"data.{key}", errors.FIELD_NOT_FOR_TYPE)
        amount = data.get("bail_amount")
        if amount not in (None, ""):
            try:
                if Decimal(str(amount)) <= 0:
                    raise InvalidOperation
            except InvalidOperation:
                from apps.api import errors as api_errors

                problems.add("data.bail_amount", api_errors.INVALID, "Enter an amount above 0.")
        for index, surety in enumerate(data.get("sureties") or []):
            problems.items.extend(
                address_problems(surety.get("address"), f"data.sureties[{index}].address")
            )
        if not complete:
            return problems.items
        if not bail_type:
            problems.missing("data.bail_type")
        if amount in (None, ""):
            problems.missing("data.bail_amount")
        if bail_type == "SURETY":
            sureties = data.get("sureties") or []
            count = data.get("number_of_sureties")
            if not count:
                problems.missing("data.number_of_sureties")
            elif count != len(sureties):
                problems.missing(
                    "data.sureties",
                    f"Enter the details of {count} sureties; {len(sureties)} given.",
                )
            for index, surety in enumerate(sureties):
                base = f"data.sureties[{index}]"
                for key in ("name", "parent_name", "phone"):
                    if not (surety.get(key) or "").strip():
                        problems.missing(f"{base}.{key}")
                if not surety.get("address"):
                    problems.missing(f"{base}.address")
                for key in ("id_proof_document_ids", "solvency_document_ids"):
                    if not surety.get(key):
                        problems.missing(f"{base}.{key}", "Attach at least one file.")
        return problems.items

    def render_entries(self, app):
        data = app.data
        entries = [
            {"term": "Type of bail", "value": BAIL_TYPES.get(data.get("bail_type"), "")},
            {"term": "Bail amount", "value": format_rupees(data.get("bail_amount"))},
        ]
        if data.get("bail_type") == "SURETY":
            entries.append(
                {"term": "Number of sureties", "value": str(data.get("number_of_sureties") or "")}
            )
            for index, surety in enumerate(data.get("sureties") or [], start=1):
                entries.extend(
                    [
                        {"term": f"Surety {index}", "value": surety.get("name", "")},
                        {
                            "term": "Father's or mother's name",
                            "value": surety.get("parent_name", ""),
                        },
                        {"term": "Phone", "value": surety.get("phone", "")},
                        {"term": "Email", "value": surety.get("email") or ""},
                        {"term": "Address", "value": address_text(surety.get("address"))},
                    ]
                )
        return entries

    def on_accept(self, app, *, order_id, values):
        """Hand the bail to the bail bond module (#12.2); it is not built, so nothing listens yet."""
        receivers = bail_bond_requested.send(
            sender=type(app), application_id=app.pk, case_id=app.case_id, order_id=order_id
        )
        return {"bail_bond_requested": True, "receivers": len(receivers)}
