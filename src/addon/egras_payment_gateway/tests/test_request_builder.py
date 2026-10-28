"""e-Challan form-building tests (spec 0022 #4)."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from django.test import SimpleTestCase

from addon.egras_payment_gateway import constants, sanitise
from addon.egras_payment_gateway.request_builder import (
    application_number,
    build_remarks,
    build_request,
    financial_year,
    select_bank,
)
from apps.payments.providers.base import ProviderPermanentError

from .base import make_config, make_line, make_request


class FinancialYearTests(SimpleTestCase):
    def test_year_boundaries_in_ist(self):
        self.assertEqual(financial_year(datetime(2026, 10, 12, 9, 0, tzinfo=constants.IST)), "2627")
        self.assertEqual(financial_year(datetime(2027, 3, 31, 23, 0, tzinfo=constants.IST)), "2627")
        self.assertEqual(financial_year(datetime(2027, 4, 1, 0, 30, tzinfo=constants.IST)), "2728")


class ApplicationNumberTests(SimpleTestCase):
    def test_deterministic_prefixed_and_bounded(self):
        reference = UUID("0f9d3a6c1b2e4f5a7b8c9d0e1f2a3b4c")
        number = application_number(reference, "DR")
        self.assertTrue(number.startswith("DR"))
        self.assertEqual(len(number), 20)
        self.assertEqual(number, application_number(reference, "DR"))


class RemarksTests(SimpleTestCase):
    def test_short_batch_is_verbatim(self):
        self.assertEqual(
            build_remarks(("DMD-1", "DMD-2"), "Dristi {demand_numbers}"), "Dristi DMD-1 DMD-2"
        )

    def test_large_batch_is_cut_with_and_n_more(self):
        numbers = tuple(f"DMD-{i:04d}" for i in range(100))
        remarks = build_remarks(numbers, "Dristi {demand_numbers}")
        self.assertLessEqual(len(remarks), sanitise.MAX_REMARKS)
        self.assertIn("more", remarks)


class BankSelectionTests(SimpleTestCase):
    def setUp(self):
        self.config = make_config()

    def test_requested_bank_is_used(self):
        self.assertEqual(select_bank({"bank": "UPI"}, self.config), "UPI")

    def test_default_is_used_when_none_requested(self):
        self.assertEqual(select_bank({}, self.config), "SBI")

    def test_invalid_bank_raises_with_field(self):
        with self.assertRaises(ProviderPermanentError) as caught:
            select_bank({"bank": "HDFC"}, self.config)
        self.assertEqual(caught.exception.code, constants.EGRAS_INVALID_BANK)
        self.assertEqual(caught.exception.field, "bank")

    def test_missing_bank_with_no_default_raises(self):
        with self.assertRaises(ProviderPermanentError) as caught:
            select_bank({}, make_config(default_bank=""))
        self.assertEqual(caught.exception.code, constants.EGRAS_BANK_REQUIRED)
        self.assertEqual(caught.exception.field, "bank")


class BuildRequestTests(SimpleTestCase):
    def setUp(self):
        self.config = make_config()

    def test_every_field_and_its_source(self):
        request = make_request([make_line("25")])
        built = build_request(request, self.config)
        form = built.form_fields

        self.assertEqual(built.provider_payment_id, form[constants.FIELD_APPLICATION_NUMBER])
        self.assertEqual(form[constants.FIELD_DTO], "01")
        self.assertEqual(form[constants.FIELD_OFFICE_NAME], "0102DDO1")
        self.assertEqual(form[constants.FIELD_PTYPE], constants.PTYPE_NET_BANKING)
        self.assertEqual(form[constants.FIELD_UURL], self.config.return_url)
        self.assertEqual(form[constants.FIELD_CHALLAN_YEAR], "2627")
        self.assertEqual(form[constants.FIELD_TOTAL_AMOUNT], "25")
        self.assertEqual(form[constants.FIELD_SCHEME_COUNT], "1")
        self.assertEqual(form[constants.scheme_name_field(1)], "0030-01-501-01-00")
        self.assertEqual(form[constants.fee_amount_field(1)], "25")

    def test_single_scheme_field_names_match_nic_sample(self):
        """NIC v3.6 sample posts the first head as ``SCHEMENAME`` with ``FEEAMOUNT1``."""
        form = build_request(make_request([make_line("25")]), self.config).form_fields
        self.assertIn("SCHEMENAME", form)
        self.assertNotIn("SCHEMENAME1", form)
        self.assertIn("FEEAMOUNT1", form)

    def test_second_scheme_name_is_suffixed(self):
        """A second head posts as ``SCHEMENAME2`` / ``FEEAMOUNT2``."""
        request = make_request(
            [
                make_line("10", charge_type="COURT_FEE"),
                make_line("15", account_head="0099-09-909-09-09"),
            ],
            amount=Decimal("25"),
        )
        form = build_request(request, make_config()).form_fields
        self.assertEqual(form["SCHEMECOUNT"], "2")
        self.assertIn("SCHEMENAME", form)
        self.assertIn("SCHEMENAME2", form)
        self.assertIn("FEEAMOUNT2", form)

    def test_total_equals_sum_of_fee_amounts(self):
        request = make_request(
            [
                make_line("20", charge_type="COURT_FEE"),
                make_line("5", account_head="0099-09-909-09-09"),
            ],
            amount=Decimal("25"),
        )
        config = make_config(scheme_map={"COURT_FEE": "0030-01-501-01-00"})
        form = build_request(request, config).form_fields
        fees = sum(int(form[constants.fee_amount_field(i)]) for i in (1, 2))
        self.assertEqual(int(form[constants.FIELD_TOTAL_AMOUNT]), fees)

    def test_replay_is_identical(self):
        request = make_request([make_line("25")])
        self.assertEqual(
            build_request(request, self.config).form_fields,
            build_request(request, self.config).form_fields,
        )

    def test_non_inr_currency_is_rejected(self):
        request = make_request([make_line("25")], currency="USD")
        with self.assertRaises(ProviderPermanentError) as caught:
            build_request(request, self.config)
        self.assertEqual(caught.exception.code, constants.EGRAS_UNSUPPORTED_CURRENCY)

    def test_amount_inconsistent_with_scheme_total_is_rejected(self):
        request = make_request([make_line("25")], amount=Decimal("30"))
        with self.assertRaises(ProviderPermanentError) as caught:
            build_request(request, self.config)
        self.assertEqual(caught.exception.code, constants.EGRAS_AMOUNT_INCONSISTENT)
