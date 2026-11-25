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


def _seed():
    from io import StringIO

    from django.core.management import call_command

    from conftest import CORE_SEED, MIGRATED_DATA

    call_command("seed", *[str(CORE_SEED / name) for name in MIGRATED_DATA], stdout=StringIO())


@pytest.fixture(autouse=True)
def seeded(settings, django_db_setup):
    """Seed the reference data again: a transactional test flushes the tables when it ends,
    taking the session's seed with it, so every test here starts by loading its own."""
    _seed()


@pytest.fixture(scope="module", autouse=True)
def reseeded_after(django_db_setup, django_db_blocker):
    """Leave the session's seed behind: the last test's flush ran before this teardown."""
    yield
    with django_db_blocker.unblock():
        _seed()


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


def _wait_until_blocked_on_a_lock(timeout=10):
    """Wait until some other connection is waiting for a row lock."""
    import time

    time.sleep(0.5)  # let the other thread connect and reach the lock
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with connection.cursor() as cursor:
            cursor.execute(
                "select count(*) from pg_stat_activity "
                "where wait_event_type = 'Lock' and datname = current_database()"
            )
            if cursor.fetchone()[0]:
                return
        time.sleep(0.05)
    raise AssertionError("no connection ever waited for the court lock")


def test_a_hearing_scheduled_while_a_date_is_being_held_becomes_the_one_it_moves(
    case, drafter, setter
):
    """The listed hearing is read under the court lock (spec 0039 #6.4): a hearing another
    order confirms while this one waits for the lock is the hearing this order moves."""
    import datetime
    import threading

    from django.db import transaction

    from apps.hearings.models import Hearing
    from apps.hearings.services import calendar
    from apps.hearings.tests.factories import schedule

    from .factories import TODAY

    order = drafting.create_outside_hearing(case_id=case.pk, actor=drafter)
    outcome = {}

    def set_date():
        try:
            next_hearing.set_next_hearing(
                order.pk,
                state="LISTED",
                date=TODAY.replace(day=26),
                purpose="ARGUMENTS",
                actor=setter,
            )
        except BaseException as exc:  # noqa: BLE001 - reported to the test
            outcome["error"] = exc
        finally:
            connections.close_all()

    with transaction.atomic():
        calendar.lock_court(case.court_id)  # another order is confirming, holding the court
        worker = threading.Thread(target=set_date, daemon=True)
        worker.start()
        _wait_until_blocked_on_a_lock()
        listed = schedule(case, TODAY.replace(day=19) if TODAY.day != 19 else TODAY, "APPEARANCE")
    worker.join(timeout=RACE_TIMEOUT_SECONDS)
    assert not worker.is_alive()
    assert "error" not in outcome, outcome
    order.refresh_from_db()
    assert order.moves_hearing_id == listed.pk
    hold = Hearing.objects.get(source_order_id=order.pk, status="PROVISIONAL")
    assert hold.moves_hearing_id == listed.pk
    assert order.items.get().item_type.code == "RESCHEDULING_OF_HEARING_DATE"
    assert datetime  # (kept for clarity of the date maths above)


def test_two_deliveries_of_one_order_dispatch_each_stage_event_once(
    ready, staff, signer, monkeypatch
):
    """The stage step is claimed under its row lock (spec 0039 #9.2): a duplicate delivery
    that overlaps it stops instead of dispatching the events again."""
    import time

    from apps.orders import ports
    from apps.orders.services import items as item_service
    from apps.orders.services import triggering

    item_service.add(ready.pk, "COGNIZANCE", actor=staff)
    lifecycle.mark_complete(ready.pk, actor=staff)
    lifecycle.send_for_signing(ready.pk, actor=staff)
    signing.record_signed_file(ready.pk, "signed", "DSC", actor=signer)
    calls = []

    def slow_dispatch(case_id, event, context):
        calls.append(event)
        time.sleep(1.5)  # long enough for the other delivery to arrive meanwhile

    monkeypatch.setattr(ports, "dispatch_stage_event", slow_dispatch)
    # The HEARING step does not apply to this order; make sure only the stage step is left.
    OrderWorkflowRun.objects.filter(order_id=ready.pk).exclude(step="STAGE").update(status="DONE")
    results = race(lambda: triggering.run(ready.pk), lambda: triggering.run(ready.pk))
    assert not [r for r in results if isinstance(r, BaseException)], results
    assert calls == ["COGNIZANCE_TAKEN"]
    stage = OrderWorkflowRun.objects.get(order_id=ready.pk, step="STAGE")
    assert stage.status == "DONE" and stage.attempts == 1
    assert sorted(results) == [0, 1]  # the loser is told to look again later
