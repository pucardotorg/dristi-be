"""Scheme (head of account) mapping tests (spec 0022 #4.3)."""

from django.test import SimpleTestCase

from addon.egras_payment_gateway import constants
from addon.egras_payment_gateway.schemes import Scheme, build_schemes, resolve_scheme
from apps.payments.providers.base import ProviderPermanentError

from .base import make_line

SCHEME_MAP = {
    "COURT_FEE": "0030-01-501-01-00",
    "0040-02-502-02-00": "0040-02-502-02-00",
    "PROCESS_COURT_FEE": "0050-03-503-03-00",
}


def build(lines, max_schemes=4):
    return build_schemes(lines, scheme_map=SCHEME_MAP, max_schemes=max_schemes)


class ResolveSchemeTests(SimpleTestCase):
    def test_account_head_is_tried_first(self):
        line = make_line("10", charge_type="COURT_FEE", account_head="0040-02-502-02-00")
        self.assertEqual(resolve_scheme(line, SCHEME_MAP), "0040-02-502-02-00")

    def test_unmapped_account_head_code_is_not_used_directly(self):
        """A client-supplied account_head is never a literal scheme code (spec 0022 #4.3)."""
        line = make_line("10", charge_type="UNKNOWN", account_head="9999-99-999-99-99")
        with self.assertRaises(ProviderPermanentError) as caught:
            resolve_scheme(line, SCHEME_MAP)
        self.assertEqual(caught.exception.code, constants.EGRAS_SCHEME_UNMAPPED)

    def test_charge_type_is_the_fallback(self):
        line = make_line("10", charge_type="COURT_FEE", account_head="")
        self.assertEqual(resolve_scheme(line, SCHEME_MAP), "0030-01-501-01-00")

    def test_unmapped_charge_is_a_permanent_error(self):
        line = make_line("10", charge_type="MYSTERY_FEE", account_head="")
        with self.assertRaises(ProviderPermanentError) as caught:
            resolve_scheme(line, SCHEME_MAP)
        self.assertEqual(caught.exception.code, constants.EGRAS_SCHEME_UNMAPPED)


class BuildSchemesTests(SimpleTestCase):
    def test_lines_on_one_head_are_grouped_and_summed(self):
        schemes = build([make_line("10"), make_line("15")])
        self.assertEqual(schemes, [Scheme("0030-01-501-01-00", 25)])

    def test_two_half_rupee_lines_on_one_head_pass(self):
        schemes = build([make_line("12.50"), make_line("12.50")])
        self.assertEqual(schemes, [Scheme("0030-01-501-01-00", 25)])

    def test_a_lone_fractional_head_fails(self):
        with self.assertRaises(ProviderPermanentError) as caught:
            build([make_line("12.50")])
        self.assertEqual(caught.exception.code, constants.EGRAS_FRACTIONAL_AMOUNT)

    def test_schemes_are_ordered_by_code(self):
        schemes = build(
            [
                make_line("5", charge_type="PROCESS_COURT_FEE"),
                make_line("7", charge_type="COURT_FEE"),
            ]
        )
        self.assertEqual(
            [scheme.code for scheme in schemes], ["0030-01-501-01-00", "0050-03-503-03-00"]
        )

    def test_too_many_schemes_fail(self):
        lines = [
            make_line("1", charge_type="COURT_FEE"),
            make_line("1", charge_type="PROCESS_COURT_FEE"),
        ]
        with self.assertRaises(ProviderPermanentError) as caught:
            build_schemes(lines, scheme_map=SCHEME_MAP, max_schemes=1)
        self.assertEqual(caught.exception.code, constants.EGRAS_TOO_MANY_SCHEMES)
