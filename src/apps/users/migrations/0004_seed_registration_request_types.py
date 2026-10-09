"""Seed the request types that verify an advocate's or clerk's registration."""

from django.db import migrations

APPROVER_ROLE = "BAR_ID_APPROVER"

REQUEST_TYPES = [
    {
        "code": "ADVOCATE_REGISTRATION",
        "name": "Advocate registration",
        "description": "Verify a new advocate's bar registration ID against their bar ID.",
        "schema": {
            "type": "object",
            "required": ["name", "bar_registration_id"],
            "properties": {
                "name": {"type": "string", "minLength": 1},
                "bar_registration_id": {"type": "string", "minLength": 1},
            },
        },
        "min_documents": 1,
    },
    {
        "code": "CLERK_REGISTRATION",
        "name": "Advocate clerk registration",
        "description": "Verify a new advocate clerk's registration number.",
        "schema": {
            "type": "object",
            "required": ["name", "clerk_registration_number"],
            "properties": {
                "name": {"type": "string", "minLength": 1},
                "clerk_registration_number": {"type": "string", "minLength": 1},
            },
        },
        # Only some clerks are asked for a bar ID.
        "min_documents": 0,
    },
]


def seed(apps, schema_editor):
    """Create the request types, each with one approval step."""
    RequestType = apps.get_model("dristi_requests", "RequestType")
    ApprovalStep = apps.get_model("dristi_requests", "ApprovalStep")
    Group = apps.get_model("auth", "Group")

    group, _ = Group.objects.get_or_create(name=APPROVER_ROLE)
    for spec in REQUEST_TYPES:
        request_type, _ = RequestType.objects.update_or_create(
            code=spec["code"],
            defaults={**{k: v for k, v in spec.items() if k != "code"}, "is_active": True},
        )
        ApprovalStep.objects.update_or_create(
            request_type=request_type,
            order=0,
            defaults={"approver_role": APPROVER_ROLE, "approver_group": group, "condition": {}},
        )


def unseed(apps, schema_editor):
    """Remove the seeded request types (and their steps)."""
    RequestType = apps.get_model("dristi_requests", "RequestType")
    RequestType.objects.filter(code__in=[spec["code"] for spec in REQUEST_TYPES]).delete()


class Migration(migrations.Migration):
    """Data migration seeding the registration verification request types."""

    dependencies = [
        ("users", "0003_audit_fields"),
        ("dristi_requests", "0003_request_document_uses_files"),
        ("auth", "0012_alter_user_first_name_max_length"),
    ]

    operations = [migrations.RunPython(seed, unseed)]
