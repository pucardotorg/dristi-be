"""The processes seed: core/ for every state, then the state's own folder (spec 0028 #3.1)."""

from io import StringIO

from django.core.management import call_command

from apps.core import services as config
from apps.processes.models import Channel, NonDeliveryReason, ProcessType, ProcessTypeChannel

from .factories import SEED


def test_core_then_kerala_in_separate_runs_loads_every_row():
    """Seeded as a deployment runs it, one folder at a time; ``--strict`` fails on a skipped row."""
    for model in (ProcessTypeChannel, NonDeliveryReason, Channel, ProcessType):
        model.objects.all().delete()

    for folder in (SEED / "core" / "processes", SEED / "kerala" / "processes"):
        call_command("seed", str(folder), "--strict", stdout=StringIO())

    assert ProcessType.objects.count() == 6
    assert set(Channel.objects.filter(is_available=True).values_list("code", flat=True)) == {
        "SMS",
        "RPAD",
        "POLICE_RPAD",
        "POLICE_ICOPS",
        "BY_HAND",
    }
    assert ProcessTypeChannel.objects.count() == 27
    assert NonDeliveryReason.objects.filter(state_code="KL").count() == 7
    assert config.get("processes.kl", "court_fee.summons") == "2.00"
