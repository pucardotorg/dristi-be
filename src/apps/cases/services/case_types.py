"""Everything that differs between case types, in one place.

Each case type declares its detail table, its details sections, the documents
it accepts and the evidence it accepts with an ``evidence_info`` schema for
each. The endpoints read from here, so a new case type is a new entry in
``CASE_TYPES`` (plus its detail model), not new endpoints (spec 0021 §1).

The code lists are closed sets (spec 0020 §9.4): the upload checklist and the
completeness gate depend on them, so they live in code, not in runtime
configuration.

Adding a document or evidence type: add it to the enum below (the shared
vocabulary, with its label), then list it under each case type that accepts it.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date

import jsonschema
from django.apps import apps
from django.db import models


class CaseType(models.TextChoices):
    """Dispute types."""

    CHEQUE_BOUNCE = "CHEQUE_BOUNCE", "Cheque bounce"


class DocumentType(models.TextChoices):
    """Every case-level document type, across case types (spec 0020 §9.3)."""

    BOUNCED_CHEQUE = "BOUNCED_CHEQUE", "Bounced cheque"
    RETURN_MEMO = "RETURN_MEMO", "Return memo"
    LEGAL_DEMAND_NOTICE = "LEGAL_DEMAND_NOTICE", "Legal demand notice"
    PROOF_OF_DISPATCH = "PROOF_OF_DISPATCH", "Proof of dispatch"
    PROOF_OF_DELIVERY_OF_DEMAND_NOTICE = (
        "PROOF_OF_DELIVERY_OF_DEMAND_NOTICE",
        "Proof of delivery of demand notice",
    )
    REPLY_TO_DEMAND_NOTICE = "REPLY_TO_DEMAND_NOTICE", "Reply to demand notice"
    PROOF_OF_DEBT = "PROOF_OF_DEBT", "Proof of debt"
    AFFIDAVIT = "AFFIDAVIT", "Affidavit"
    VAKALATNAMA = "VAKALATNAMA", "Vakalatnama"
    POA_DOCUMENT = "POA_DOCUMENT", "POA document"
    OTHER_SUPPORTING_DOCUMENT = "OTHER_SUPPORTING_DOCUMENT", "Other supporting document"


class EvidenceType(models.TextChoices):
    """Every evidence type, across case types (spec 0021 §5.2)."""

    CHEQUE = "CHEQUE", "Cheque"
    RETURN_MEMO = "RETURN_MEMO", "Return memo"
    LEGAL_DEMAND_NOTICE = "LEGAL_DEMAND_NOTICE", "Legal demand notice"


class ReturnReason(models.TextChoices):
    """Why the bank returned the cheque unpaid, from the return memo."""

    FUNDS_INSUFFICIENT = "FUNDS_INSUFFICIENT", "Funds insufficient"
    EXCEEDS_ARRANGEMENT = "EXCEEDS_ARRANGEMENT", "Exceeds arrangement"
    ACCOUNT_CLOSED = "ACCOUNT_CLOSED", "Account closed"
    PAYMENT_STOPPED_BY_DRAWER = "PAYMENT_STOPPED_BY_DRAWER", "Payment stopped by drawer"
    SIGNATURE_DIFFERS_OR_INCOMPLETE = (
        "SIGNATURE_DIFFERS_OR_INCOMPLETE",
        "Drawer's signature differs / incomplete",
    )
    AMOUNT_IN_WORDS_AND_FIGURES_DIFFER = (
        "AMOUNT_IN_WORDS_AND_FIGURES_DIFFER",
        "Amount in words and figures differ",
    )
    REFER_TO_DRAWER = "REFER_TO_DRAWER", "Refer to drawer"
    POST_DATED_OR_STALE = "POST_DATED_OR_STALE", "Cheque post-dated / stale"


class NatureOfDebt(models.TextChoices):
    """The debt or liability the cheque was given for."""

    LOAN_OR_ADVANCE_REPAYMENT = "LOAN_OR_ADVANCE_REPAYMENT", "Loan / advance repayment"
    GOODS_SUPPLIED = "GOODS_SUPPLIED", "Payment for goods supplied"
    SERVICES_RENDERED = "SERVICES_RENDERED", "Payment for services rendered"
    BUSINESS_OR_TRADE_TRANSACTION = "BUSINESS_OR_TRADE_TRANSACTION", "Business / trade transaction"
    BORROWED_MONEY_REPAYMENT = "BORROWED_MONEY_REPAYMENT", "Repayment of borrowed money"
    OTHER_LIABILITY = "OTHER_LIABILITY", "Other liability"


class ModeOfService(models.TextChoices):
    """How the legal demand notice was sent."""

    REGISTERED_POST = "REGISTERED_POST", "Registered post (RPAD)"
    SPEED_POST = "SPEED_POST", "Speed post"
    COURIER = "COURIER", "Courier"
    EMAIL = "EMAIL", "Email"
    HAND_DELIVERY = "HAND_DELIVERY", "Hand delivery"
    FAX = "FAX", "Fax"


class PaymentStatus(models.TextChoices):
    """Whether the drawer has paid part of the cheque amount."""

    PART_PAYMENT = "PART_PAYMENT", "Part Payment"
    NO_PAYMENT_MADE = "NO_PAYMENT_MADE", "No Payment Made"


@dataclass(frozen=True)
class CaseTypeConfig:
    """What one case type accepts.

    ``document_types`` are the types uploadable through the case documents
    endpoint. VAKALATNAMA and POA_DOCUMENT are uploaded there too (spec 0021
    §3.4): they are linked to the case only, not to the representation or
    mandate they belong to.
    """

    detail_model: str
    # Details section (a JSON column on the detail model) -> its schema.
    section_schemas: dict[str, dict]
    document_types: tuple[str, ...]
    evidence_schemas: dict[str, dict] = field(default_factory=dict)
    # Details section -> rules JSON Schema cannot express, called with the
    # section's data; returns ``SchemaError``s.
    section_checks: dict[str, Callable[[dict], list]] = field(default_factory=dict)
    # The completeness check (spec 0021 §6.3) requires at least one of each.
    required_document_types: tuple[str, ...] = ()
    required_evidence_types: tuple[str, ...] = ()
    # Where the date the cause of action arose is stored, which the cases list
    # shows: (lookup from a case to a JSON field, key in it); ``None`` when the
    # case type records none.
    cause_of_action_date_key: tuple[str, str] | None = None

    @property
    def sections(self):
        """Return the details section names."""
        return tuple(self.section_schemas)

    def get_detail_model(self):
        """Return the type-specific detail model class."""
        return apps.get_model(self.detail_model)


def _date():
    return {"type": "string", "format": "date"}


def _text():
    return {"type": "string", "minLength": 1}


def _choice(choices):
    """One of ``choices``' codes; each option carries its label as ``title``, for clients."""
    return {"oneOf": [{"const": value, "title": label} for value, label in choices.choices]}


