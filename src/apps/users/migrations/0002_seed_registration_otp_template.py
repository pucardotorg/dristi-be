"""Seed the SMS template that registration OTPs are sent with.

The login template (ACCOUNT_LOGIN_OTP_SMS) already ships with the messaging
app. Registration needs its own so the wording matches what the user is
actually doing, and it is seeded here rather than in messaging/ because this
app is its only caller.
"""

from django.db import migrations

TEMPLATE = {
    "message_key": "ACCOUNT_REGISTRATION_OTP_SMS",
    "message_type": "sms",
    "subject": "",
    "content": "Use OTP {{otp}} to verify your mobile number and create your account - On Courts",
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
    """Create or update the registration OTP template."""
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
    """Remove the registration OTP template."""
    MessageTemplate = apps.get_model("messaging", "MessageTemplate")
    MessageTemplate.objects.filter(
        message_key=TEMPLATE["message_key"],
        message_type=TEMPLATE["message_type"],
    ).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("users", "0001_initial"),
        # The template table and its key-format constraint must exist first.
        ("messaging", "0005_seed_message_templates"),
    ]

    operations = [
        migrations.RunPython(seed_template, unseed_template),
    ]
