"""Input and output contract of the CHECKS rule (spec 0024 #2.4).

The input is facts the case-type plugin computes; a rule never recomputes the
law. The output is a list of advisory alerts. 0019 validates both against the
bound rule's own schemas; this module validates them again against these, so a
rule whose schemas drift from the contract cannot reach the screen.
"""

from jsonschema import Draft202012Validator

DATE = {"type": "string", "format": "date"}
NULLABLE_DATE = {"type": ["string", "null"], "format": "date"}

CHECKS_INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "case_type": {"type": "string", "minLength": 1},
        "today": DATE,
        "cheques": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer", "minimum": 0},
                    "cheque_date": DATE,
                    "presented_on": DATE,
                    "valid_until": DATE,
                    "returned_on": DATE,
                    "amount": {"type": "number", "minimum": 0},
                    "return_reason": {"type": "string"},
                },
                "required": [
                    "index",
                    "cheque_date",
                    "presented_on",
                    "valid_until",
                    "returned_on",
                    "amount",
                    "return_reason",
                ],
                "additionalProperties": False,
            },
        },
        "notice": {
            "type": "object",
            "properties": {
                "dispatched_on": DATE,
                "served_on": NULLABLE_DATE,
                "delivered": {"type": "boolean"},
                "postal_receipt_uploaded": {"type": "boolean"},
                "delivery_proof_uploaded": {"type": "boolean"},
            },
            "required": [
                "dispatched_on",
                "served_on",
                "delivered",
                "postal_receipt_uploaded",
                "delivery_proof_uploaded",
            ],
            "additionalProperties": False,
        },
        "cause_of_action_on": NULLABLE_DATE,
        "filed_on": DATE,
        "delay_applicable": {"type": "boolean"},
        "delay_prayer_present": {"type": "boolean"},
        "complainant_is_institution": {"type": "boolean"},
        "complainant_cin_or_pan_present": {"type": "boolean"},
    },
    "required": [
        "case_type",
        "today",
        "cheques",
        "notice",
        "cause_of_action_on",
        "filed_on",
        "delay_applicable",
        "delay_prayer_present",
        "complainant_is_institution",
        "complainant_cin_or_pan_present",
    ],
    "additionalProperties": False,
}

SEVERITIES = ("INFO", "WARNING")

ALERT_SCHEMA = {
    "type": "object",
    "properties": {
        "code": {"type": "string", "pattern": "^[A-Z0-9_]+$"},
        "severity": {"enum": list(SEVERITIES)},
        "field_refs": {"type": "array", "items": {"type": "string", "minLength": 1}},
        "message": {"type": "string", "minLength": 1},
    },
    "required": ["code", "severity", "field_refs", "message"],
    "additionalProperties": False,
}

# Requiring "alerts" rejects the {} / [] ZEN returns when nothing matches, as
# 0019 demands of a GoRules output schema; a clean case is {"alerts": []}.
CHECKS_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {"alerts": {"type": "array", "items": ALERT_SCHEMA}},
    "required": ["alerts"],
    "additionalProperties": False,
}

# The spec's example filing: used for the admin dry run and the policy report.
SAMPLE_INPUT = {
    "case_type": "CHEQUE_BOUNCE",
    "today": "2026-08-03",
    "cheques": [
        {
            "index": 0,
            "cheque_date": "2019-04-05",
            "presented_on": "2016-04-04",
            "valid_until": "2019-07-04",
            "returned_on": "2016-04-04",
            "amount": 5205000,
            "return_reason": "FUNDS_INSUFFICIENT",
        }
    ],
    "notice": {
        "dispatched_on": "2016-04-12",
        "served_on": "2016-04-14",
        "delivered": True,
        "postal_receipt_uploaded": False,
        "delivery_proof_uploaded": False,
    },
    "cause_of_action_on": "2016-04-28",
    "filed_on": "2026-07-04",
    "delay_applicable": True,
    "delay_prayer_present": True,
    "complainant_is_institution": True,
    "complainant_cin_or_pan_present": False,
}

# Shown in place of the rule's alerts when the checks cannot be evaluated.
CHECKS_UNAVAILABLE = {
    "code": "CHECKS_UNAVAILABLE",
    "severity": "WARNING",
    "field_refs": [],
    "message": "Advisory checks are unavailable. Review the filing without them.",
}


class ContractError(Exception):
    """Facts or a rule result that do not satisfy the CHECKS contract."""


def _validator(schema):
    return Draft202012Validator(schema, format_checker=Draft202012Validator.FORMAT_CHECKER)


_INPUT = _validator(CHECKS_INPUT_SCHEMA)
_OUTPUT = _validator(CHECKS_OUTPUT_SCHEMA)


def _validate(validator, instance, label):
    problems = sorted(
        f"{'/'.join(str(part) for part in error.absolute_path) or '$'}: {error.message}"
        for error in validator.iter_errors(instance)
    )
    if problems:
        raise ContractError(f"{label} breaks the CHECKS contract: " + "; ".join(problems))


def validate_input(facts):
    """Raise ContractError unless ``facts`` satisfy the CHECKS input contract."""
    _validate(_INPUT, facts, "Input")


def validate_output(result):
    """Raise ContractError unless ``result`` satisfies the CHECKS output contract."""
    _validate(_OUTPUT, result, "Output")
