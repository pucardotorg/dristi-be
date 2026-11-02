"""Signal receivers (spec 0024 #1, #5.2).

Until the 0011 engine sends ``state_entered``, a round opens when a case is
saved in a stage status (``ports.STATUS_STAGE``). ``open_round`` returns the
open round when there is one, so every other save in that status is a no-op.

The filer's corrections and re-uploads are recorded from the ``apps.cases``
change signals, sent inside the write's transaction.
"""

from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.cases.models import Case
from apps.cases.signals import case_document_replaced, case_field_changed

from . import ports
from .services import responses, rounds


@receiver(post_save, sender=Case, dispatch_uid="scrutiny_open_round_on_stage_entry")
def open_round_on_stage_entry(sender, instance, raw=False, **kwargs):
    """Open the round for the stage the case is in, if none is open."""
    if not raw and instance.status in ports.STATUS_STAGE:
        rounds.open_round(instance)


@receiver(case_field_changed, dispatch_uid="scrutiny_record_field_change")
def record_field_change(sender, case_id, field_ref, section, old, new, actor, **kwargs):
    """Answer the raised flag on the changed field, or on its section (#5.2)."""
    responses.record_field_change(case_id, field_ref, section, old, new, actor)


@receiver(case_document_replaced, dispatch_uid="scrutiny_record_document_replaced")
def record_document_replaced(sender, case_id, old_document_id, new_document_id, actor, **kwargs):
    """Answer the raised flag on the replaced document (#5.2)."""
    responses.record_document_replaced(case_id, old_document_id, new_document_id, actor)
