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
                    models.Q(
                        ("cin__isnull", True),
                        ("pan__isnull", True),
                        ("pan_cin_skip_declared", True),
                    ),
                    models.Q(
                        ("pan_cin_skip_declared", False),
                        models.Q(("pan__isnull", False), ("cin__isnull", False), _connector="OR"),
                    ),
                    _connector="OR",
                ),
                name="parties_institution_pan_cin_or_skip_declared",
                violation_error_message="Enter a PAN or a CIN, or declare that neither is given.",
            ),
        ),
    ]
