"""Seed the national CHECKS rule and its default binding (spec 0024 #2.4, #9.2).

Self-contained on purpose: the rule and its schemas are copied here, not
imported, so later edits to the app cannot change what this migration seeds.
A state changes its checks by adding its own rule and binding, not by editing
this one. A rule that already exists under the code is left as it is.
"""

import json

from django.db import migrations

RULE_CODE = "SCRUTINY_CHECKS_DEFAULT"

DATE = {"type": "string", "format": "date"}
NULLABLE_DATE = {"type": ["string", "null"], "format": "date"}

INPUT_SCHEMA = {
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

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "alerts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "code": {"type": "string", "pattern": "^[A-Z0-9_]+$"},
                    "severity": {"enum": ["INFO", "WARNING"]},
                    "field_refs": {"type": "array", "items": {"type": "string", "minLength": 1}},
                    "message": {"type": "string", "minLength": 1},
                },
                "required": ["code", "severity", "field_refs", "message"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["alerts"],
    "additionalProperties": False,
}


def _alert(code, severity, field_refs, message):
    """A ZEN object literal for one alert; ``field_refs`` and ``message`` are expressions."""
    return (
        f'{{code: "{code}", severity: "{severity}", field_refs: {field_refs}, message: {message}}}'
    )


def _cheque_ref(field_id):
    """A ZEN expression for ``field_id`` on the cheque in scope, e.g. ``CHQ-8[0]``."""
    return f'"{field_id}[" + string(#.index) + "]"'


def _per_cheque(condition, alert):
    """One alert for every cheque that meets ``condition``."""
    return f"map(filter(cheques, {condition}), {alert})"


# One row per check (collect hit policy): adding a check is adding a row. A
# blank "When" matches every case; per-cheque rows filter inside their output.
CHECKS = [
    (
        "PRESENTED_AFTER_VALIDITY",
        "",
        _per_cheque(
            "d(#.presented_on) > d(#.valid_until)",
            _alert(
                "PRESENTED_AFTER_VALIDITY",
                "WARNING",
                f"[{_cheque_ref('CHQ-8')}]",
                '"Presented after validity — valid until " + d(#.valid_until).format("%d/%m/%Y")',
            ),
        ),
    ),
    (
        "PRESENTED_BEFORE_CHEQUE_DATE",
        "",
        _per_cheque(
            "d(#.presented_on) < d(#.cheque_date)",
            _alert(
                "PRESENTED_BEFORE_CHEQUE_DATE",
                "WARNING",
                f"[{_cheque_ref('CHQ-1')}, {_cheque_ref('CHQ-8')}]",
                '"Presented before the date on the cheque."',
            ),
        ),
    ),
    (
        "NOTICE_AFTER_30_DAYS",
        "",
        _per_cheque(
            "d(notice.dispatched_on) > d(#.returned_on).add(30, 'd')",
            _alert(
                "NOTICE_AFTER_30_DAYS",
                "WARNING",
                f'[{_cheque_ref("CHQ-9")}, "LDN-2[0]"]',
                '"Demand notice dispatched more than 30 days after the cheque was returned."',
            ),
        ),
    ),
    (
        "DELAY_WITHOUT_PRAYER",
        "delay_applicable and not delay_prayer_present",
        "["
        + _alert(
            "DELAY_WITHOUT_PRAYER",
            "WARNING",
            '["JUR-11", "JUR-12"]',
            '"Filed after the limitation period with no prayer for condonation of delay."',
        )
        + "]",
    ),
    (
        "NON_FUNDS_RETURN_REASON",
        "",
        _per_cheque(
            '#.return_reason != "FUNDS_INSUFFICIENT"',
            _alert(
                "NON_FUNDS_RETURN_REASON",
                "WARNING",
                f"[{_cheque_ref('CHQ-9')}]",
                '"Returned for a reason other than insufficient funds — check that S.138 applies."',
            ),
        ),
    ),
    (
        "NO_POSTAL_RECEIPT",
        "not notice.postal_receipt_uploaded",
        "["
        + _alert("NO_POSTAL_RECEIPT", "INFO", '["LDN-3[0]"]', '"No postal receipt uploaded."')
        + "]",
    ),
    (
        "NO_DELIVERY_PROOF",
        "not notice.delivery_proof_uploaded",
        "["
        + _alert("NO_DELIVERY_PROOF", "INFO", '["LDN-6[0]"]', '"No delivery proof uploaded."')
        + "]",
    ),
    (
        "INSTITUTION_WITHOUT_CIN_OR_PAN",
        "complainant_is_institution and not complainant_cin_or_pan_present",
        "["
        + _alert(
            "INSTITUTION_WITHOUT_CIN_OR_PAN",
            "WARNING",
            '["LIT-18a[0]"]',
            '"Institutional complainant filed without a CIN or PAN."',
        )
        + "]",
    ),
]

