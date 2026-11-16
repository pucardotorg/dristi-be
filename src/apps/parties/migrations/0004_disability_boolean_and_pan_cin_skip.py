"""Turn ``disability_status`` into a yes/no boolean; record the PAN/CIN skip declaration.

Postgres cannot cast the old disability text values to a boolean, so the
column is dropped and added again. No deployment holds real data yet, so the
old values are not carried over.
"""

from django.db import migrations, models

PEOPLE = ("person", "historicalperson")
INSTITUTIONS = ("institution", "historicalinstitution")


class Migration(migrations.Migration):
    dependencies = [
        ("parties", "0003_institution_pan_cin"),
    ]

    operations = [
        *(migrations.RemoveField(model_name=name, name="disability_status") for name in PEOPLE),
        *(
            migrations.AddField(
                model_name=name,
                name="disability_status",
                field=models.BooleanField(default=False, db_default=False),
            )
            for name in PEOPLE
        ),
        *(
            migrations.AddField(
                model_name=name,
                name="pan_cin_skip_declared",
                field=models.BooleanField(default=False, verbose_name="Declared no PAN or CIN"),
            )
            for name in INSTITUTIONS
        ),
        migrations.AddConstraint(
            model_name="institution",
            constraint=models.CheckConstraint(
                check=models.Q(
                    ("pan_cin_skip_declared", False),
                    models.Q(("cin__isnull", True), ("pan__isnull", True)),
                    _connector="OR",
                ),
                name="parties_institution_skip_declared_without_pan_cin",
                violation_error_message=(
                    "Leave the PAN and CIN out when declaring that neither is given."
                ),
            ),
        ),
    ]
