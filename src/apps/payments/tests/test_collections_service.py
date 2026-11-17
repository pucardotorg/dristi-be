"""Recording an attested collection (spec 0032 #4.3, #4.4, #8.5, #17.2 COL-01 – COL-24).

Runs on the fake attested provider (``counter``): these tests pin the generic
``apps.payments`` behaviour, independent of the offline addon's own rules.
"""

from datetime import timedelta
from decimal import Decimal
from unittest import mock

import pytest
from django.db import transaction
from django.utils import timezone

from apps.api import errors as api_errors
from apps.api.errors import BusinessError
from apps.payments import errors
from apps.payments.enums import (
    AttestationOutcome,
    DemandItemStatus,
    DemandStatus,
    PaymentStatus,
)
from apps.payments.exceptions import ImmutableRecordError
from apps.payments.models import DemandItem, Payment, PaymentAttestation
from apps.payments.providers.base import (
    ProviderOutcome,
    ProviderPermanentError,
    ProviderTransientError,
)
from apps.payments.services import PaymentService
from apps.payments.services.payments import normalise_receipt
from apps.payments.signals import payment_completed

from .fakes import FakeAttestedProvider, status
from .helpers import item, item_ids

pytestmark = pytest.mark.django_db


@pytest.fixture
def request_(raise_demand, user, attested_provider):
    """A pending attested payment for every item of a three-item demand."""

    demand = raise_demand()
    return PaymentService.create_payment(
        demand=demand,
        demand_item_ids=item_ids(demand),
        client_request_id="k",
        provider="counter",
        actor=user,
    ).payment


def record(payment, actor, **overrides):
    values = {
        "provider": payment.provider,
        "provider_payment_id": payment.provider_payment_id,
        "amount": sum((p.amount for p in PaymentService.provider_group(payment)), Decimal("0.00")),
        "method": "CASH",
        "receipt_number": "CJM/EKM/2026/004512",
        "collected_at": timezone.now(),
        "details": {},
        "remarks": "",
        "late": False,
        "actor": actor,
    }
    values.update(overrides)
    return PaymentService.record_collection(**values)


def error_of(callable_, *args, **kwargs) -> BusinessError:
    with pytest.raises(BusinessError) as caught:
        callable_(*args, **kwargs)
    return caught.value