GRAPH = {
    "nodes": [
        {"id": "request", "type": "inputNode", "name": "Request"},
        {
            "id": "checks",
            "type": "decisionTableNode",
            "name": "Scrutiny checks",
            "content": {
                "hitPolicy": "collect",
                # Under outputPath a table matching no row gives {"found": []}, not {}.
                "outputPath": "found",
                "inputs": [{"id": "when", "name": "When"}],
                "outputs": [
                    {"id": "check", "name": "Check", "field": "check"},
                    {"id": "alerts", "name": "Alerts", "field": "alerts"},
                ],
                "rules": [
                    {"_id": code, "when": when, "check": f'"{code}"', "alerts": alerts}
                    for code, when, alerts in CHECKS
                ],
            },
        },
        {
            "id": "flatten",
            "type": "expressionNode",
            "name": "Alerts",
            "content": {
                "expressions": [
                    {"id": "alerts", "key": "alerts", "value": "flatMap(found, #.alerts)"}
                ]
            },
        },
        {"id": "response", "type": "outputNode", "name": "Response"},
    ],
    "edges": [
        {"id": "request-checks", "sourceId": "request", "targetId": "checks", "type": "edge"},
        {"id": "checks-flatten", "sourceId": "checks", "targetId": "flatten", "type": "edge"},
        {"id": "flatten-response", "sourceId": "flatten", "targetId": "response", "type": "edge"},
    ],
}


def seed(apps, schema_editor):
    BusinessRule = apps.get_model("core", "BusinessRule")
    ScrutinyRuleBinding = apps.get_model("scrutiny", "ScrutinyRuleBinding")
    BusinessRule.objects.get_or_create(
        code=RULE_CODE,
        defaults={
            "name": "Scrutiny advisory checks (national default)",
            "description": "Warnings shown to the scrutiny officer beside the filed "
            "fields (spec 0024 #2.4). Advisory only; no alert blocks an action.",
            "engine": "gorules",
            "rule_expression": json.dumps(GRAPH, ensure_ascii=False),
            "rule_input_schema": INPUT_SCHEMA,
            "rule_output_schema": OUTPUT_SCHEMA,
        },
    )
    if not ScrutinyRuleBinding.objects.filter(
        decision="CHECKS", organization__isnull=True, is_active=True
    ).exists():
        ScrutinyRuleBinding.objects.create(
            decision="CHECKS",
            organization=None,
            rule_code=RULE_CODE,
            note="National default shipped with every deployment.",
        )


def unseed(apps, schema_editor):
    apps.get_model("scrutiny", "ScrutinyRuleBinding").objects.filter(
        decision="CHECKS", organization__isnull=True, rule_code=RULE_CODE
    ).delete()
    apps.get_model("core", "BusinessRule").objects.filter(code=RULE_CODE).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0006_businessrule_historicalbusinessrule"),
        ("scrutiny", "0001_initial"),
    ]

    operations = [migrations.RunPython(seed, unseed)]
