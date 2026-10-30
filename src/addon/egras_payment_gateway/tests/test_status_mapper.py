"""Verification status-mapping tests (spec 0022 #6.3)."""

from decimal import Decimal

from django.test import SimpleTestCase

from addon.egras_payment_gateway import constants
from addon.egras_payment_gateway.status_mapper import map_grn_details, map_grn_records
from apps.payments.providers.base import ProviderOutcome, ProviderTransientError

PROVIDER_PAYMENT_ID = "DR0F9D3A6C1B2E4F5A7B"


def details(**overrides):
    base = {
        constants.STATUS_ELEMENT: "Successfull",
        constants.GRN_ELEMENT: "1231234",
        constants.CIN_ELEMENT: "CIN123",
        constants.AMOUNT_ELEMENT: "775",
        constants.BANKDATE_ELEMENT: "12/10/2026",
        constants.PURPOSE_ELEMENT: "Dristi DMD-1",
    }
    base.update(overrides)
    return base


def mapped(**overrides):
    return map_grn_details(details(**overrides), provider_payment_id=PROVIDER_PAYMENT_ID)


class StatusMapperTests(SimpleTestCase):
    def test_success_with_grn_cin_and_integer_amount(self):
        status = mapped()
        self.assertEqual(status.outcome, ProviderOutcome.SUCCESS)
        self.assertEqual(status.provider_reference, "1231234")
        self.assertEqual(status.amount, Decimal("775"))
        self.assertEqual(status.metadata["cin"], "CIN123")
        self.assertIsNotNone(status.paid_at)

    def test_success_without_grn_is_incomplete_pending(self):
        status = mapped(GRN="")
        self.assertEqual(status.outcome, ProviderOutcome.PENDING)
        self.assertEqual(status.failure_code, constants.EGRAS_SUCCESS_INCOMPLETE)

    def test_failure_is_failed(self):
        status = mapped(Status="Failure")
        self.assertEqual(status.outcome, ProviderOutcome.FAILED)
        self.assertEqual(status.failure_code, constants.EGRAS_PAYMENT_FAILED)
        self.assertEqual(status.failure_message, constants.FAILURE_MESSAGE)

    def test_pending_is_pending(self):
        status = mapped(Status="Pending")
        self.assertEqual(status.outcome, ProviderOutcome.PENDING)

    def test_not_found_is_not_found(self):
        status = mapped(Status="Not Found")
        self.assertEqual(status.outcome, ProviderOutcome.NOT_FOUND)

    def test_empty_try_later_response_is_transient(self):
        empty = dict.fromkeys(details(), "")
        empty[constants.STATUS_ELEMENT] = "Pending"
        with self.assertRaises(ProviderTransientError) as caught:
            map_grn_details(empty, provider_payment_id=PROVIDER_PAYMENT_ID)
        self.assertEqual(caught.exception.code, constants.EGRAS_VERIFY_EMPTY)

    def test_unknown_vocabulary_is_pending_not_failed(self):
        status = mapped(Status="Reconciling")
        self.assertEqual(status.outcome, ProviderOutcome.PENDING)
        self.assertEqual(status.failure_code, constants.EGRAS_UNKNOWN_STATUS)


def records_mapped(records):
    return map_grn_records(records, provider_payment_id=PROVIDER_PAYMENT_ID)


class MultiRecordTests(SimpleTestCase):
    """ArrayOfGrnDetails: each record stands alone; a success always wins (#6.3)."""

    def test_no_records_is_transient(self):
        with self.assertRaises(ProviderTransientError) as caught:
            records_mapped([])
        self.assertEqual(caught.exception.code, constants.EGRAS_VERIFY_EMPTY)

    def test_single_record_behaves_like_before(self):
        status = records_mapped([details()])
        self.assertEqual(status.outcome, ProviderOutcome.SUCCESS)
        self.assertEqual(status.provider_reference, "1231234")

    def test_failure_then_success_resolves_to_success(self):
        """A failed first record must not hide money collected under a later GRN."""
        failed = details(Status="Failure", GRN="111", CIN="", Amount="", Bankdate="")
        success = details(Status="Successfull", GRN="222", CIN="CIN9", Amount="100")
        status = records_mapped([failed, success])
        self.assertEqual(status.outcome, ProviderOutcome.SUCCESS)
        self.assertEqual(status.provider_reference, "222")  # never mixed with 111
        self.assertEqual(status.metadata["cin"], "CIN9")

    def test_failure_and_pending_resolves_to_pending(self):
        failed = details(Status="Failure", GRN="111", CIN="", Amount="", Bankdate="")
        pending = details(Status="Pending", GRN="222", CIN="", Amount="", Bankdate="")
        self.assertEqual(records_mapped([failed, pending]).outcome, ProviderOutcome.PENDING)

    def test_all_failed_resolves_to_failed(self):
        a = details(Status="Failure", GRN="111", CIN="", Amount="", Bankdate="")
        b = details(Status="Failure", GRN="222", CIN="", Amount="", Bankdate="")
        self.assertEqual(records_mapped([a, b]).outcome, ProviderOutcome.FAILED)

    def test_empty_record_is_skipped_so_the_real_one_wins(self):
        empty = dict.fromkeys(details(), "")
        empty[constants.STATUS_ELEMENT] = "Pending"
        status = records_mapped([empty, details()])
        self.assertEqual(status.outcome, ProviderOutcome.SUCCESS)

    def test_two_successes_are_flagged_for_reconciliation(self):
        s1 = details(Status="Successfull", GRN="111", CIN="CIN1", Amount="100")
        s2 = details(Status="Successfull", GRN="222", CIN="CIN2", Amount="100")
        status = records_mapped([s1, s2])
        self.assertEqual(status.outcome, ProviderOutcome.SUCCESS)
        self.assertTrue(status.metadata["needs_reconciliation"])
        self.assertEqual(status.metadata["success_grns"], ["111", "222"])
