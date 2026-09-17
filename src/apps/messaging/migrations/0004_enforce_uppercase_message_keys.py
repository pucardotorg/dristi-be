from django.db import migrations, models
from django.db.models import Count
from django.db.models.functions import Upper


def normalize_message_keys(apps, schema_editor):
    MessageTemplate = apps.get_model("messaging", "MessageTemplate")
    MessageLog = apps.get_model("messaging", "MessageLog")

    collisions = (
        MessageTemplate.objects.annotate(upper_key=Upper("message_key"))
        .values("upper_key", "message_type")
        .annotate(total=Count("id"))
        .filter(total__gt=1)
    )
    if collisions.exists():
        conflict = collisions.first()
        raise RuntimeError(
            "Cannot normalize message_key values to uppercase because duplicate "
            "templates would be created for key "
            f"'{conflict['upper_key']}' and type '{conflict['message_type']}'."
        )

    MessageTemplate.objects.update(message_key=Upper("message_key"))
    MessageLog.objects.update(message_key=Upper("message_key"))


class Migration(migrations.Migration):
    dependencies = [
        ("messaging", "0003_add_messagetemplate_category"),
    ]

    operations = [
        migrations.RunPython(normalize_message_keys, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="messagetemplate",
            constraint=models.CheckConstraint(
                check=models.Q(message_key__regex=r"^[A-Z][A-Z0-9_]*$"),
                name="messagetemplate_message_key_upper_snake",
            ),
        ),
        migrations.AddConstraint(
            model_name="messagelog",
            constraint=models.CheckConstraint(
                check=models.Q(message_key__regex=r"^[A-Z][A-Z0-9_]*$"),
                name="messagelog_message_key_upper_snake",
            ),
        ),
    ]
