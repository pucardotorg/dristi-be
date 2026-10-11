"""Create a VERIFIED person for every existing litigant (spec 0020 §12.2).

Litigants registered through OTP before ``person`` existed, so they have no
row to link filings to. Their mobile number was OTP-confirmed, hence
VERIFIED. Advocates and clerks are left alone: they get a person only if they
become a party to a case. Re-running skips users who already have a person.
"""

from django.db import migrations

LITIGANT = "LITIGANT"
VERIFIED = "VERIFIED"


def backfill_litigant_persons(apps, schema_editor):
    """Insert one person per litigant user that does not have one yet."""
    User = apps.get_model("users", "User")
    Person = apps.get_model("parties", "Person")

    litigants = User.objects.filter(role=LITIGANT, person__isnull=True)
    Person.objects.bulk_create(
        [
            Person(
                name=user.name,
                phone_number=user.mobile_number,
                email_address=user.email or None,
                user_id=user.id,
                verification_level=VERIFIED,
            )
            for user in litigants.iterator()
        ],
        batch_size=500,
    )


class Migration(migrations.Migration):
    dependencies = [
        ("parties", "0001_initial"),
        ("users", "0003_audit_fields"),
    ]

    operations = [
        # Not reversed: by then the rows may be referenced by filings, and the
        # people they describe existed regardless.
        migrations.RunPython(backfill_litigant_persons, migrations.RunPython.noop),
    ]
