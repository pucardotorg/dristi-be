"""End to end through 0017's APIs with the real offline provider (spec 0032 #2, #17.5).

payer creates → instructions → staff look up → staff record → payer sees SUCCESS
→ raising module hears ``payment_completed``; and the abandoned-request path
through the poller.
"""

from datetime import timedelta
from unittest import mock

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from addon.offline_payment import constants, reference, validity
from addon.offline_payment.config import resolve_config
from apps.payments import errors as payment_errors
from apps.payments.enums import AttestationOutcome, DemandStatus, PaymentStatus
from apps.payments.models import Payment, PaymentAttestation
from apps.payments.services import PaymentService, polling
from apps.payments.signals import payment_completed
from apps.payments.tasks import notify_payment_completed
from apps.payments.tests.helpers import assert_error, item, item_ids

from .base import frozen_now

pytestmark = pytest.mark.django_db


@pytest.fixture
def clerk(make_user):
    from django.contrib.auth.models import Permission

    staff = make_user("Suresh K")
    staff.user_permissions.add(
        *Permission.objects.filter(
            content_type__app_label="payments",
            codename__in=[
                "view_payment_collection",
                "record_payment_collection",
                "record_late_payment_collection",
                "cancel_payment_collection",
            ],
        )
    )
    return type(staff).objects.get(pk=staff.pk)


