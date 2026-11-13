"""Raising and cancelling demands (spec 0017 #6.1, #11, #18 "Demand")."""

import uuid
from decimal import Decimal

import pytest

from apps.api import errors as api_errors
from apps.api.errors import BusinessError
from apps.payments import errors
from apps.payments.enums import ChargeType, DemandItemStatus, DemandStatus, ReferenceType
from apps.payments.exceptions import ImmutableRecordError
from apps.payments.models import Demand, DemandItem
from apps.payments.services import DemandService, PaymentService

from .helpers import item, item_ids

pytestmark = pytest.mark.django_db


def raises(error, field=None):
    """Context manager asserting a ``BusinessError`` with ``error`` on ``field``."""

    class _Check:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            assert exc_type is BusinessError, f"expected {error.code}, got {exc!r}"
            assert exc.error is error, (exc.error.code, error.code)
            detail = exc.detail
            if field is None:
                assert not isinstance(detail, dict), detail
            else:
                assert isinstance(detail, dict) and field in detail, detail
            return True

    return _Check()


class TestRaise:
    def test_single_item(self, raise_demand):
        demand = raise_demand([item(unit_amount="20.00")])
        assert demand.status == DemandStatus.RAISED
        assert demand.total_amount == Decimal("20.00")
        assert demand.paid_amount == Decimal("0.00")
        assert demand.due_amount == Decimal("20.00")
        [only] = demand.items.all()
        assert only.status == DemandItemStatus.UNPAID
        assert only.due_amount == only.amount == Decimal("20.00")

    def test_multiple_items_compute_amount_and_total(self, raise_demand):
        demand = raise_demand(
            [
                item(unit_amount="12.50", quantity=2),
                item(ChargeType.COMPLAINT_FEE, unit_amount="500.00"),
                item(ChargeType.EPOST_FEE, unit_amount="33.33", quantity="1.50"),
            ]
        )
        amounts = [i.amount for i in demand.items.order_by("position")]
        # 33.33 * 1.5 = 49.995, rounded half up once, when the item is computed.
        assert amounts == [Decimal("25.00"), Decimal("500.00"), Decimal("50.00")]
        assert demand.total_amount == Decimal("575.00")

    def test_spec_filing_example_totals_707_50(self, raise_demand):
        """The worked example of spec 0017 #12.1."""
        rows = [
            ("COURT_FEE", "12.50", 1),
            ("LEGAL_BENEFIT_FEE", "12.50", 1),
            ("ADVOCATE_WELFARE_FUND", "100.00", 1),
            ("STIPEND_STAMP", "25.00", 1),
            ("ADVOCATE_CLERK_WELFARE_FUND", "20.00", 1),
            ("COMPLAINT_FEE", "500.00", 1),
            ("PROCESS_COURT_FEE", "12.50", 2),
            ("PROCESS_COURT_FEE", "12.50", 1),
        ]
        demand = raise_demand(
            [item(c, unit_amount=a, quantity=q) for c, a, q in rows],
            reference_type=ReferenceType.CASE_FILING,
            reference_id="filing-456",
        )
        assert demand.total_amount == Decimal("707.50")

    def test_item_reference_defaults_to_the_demand(self, raise_demand):
        demand = raise_demand(
            [item()], reference_type=ReferenceType.APPLICATION, reference_id="app-1"
        )
        [only] = demand.items.all()
        assert (only.reference_type, only.reference_id) == ("APPLICATION", "app-1")

    def test_snapshot_fields_are_stored(self, raise_demand):
        demand = raise_demand(
            [item(ChargeType.STIPEND_STAMP, account_head="8031-00-102-94-07-00-00-N-V")]
        )
        assert demand.items.get().account_head == "8031-00-102-94-07-00-00-N-V"

    def test_numbers_are_sequential_per_year(self, raise_demand):
        first = raise_demand([item()])
        second = raise_demand([item()])
        prefix, year, seq = first.demand_number.split("-")
        assert prefix == "DMD" and len(year) == 4 and len(seq) == 6
        assert int(second.demand_number.split("-")[2]) == int(seq) + 1

    def test_empty_item_list_is_rejected(self, case_id):
        with raises(api_errors.EMPTY, field="items"):
            DemandService.raise_demand(
                case=case_id, reference_type="ORDER", reference_id="o", items=[]
            )

    @pytest.mark.parametrize("quantity", ["0", "-1"])
    def test_non_positive_quantity_is_rejected(self, raise_demand, quantity):
        with raises(api_errors.MIN_VALUE, field="items[0].quantity"):
            raise_demand([item(quantity=quantity)])

    @pytest.mark.parametrize("unit_amount", ["0", "-5.00"])
    def test_non_positive_unit_amount_is_rejected(self, raise_demand, unit_amount):
        with raises(api_errors.MIN_VALUE, field="items[0].unit_amount"):
            raise_demand([item(unit_amount=unit_amount)])

    def test_amount_rounding_to_zero_is_rejected(self, raise_demand):
        with raises(api_errors.MIN_VALUE, field="items[0]"):
            raise_demand([item(unit_amount="0.01", quantity="0.01")])

    def test_unknown_charge_type_is_rejected(self, raise_demand):
        with raises(api_errors.INVALID_CHOICE, field="items[0].charge_type"):
            raise_demand([item("PARKING_FEE")])

    def test_quantity_breakdown_must_multiply_to_quantity(self, raise_demand):
        good = {"quantity_breakdown": {"addresses": 2, "rounds": 3}}
        demand = raise_demand([item(quantity=6, metadata=good)])
        assert demand.items.get().quantity == Decimal("6")

        bad = {"quantity_breakdown": {"addresses": 2, "rounds": 2}}
        with raises(errors.QUANTITY_BREAKDOWN_MISMATCH, field="items[1].metadata"):
            raise_demand([item(), item(quantity=6, metadata=bad)])

    @pytest.mark.parametrize("breakdown", [{}, {"addresses": "two"}, {"rounds": 0}, [2, 3]])
    def test_unusable_breakdown_is_a_mismatch(self, raise_demand, breakdown):
        with raises(errors.QUANTITY_BREAKDOWN_MISMATCH, field="items[0].metadata"):
            raise_demand([item(metadata={"quantity_breakdown": breakdown})])

    def test_an_invalid_item_creates_nothing(self, raise_demand):
        with raises(api_errors.MIN_VALUE, field="items[1].unit_amount"):
            raise_demand([item(), item(unit_amount="0")])
        assert not Demand.objects.exists()
        assert not DemandItem.objects.exists()

    @pytest.mark.parametrize(
        "field,value",
        [
            ("unit_amount", "12.505"),  # more places than the column keeps
            ("unit_amount", "1" * 17),  # more whole digits than numeric(18, 2)
            ("quantity", "1.005"),
            ("quantity", "1" * 9),  # numeric(10, 2) keeps 8 whole digits
        ],
    )
    def test_numbers_must_fit_their_columns(self, raise_demand, field, value):
        """In-process callers get the serializer's validation, not rounding or a 500."""
        with raises(api_errors.TOO_MANY_DIGITS, field=f"items[0].{field}"):
            raise_demand([item(**{field: value})])
        assert not Demand.objects.exists()

    @pytest.mark.parametrize(
        "value,expected",
        [
            # A nonzero digit beyond the 28-digit decimal context: normalize()
            # would round it away and accept the value.
            ("12.500000000000000000000000000001", False),
            ("12.5000000000000000000000000000000", True),  # only trailing zeros
            ("12.50", True),
            ("12.505", False),
            ("0", True),
            ("0.000", True),
            ("0E+5", True),
            ("1E+2", True),
            ("9999999999999999.99", True),  # 16 whole digits, the most numeric(18, 2) holds
            ("1E+16", False),  # 17 whole digits
            ("-1.005", False),
        ],
    )
    def test_fits_reads_the_digits_without_rounding(self, value, expected):
        from apps.payments.services.demands import MONEY_DIGITS, fits

        assert fits(Decimal(value), MONEY_DIGITS) is expected

    def test_digit_beyond_context_precision_is_rejected(self, raise_demand):
        with raises(api_errors.TOO_MANY_DIGITS, field="items[0].unit_amount"):
            raise_demand([item(unit_amount="12.500000000000000000000000000001")])
        assert not Demand.objects.exists()

    def test_amounts_that_overflow_are_rejected(self, raise_demand):
        huge = "99999999999999.99"  # fits on its own; times the quantity it does not
        with raises(api_errors.MAX_VALUE, field="items[0]"):
            raise_demand([item(unit_amount=huge, quantity="99999999")])
        nearly = "9999999999999999.99"  # the largest single amount
        with raises(api_errors.MAX_VALUE, field="items"):
            raise_demand([item(unit_amount=nearly), item(unit_amount=nearly)])
        assert not Demand.objects.exists()

    def test_trailing_zeros_are_fine(self, raise_demand):
        demand = raise_demand([item(unit_amount="12.5000", quantity="2.00")])
        assert demand.total_amount == Decimal("25.00")

    def test_reference_ids_are_bounded(self, raise_demand):
        """In-process callers get a validation error, not a database error."""
        with raises(api_errors.MAX_LENGTH, field="reference_id"):
            raise_demand([item()], reference_id="x" * 65)
        with raises(api_errors.MAX_LENGTH, field="items[0].reference_id"):
            raise_demand([item(reference_id="y" * 65)])
        with raises(api_errors.REQUIRED, field="reference_id"):
            raise_demand([item()], reference_id="")

    def test_case_is_required(self):
        with raises(api_errors.REQUIRED, field="case_id"):
            DemandService.raise_demand(
                case=None, reference_type="ORDER", reference_id="o", items=[item()]
            )

    def test_case_may_be_an_instance(self, user, make_case):
        case = make_case()
        demand = DemandService.raise_demand(
            case=case, reference_type="ORDER", reference_id="o", items=[item()], actor=user
        )
        assert demand.case == case

    @pytest.mark.parametrize("case", [uuid.UUID(int=1), "not-a-uuid"])
    def test_case_must_exist(self, case):
        """An unknown case is a validation error, not a database error."""
        with raises(api_errors.DOES_NOT_EXIST, field="case_id"):
            DemandService.raise_demand(
                case=case, reference_type="ORDER", reference_id="o", items=[item()]
            )
        assert not Demand.objects.exists()