class TestCredit:
    def test_col_01_single_payment(self, request_, clerk):
        result = record(request_, clerk)
        assert result.created
        request_.refresh_from_db()
        assert request_.status == PaymentStatus.SUCCESS
        assert request_.provider_reference == "CJM/EKM/2026/004512"
        assert request_.updated_by == clerk
        assert request_.metadata["provider"]["method"] == "CASH"
        demand = request_.demand
        demand.refresh_from_db()
        assert demand.status == DemandStatus.PAID
        assert {i.status for i in demand.items.all()} == {DemandItemStatus.PAID}

        attestation = result.attestation
        assert attestation.outcome == AttestationOutcome.CREDITED
        assert attestation.created_by == clerk
        assert attestation.amount == Decimal("37.50")
        assert attestation.receipt_number == "CJM/EKM/2026/004512"
        assert attestation.currency == "INR"

    def test_col_02_batch(self, raise_demand, user, attested_provider, clerk, make_case):
        demands = [
            raise_demand([item()], reference_id="a"),
            raise_demand([item(), item()], reference_id="b"),
            raise_demand([item()], case=make_case(), reference_id="c"),
        ]
        payments = PaymentService.create_batch(
            selections=[{"demand": d, "demand_item_ids": item_ids(d)} for d in demands],
            client_request_id="b",
            provider="counter",
            actor=user,
        ).payments
        record(payments[0], clerk, amount="50.00")
        assert {p.status for p in Payment.objects.all()} == {PaymentStatus.SUCCESS}
        assert PaymentAttestation.objects.count() == 1
        for demand in demands:
            demand.refresh_from_db()
            assert demand.status == DemandStatus.PAID

    def test_col_02_part_of_a_batch_cannot_be_recorded(
        self, raise_demand, user, attested_provider, clerk
    ):
        demands = [raise_demand([item()], reference_id=f"d{n}") for n in range(2)]
        payments = PaymentService.create_batch(
            selections=[{"demand": d, "demand_item_ids": item_ids(d)} for d in demands],
            client_request_id="b",
            provider="counter",
            actor=user,
        ).payments
        error = error_of(record, payments[0], clerk, amount="12.50")
        assert (error.error, "amount" in error.detail) == (errors.COLLECTION_DETAILS_INVALID, True)

    def test_col_03_partially_selected_items(self, raise_demand, user, attested_provider, clerk):
        demand = raise_demand()
        payment = PaymentService.create_payment(
            demand=demand,
            demand_item_ids=item_ids(demand, 0),
            client_request_id="k",
            provider="counter",
            actor=user,
        ).payment
        record(payment, clerk)
        demand.refresh_from_db()
        assert demand.status == DemandStatus.PARTIALLY_PAID
        statuses = [i.status for i in demand.items.order_by("position")]
        assert statuses == [DemandItemStatus.PAID, DemandItemStatus.UNPAID, DemandItemStatus.UNPAID]

    def test_col_04_receivers_hear_once_after_commit(
        self, request_, clerk, django_capture_on_commit_callbacks
    ):
        from apps.payments.tasks import notify_payment_completed

        received = []

        def receiver(sender, payment, demand_paid, **kwargs):
            received.append((payment.pk, demand_paid))

        payment_completed.connect(receiver)
        try:
            with mock.patch.object(
                notify_payment_completed, "send", side_effect=notify_payment_completed
            ):
                with django_capture_on_commit_callbacks(execute=False) as callbacks:
                    record(request_, clerk)
                assert received == []  # nothing before commit
                for callback in callbacks:
                    callback()
        finally:
            payment_completed.disconnect(receiver)
        assert received == [(request_.pk, True)]

    def test_col_04_sent_once(self, request_, clerk, django_capture_on_commit_callbacks):
        with mock.patch("apps.payments.tasks.notify_payment_completed.send") as send:
            with django_capture_on_commit_callbacks(execute=True):
                record(request_, clerk)
            assert send.call_count == 1
            with django_capture_on_commit_callbacks(execute=True):
                record(request_, clerk)  # identical replay
            assert send.call_count == 1

    def test_col_04_rollback_publishes_nothing(
        self, request_, clerk, django_capture_on_commit_callbacks
    ):
        with mock.patch("apps.payments.tasks.notify_payment_completed.send") as send:
            with django_capture_on_commit_callbacks(execute=True) as callbacks:
                try:
                    with transaction.atomic():
                        record(request_, clerk)
                        raise RuntimeError("roll back")
                except RuntimeError:
                    pass
            assert callbacks == [] and send.call_count == 0
        request_.refresh_from_db()
        assert request_.status == PaymentStatus.PENDING
        assert not PaymentAttestation.objects.exists()