def _ifsc():
    return {"type": "string", "pattern": "^[A-Z]{4}0[A-Z0-9]{6}$"}


def _rich_text():
    """Editor output; may be empty when the field is optional."""
    return {"type": "string"}


def _required_when(field, value, fields):
    """Require ``fields`` when ``field`` is ``value``.

    Several rules on one object go in an ``allOf`` list, since an object has
    only one ``if``.
    """
    return {
        "if": {"properties": {field: {"const": value}}, "required": [field]},
        "then": {"required": fields},
    }


def _object(required, properties, **extra):
    """A strict schema: unknown keys are rejected, so a typo is a 400, not lost data."""
    return {
        "type": "object",
        "required": required,
        "properties": properties,
        "additionalProperties": False,
        **extra,
    }


# A cheque bounce complaint is due within one month of the cause of action
# (NI Act s.142(b)); one filed later needs a reason for the court to condone the delay.
LIMITATION_PERIOD_DAYS = 30


def _limitation_errors(data):
    """Check the complaint filing date against the cause of action.

    The complaint cannot be filed before the cause of action arose, and one
    filed after the limitation period needs a ``condonation_reason``.
    """
    try:
        arose = date.fromisoformat(data["cause_of_action_date"])
        filed = date.fromisoformat(data["complaint_filing_date"])
    except (KeyError, TypeError, ValueError):
        # Missing or malformed: the schema reports it.
        return []
    if filed < arose:
        return [
            SchemaError(
                "complaint_filing_date",
                "The complaint filing date cannot be before the cause of action date.",
                "minimum",
            )
        ]
    if (filed - arose).days <= LIMITATION_PERIOD_DAYS or "condonation_reason" in data:
        return []
    return [
        SchemaError(
            "",
            "'condonation_reason' is a required property: the complaint is filed more "
            f"than {LIMITATION_PERIOD_DAYS} days after the cause of action.",
            "required",
        )
    ]


