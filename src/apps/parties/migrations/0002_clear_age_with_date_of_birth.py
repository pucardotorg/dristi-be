"""Drop stated ages kept next to a date of birth (spec 0020 §2.4).

``Person.clean_fields`` now clears ``age`` once the date of birth is known;
this brings rows saved under the earlier "must match" rule in line.
"""

from django.db import migrations


def clear_age(apps, schema_editor):
    Person = apps.get_model("parties", "Person")
    Person.objects.filter(date_of_birth__isnull=False, age__isnull=False).update(age=None)


class Migration(migrations.Migration):
    dependencies = [
        ("parties", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(clear_age, migrations.RunPython.noop),
    ]
