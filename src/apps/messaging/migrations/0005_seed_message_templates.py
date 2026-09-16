from django.db import migrations

TEMPLATES = [
    {
        "message_key": "LOGIN_OTP_SMS",
        "message_type": "sms",
        "subject": "",
        "content": "Use OTP {{otp}} to log in to your account - On Courts",
        "data_schema": {
            "type": "object",
            "properties": {"otp": {"type": "string"}},
            "required": ["otp"],
            "additionalProperties": False,
        },
        "priority": "MEDIUM",
        "category": "OTP",
        "max_retries": 1,
    },
    {
        "message_key": "EFILE_SIGNATURE_PENDING_SMS",
        "message_type": "sms",
        "subject": "",
        "content": "Case file is pending your signature. Log in or use link {{link}} to sign. - On Courts",
        "data_schema": {
            "type": "object",
            "properties": {"link": {"type": "string"}},
            "required": ["link"],
            "additionalProperties": False,
        },
        "priority": "MEDIUM",
        "category": "NOTIFICATION",
        "max_retries": 0,
    },
    {
        "message_key": "CASE_FILING_MOBILE_VERIFICATION_OTP_SMS",
        "message_type": "sms",
        "subject": "",
        "content": "Use OTP {{otp}} to verify your mobile number and complete case filing for {{case_number}}. View the case file using link {{link}} - On Courts",
        "data_schema": {
            "type": "object",
            "properties": {
                "otp": {"type": "string"},
                "case_number": {"type": "string"},
                "link": {"type": "string"},
            },
            "required": ["otp", "case_number", "link"],
            "additionalProperties": False,
        },
        "priority": "MEDIUM",
        "category": "OTP",
        "max_retries": 1,
    },
    {
        "message_key": "CASE_SCRUTINY_ERRORS_SMS",
        "message_type": "sms",
        "subject": "",
        "content": "Errors have been identified in case {{case_number}} during scrutiny. Log in to {{link}} to rectify the file within {{deadline}} days. - On Courts",
        "data_schema": {
            "type": "object",
            "properties": {
                "case_number": {"type": "string"},
                "link": {"type": "string"},
                "deadline": {"type": "string"},
            },
            "required": ["case_number", "link", "deadline"],
            "additionalProperties": False,
        },
        "priority": "MEDIUM",
        "category": "NOTIFICATION",
        "max_retries": 0,
    },
    {
        "message_key": "CASE_SCRUTINY_PASSED_SMS",
        "message_type": "sms",
        "subject": "",
        "content": "Case {{case_number}} has passed scrutiny and is pending registration. - On Courts",
        "data_schema": {
            "type": "object",
            "properties": {"case_number": {"type": "string"}},
            "required": ["case_number"],
            "additionalProperties": False,
        },
        "priority": "MEDIUM",
        "category": "NOTIFICATION",
        "max_retries": 0,
    },
    {
        "message_key": "ACCOUNT_REGISTRATION_REJECTED_SMS",
        "message_type": "sms",
        "subject": "",
        "content": "Your account registration request has been rejected. Log in to {{link}} to view the reason and resubmit - On Courts",
        "data_schema": {
            "type": "object",
            "properties": {"link": {"type": "string"}},
            "required": ["link"],
            "additionalProperties": False,
        },
        "priority": "MEDIUM",
        "category": "NOTIFICATION",
        "max_retries": 0,
    },
    {
        "message_key": "ACCOUNT_REGISTRATION_APPROVED_SMS",
        "message_type": "sms",
        "subject": "",
        "content": "Your account registration request has been approved. Log in to {{link}} to start using your account - On Courts",
        "data_schema": {
            "type": "object",
            "properties": {"link": {"type": "string"}},
            "required": ["link"],
            "additionalProperties": False,
        },
        "priority": "MEDIUM",
        "category": "NOTIFICATION",
        "max_retries": 0,
    },
]


def seed_templates(apps, schema_editor):
    MessageTemplate = apps.get_model("messaging", "MessageTemplate")

    for template in TEMPLATES:
        MessageTemplate.objects.update_or_create(
            message_key=template["message_key"],
            message_type=template["message_type"],
            defaults={
                "subject": template["subject"],
                "content": template["content"],
                "data_schema": template["data_schema"],
                "priority": template["priority"],
                "category": template["category"],
                "max_retries": template["max_retries"],
            },
        )


def unseed_templates(apps, schema_editor):
    MessageTemplate = apps.get_model("messaging", "MessageTemplate")

    keys = [template["message_key"] for template in TEMPLATES]
    MessageTemplate.objects.filter(message_key__in=keys, message_type="sms").delete()


class Migration(migrations.Migration):
    dependencies = [
        ("messaging", "0004_enforce_uppercase_message_keys"),
    ]

    operations = [
        migrations.RunPython(seed_templates, unseed_templates),
    ]