CASE_TYPES = {
    CaseType.CHEQUE_BOUNCE: CaseTypeConfig(
        detail_model="cases.ChequeBounceCase",
        cause_of_action_date_key=("cheque_bounce__jurisdiction_limitation", "cause_of_action_date"),
        section_schemas={
            # Which court can hear the case, and whether the complaint is in time.
            "jurisdiction_limitation": _object(
                required=[
                    "cheque_deposited_by_payee",
                    "cause_of_action_date",
                    "complaint_filing_date",
                ],
                properties={
                    # Jurisdiction follows the branch where the cheque was
                    # presented and the complainant holds the account.
                    "cheque_deposited_by_payee": {"type": "boolean"},
                    "payee_ifsc_code": _ifsc(),
                    "payee_bank_name": _text(),
                    "payee_bank_branch": _text(),
                    # Police station of the payee's branch when the payee
                    # deposited the cheque, otherwise of the drawer's.
                    "payee_bank_police_station": _text(),
                    "drawer_bank_police_station": _text(),
                    # Another S.138 complaint pending between the same parties.
                    "other_complaints_pending": {"type": "boolean"},
                    "cause_of_action_date": _date(),
                    "complaint_filing_date": _date(),
                    # Why the complaint is late; required when it is filed
                    # after the limitation period (``_limitation_errors``).
                    "condonation_reason": _text(),
                },
                allOf=[
                    _required_when(
                        "cheque_deposited_by_payee",
                        True,
                        [
                            "payee_ifsc_code",
                            "payee_bank_name",
                            "payee_bank_branch",
                            "payee_bank_police_station",
                        ],
                    ),
                    _required_when(
                        "cheque_deposited_by_payee", False, ["drawer_bank_police_station"]
                    ),
                ],
            ),
            # Willingness to settle, other details for the court, and the relief sought.
            "adr_other_prayer": _object(
                required=["final_relief"],
                properties={
                    "adr_preference": {"enum": ["YES", "NO", "MAYBE"]},
                    "other_details": _rich_text(),
                    "interim_relief": _rich_text(),
                    "final_relief": _text(),
                },
            ),
        },
        section_checks={"jurisdiction_limitation": _limitation_errors},
        document_types=(
            DocumentType.BOUNCED_CHEQUE,
            DocumentType.RETURN_MEMO,
            DocumentType.LEGAL_DEMAND_NOTICE,
            DocumentType.PROOF_OF_DISPATCH,
            DocumentType.PROOF_OF_DELIVERY_OF_DEMAND_NOTICE,
            DocumentType.REPLY_TO_DEMAND_NOTICE,
            DocumentType.PROOF_OF_DEBT,
            DocumentType.AFFIDAVIT,
            DocumentType.VAKALATNAMA,
            DocumentType.POA_DOCUMENT,
            DocumentType.OTHER_SUPPORTING_DOCUMENT,
        ),
        required_document_types=(
            DocumentType.BOUNCED_CHEQUE,
            DocumentType.RETURN_MEMO,
            DocumentType.LEGAL_DEMAND_NOTICE,
            DocumentType.PROOF_OF_DISPATCH,
        ),
        required_evidence_types=(
            EvidenceType.CHEQUE,
            EvidenceType.RETURN_MEMO,
            EvidenceType.LEGAL_DEMAND_NOTICE,
        ),
        # One RETURN_MEMO and one LEGAL_DEMAND_NOTICE per cheque, matched to it
        # by ordinal: cheque #1, return memo #1, demand notice #1.
        evidence_schemas={
            # As written on the cheque leaf, plus the drawer's bank and account.
            EvidenceType.CHEQUE: _object(
                required=[
                    "cheque_date",
                    "amount",
                    "cheque_number",
                    "ifsc_code",
                    "bank_name",
                    "bank_branch",
                    "account_number",
                ],
                properties={
                    "cheque_date": _date(),
                    "amount": {"type": "number", "exclusiveMinimum": 0},
                    # The six-digit number, not the full MICR line.
                    "cheque_number": {"type": "string", "pattern": "^[0-9]{6}$"},
                    "ifsc_code": _ifsc(),
                    "bank_name": _text(),
                    "bank_branch": _text(),
                    # The drawer's account the cheque is drawn on.
                    "account_number": {"type": "string", "pattern": "^[0-9]{9,18}$"},
                },
            ),
            # From the memo the bank issued when the cheque was dishonoured.
            EvidenceType.RETURN_MEMO: _object(
                required=["presentation_date", "return_date", "return_reason"],
                properties={
                    "presentation_date": _date(),
                    "return_date": _date(),
                    "return_reason": _choice(ReturnReason),
                },
            ),
            EvidenceType.LEGAL_DEMAND_NOTICE: _object(
                required=[
                    "nature_of_debt",
                    "dispatch_date",
                    "mode_of_service",
                    "is_delivered",
                    "payment_status",
                ],
                properties={
                    # Nature of debt
                    "nature_of_debt": _choice(NatureOfDebt),
                    # Legal demand notice
                    "dispatch_date": _date(),
                    "mode_of_service": _choice(ModeOfService),
                    "tracking_number": _text(),
                    "is_delivered": {"type": "boolean"},
                    # The 15-day payment window runs from this date.
                    "delivery_date": _date(),
                    # When an undelivered notice came back to the delivery agency.
                    "return_date": _date(),
                    "non_delivery_reason": _text(),
                    "accused_replied": {"type": "boolean"},
                    # Payment against the cheque
                    "payment_status": _choice(PaymentStatus),
                    "part_payment_amount": {"type": "number", "exclusiveMinimum": 0},
                },
                allOf=[
                    # A delivered notice needs its delivery date; an undelivered
                    # one, when it came back and why.
                    _required_when("is_delivered", True, ["delivery_date"]),
                    _required_when("is_delivered", False, ["return_date", "non_delivery_reason"]),
                    _required_when(
                        "payment_status", PaymentStatus.PART_PAYMENT.value, ["part_payment_amount"]
                    ),
                ],
            ),
        },
    ),
}


