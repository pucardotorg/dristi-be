"""Validating a recorded collection (spec 0032 #8, #17.1 ATT-01 – ATT-25).

``now`` is frozen at 12 Nov 2026 11:45 IST: one day after the request was
issued, well inside its validity.
"""

import socket
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest import mock

import pytest

from addon.offline_payment import constants, methods
from addon.offline_payment.config import resolve_config
from addon.offline_payment.provider import OfflinePaymentProvider
from apps.payments.providers.base import ProviderOutcome, ProviderPermanentError

from .base import ISSUED_AT, attestation, frozen_now, ist
from .test_reference import ref

pytestmark = pytest.mark.usefixtures("offline_config")

NOW = ist(2026, 11, 12, 11, 45)
COLLECTED = ist(2026, 11, 12, 11, 42)
VALID_UNTIL = ist(2026, 11, 18, 23, 59, 59, 999999)
EXPIRES_AT = ist(2026, 11, 19, 23, 59, 59, 999999)
DD = {
    "instrument_number": "123456",
    "instrument_date": "2026-11-10",
    "bank_name": "State Bank of India",
    "branch": "MG Road, Kochi",
}
POS = {"transaction_reference": "TXN123ABC", "terminal_id": "T-01"}


def attest(now=NOW, **overrides):
    overrides.setdefault("collected_at", COLLECTED)
    with frozen_now(now):
        return OfflinePaymentProvider().attest(attestation(ref(), **overrides))


def refusal(now=NOW, **overrides) -> tuple[str, str | None]:
    with pytest.raises(ProviderPermanentError) as caught:
        attest(now, **overrides)
    return caught.value.code, caught.value.field


class TestAccepted:
    def test_att_01_cash(self):
        status = attest(receipt_number=" cjm/ekm/2026/1 ")
        assert status.outcome == ProviderOutcome.SUCCESS
        assert status.provider_payment_id == ref()
        assert status.amount == Decimal("707.50")
        assert status.provider_reference == "CJM/EKM/2026/1"
        assert status.paid_at == COLLECTED
        assert status.failure_code == status.failure_message == ""
        assert status.metadata == {"method": "CASH", "collected_at": COLLECTED.isoformat()}

    def test_att_02_demand_draft_without_the_optional_branch(self):
        details = {k: v for k, v in DD.items() if k != "branch"}
        status = attest(method="DEMAND_DRAFT", details=details)
        assert status.outcome == ProviderOutcome.SUCCESS
        assert status.metadata == {
            "method": "DEMAND_DRAFT",
            "collected_at": COLLECTED.isoformat(),
            **details,
        }

    def test_att_03_pos(self):
        status = attest(method="POS", details=POS)
        assert status.outcome == ProviderOutcome.SUCCESS
        assert status.metadata["transaction_reference"] == "TXN123ABC"

    def test_method_is_case_insensitive(self):
        assert attest(method=" cash ").metadata["method"] == "CASH"

    def test_att_05_trailing_zero(self):
        assert attest(amount=Decimal("707.50"), expected_amount=Decimal("707.5"))
        assert attest(amount="707.5", expected_amount=Decimal("707.50"))

    def test_att_14_recording_within_the_grace(self):
        assert attest(now=EXPIRES_AT, collected_at=VALID_UNTIL)

    def test_att_15_late_recording_skips_the_deadline(self):
        assert attest(now=EXPIRES_AT + timedelta(days=3), late=True)

    def test_att_22_remarks_at_the_limit(self):
        assert attest(remarks="x" * 500)

    def test_att_25_pure_and_fresh(self):
        def refuse(*args, **kwargs):
            raise AssertionError("network access")

        with mock.patch.object(socket, "socket", refuse):
            first = attest()
            second = attest()
        assert first == second and first is not second