class TestReplayAndUniqueness:
    def test_col_05_identical_replay(self, request_, clerk, caplog):
        first = record(request_, clerk)
        caplog.set_level("INFO", logger="apps.payments")
        again = record(request_, clerk, receipt_number=" cjm/ekm/2026/004512 ", amount="37.5")
        assert not again.created
        assert again.attestation.pk == first.attestation.pk
        assert PaymentAttestation.objects.count() == 1
        assert "event=PAYMENT_COLLECTION_REPLAYED" in caplog.text
        assert len(FakeAttestedProvider.attest_calls) == 1

    def test_col_05_replay_by_another_clerk(self, request_, clerk, make_user, grant):
        record(request_, clerk)
        other = grant(make_user("Other clerk"), "record_payment_collection")
        assert not record(request_, other).created

    @pytest.mark.parametrize(
        "change", [{"receipt_number": "OTHER-1"}, {"amount": "1.00"}, {"method": "DD"}]
    )
    def test_col_06_replay_with_a_difference(self, request_, clerk, change):
        record(request_, clerk)
        assert error_of(record, request_, clerk, **change).error is errors.COLLECTION_NOT_OPEN

    def test_col_07_receipt_used_by_another_request(
        self, raise_demand, user, attested_provider, clerk
    ):
        first, second = (
            PaymentService.create_payment(
                demand=d,
                demand_item_ids=item_ids(d),
                client_request_id="k",
                provider="counter",
                actor=user,
            ).payment
            for d in (raise_demand(reference_id="a"), raise_demand(reference_id="b"))
        )
        record(first, clerk)
        error = error_of(record, second, clerk)
        assert error.error is errors.RECEIPT_NUMBER_USED
        assert "receipt_number" in error.detail
        second.refresh_from_db()
        assert second.status == PaymentStatus.PENDING

    def test_col_08_receipt_normalisation(self, raise_demand, user, attested_provider, clerk):
        first, second = (
            PaymentService.create_payment(
                demand=d,
                demand_item_ids=item_ids(d),
                client_request_id="k",
                provider="counter",
                actor=user,
            ).payment
            for d in (raise_demand(reference_id="a"), raise_demand(reference_id="b"))
        )
        record(first, clerk, receipt_number="  rcpt-9 ")
        assert PaymentAttestation.objects.get().receipt_number == "RCPT-9"
        assert error_of(record, second, clerk, receipt_number="RCPT-9").error is (
            errors.RECEIPT_NUMBER_USED
        )

    def test_concurrent_receipt_use_maps_the_integrity_error(self, request_, clerk, monkeypatch):
        """A receipt taken between the check and the insert: the constraint decides (#4.4)."""

        original = FakeAttestedProvider.attest

        def racing(self, attestation):
            PaymentAttestation.objects.create(
                provider="counter",
                provider_payment_id="CTR-OTHER",
                receipt_number=normalise_receipt(attestation.receipt_number),
                amount=Decimal("1.00"),
                currency="INR",
                method="CASH",
                collected_at=timezone.now(),
                outcome=AttestationOutcome.CREDITED,
            )
            return original(self, attestation)

        monkeypatch.setattr(FakeAttestedProvider, "attest", racing)
        error = error_of(record, request_, clerk)
        assert error.error is errors.RECEIPT_NUMBER_USED
        assert "receipt_number" in error.detail
        request_.refresh_from_db()
        assert request_.status == PaymentStatus.PENDING

    def test_concurrent_record_of_the_same_request(self, request_, clerk, monkeypatch):
        """Where row locks are not enforced, the request constraint still holds."""

        original = FakeAttestedProvider.attest

        def racing(self, attestation):
            PaymentAttestation.objects.create(
                provider="counter",
                provider_payment_id=attestation.provider_payment_id,
                receipt_number="SOMEONE-ELSE",
                amount=attestation.amount,
                currency="INR",
                method="CASH",
                collected_at=timezone.now(),
                outcome=AttestationOutcome.CREDITED,
            )
            return original(self, attestation)

        monkeypatch.setattr(FakeAttestedProvider, "attest", racing)
        assert error_of(record, request_, clerk).error is errors.COLLECTION_NOT_OPEN


class TestWhoMayRecord:
    def test_col_09_creator_cannot_record(self, request_, user, grant):
        payer = grant(user, "record_payment_collection", "record_late_payment_collection")
        payer.is_superuser = True
        assert error_of(record, request_, payer).error is errors.COLLECTOR_IS_PAYER
        assert not PaymentAttestation.objects.exists()

    def test_col_10_creator_of_another_payment_in_the_batch(
        self, raise_demand, user, attested_provider, clerk
    ):
        demands = [raise_demand([item()], reference_id=f"d{n}") for n in range(2)]
        payments = PaymentService.create_batch(
            selections=[{"demand": d, "demand_item_ids": item_ids(d)} for d in demands],
            client_request_id="b",
            provider="counter",
            actor=user,
        ).payments
        Payment.objects.filter(pk=payments[1].pk).update(created_by=clerk)
        assert error_of(record, payments[0], clerk, amount="25.00").error is (
            errors.COLLECTOR_IS_PAYER
        )