def get_config(case_type):
    """Return the configuration for ``case_type``."""
    return CASE_TYPES[case_type]


@dataclass(frozen=True)
class SchemaError:
    """One way data breaks a schema.

    ``path`` locates the offending value (``cheque_number``, ``items[0].name``),
    empty for the object as a whole; jsonschema's ``message`` names the value
    but not where it was sent. ``keyword`` is the schema keyword that failed
    (``required``, ``pattern`` …).
    """

    path: str
    message: str
    keyword: str

    def __str__(self):
        return f"{self.path}: {self.message}" if self.path else self.message


def schema_errors(schema, data):
    """Return every way ``data`` breaks ``schema``; empty when it fits.

    Shared by the API (which reports them as a 400, each on its field path) and
    the models' ``clean()`` (so the admin, and any other write that validates,
    enforces the same rules).
    """
    validator = jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker())
    return [
        SchemaError(_path(error.absolute_path), error.message, error.validator)
        for error in validator.iter_errors(data)
    ]


def section_errors(config, section, data):
    """Return every way ``data`` breaks ``section``'s schema and checks; empty when it fits.

    The checks run only on data that fits the schema's shape (an object).
    """
    problems = schema_errors(config.section_schemas[section], data)
    check = config.section_checks.get(section)
    if check and isinstance(data, dict):
        problems += check(data)
    return problems


def _path(parts):
    """Build a spec 0000 §9.1 field path: dotted keys, indexed list elements."""
    path = ""
    for part in parts:
        if isinstance(part, int):
            path += f"[{part}]"
        else:
            path += f".{part}" if path else str(part)
    return path


def get_description(case_type):
    """Return what ``case_type`` accepts, for clients to build their forms from."""
    config = get_config(case_type)
    return {
        "case_type": case_type,
        "label": CaseType(case_type).label,
        "sections": [
            {"code": code, "schema": schema} for code, schema in config.section_schemas.items()
        ],
        "document_types": [
            {"code": code, "label": DocumentType(code).label} for code in config.document_types
        ],
        "required_document_types": list(config.required_document_types),
        "evidence_types": [
            {"code": code, "label": EvidenceType(code).label, "schema": schema}
            for code, schema in config.evidence_schemas.items()
        ],
    }