class TestRulesInOrder:
    """One test per rule of #8.2."""

    def test_rule_01_and_att_23_malformed_reference(self):
        with frozen_now(NOW), pytest.raises(ProviderPermanentError) as caught:
            OfflinePaymentProvider().attest(attestation("OFL-261111-00000-00000-X"))
        assert (caught.value.code, caught.value.field) == (
            constants.OFFLINE_REFERENCE_MALFORMED,
            None,
        )

    def test_rule_02_currency(self):
        assert refusal(currency="USD") == (constants.OFFLINE_UNSUPPORTED_CURRENCY, None)

    def test_rule_03_and_att_04_method_not_enabled(self, settings):
        assert refusal(method="CHEQUE") == (constants.OFFLINE_METHOD_NOT_ALLOWED, "method")
        settings.OFFLINE_PAYMENT_METHODS = ["CASH"]
        assert refusal(method="POS", details=POS) == (
            constants.OFFLINE_METHOD_NOT_ALLOWED,
            "method",
        )

    @pytest.mark.parametrize(
        "amount", ["707.49", "707.51", "0", "-707.50", "707.505", "abc", "NaN", "Infinity"]
    )
    def test_rule_04_and_att_06_exact_amount(self, amount):
        assert refusal(amount=amount) == (constants.OFFLINE_AMOUNT_MISMATCH, "amount")

    def test_rule_05_and_att_07_cash_cap(self, settings):
        settings.OFFLINE_PAYMENT_CASH_MAX_AMOUNT = "707.50"
        assert attest()  # exactly at the cap
        settings.OFFLINE_PAYMENT_CASH_MAX_AMOUNT = "707.49"
        assert refusal() == (constants.OFFLINE_CASH_LIMIT_EXCEEDED, "amount")
        # A demand draft above the cash cap is fine.
        assert attest(method="DEMAND_DRAFT", details=DD)

    @pytest.mark.parametrize("receipt", ["", "   ", "A" * 65, "CJM 2026 1", "CJM#1", "/CJM"])
    def test_rule_06_and_att_09_receipt(self, receipt):
        assert refusal(receipt_number=receipt) == (
            constants.OFFLINE_RECEIPT_INVALID,
            "receipt_number",
        )

    def test_rule_06_custom_pattern(self, settings):
        settings.OFFLINE_PAYMENT_RECEIPT_PATTERN = r"^R\d{4}$"
        assert attest(receipt_number="r1234").provider_reference == "R1234"
        assert refusal(receipt_number="CJM/1")[0] == constants.OFFLINE_RECEIPT_INVALID

    def test_rule_07_and_att_10_naive_collected_at(self):
        assert refusal(collected_at=datetime(2026, 11, 12, 11, 42)) == (
            constants.OFFLINE_COLLECTED_AT_INVALID,
            "collected_at",
        )
        assert refusal(collected_at="2026-11-12T11:42:00+05:30")[0] == (
            constants.OFFLINE_COLLECTED_AT_INVALID
        )

    def test_rule_08_and_att_11_before_the_request(self):
        assert refusal(collected_at=ISSUED_AT - timedelta(seconds=1)) == (
            constants.OFFLINE_COLLECTED_BEFORE_REQUEST,
            "collected_at",
        )
        assert attest(collected_at=ISSUED_AT)

    def test_rule_09_and_att_12_clock_skew(self):
        assert attest(collected_at=NOW + timedelta(minutes=4))
        assert refusal(collected_at=NOW + timedelta(minutes=6)) == (
            constants.OFFLINE_COLLECTED_IN_FUTURE,
            "collected_at",
        )

    def test_rule_10_and_att_13_after_valid_until(self):
        later = EXPIRES_AT
        assert attest(now=later, collected_at=VALID_UNTIL)
        assert refusal(now=later, collected_at=VALID_UNTIL + timedelta(microseconds=1)) == (
            constants.OFFLINE_COLLECTED_AFTER_EXPIRY,
            "collected_at",
        )

    def test_rule_10_applies_to_late_recording_too(self):
        assert refusal(
            now=EXPIRES_AT + timedelta(days=1),
            collected_at=VALID_UNTIL + timedelta(hours=1),
            late=True,
        )[0] == (constants.OFFLINE_COLLECTED_AFTER_EXPIRY)

    def test_rule_11_and_att_15_recorded_after_expires_at(self):
        assert refusal(now=EXPIRES_AT + timedelta(microseconds=1)) == (
            constants.OFFLINE_REQUEST_EXPIRED,
            None,
        )

    def test_rule_12_and_att_16_required_detail(self):
        details = {k: v for k, v in DD.items() if k != "instrument_number"}
        assert refusal(method="DEMAND_DRAFT", details=details) == (
            constants.OFFLINE_DETAIL_REQUIRED,
            "details.instrument_number",
        )
        blank = {**DD, "bank_name": "  "}
        assert refusal(method="DEMAND_DRAFT", details=blank) == (
            constants.OFFLINE_DETAIL_REQUIRED,
            "details.bank_name",
        )

    def test_rule_12_and_att_21_unknown_detail(self):
        assert refusal(details={"instrument_number": "123456"}) == (
            constants.OFFLINE_DETAIL_UNKNOWN,
            "details.instrument_number",
        )
        assert refusal(method="POS", details={**POS, "cvv": "123"}) == (
            constants.OFFLINE_DETAIL_UNKNOWN,
            "details.cvv",
        )

    @pytest.mark.parametrize("number", ["12345", "1234567", "12a456", "12 456"])
    def test_rule_13_and_att_17_dd_number(self, number):
        assert refusal(method="DEMAND_DRAFT", details={**DD, "instrument_number": number}) == (
            constants.OFFLINE_DETAIL_INVALID,
            "details.instrument_number",
        )

    @pytest.mark.parametrize("drawn", ["2026-02-30", "10/11/2026", "2026-1-5", "yesterday"])
    def test_rule_13_and_att_20_dd_date_format(self, drawn):
        assert refusal(method="DEMAND_DRAFT", details={**DD, "instrument_date": drawn}) == (
            constants.OFFLINE_DETAIL_INVALID,
            "details.instrument_date",
        )

    def test_rule_13_text_lengths(self):
        assert refusal(method="DEMAND_DRAFT", details={**DD, "bank_name": "B" * 101}) == (
            constants.OFFLINE_DETAIL_INVALID,
            "details.bank_name",
        )
        assert refusal(method="DEMAND_DRAFT", details={**DD, "branch": "B" * 101})[1] == (
            "details.branch"
        )
        assert refusal(method="DEMAND_DRAFT", details={**DD, "bank_name": "SBI\x00"})[0] == (
            constants.OFFLINE_DETAIL_INVALID
        )

    @pytest.mark.parametrize("txn", ["ABC12", "A" * 33, "TXN-1234", "TXN 1234"])
    def test_rule_13_pos_transaction_reference(self, txn):
        assert refusal(method="POS", details={"transaction_reference": txn}) == (
            constants.OFFLINE_DETAIL_INVALID,
            "details.transaction_reference",
        )

    def test_rule_13_pos_terminal_is_optional_but_bounded(self):
        assert attest(method="POS", details={"transaction_reference": "ABC123"})
        assert refusal(method="POS", details={**POS, "terminal_id": "T" * 17})[1] == (
            "details.terminal_id"
        )

    def test_rule_14_and_att_18_dd_dated_after_collection(self):
        # Collected 12 Nov 00:30 IST (11 Nov 19:00 UTC): a DD dated 12 Nov is fine,
        # 13 Nov is not; the IST date is what counts.
        collected = datetime(2026, 11, 11, 19, 0, tzinfo=UTC)
        assert attest(
            method="DEMAND_DRAFT",
            details={**DD, "instrument_date": "2026-11-12"},
            collected_at=collected,
        )
        assert refusal(
            method="DEMAND_DRAFT",
            details={**DD, "instrument_date": "2026-11-13"},
            collected_at=collected,
        ) == (constants.OFFLINE_DD_DATE_INVALID, "details.instrument_date")

    def test_rule_14_and_att_19_dd_age(self):
        on_limit = (COLLECTED.date() - timedelta(days=90)).isoformat()
        too_old = (COLLECTED.date() - timedelta(days=91)).isoformat()
        assert attest(method="DEMAND_DRAFT", details={**DD, "instrument_date": on_limit})
        assert refusal(method="DEMAND_DRAFT", details={**DD, "instrument_date": too_old}) == (
            constants.OFFLINE_DD_STALE,
            "details.instrument_date",
        )

    def test_rule_15_and_att_22_remarks(self):
        assert refusal(remarks="x" * 501) == (constants.OFFLINE_REMARKS_TOO_LONG, "remarks")

    def test_att_24_first_broken_rule_wins(self):
        assert refusal(
            method="CHEQUE",
            amount="1.00",
            receipt_number="",
            remarks="x" * 600,
        ) == (constants.OFFLINE_METHOD_NOT_ALLOWED, "method")
        assert refusal(amount="1.00", receipt_number="", remarks="x" * 600)[1] == "amount"
        assert refusal(receipt_number="", remarks="x" * 600)[1] == "receipt_number"

    def test_rejection_is_logged_without_values(self, caplog):
        caplog.set_level("INFO", logger="addon.offline_payment")
        refusal(amount="1.00")
        assert "event=OFFLINE_ATTESTATION_REJECTED" in caplog.text
        assert "OFFLINE_AMOUNT_MISMATCH" in caplog.text


class TestMethods:
    def test_fixed_set_and_fields(self):
        assert methods.SUPPORTED == ("CASH", "DEMAND_DRAFT", "POS")
        dd = methods.method("DEMAND_DRAFT")
        assert [(f.key, f.kind, f.required, f.max_length) for f in dd.fields] == [
            ("instrument_number", "digits", True, 6),
            ("instrument_date", "date", True, 64),
            ("bank_name", "text", True, 100),
            ("branch", "text", False, 100),
        ]
        assert methods.method("CASH").fields == ()
        pos = methods.method("POS")
        assert [(f.key, f.required, f.max_length) for f in pos.fields] == [
            ("transaction_reference", True, 32),
            ("terminal_id", False, 16),
        ]

    def test_enabled_ignores_unsupported_codes(self, settings):
        settings.OFFLINE_PAYMENT_METHODS = ["CASH", "CHEQUE"]
        assert [m.code for m in methods.enabled(resolve_config())] == ["CASH"]

    def test_no_cheques(self):
        assert "CHEQUE" not in methods.SUPPORTED
