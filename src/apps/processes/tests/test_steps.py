"""The step table's queries and tests agree (spec 0028 #4, ``steps.py``)."""

import uuid

import pytest

from apps.processes import steps
from apps.processes.enums import ProcessStatus, Step
from apps.processes.models import Channel, NonDeliveryReason, Process

from .factories import accused, mark_signed, recipient, start


@pytest.fixture
def processes(case):
    """A process on every allowed summons channel, put through every status."""
    made = start(case, recipient(accused(case), "SMS", "RPAD"))
    reason = NonDeliveryReason.objects.first()
    rows = []
    for status in ProcessStatus:
        for process in made:
            clone = Process.objects.get(pk=process.pk)
            clone.pk = None
            clone.order_item_id = uuid.uuid4()  # its own item, so it is not a duplicate
            clone.save()
            rows.append(mark_signed(clone, status=status, reason=reason))
    return rows


@pytest.mark.parametrize("step", list(Step))
def test_each_steps_query_matches_its_test(processes, step):
    rule = steps.STEPS[step]
    rows = Process.objects.filter(pk__in=[p.pk for p in processes])
    by_query = set(rows.filter(rule.where).values_list("pk", flat=True))
    by_test = {p.pk for p in processes if step in steps.applicable_steps(p)}

    assert by_query == by_test
    assert by_test, "the fixture reaches every step"


def test_a_system_send_is_not_a_persons_step(case):
    (process,) = start(case, recipient(accused(case), "SMS"))
    mark_signed(process)

    assert Channel.objects.get(code="SMS").send_mode == "SYSTEM"
    assert Step.SEND not in steps.applicable_steps(process)