class TestCancel:
    def test_cancel_item_recomputes_the_demand(self, raise_demand):
        demand = raise_demand()
        first = demand.items.order_by("position").first()
        DemandService.cancel_item(first, reason="process expired")

        first.refresh_from_db()
        demand.refresh_from_db()
        assert first.status == DemandItemStatus.CANCELLED
        assert first.due_amount == Decimal("0.00")
        assert first.cancellation_reason == "process expired"
        assert demand.total_amount == Decimal("25.00")
        assert demand.due_amount == Decimal("25.00")
        assert demand.status == DemandStatus.RAISED

    def test_cancelling_every_item_cancels_the_demand(self, raise_demand):
        demand = raise_demand([item()])
        DemandService.cancel_item(demand.items.get())
        demand.refresh_from_db()
        assert demand.status == DemandStatus.CANCELLED
        assert demand.total_amount == Decimal("0.00")

    def test_cancel_demand(self, raise_demand):
        demand = raise_demand()
        DemandService.cancel_demand(demand, reason="draft deleted")
        demand.refresh_from_db()
        assert demand.status == DemandStatus.CANCELLED
        assert demand.cancellation_reason == "draft deleted"
        assert set(demand.items.values_list("status", flat=True)) == {DemandItemStatus.CANCELLED}
        # Idempotent.
        assert DemandService.cancel_demand(demand).status == DemandStatus.CANCELLED

    def test_paid_item_cannot_be_cancelled(self, raise_demand, no_provider, user):
        demand = raise_demand()
        [paid] = item_ids(demand, 0)
        collection = PaymentService.create_payment(
            demand=demand, demand_item_ids=[paid], client_request_id="k", actor=user
        )
        PaymentService.confirm_payment(collection.payment)

        with raises(errors.ITEM_NOT_CANCELLABLE):
            DemandService.cancel_item(DemandItem.objects.get(pk=paid))
        with raises(errors.DEMAND_NOT_CANCELLABLE):
            DemandService.cancel_demand(demand)

    def test_item_with_payment_in_flight_cannot_be_cancelled(self, raise_demand, no_provider, user):
        demand = raise_demand()
        [target] = item_ids(demand, 1)
        PaymentService.create_payment(
            demand=demand, demand_item_ids=[target], client_request_id="k", actor=user
        )
        with raises(errors.ITEM_NOT_CANCELLABLE):
            DemandService.cancel_item(DemandItem.objects.get(pk=target))
        with raises(errors.DEMAND_NOT_CANCELLABLE):
            DemandService.cancel_demand(demand)


class TestImmutability:
    def test_paid_item_amount_is_frozen(self, raise_demand, no_provider, user):
        demand = raise_demand([item()])
        collection = PaymentService.create_payment(
            demand=demand, demand_item_ids=item_ids(demand), client_request_id="k", actor=user
        )
        PaymentService.confirm_payment(collection.payment)

        paid = DemandItem.objects.get()
        paid.amount = Decimal("1.00")
        with pytest.raises(ImmutableRecordError):
            paid.save()

    def test_items_are_never_deleted(self, raise_demand):
        demand = raise_demand([item()])
        with pytest.raises(ImmutableRecordError):
            demand.items.get().delete()
        # Bulk deletes skip Model.delete(); the queryset refuses them too.
        with pytest.raises(ImmutableRecordError):
            DemandItem.objects.filter(demand=demand).delete()
        assert demand.items.count() == 1

    def test_history_records_state_changes(self, raise_demand):
        demand = raise_demand([item(), item()])
        DemandService.cancel_item(demand.items.order_by("position").first())
        assert demand.history.count() >= 2
        assert DemandItem.history.filter(status=DemandItemStatus.CANCELLED).exists()