class TestNotRecordable:
    def test_col_11_provider_not_attested(self, raise_demand, user, attested_provider, clerk):
        demand = raise_demand()
        payment = PaymentService.create_payment(
            demand=demand, demand_item_ids=item_ids(demand), client_request_id="k", actor=user
        ).payment
        assert payment.provider == "fake"
        assert error_of(record, payment, clerk).error is api_errors.NOT_FOUND
        assert error_of(record, payment, clerk, provider="mock").error is api_errors.NOT_FOUND
        assert error_of(record, payment, clerk, provider="ghost").error is api_errors.NOT_FOUND

    def test_col_12_unknown_reference(self, request_, clerk):
        for reference in ("CTR-NOPE", ""):
            error = error_of(record, request_, clerk, provider_payment_id=reference)
            assert error.error is api_errors.NOT_FOUND

    def test_col_13_already_successful(self, request_, clerk):
        PaymentService.confirm_payment(request_)
        assert error_of(record, request_, clerk).error is errors.COLLECTION_NOT_OPEN
        assert error_of(record, request_, clerk, late=True).error is errors.COLLECTION_NOT_OPEN

    @pytest.mark.parametrize("close", ["fail", "cancel"])
    def test_col_14_closed_and_not_late(self, request_, clerk, close):
        if close == "fail":
            PaymentService.fail_payment(request_, failure_code="X")
        else:
            PaymentService.cancel_payment(request_)
        assert error_of(record, request_, clerk).error is errors.COLLECTION_NOT_OPEN
        assert not FakeAttestedProvider.attest_calls

    @pytest.mark.parametrize("close", ["fail", "cancel"])
    def test_col_15_late_flags_and_never_credits(self, request_, clerk, close, caplog):
        if close == "fail":
            PaymentService.fail_payment(request_, failure_code="EXPIRED")
        else:
            PaymentService.cancel_payment(request_)
        caplog.set_level("ERROR", logger="apps.payments")
        result = record(request_, clerk, late=True)
        assert result.attestation.outcome == AttestationOutcome.FLAGGED
        assert FakeAttestedProvider.attest_calls[0].late is True
        request_.refresh_from_db()
        assert request_.status in (PaymentStatus.FAILED, PaymentStatus.CANCELLED)
        assert request_.needs_reconciliation
        assert request_.metadata["reconciliation"]["reason"] == "PAYMENT_LATE_SUCCESS"
        assert "PAYMENT_LATE_SUCCESS" in caplog.text
        assert set(
            DemandItem.objects.filter(demand=request_.demand).values_list("status", flat=True)
        ) == {DemandItemStatus.UNPAID}

    def test_open_request_is_never_late(self, request_, clerk):
        record(request_, clerk, late=True)
        assert FakeAttestedProvider.attest_calls[0].late is False
        assert PaymentAttestation.objects.get().outcome == AttestationOutcome.CREDITED