def client_for(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


def create(payer_client, demand, key="attempt-1", **extra):
    body = {
        "client_request_id": key,
        "demand_item_ids": [str(i) for i in item_ids(demand)],
        "provider": "offline",
        "provider_options": {"counter": "EKM-CJM"},
        **extra,
    }
    return payer_client.post(
        reverse("payments-demand-payments", kwargs={"demand_id": demand.pk}), body, format="json"
    )


def collection_url(name, ref):
    return reverse(f"payments-collection-{name}", kwargs={"provider": "offline", "reference": ref})


def deliver_completions(callbacks):
    """Run the on-commit hooks, with the actor executing inline."""

    with mock.patch.object(notify_payment_completed, "send", side_effect=notify_payment_completed):
        for callback in callbacks:
            callback()


def test_payer_to_staff_to_success(
    offline, raise_demand, user, clerk, django_capture_on_commit_callbacks
):
    payer = client_for(user)
    demand = raise_demand([item(unit_amount="700.00"), item(unit_amount="7.50")])

    created = create(payer, demand)
    assert created.status_code == 201, created.content
    body = created.json()
    assert body["status"] == PaymentStatus.PENDING
    assert body["provider"] == "offline"
    action = body["provider_action"]
    assert action["kind"] == "SHOW_INSTRUCTIONS"
    details = {d["key"]: d["value"] for d in action["details"]}
    ref = body["provider_payment_id"]
    assert details["reference"] == ref and details["amount"] == "₹ 707.50"
    assert body["attestation"] is None

    # The clerk types the reference sloppily.
    desk = client_for(clerk)
    typed = ref.lower().replace("-", " ")
    lookup = desk.get(collection_url("detail", typed))
    assert lookup.status_code == 200, lookup.content
    assert lookup.json()["reference"] == ref
    assert lookup.json()["amount"] == "707.50"
    assert lookup.json()["expired"] is False

    received = []

    def receiver(sender, payment, demand_paid, **kwargs):
        received.append(demand_paid)

    payment_completed.connect(receiver)
    try:
        with django_capture_on_commit_callbacks() as callbacks:
            confirmed = desk.post(
                collection_url("confirm", ref),
                {
                    "amount": "707.50",
                    "method": "DEMAND_DRAFT",
                    "receipt_number": "cjm/ekm/2026/004512",
                    "details": {
                        "instrument_number": "123456",
                        "instrument_date": timezone.localdate().isoformat(),
                        "bank_name": "State Bank of India",
                    },
                },
                format="json",
            )
        deliver_completions(callbacks)
    finally:
        payment_completed.disconnect(receiver)
    assert confirmed.status_code == 200, confirmed.content
    assert confirmed.json()["attestation"]["outcome"] == AttestationOutcome.CREDITED
    assert received == [True]

    seen = payer.get(reverse("payments-payment-detail", kwargs={"payment_id": body["id"]})).json()
    assert seen["status"] == PaymentStatus.SUCCESS
    assert seen["provider_reference"] == "CJM/EKM/2026/004512"
    assert seen["attestation"]["method"] == "DEMAND_DRAFT"
    demand.refresh_from_db()
    assert demand.status == DemandStatus.PAID
    payment = Payment.objects.get()
    assert payment.metadata["provider"]["instrument_number"] == "123456"
    assert payment.metadata["provider"]["counter"] == "EKM-CJM"


def test_batch_of_three_demands_on_two_cases(offline, raise_demand, user, clerk, make_case):
    other_case = make_case()
    demands = [
        raise_demand([item()], reference_id="a"),
        raise_demand([item()], reference_id="b"),
        raise_demand([item()], case=other_case, reference_id="c"),
    ]
    response = client_for(user).post(
        reverse("payments-batch-list"),
        {
            "client_request_id": "batch-1",
            "provider": "offline",
            "provider_options": {"counter": "EKM-CJM"},
            "selections": [
                {"demand_id": str(d.pk), "demand_item_ids": [str(i) for i in item_ids(d)]}
                for d in demands
            ],
        },
        format="json",
    )
    assert response.status_code == 201, response.content
    body = response.json()
    details = {d["key"]: d["value"] for d in body["provider_action"]["details"]}
    assert details["amount"] == "₹ 37.50"
    assert len(details["payments"].split(", ")) == 3
    ref = body["payments"][0]["provider_payment_id"]

    desk = client_for(clerk)
    assert len(desk.get(collection_url("detail", ref)).json()["payments"]) == 3
    confirmed = desk.post(
        collection_url("confirm", ref),
        {"amount": "37.50", "method": "CASH", "receipt_number": "R-77"},
        format="json",
    )
    assert confirmed.status_code == 200, confirmed.content
    assert set(Payment.objects.values_list("status", flat=True)) == {PaymentStatus.SUCCESS}
    for demand in demands:
        demand.refresh_from_db()
        assert demand.status == DemandStatus.PAID


def test_abandoned_request_expires_and_items_are_payable_again(offline, raise_demand, user):
    payer = client_for(user)
    demand = raise_demand()
    create(payer, demand)
    payment = Payment.objects.get()
    issued_on = reference.parse(payment.provider_payment_id, "OFL").issued_on
    expires = validity.expires_at(issued_on, resolve_config())

    with frozen_now(expires - timedelta(hours=1)):
        polling.poll_one(payment, now=expires - timedelta(hours=1))
    payment.refresh_from_db()
    assert payment.status == PaymentStatus.PENDING

    after = expires + timedelta(minutes=1)
    with frozen_now(after):
        polling.poll_one(payment, now=after)
    payment.refresh_from_db()
    assert payment.status == PaymentStatus.FAILED
    assert payment.failure_code == constants.OFFLINE_REQUEST_EXPIRED
    assert not payment.needs_reconciliation  # failed, never PAYMENT_STUCK

    # The payer now pays online (the mock is the default).
    again = payer.post(
        reverse("payments-demand-payments", kwargs={"demand_id": demand.pk}),
        {"client_request_id": "online-1", "demand_item_ids": [str(i) for i in item_ids(demand)]},
        format="json",
    )
    assert again.status_code == 201
    assert again.json()["provider"] == "mock"


@pytest.mark.parametrize(("validity_days", "grace_hours"), [(1, 0), (7, 24), (90, 168), (3, 100)])
def test_lif_10_never_flagged_stuck_before_it_fails(
    offline, raise_demand, user, settings, validity_days, grace_hours
):
    settings.OFFLINE_PAYMENT_VALIDITY_DAYS = validity_days
    settings.OFFLINE_PAYMENT_RECORDING_GRACE_HOURS = grace_hours
    create(client_for(user), raise_demand())
    payment = Payment.objects.get()
    expires = validity.expires_at(
        reference.parse(payment.provider_payment_id, "OFL").issued_on, resolve_config()
    )
    # Poll at expiry (still pending) and right after it (failed): never stuck.
    for moment in (expires, expires + timedelta(microseconds=1)):
        with frozen_now(moment):
            polling.poll_one(payment, now=moment)
        payment.refresh_from_db()
        assert not payment.needs_reconciliation
    assert payment.status == PaymentStatus.FAILED


def test_late_collection_after_expiry(offline, raise_demand, user, clerk):
    create(client_for(user), raise_demand())
    payment = Payment.objects.get()
    ref = payment.provider_payment_id
    issued_on = reference.parse(ref, "OFL").issued_on
    config = resolve_config()
    collected = validity.valid_until(issued_on, config) - timedelta(hours=2)
    later = validity.expires_at(issued_on, config) + timedelta(days=1)
    desk = client_for(clerk)
    body = {
        "amount": "37.50",
        "method": "CASH",
        "receipt_number": "LATE-1",
        "collected_at": collected.isoformat(),
    }
    with frozen_now(later):
        # Not yet failed by the poller: open, but past the recording deadline.
        assert_error(
            desk.post(collection_url("confirm", ref), body, format="json"),
            payment_errors.COLLECTION_REJECTED,
        )
        polling.poll_one(payment, now=later)
        assert_error(
            desk.post(collection_url("confirm", ref), body, format="json"),
            payment_errors.COLLECTION_NOT_OPEN,
        )
        late = desk.post(collection_url("confirm", ref), {**body, "late": True}, format="json")
    assert late.status_code == 200, late.content
    assert late.json()["attestation"]["outcome"] == AttestationOutcome.FLAGGED
    payment.refresh_from_db()
    assert payment.status == PaymentStatus.FAILED and payment.needs_reconciliation


def test_lif_12_disabled_refuses_new_requests_but_records_open_ones(
    offline, raise_demand, user, clerk, settings
):
    payer = client_for(user)
    create(payer, raise_demand(reference_id="open"))
    open_ref = Payment.objects.get().provider_payment_id
    settings.OFFLINE_PAYMENT_ENABLED = False

    assert_error(create(payer, raise_demand(reference_id="new")), payment_errors.PROVIDER_REJECTED)
    failed = Payment.objects.get(failure_code=constants.OFFLINE_DISABLED)
    assert failed.status == PaymentStatus.FAILED

    # The payer can still see the instructions of the request in flight.
    open_payment = Payment.objects.get(provider_payment_id=open_ref)
    shown = payer.get(reverse("payments-payment-action", kwargs={"payment_id": open_payment.pk}))
    assert shown.status_code == 200, shown.content

    confirmed = client_for(clerk).post(
        collection_url("confirm", open_ref),
        {"amount": "37.50", "method": "CASH", "receipt_number": "R-1"},
        format="json",
    )
    assert confirmed.status_code == 200, confirmed.content


def test_counter_errors_map_to_provider_options(offline, raise_demand, user):
    payer = client_for(user)
    assert_error(
        create(payer, raise_demand(), provider_options={"counter": "NOPE"}),
        payment_errors.PROVIDER_OPTION_INVALID,
        "provider_options.counter",
    )
    assert_error(
        create(payer, raise_demand(reference_id="2"), key="k2", provider_options={}),
        payment_errors.PROVIDER_OPTION_INVALID,
        "provider_options.counter",
    )


def test_offline_failure_codes_never_reach_the_errors_array(offline, raise_demand, user, settings):
    settings.OFFLINE_PAYMENT_MAX_AMOUNT = "1.00"
    response = create(client_for(user), raise_demand())
    codes = [error["code"] for error in response.json()["errors"]]
    assert codes == [payment_errors.PROVIDER_REJECTED.code]
    assert "OFFLINE" not in str(response.json()["errors"])
    assert Payment.objects.get().failure_code == constants.OFFLINE_AMOUNT_TOO_LARGE


def test_replay_returns_the_same_instructions(offline, raise_demand, user):
    payer = client_for(user)
    demand = raise_demand()
    first = create(payer, demand).json()
    again = create(payer, demand)
    assert again.status_code == 200
    assert again.json()["provider_action"] == first["provider_action"]

    shown = payer.get(reverse("payments-payment-action", kwargs={"payment_id": first["id"]}))
    assert shown.json()["provider_action"] == first["provider_action"]


def test_prefix_change_makes_old_replays_conflict(offline, raise_demand, user, settings):
    payer = client_for(user)
    demand = raise_demand()
    create(payer, demand)
    settings.OFFLINE_PAYMENT_REFERENCE_PREFIX = "CRT"
    assert_error(create(payer, demand), payment_errors.PROVIDER_REPLAY_MISMATCH)


def test_staff_cancel_then_payer_pays_again(offline, raise_demand, user, clerk):
    payer = client_for(user)
    demand = raise_demand()
    create(payer, demand)
    ref = Payment.objects.get().provider_payment_id
    cancelled = client_for(clerk).post(
        collection_url("cancel", ref), {"reason": "Payer asked."}, format="json"
    )
    assert cancelled.status_code == 200 and cancelled.json()["status"] == PaymentStatus.CANCELLED
    assert create(payer, demand, key="attempt-2").status_code == 201
    assert not PaymentAttestation.objects.exists()


def test_service_level_cancel_by_payer_is_immediate(offline, raise_demand, user):
    demand = raise_demand()
    payment = PaymentService.create_payment(
        demand=demand,
        demand_item_ids=item_ids(demand),
        client_request_id="k",
        provider="offline",
        provider_options={"counter": "EKM-CJM"},
        actor=user,
    ).payment
    with mock.patch("addon.offline_payment.provider.OfflinePaymentProvider.fetch_status") as fetch:
        PaymentService.request_cancellation(payment, actor=user)
    fetch.assert_not_called()
    payment.refresh_from_db()
    assert payment.status == PaymentStatus.CANCELLED
