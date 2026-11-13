"""Return-URL callback parsing tests (spec 0022 #5)."""

import base64
import os

from django.test import SimpleTestCase

from addon.egras_payment_gateway import constants
from addon.egras_payment_gateway.callback_parser import parse
from addon.egras_payment_gateway.config import reset_config_cache
from apps.payments.providers.base import ProviderCallbackMalformed, ProviderOutcome

from .base import (
    RESPONSE_FIELDS,
    encrypt_pay_res,
    make_config,
    make_response_key,
    write_key_file,
)

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


class EncryptedCallbackTests(SimpleTestCase):
    """e-GRAS v3.7 posts a single encrypted ``payRes`` field (spec 0022 #5.4)."""

    def setUp(self):
        self.key = make_response_key()
        self.path = write_key_file(self.key)
        self.addCleanup(os.unlink, self.path)
        self.addCleanup(reset_config_cache)
        self.config = make_config(response_key_path=self.path)

    def test_encrypted_payres_is_decrypted_to_the_hint(self):
        pay_res = encrypt_pay_res(RESPONSE_FIELDS, self.key)
        callback = parse({"payRes": pay_res}, self.config)
        self.assertFalse(callback.trusted)
        self.assertEqual(callback.status.provider_payment_id, APPLICATION_NUMBER)
        self.assertEqual(callback.status.outcome, ProviderOutcome.SUCCESS)
        self.assertEqual(callback.status.provider_reference, "1234567890")

    def test_wrong_key_makes_the_callback_malformed(self):
        pay_res = encrypt_pay_res(RESPONSE_FIELDS, make_response_key())  # a different key
        with self.assertRaises(ProviderCallbackMalformed) as caught:
            parse({"payRes": pay_res}, self.config)
        self.assertEqual(caught.exception.code, constants.EGRAS_RESPONSE_DECRYPT_FAILED)

    def test_tampered_payres_is_malformed(self):
        raw = bytearray(base64.b64decode(encrypt_pay_res(RESPONSE_FIELDS, self.key)))
        raw[-1] ^= 0x01
        with self.assertRaises(ProviderCallbackMalformed) as caught:
            parse({"payRes": base64.b64encode(bytes(raw)).decode()}, self.config)
        self.assertEqual(caught.exception.code, constants.EGRAS_RESPONSE_DECRYPT_FAILED)

    def test_missing_key_config_makes_the_callback_malformed(self):
        pay_res = encrypt_pay_res(RESPONSE_FIELDS, self.key)
        with self.assertRaises(ProviderCallbackMalformed):
            parse({"payRes": pay_res}, make_config(response_key_path=""))

    def test_checksum_mismatch_is_logged_but_still_parsed(self):
        # The GCM tag already authenticated the payload; a bad checksum is not fatal.
        pay_res = encrypt_pay_res({**RESPONSE_FIELDS, "checksum": "deadbeef"}, self.key)
        callback = parse({"payRes": pay_res}, self.config)
        self.assertEqual(callback.status.provider_payment_id, APPLICATION_NUMBER)

    def test_plain_payload_still_works_when_no_payres(self):
        callback = parse(payload(), self.config)
        self.assertEqual(callback.status.provider_payment_id, APPLICATION_NUMBER)