class TestProviderAnswers:
    def test_col_18_field_error(self, request_, clerk):
        FakeAttestedProvider.attest_error = ProviderPermanentError(
            "X_BAD", "bad dd", field="details.number"
        )
        error = error_of(record, request_, clerk)
        assert error.error is errors.COLLECTION_DETAILS_INVALID
        assert "details.number" in error.detail
        assert not PaymentAttestation.objects.exists()
        request_.refresh_from_db()
        assert request_.status == PaymentStatus.PENDING

    def test_col_18_non_field_error(self, request_, clerk):
        FakeAttestedProvider.attest_error = ProviderPermanentError("X_EXPIRED", "expired")
        assert error_of(record, request_, clerk).error is errors.COLLECTION_REJECTED
        assert not PaymentAttestation.objects.exists()

    def test_transient_error_is_unavailable(self, request_, clerk):
        FakeAttestedProvider.attest_error = ProviderTransientError("DOWN")
        assert error_of(record, request_, clerk).error is errors.PROVIDER_UNAVAILABLE

    @pytest.mark.parametrize("outcome", ["PENDING", "FAILED", "NOT_FOUND"])
    def test_col_19_non_success_is_a_provider_bug(self, request_, clerk, outcome, caplog):
        FakeAttestedProvider.attest_status = status(request_.provider_payment_id, outcome)
        caplog.set_level("ERROR", logger="apps.payments")
        assert error_of(record, request_, clerk).error is errors.COLLECTION_REJECTED
        assert "PAYMENT_ATTESTATION_UNEXPECTED" in caplog.text
        assert not PaymentAttestation.objects.exists()
        request_.refresh_from_db()
        assert request_.status == PaymentStatus.PENDING

    def test_col_19_status_for_another_reference(self, request_, clerk):
        FakeAttestedProvider.attest_status = status("CTR-OTHER", "SUCCESS", amount="37.50")
        assert error_of(record, request_, clerk).error is errors.COLLECTION_REJECTED

    def test_col_20_amount_mismatch_is_flagged(self, request_, clerk):
        FakeAttestedProvider.attest_status = status(
            request_.provider_payment_id, "SUCCESS", amount="37.49"
        )
        result = record(request_, clerk)
        assert result.attestation.outcome == AttestationOutcome.FLAGGED
        request_.refresh_from_db()
        assert request_.status == PaymentStatus.PENDING
        assert request_.needs_reconciliation
        assert request_.metadata["reconciliation"]["reason"] == "PAYMENT_AMOUNT_MISMATCH"

    @pytest.mark.parametrize("amount", ["abc", "0", "-1", "NaN"])
    def test_malformed_amount_is_a_field_error(self, request_, clerk, amount):
        error = error_of(record, request_, clerk, amount=amount)
        assert error.error is errors.COLLECTION_DETAILS_INVALID
        assert "amount" in error.detail

    def test_attestation_carries_what_apps_payments_knows(self, request_, clerk):
        record(request_, clerk, details={"number": 123456}, remarks="r")
        [sent] = FakeAttestedProvider.attest_calls
        assert sent.expected_amount == Decimal("37.50")
        assert sent.initiated_at == request_.initiated_at
        assert sent.currency == "INR"
        assert sent.details == {"number": "123456"}
        assert sent.receipt_number == "CJM/EKM/2026/004512"

    def test_method_is_stored_as_the_provider_code(self, request_, clerk):
        result = record(request_, clerk, method=" cash ")
        assert result.attestation.method == "CASH"
        assert FakeAttestedProvider.attest_calls[0].method == "CASH"
        assert not record(request_, clerk, method="Cash").created  # identical replay

    def test_an_unknown_method_is_passed_to_the_provider_as_typed(self, request_, clerk):
        record(request_, clerk, method=" cheque ")
        assert FakeAttestedProvider.attest_calls[0].method == "cheque"

    def test_collected_at_defaults_to_now(self, request_, clerk):
        record(request_, clerk, collected_at=None)
        assert FakeAttestedProvider.attest_calls[0].collected_at is not None


