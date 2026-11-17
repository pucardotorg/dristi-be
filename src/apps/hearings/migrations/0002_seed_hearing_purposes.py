"""Seed the hearing purposes from the order template catalogue (spec 0023 #2.2).

Self-contained on purpose: the rows are copied here, not imported, so later
edits to the app cannot change what this migration seeds. ``REVIEW_APPLICATION``
appears twice in the catalogue and is seeded once. A purpose that already
exists under the code is left as it is, so admin edits survive a re-run.
"""

from django.db import migrations

# (code, label), in display order; sequence is the 1-based position.
PURPOSES = [
    ("CONDONATION_OF_DELAY", "Condonation of delay"),
    ("ADMISSION", "Admission"),
    ("DELAY_CONDONATION_AND_ADMISSION", "Delay condonation and admission"),
    ("COGNIZANCE", "Cognizance"),
    ("APPEARANCE", "Appearance"),
    ("BAIL", "Bail"),
    ("PLEA", "Plea"),
    ("EVIDENCE_OF_COMPLAINANT", "Evidence of the complainant"),
    ("EXAMINATION_OF_ACCUSED", "Examination of the accused under S. 351 BNSS"),
    ("EVIDENCE_OF_ACCUSED", "Evidence of the accused"),
    ("ARGUMENTS", "Arguments"),
    ("JUDGEMENT", "Judgement"),
    ("FOR_REPORTS", "For reports"),
    ("ADR", "ADR"),
    ("MEDIATION", "Mediation"),
    ("WARRANT", "Warrant"),
    ("EXECUTION", "Execution"),
    ("REVIEW_APPLICATION", "Review application"),
    ("TO_ISSUE_ORDER", "To issue order"),
]


def seed(apps, schema_editor):
    """Create each purpose that does not exist yet."""
    HearingPurpose = apps.get_model("hearings", "HearingPurpose")
    for sequence, (code, label) in enumerate(PURPOSES, start=1):
        HearingPurpose.objects.get_or_create(
            code=code, defaults={"label": label, "sequence": sequence}
        )


def unseed(apps, schema_editor):
    """Remove the seeded purposes."""
    apps.get_model("hearings", "HearingPurpose").objects.filter(
        code__in=[code for code, _ in PURPOSES]
    ).delete()


class Migration(migrations.Migration):
    """Data migration seeding the hearing purposes."""

    dependencies = [("hearings", "0001_initial")]

    operations = [migrations.RunPython(seed, unseed)]
