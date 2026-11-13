"""Payer-field sanitisation tests (spec 0022 #4.8)."""

from django.test import SimpleTestCase

from addon.egras_payment_gateway import constants, sanitise
from apps.payments.providers.base import ProviderPermanentError

from .base import make_config, make_payer


class FieldCleaningTests(SimpleTestCase):
    def test_disallowed_characters_are_removed_and_spaces_collapsed(self):
        self.assertEqual(sanitise.clean("Ravi   @Kumar!", sanitise.NAME_ALLOWED, 50), "Ravi Kumar")

    def test_length_is_truncated(self):
        self.assertEqual(sanitise.clean("a" * 80, sanitise.NAME_ALLOWED, 50), "a" * 50)

    def test_non_ascii_letters_are_removed(self):
        # Malayalam name drops out of a restricted ASCII field.
        self.assertEqual(sanitise.clean("രവി Ravi", sanitise.NAME_ALLOWED, 50), "Ravi")

    def test_pincode_keeps_six_digits_or_blanks(self):
        self.assertEqual(sanitise.clean_pincode("682 001"), "682001")
        self.assertEqual(sanitise.clean_pincode("6820"), "")

    def test_phone_normalisation(self):
        self.assertEqual(sanitise.clean_phone("+91 98765 43210"), "9876543210")
        self.assertEqual(sanitise.clean_phone("09876543210"), "9876543210")
        self.assertEqual(sanitise.clean_phone("12345"), "")

    def test_invalid_email_is_blanked(self):
        self.assertEqual(sanitise.clean_email("not-an-email"), "")
        self.assertEqual(sanitise.clean_email("ravi@example.com"), "ravi@example.com")


class SanitisePayerTests(SimpleTestCase):
    def setUp(self):
        self.config = make_config()

    def test_a_clean_payer_is_unchanged(self):
        payer = sanitise.sanitise_payer(make_payer(), self.config)
        self.assertEqual(payer.fullname, "Ravi Kumar")
        self.assertEqual(payer.pincode, "682001")
        self.assertEqual(payer.phone, "9876543210")

    def test_empty_fields_fall_back(self):
        payer = sanitise.sanitise_payer(
            make_payer(city="", address="", pincode="", email="bad", phone="x"), self.config
        )
        self.assertEqual(payer.cityname, "NA")
        self.assertEqual(payer.address, "NA")
        self.assertEqual(payer.pincode, "000000")
        self.assertEqual(payer.email, "")
        self.assertEqual(payer.phone, "")

    def test_an_unrepresentable_name_is_fatal(self):
        with self.assertRaises(ProviderPermanentError) as caught:
            sanitise.sanitise_payer(make_payer(name="രവി"), self.config)
        self.assertEqual(caught.exception.code, constants.EGRAS_INVALID_PAYER)