class TestLifecycleInterplay:
    def test_col_21_items_of_an_open_request_cannot_be_cancelled(self, request_, clerk):
        from apps.payments.services import DemandService

        item_ = request_.demand.items.first()
        with pytest.raises(BusinessError) as caught:
            DemandService.cancel_item(item_)
        assert caught.value.error is errors.ITEM_NOT_CANCELLABLE
        assert record(request_, clerk).created

    def test_col_22_success_from_polling_is_ignored(self, request_, caplog):
        from apps.payments.services.polling import poll_one

        FakeAttestedProvider.fetch_outcome = ProviderOutcome.SUCCESS
        caplog.set_level("ERROR", logger="apps.payments")
        poll_one(request_, now=timezone.now() + timedelta(hours=1))
        request_.refresh_from_db()
        assert request_.status == PaymentStatus.PENDING
        assert not request_.needs_reconciliation
        assert "PAYMENT_ATTESTED_PROVIDER_SUCCESS" in caplog.text

    def test_col_22_success_through_refresh_is_ignored(self, request_):
        FakeAttestedProvider.fetch_outcome = ProviderOutcome.SUCCESS
        PaymentService.refresh_from_provider(request_)
        request_.refresh_from_db()
        assert request_.status == PaymentStatus.PENDING

    def test_failed_from_polling_is_applied(self, request_):
        FakeAttestedProvider.fetch_outcome = ProviderOutcome.FAILED
        PaymentService.refresh_from_provider(request_)
        request_.refresh_from_db()
        assert request_.status == PaymentStatus.FAILED

    def test_col_23_attestations_are_immutable(self, request_, clerk):
        attestation = record(request_, clerk).attestation
        attestation.remarks = "edited"
        with pytest.raises(ImmutableRecordError):
            attestation.save()
        with pytest.raises(ImmutableRecordError):
            attestation.delete()
        with pytest.raises(ImmutableRecordError):
            PaymentAttestation.objects.all().delete()
        with pytest.raises(ImmutableRecordError):
            PaymentAttestation.objects.update(remarks="edited")
        assert PaymentAttestation.objects.get().remarks == ""

    def test_col_24_history_names_the_recorder(self, request_, clerk):
        record(request_, clerk)
        latest = request_.history.order_by("-history_date").first()
        assert latest.status == PaymentStatus.SUCCESS
        assert latest.history_user == clerk
        attestation = PaymentAttestation.objects.get()
        assert attestation.history.get().history_user == clerk

    def test_recorded_event_is_logged(self, request_, clerk, caplog):
        caplog.set_level("INFO", logger="apps.payments")
        record(request_, clerk)
        assert "event=PAYMENT_COLLECTION_RECORDED" in caplog.text
        assert "outcome=CREDITED" in caplog.text
        assert request_.payer.get("phone", "x") not in caplog.text


class TestStaffCancel:
    def test_cancel_by_staff(self, request_, clerk, caplog):
        caplog.set_level("INFO", logger="apps.payments")
        PaymentService.cancel_collection(
            provider="counter",
            provider_payment_id=request_.provider_payment_id,
            reason="Payer will pay online.",
            actor=clerk,
        )
        request_.refresh_from_db()
        assert request_.status == PaymentStatus.CANCELLED
        assert request_.failure_message == "Payer will pay online."
        assert request_.updated_by == clerk
        assert "event=PAYMENT_COLLECTION_CANCELLED" in caplog.text

    def test_cancel_terminal(self, request_, clerk):
        PaymentService.confirm_payment(request_)
        error = error_of(
            PaymentService.cancel_collection,
            provider="counter",
            provider_payment_id=request_.provider_payment_id,
            reason="x",
            actor=clerk,
        )
        assert error.error is errors.PAYMENT_NOT_CANCELLABLE

    def test_cancel_unknown(self, request_, clerk):
        error = error_of(
            PaymentService.cancel_collection,
            provider="fake",
            provider_payment_id=request_.provider_payment_id,
            reason="x",
            actor=clerk,
        )
        assert error.error is api_errors.NOT_FOUND


class TestCorruptGroup:
    def test_two_groups_sharing_a_reference_are_never_credited(
        self, raise_demand, user, attested_provider, clerk
    ):
        demand_a, demand_b = raise_demand(reference_id="a"), raise_demand(reference_id="b")
        first, second = (
            PaymentService.create_payment(
                demand=demand,
                demand_item_ids=item_ids(demand),
                client_request_id="k",
                provider="counter",
                actor=user,
            ).payment
            for demand in (demand_a, demand_b)
        )
        # Simulate data written before the collision guard existed.
        Payment.objects.filter(pk=second.pk).update(provider_payment_id=first.provider_payment_id)
        assert error_of(record, first, clerk, amount="75.00").error is api_errors.CONFLICT
        assert not PaymentAttestation.objects.exists()


def test_normalise_receipt():
    assert normalise_receipt("  ab/1 ") == "AB/1"
    assert normalise_receipt(None) == ""
