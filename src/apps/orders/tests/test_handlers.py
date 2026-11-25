"""Handlers (spec 0039 #1.2, #9.3): the registry, the system check and the built-ins."""

import datetime
import uuid

import pytest
from django.core.checks import Error, Warning  # noqa: A004
from rest_framework.exceptions import NotFound

from apps.api.errors import BusinessError
from apps.orders import handlers
from apps.orders.handlers import base, checks
from apps.orders.handlers.base import ItemContext, OrderItemHandler, RunResult
from apps.orders.models import OrderItem, OrderItemType, OrderWorkflowRun
from apps.orders.services import items, lifecycle, signing, triggering

from .factories import code
from .test_triggering import COST, trigger

pytestmark = pytest.mark.django_db


class Stub(OrderItemHandler):
    item_codes = ("BAIL",)

    def execute(self, ctx, values, *, run_id):
        return RunResult("DONE", {"stub": True})


@pytest.fixture
def registry():
    """Restore the registry after a test changes it."""
    saved = base.registered()
    yield
    base._registry.clear()
    base._registry.update(saved)


def test_the_registry_refuses_a_second_real_handler(registry):
    base.register(Stub())
    with pytest.raises(base.DuplicateHandler):
        base.register(Stub())


def test_a_real_handler_replaces_a_placeholder(registry):
    assert base.get("BAIL").placeholder is True
    base.register(Stub())
    assert base.get("BAIL").placeholder is False


def test_register_builtin_never_replaces_a_real_handler_with_a_stand_in(registry):
    base.register(Stub())
    handlers.register_builtin()
    assert base.get("BAIL").placeholder is False


def test_the_check_fails_for_a_workflow_item_without_a_handler(registry):
    base.unregister("COST")
    errors = checks.check_workflow_items_have_handlers(None, databases=["default"])
    assert [e.id for e in errors if isinstance(e, Error)] == ["orders.E001"]
    assert "COST" in errors[0].msg


def test_the_check_warns_about_placeholders_until_the_owning_modules_register(registry):
    results = checks.check_workflow_items_have_handlers(None, databases=["default"])
    warnings = [r for r in results if isinstance(r, Warning)]
    assert [w.id for w in warnings] == ["orders.W001"]
    assert "ISSUE_OF_SUMMONS" in warnings[0].msg and "ACCEPT_APPLICATION" in warnings[0].msg
    base.register(Stub())
    results = checks.check_workflow_items_have_handlers(None, databases=["default"])
    listed = results[-1].msg.removeprefix("Order items using a placeholder handler: ").rstrip(".")
    assert "BAIL" not in listed.split(", ")


def test_a_retired_workflow_item_needs_no_handler(registry):
    base.unregister("COST")
    OrderItemType.objects.filter(code="COST").update(is_active=False)
    assert (
        checks.check_workflow_items_have_handlers(None, databases=["default"])[0].id
        != "orders.E001"
    )


# -- built-ins ---------------------------------------------------------------------------


def test_mandatory_submission_opens_a_task_for_the_directed_side(
    ready, staff, signer, record_ports
):
    values = {
        "party_type": "ACCUSED",
        "document_type": "REPLY",
        "document_details": "Reply to the complaint",
        "deadline": (datetime.date.today() + datetime.timedelta(days=30)).isoformat(),
    }
    order = trigger(ready, staff, signer, ("MANDATORY_SUBMISSIONS", values))
    triggering.run(order.pk)
    (call,) = [(a, k) for n, a, k in record_ports if n == "open_item_task"]
    assert call[0][2] == "mandatory_submission"
    assert call[1]["side"] == "ACCUSED" and call[1]["due"] == values["deadline"]


def test_mandatory_submission_needs_all_its_fields_to_complete(ready, staff):
    items.add(ready.pk, "MANDATORY_SUBMISSIONS", actor=staff, values={"party_type": "ACCUSED"})
    with pytest.raises(Exception) as excinfo:
        lifecycle.mark_complete(ready.pk, actor=staff)
    keys = dict(excinfo.value.problems)
    assert {"items[1].values.document_type", "items[1].values.deadline"} <= set(keys)


def test_cost_paying_and_receiving_party_must_differ(ready, staff):
    bad = {**COST, "receiving_party": "ACCUSED"}
    with pytest.raises(Exception) as excinfo:
        items.add(ready.pk, "COST", actor=staff, values=bad)
    assert "values.receiving_party" in excinfo.value.detail


def test_a_cost_demand_is_raised_for_the_paying_sides_user(ready, staff, signer, case):
    from apps.payments.models import Demand

    order = trigger(
        ready,
        staff,
        signer,
        ("COST", {**COST, "paying_party": "COMPLAINANT", "receiving_party": "COURT"}),
    )
    triggering.run(order.pk)
    demand = Demand.objects.get(reference_type="ORDER")
    from apps.cases.models import CaseParticipant, ParticipantRole

    complainant = CaseParticipant.objects.get(case=case, role=ParticipantRole.COMPLAINANT)
    assert demand.user_id == complainant.person.user_id


