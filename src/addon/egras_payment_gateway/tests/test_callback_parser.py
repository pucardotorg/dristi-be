"""Return-URL callback parsing tests (spec 0022 #5)."""

from django.test import SimpleTestCase

from addon.egras_payment_gateway import constants
from addon.egras_payment_gateway.callback_parser import parse
from apps.payments.providers.base import ProviderCallbackMalformed, ProviderOutcome

from .base import make_config

APPLICATION_NUMBER = "DR0F9D3A6C1B2E4F5A7B"


def payload(**overrides):
    base = {
        "Applicationnumber": APPLICATION_NUMBER,
        "GRN": "1231234",
        "status": "Success",
        "CIN": "CIN123",
        "bankcode": "SBI",
        "amount": "775",
        "tdate": "12/10/2026",
        "payment_type": "N",
    }
    base.update(overrides)
    return base


class CallbackParserTests(SimpleTestCase):
    def setUp(self):
        self.config = make_config()

    def test_callback_is_never_trusted(self):
        callback = parse(payload(), self.config)
        self.assertFalse(callback.trusted)
        self.assertEqual(callback.status.provider_payment_id, APPLICATION_NUMBER)

    def test_field_names_are_case_insensitive(self):
        callback = parse(payload(Status="Failure"), self.config)
        self.assertEqual(callback.status.outcome, ProviderOutcome.FAILED)

    def test_hints_are_mapped_best_effort(self):
        self.assertEqual(
            parse(payload(status="Success"), self.config).status.outcome, ProviderOutcome.SUCCESS
        )
        self.assertEqual(
            parse(payload(status="Pending"), self.config).status.outcome, ProviderOutcome.PENDING
        )
        self.assertEqual(
            parse(payload(status="Not Found"), self.config).status.outcome,
            ProviderOutcome.NOT_FOUND,
        )

    def test_grn_hint_is_recorded_but_never_applied(self):
        callback = parse(payload(), self.config)
        self.assertEqual(callback.status.provider_reference, "1231234")

    def test_missing_application_number_is_malformed(self):
        data = payload()
        del data["Applicationnumber"]
        with self.assertRaises(ProviderCallbackMalformed) as caught:
            parse(data, self.config)
        self.assertEqual(caught.exception.code, constants.EGRAS_CALLBACK_MALFORMED)

    def test_wrong_prefix_is_malformed(self):
        with self.assertRaises(ProviderCallbackMalformed):
            parse(payload(Applicationnumber="XY123456"), self.config)

    def test_error_only_payload_is_malformed(self):
        with self.assertRaises(ProviderCallbackMalformed):
            parse({"status": "Transaction could not be processed"}, self.config)
