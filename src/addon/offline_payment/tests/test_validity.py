"""Validity, expiry and fetch_status (spec 0032 #6, #17.1 VAL-01 – VAL-09)."""

from datetime import date, timedelta

import pytest

from addon.offline_payment import constants, validity
from addon.offline_payment.config import OfflineConfig, resolve_config
from addon.offline_payment.provider import OfflinePaymentProvider
from apps.payments.providers.base import ProviderOutcome

from .base import ISSUED_AT, frozen_now, ist
from .test_reference import ref

MICRO = timedelta(microseconds=1)
ISSUED_ON = date(2026, 11, 11)


def config(**values) -> OfflineConfig:
    return OfflineConfig(**values)


def test_val_01_valid_until_is_the_end_of_the_last_day():
    assert validity.valid_until(ISSUED_ON, config()) == ist(2026, 11, 18, 23, 59, 59, 999999)


def test_val_02_expires_after_the_grace():
    assert validity.expires_at(ISSUED_ON, config()) == ist(2026, 11, 19, 23, 59, 59, 999999)


def test_val_03_zero_grace():
    no_grace = config(grace_hours=0)
    assert validity.expires_at(ISSUED_ON, no_grace) == validity.valid_until(ISSUED_ON, no_grace)


class TestFetchStatus:
    """VAL-04, VAL-06 – VAL-08, through the provider and the configured settings."""

    @pytest.fixture(autouse=True)
    def _config(self, offline_config):
        self.provider = OfflinePaymentProvider()
        self.reference = ref()
        self.expires = validity.expires_at(ISSUED_ON, resolve_config())

    def fetch(self, at, reference=None):
        with frozen_now(at):
            ref_ = self.reference if reference is None else reference
            return self.provider.fetch_status(provider_payment_id=ref_)

    def test_val_04_boundaries(self):
        assert self.fetch(self.expires - MICRO).outcome == ProviderOutcome.PENDING
        assert self.fetch(self.expires).outcome == ProviderOutcome.PENDING
        after = self.fetch(self.expires + MICRO)
        assert after.outcome == ProviderOutcome.FAILED
        assert after.failure_code == constants.OFFLINE_REQUEST_EXPIRED
        assert after.failure_message
        assert after.amount is None and after.provider_reference == ""

    def test_val_06_raising_validity_extends_issued_requests(self, settings):
        settings.OFFLINE_PAYMENT_VALIDITY_DAYS = 10
        assert self.fetch(self.expires + timedelta(days=2)).outcome == ProviderOutcome.PENDING

    def test_val_07_lowering_validity_expires_issued_requests_early(self, settings):
        settings.OFFLINE_PAYMENT_VALIDITY_DAYS = 1
        assert self.fetch(ISSUED_AT + timedelta(days=3)).outcome == ProviderOutcome.FAILED

    @pytest.mark.parametrize(
        "foreign",
        ["", "garbage", "DR0F9D3A2B1C", "MOCK-abc-SUCCESS-1.00", "OFL-261341-7K3QF-9XM2H-V"],
    )
    def test_val_08_foreign_or_malformed_is_not_found(self, foreign):
        status = self.fetch(ISSUED_AT, reference=foreign)
        assert status.outcome == ProviderOutcome.NOT_FOUND

    def test_never_success(self):
        for days in range(0, 30):
            status = self.fetch(ISSUED_AT + timedelta(days=days))
            assert status.outcome != ProviderOutcome.SUCCESS

    def test_a_changed_prefix_no_longer_recognises_old_references(self, settings):
        settings.OFFLINE_PAYMENT_REFERENCE_PREFIX = "CRT"
        assert self.fetch(ISSUED_AT).outcome == ProviderOutcome.NOT_FOUND


@pytest.mark.parametrize(
    ("issued", "days", "until"),
    [
        (date(2026, 3, 31), 7, date(2026, 4, 7)),  # VAL-05: across a month
        (date(2026, 12, 28), 7, date(2027, 1, 4)),  # across a year
        (date(2028, 2, 27), 3, date(2028, 3, 1)),  # leap year
    ],
)
def test_val_05_calendar_arithmetic(issued, days, until):
    deadline = validity.valid_until(issued, config(validity_days=days))
    assert deadline.date() == until


@pytest.mark.parametrize("validity_days", [1, 2, 7, 30, 89, 90])
@pytest.mark.parametrize("grace_hours", [0, 1, 24, 100, 168])
def test_val_09_pending_horizon_covers_the_longest_open_request(validity_days, grace_hours):
    """Created at 00:00:00 IST on the issue day, a request is open until expires_at."""

    cfg = config(validity_days=validity_days, grace_hours=grace_hours)
    earliest_creation = ist(2026, 11, 11, 0, 0, 0)
    assert validity.expires_at(earliest_creation.date(), cfg) - earliest_creation < (
        cfg.pending_horizon
    )


def test_format_ist():
    assert validity.format_ist(ist(2026, 11, 18, 23, 59, 59)) == "18 Nov 2026, 11:59 PM IST"
    assert validity.format_ist(ist(2026, 1, 5, 0, 5)) == "5 Jan 2026, 12:05 AM IST"


def test_ist_date_of_a_utc_time():
    from datetime import UTC, datetime

    assert validity.ist_date(datetime(2026, 11, 10, 18, 30, tzinfo=UTC)) == ISSUED_ON
    assert validity.ist_date(datetime(2026, 11, 10, 18, 29, tzinfo=UTC)) == date(2026, 11, 10)