def test_witness_batta_opens_a_task_and_the_paying_side_confirms_it(
    ready, staff, signer, record_ports, case, complainant_user
):
    from apps.cases.models import CaseParticipant, ParticipantRole
    from apps.parties.models import Person

    witness = CaseParticipant.objects.create(
        case=case,
        person=Person.objects.create(name="W", phone_number="+919700000001"),
        role=ParticipantRole.WITNESS,
        ordinal=1,
        name_at_filing="W",
    )
    values = {"paying_party": "COMPLAINANT", "amount": "100.00", "pay_by": "2026-12-01"}
    order = trigger(ready, staff, signer, ("WITNESS_BATTA", values))
    triggering.run(order.pk)
    item = order.items.get()
    assert item.values["witness"] == str(witness.pk)
    assert "witness_batta" in [args[2] for n, args, _ in record_ports if n == "open_item_task"]
    # Not the other side, not a stranger.
    from apps.hearings.tests.factories import make_user

    for outsider in (staff, make_user(name="Nobody")):
        with pytest.raises((NotFound, BusinessError)):
            items.confirm_paid(order.pk, item.pk, user=outsider)
    items.confirm_paid(order.pk, item.pk, user=complainant_user)
    assert "witness_batta" in [args[1] for n, args, _ in record_ports if n == "complete_item_task"]
    run = order.runs.get(order_item=item)
    assert run.result["paid_confirmed_by"] == str(complainant_user.pk)


def test_a_party_cannot_confirm_a_batta_on_an_order_that_is_not_yet_signed(
    ready, staff, complainant_user
):
    from rest_framework.exceptions import NotFound

    item = items.add(ready.pk, "WITNESS_BATTA", actor=staff)
    with pytest.raises(NotFound):  # a draft does not exist for a party (PUB-02)
        items.confirm_paid(ready.pk, item.pk, user=complainant_user)


def test_placeholder_defaults_name_every_accused(ready):
    handler = handlers.get("ISSUE_OF_SUMMONS")
    ctx = ItemContext(case_id=ready.case_id, order_id=ready.pk)
    assert len(handler.defaults(ctx)["party_names"]) == 1
    assert signing and code


def test_the_mandatory_submission_deadline_uses_the_court_date(monkeypatch):
    from apps.hearings.services import calendar
    from apps.orders.handlers.builtin import MandatorySubmissionHandler

    court_today = datetime.date(2026, 5, 10)
    monkeypatch.setattr(calendar, "business_date", lambda: court_today)
    handler = MandatorySubmissionHandler()
    yesterday = (court_today - datetime.timedelta(days=1)).isoformat()
    assert handler.validate(None, {"deadline": yesterday}, complete=True)
    assert not handler.validate(None, {"deadline": court_today.isoformat()}, complete=True)


def test_cost_demand_lookup_and_creation_hold_the_item_lock(ready, staff, monkeypatch):
    """The run's own item row is locked before the demand is looked up or raised."""
    from django.db.models import QuerySet

    from apps.orders.handlers import builtin
    from apps.orders.handlers.base import ItemContext
    from apps.payments.models import Demand
    from apps.payments.services.demands import DemandService

    other = items.add(ready.pk, "COGNIZANCE", actor=staff)  # a row it must not lock instead
    item = items.add(ready.pk, "COST", actor=staff)
    events = []
    real_get = QuerySet.get
    real_filter = Demand.objects.filter

    def get(self, *args, **kwargs):
        row = real_get(self, *args, **kwargs)
        if self.query.select_for_update:
            events.append(("lock", self.model, row.pk))
        return row

    def lookup(*args, **kwargs):
        events.append(("lookup", Demand))
        return real_filter(*args, **kwargs)

    def raise_demand(**kwargs):
        # The sentinel stops the handler here, before any payment side effect.
        assert events == [("lock", OrderItem, item.pk), ("lookup", Demand)], (
            "the run's own item row must be locked before the demand is looked up"
        )
        raise RuntimeError("stop")

    monkeypatch.setattr(QuerySet, "get", get)
    monkeypatch.setattr(Demand.objects, "filter", lookup)
    monkeypatch.setattr(DemandService, "raise_demand", raise_demand)
    ctx = ItemContext(
        case_id=ready.case_id,
        order_id=ready.pk,
        hearing_id=ready.hearing_id,
        target_type="",
        target_id=None,
        item_id=item.pk,
        source="",
    )
    with pytest.raises(RuntimeError, match="stop"):
        builtin.CostHandler().execute(ctx, {"amount": "10", "paying_party": "ACCUSED"}, run_id=None)
    assert other.pk != item.pk


