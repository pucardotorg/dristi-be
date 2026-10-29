"""Signal receivers (spec 0024 #1).

Until the 0011 engine sends ``state_entered``, a round opens when a case is
saved in a stage status (``ports.STATUS_STAGE``). ``open_round`` returns the
open round when there is one, so every other save in that status is a no-op.
"""

from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.cases.models import Case

from . import ports
from .services import rounds


@receiver(post_save, sender=Case, dispatch_uid="scrutiny_open_round_on_stage_entry")
def open_round_on_stage_entry(sender, instance, raw=False, **kwargs):
    """Open the round for the stage the case is in, if none is open."""
    if not raw and instance.status in ports.STATUS_STAGE:
        rounds.open_round(instance)
