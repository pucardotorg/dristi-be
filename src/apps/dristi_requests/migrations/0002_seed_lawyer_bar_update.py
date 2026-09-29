"""Seed the LAWYER_BAR_UPDATE request type, its schema and approval step."""

from django.db import migrations

CODE = "LAWYER_BAR_UPDATE"
APPROVER_ROLE = "BAR_ID_APPROVER"
SCHEMA = {
    "type": "object",
    "required": ["name", "bar_number"],
    "properties": {
        "name": {"type": "string", "minLength": 1},
        "bar_number": {"type": "string", "minLength": 1},
    },
}


def seed(apps, schema_editor):
    """Create the request type, approval step and approver group."""
    RequestType = apps.get_model("dristi_requests", "RequestType")
    ApprovalStep = apps.get_model("dristi_requests", "ApprovalStep")
    Group = apps.get_model("auth", "Group")

    request_type, _ = RequestType.objects.update_or_create(
        code=CODE,
        defaults={
            "name": "Lawyer bar details update",
            "description": "Update a lawyer's name and bar registration number.",
            "schema": SCHEMA,
            "min_documents": 1,
            "is_active": True,
        },
    )
    group, _ = Group.objects.get_or_create(name=APPROVER_ROLE)
    ApprovalStep.objects.update_or_create(
        request_type=request_type,
        order=0,
        defaults={"approver_role": APPROVER_ROLE, "approver_group": group, "condition": {}},
    )


def unseed(apps, schema_editor):
    """Remove the seeded request type (and its steps)."""
    RequestType = apps.get_model("dristi_requests", "RequestType")
    RequestType.objects.filter(code=CODE).delete()


class Migration(migrations.Migration):
    """Data migration seeding the first request type."""

    dependencies = [
        ("dristi_requests", "0001_initial"),
        ("auth", "0012_alter_user_first_name_max_length"),
    ]

    operations = [migrations.RunPython(seed, unseed)]
