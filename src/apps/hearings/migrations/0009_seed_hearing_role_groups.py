"""Seed the groups the placeholder court roles are held as (spec 0023 #1.2, ``ports.py``).

Removed with ``ports.py`` once court roles are held per courtroom (spec 0026).
"""

from django.db import migrations

ROLES = ("HEARING_CONTROLLER", "NEXT_HEARING_SETTER", "ORDER_DATA_FILLER")


def seed_groups(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    for name in ROLES:
        Group.objects.get_or_create(name=name)


def unseed_groups(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Group.objects.filter(name__in=ROLES).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("hearings", "0008_seed_hearing_message_templates"),
        ("auth", "0012_alter_user_first_name_max_length"),
    ]

    operations = [
        migrations.RunPython(seed_groups, unseed_groups),
    ]
