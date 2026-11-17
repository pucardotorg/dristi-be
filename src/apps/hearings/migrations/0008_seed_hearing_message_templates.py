"""Seed the SMS templates hearings notify parties with (spec 0023 #11.1)."""

from django.db import migrations


def _schema(*keys):
    return {
        "type": "object",
        "properties": {key: {"type": "string"} for key in keys},
        "required": list(keys),
        "additionalProperties": False,
    }


TEMPLATES = [
    {
        "message_key": "HEARING_SCHEDULED",
        "content": (
            "Case {{case_number}} ({{case_title}}) is listed on {{hearing_date}} at {{sitting_time}} "
            "for {{purpose}} before {{court}} ({{mode}}). - On Courts"
        ),
        "data_schema": _schema(
            "case_number", "case_title", "hearing_date", "sitting_time", "purpose", "court", "mode"
        ),
    },
    {
        "message_key": "HEARING_RESCHEDULED",
        "content": (
            "The hearing of case {{case_number}} ({{case_title}}) on {{old_date}} is moved to "
            "{{new_date}} for {{purpose}}. Reason: {{reason}}. - On Courts"
        ),
        "data_schema": _schema(
            "case_number", "case_title", "old_date", "new_date", "purpose", "reason"
        ),
    },
    {
        "message_key": "HEARING_CANCELLED",
        "content": (
            "The hearing of case {{case_number}} ({{case_title}}) on {{hearing_date}} is cancelled."
            " - On Courts"
        ),
        "data_schema": _schema("case_number", "case_title", "hearing_date"),
    },
]


def seed_templates(apps, schema_editor):
    MessageTemplate = apps.get_model("messaging", "MessageTemplate")
    for template in TEMPLATES:
        MessageTemplate.objects.update_or_create(
            message_key=template["message_key"],
            message_type="sms",
            defaults={
                "subject": "",
                "content": template["content"],
                "data_schema": template["data_schema"],
                "priority": "MEDIUM",
                "category": "NOTIFICATION",
                "max_retries": 0,
            },
        )


def unseed_templates(apps, schema_editor):
    MessageTemplate = apps.get_model("messaging", "MessageTemplate")
    MessageTemplate.objects.filter(
        message_key__in=[template["message_key"] for template in TEMPLATES], message_type="sms"
    ).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("hearings", "0007_bulk_reschedule"),
        ("messaging", "0007_gateway_audit_fields"),
    ]

    operations = [
        migrations.RunPython(seed_templates, unseed_templates),
    ]
