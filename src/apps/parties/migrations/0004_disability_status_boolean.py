"""Turn ``disability_status`` from a kind of disability into a yes/no boolean.

Postgres cannot cast the old text values to a boolean, so the column is
dropped and added again. No deployment holds real data yet, so the old values
are not carried over.
"""

from django.db import migrations, models

MODELS = ("person", "historicalperson")


class Migration(migrations.Migration):
    dependencies = [
        ("parties", "0003_institution_pan_cin"),
    ]

    operations = [
        *(migrations.RemoveField(model_name=name, name="disability_status") for name in MODELS),
        *(
            migrations.AddField(
                model_name=name,
                name="disability_status",
                field=models.BooleanField(default=False, db_default=False),
            )
            for name in MODELS
        ),
    ]
