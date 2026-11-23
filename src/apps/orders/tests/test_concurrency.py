"""Racing signatures, completion, numbers and drafts (spec 0039 #12.5).

Real threads on real connections: ``select_for_update`` is a no-op on SQLite, so
these run only on PostgreSQL (CI sets ``DATABASE_URL``).
"""

import threading

import pytest
from django.db import connection, connections

from apps.api.errors import BusinessError
from apps.orders.enums import OrderStatus
from apps.orders.models import Order, OrderWorkflowRun
from apps.orders.services import drafting, lifecycle, next_hearing, signing

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.skipif(
        connection.vendor != "postgresql", reason="row locks need PostgreSQL (spec 0039 #12.5)"
    ),
]

RACE_TIMEOUT_SECONDS = 30


@pytest.fixture(autouse=True)
def seeded(settings, django_db_setup):
    """Seed the reference data again: a transactional test flushes the tables when it ends,
    taking the session's seed with it, so every test here starts by loading its own."""
    from io import StringIO

    from django.core.management import call_command

    from conftest import CORE_SEED, MIGRATED_DATA

    call_command("seed", *[str(CORE_SEED / name) for name in MIGRATED_DATA], stdout=StringIO())


def race(*calls):
    """Run ``calls`` at the same moment in threads; return each result or exception."""
    barrier = threading.Barrier(len(calls))
    results = [None] * len(calls)

    def run(index, call):
        try:
            barrier.wait()
            results[index] = call()
        except BaseException as exc:  # noqa: BLE001 - reported to the test
            results[index] = exc
        finally:
            connections.close_all()

    threads = [threading.Thread(target=run, args=(i, c), daemon=True) for i, c in enumerate(calls)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=RACE_TIMEOUT_SECONDS)
    stuck = [thread for thread in threads if thread.is_alive()]
    assert not stuck, f"{len(stuck)} worker(s) still running after {RACE_TIMEOUT_SECONDS}s"
    return results


def test_sign_and_mark_complete_arriving_together_trigger_exactly_once(ready, staff, signer):
    lifecycle.send_for_signing(ready.pk, actor=staff)
    results = race(
        lambda: signing.record_signed_file(ready.pk, "signed", "DSC", actor=signer),
        lambda: lifecycle.mark_complete(ready.pk, actor=staff),
    )
    assert not [r for r in results if isinstance(r, BaseException)], results
    order = Order.objects.get(pk=ready.pk)
    assert order.status == OrderStatus.TRIGGERED
    assert OrderWorkflowRun.objects.filter(order=order, step="HEARING").count() == 1


def test_two_signatures_at_once_record_one(ready, staff, signer):
    lifecycle.send_for_signing(ready.pk, actor=staff)
    results = race(
        lambda: signing.record_signed_file(ready.pk, "signed-a", "DSC", actor=signer),
        lambda: signing.record_signed_file(ready.pk, "signed-b", "DSC", actor=signer),
    )
    failures = [r for r in results if isinstance(r, BaseException)]
    assert len(failures) == 1 and isinstance(failures[0], BusinessError)
    assert failures[0].error.code == "E14001"
    assert Order.objects.get(pk=ready.pk).signed_file_id in ("signed-a", "signed-b")


def test_two_drafts_for_one_hearing_at_once_are_one_order(hearing, drafter, staff):
    results = race(
        lambda: drafting.create_in_hearing(hearing_id=hearing.pk, actor=drafter),
        lambda: drafting.create_in_hearing(hearing_id=hearing.pk, actor=staff),
    )
    assert not [r for r in results if isinstance(r, BaseException)], results
    assert len({order.pk for order, _ in results}) == 1
    assert sorted(created for _, created in results) == [False, True]
    assert Order.objects.filter(hearing_id=hearing.pk).count() == 1


def test_numbers_allotted_at_once_are_distinct_and_gap_free(
    case, courtroom, staff, signer, monkeypatch
):
    from apps.hearings.tests.factories import make_case

    monkeypatch.setattr(signing, "_store", lambda order, content, name, actor: "file")
    monkeypatch.setattr(signing, "_initiate", lambda order, actor, file_id: "initiation")
    orders = []
    for other in (case, make_case(courtroom), make_case(courtroom)):
        order = drafting.create_outside_hearing(case_id=other.pk, actor=staff)
        drafting.edit_text(order.pk, "<p>x</p>", actor=staff)
        next_hearing.set_next_hearing(order.pk, state="NOT_LISTED_AGAIN", actor=staff)
        lifecycle.send_for_signing(order.pk, actor=staff)
        orders.append(order)
    results = race(*[lambda o=o: signing.start_signing(o.pk, actor=signer) for o in orders])
    assert not [r for r in results if isinstance(r, BaseException)], results
    numbers = sorted(
        Order.objects.filter(pk__in=[o.pk for o in orders]).values_list("number", flat=True)
    )
    assert [n.rsplit("/", 2)[1] for n in numbers] == ["1", "2", "3"]
