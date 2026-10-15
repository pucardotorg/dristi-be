"""Seed the SMS template that password-reset OTPs are sent with (see 0002)."""

from django.db import migrations

TEMPLATE = {
    "message_key": "ACCOUNT_PASSWORD_RESET_OTP_SMS",
    "message_type": "sms",
    "subject": "",
    "content": "Use OTP {{otp}} to reset your account password.",
    "data_schema": {
        "type": "object",
        "properties": {"otp": {"type": "string"}},
        "required": ["otp"],
        "additionalProperties": False,
    },
    "priority": "MEDIUM",
    "category": "OTP",
    "max_retries": 1,
}


def seed_template(apps, schema_editor):
    """Create or update the password-reset OTP template."""
    MessageTemplate = apps.get_model("messaging", "MessageTemplate")
    MessageTemplate.objects.update_or_create(
        message_key=TEMPLATE["message_key"],
        message_type=TEMPLATE["message_type"],
        defaults={
            "subject": TEMPLATE["subject"],
            "content": TEMPLATE["content"],
            "data_schema": TEMPLATE["data_schema"],
            "priority": TEMPLATE["priority"],
            "category": TEMPLATE["category"],
            "max_retries": TEMPLATE["max_retries"],
        },
    )


def unseed_template(apps, schema_editor):
    """Remove the password-reset OTP template."""
    MessageTemplate = apps.get_model("messaging", "MessageTemplate")
    MessageTemplate.objects.filter(
        message_key=TEMPLATE["message_key"],
        message_type=TEMPLATE["message_type"],
    ).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("users", "0004_seed_registration_request_types"),
        ("messaging", "0005_seed_message_templates"),
    ]

    operations = [
        migrations.RunPython(seed_template, unseed_template),
    ]