def test_a_batta_cannot_be_confirmed_before_its_workflow_step_is_done(
    ready, staff, signer, complainant_user, record_ports, case
):
    from apps.cases.models import CaseParticipant, ParticipantRole
    from apps.orders.enums import RunStatus
    from apps.parties.models import Person

    CaseParticipant.objects.create(
        case=case,
        person=Person.objects.create(name="W", phone_number="+919700000001"),
        role=ParticipantRole.WITNESS,
        ordinal=1,
        name_at_filing="W",
    )
    values = {"paying_party": "COMPLAINANT", "amount": "100.00", "pay_by": "2026-12-01"}
    order = trigger(ready, staff, signer, ("WITNESS_BATTA", values))
    item = order.items.get()
    OrderWorkflowRun.objects.filter(order_item=item).update(status=RunStatus.PENDING)
    with pytest.raises(BusinessError):
        items.confirm_paid(order.pk, item.pk, user=complainant_user)
    assert "paid_confirmed_by" not in order.runs.get(order_item=item).result


@pytest.mark.parametrize(
    ("item_code", "payload"),
    [
        ("COGNIZANCE", {}),
        ("MOVE_OUT_OF_LONG_PENDING_REGISTER", {}),
        ("SCHEDULING_OF_HEARING_DATE", {"done_by": "HEARING"}),
        ("RESCHEDULING_OF_HEARING_DATE", {"done_by": "HEARING"}),
    ],
)
def test_items_whose_effect_is_another_step_are_done_at_once(ready, item_code, payload):
    """Their work is the HEARING or STAGE step's, so their own run has nothing left to do."""
    ctx = ItemContext(case_id=ready.case_id, order_id=ready.pk)
    result = handlers.get(item_code).execute(ctx, {}, run_id=uuid.uuid4())
    assert (result.status, result.payload) == ("DONE", payload)


def test_an_item_with_no_workflow_of_its_own_is_done_at_once():
    from apps.orders.handlers.builtin import NoWorkflowHandler

    result = NoWorkflowHandler().execute(None, {}, run_id=uuid.uuid4())
    assert result == RunResult("DONE")


def test_the_contract_defaults_check_nothing_and_say_nothing(ready):
    ctx = ItemContext(case_id=ready.case_id, order_id=ready.pk)
    assert Stub().validate_target(ctx) == []
    assert Stub().summary(ctx, {"any": "value"}) == ""


def test_rescheduling_has_no_defaults_without_a_scheduled_hearing(case):
    ctx = ItemContext(case_id=case.pk, order_id=uuid.uuid4())
    assert handlers.get("RESCHEDULING_OF_HEARING_DATE").defaults(ctx) == {}


def test_process_defaults_are_empty_for_a_case_without_an_accused(case):
    from apps.cases.models import CaseParticipant, ParticipantRole

    CaseParticipant.objects.filter(case=case, role=ParticipantRole.ACCUSED).delete()
    ctx = ItemContext(case_id=case.pk, order_id=uuid.uuid4())
    assert handlers.get("ISSUE_OF_SUMMONS").defaults(ctx) == {}


def test_a_process_recipient_needs_a_channel_to_complete():
    handler = handlers.get("ISSUE_OF_SUMMONS")
    values = {"recipients": [{"party_id": str(uuid.uuid4()), "channels": ["EMAIL"]}, {}]}
    assert handler.validate(None, values, complete=False) == []
    problems = handler.validate(None, values, complete=True)
    assert [(p.field, p.code) for p in problems] == [("values.recipients[1].channels", "REQUIRED")]


def test_withdrawal_needs_the_applications_module_only_when_decided_on_an_application():
    from apps.orders.handlers.placeholders import MODULE_NOT_AVAILABLE

    handler = handlers.get("WITHDRAWAL_OF_CASE")
    case_id, order_id = uuid.uuid4(), uuid.uuid4()
    own = handler.execute(ItemContext(case_id=case_id, order_id=order_id), {}, run_id=uuid.uuid4())
    assert own.status == "DONE"
    on_application = handler.execute(
        ItemContext(case_id=case_id, order_id=order_id, target_id=uuid.uuid4()),
        {},
        run_id=uuid.uuid4(),
    )
    assert (on_application.status, on_application.error_code) == ("FAILED", MODULE_NOT_AVAILABLE)
    assert on_application.payload == {"module": "applications"}


def test_the_check_is_silent_when_the_catalogue_cannot_be_read(monkeypatch):
    from django.db import DatabaseError

    from apps.orders.models import OrderItemType

    def unreadable(*args, **kwargs):
        raise DatabaseError("no such table")

    monkeypatch.setattr(OrderItemType.objects, "filter", unreadable)
    assert checks.check_workflow_items_have_handlers(None, databases=["default"]) == []
