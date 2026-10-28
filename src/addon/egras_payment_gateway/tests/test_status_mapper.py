"""Verification status-mapping tests (spec 0022 #6.3)."""

from decimal import Decimal

from django.test import SimpleTestCase

from addon.egras_payment_gateway import constants
from addon.egras_payment_gateway.status_mapper import map_grn_details
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
