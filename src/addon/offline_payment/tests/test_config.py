"""Configuration loading (spec 0032 #13.2)."""

from datetime import timedelta
from decimal import Decimal

from django.test import override_settings

from addon.offline_payment import constants
from addon.offline_payment.config import Counter, OfflineConfig, resolve_config

from .base import COUNTERS


def test_defaults_without_any_setting():
    config = OfflineConfig()
    assert config.enabled is True
    assert config.label == "Pay at the court counter"
    assert config.reference_prefix == "OFL"
    assert config.validity == timedelta(days=7)
    assert config.grace == timedelta(hours=24)
    assert config.methods == ("CASH", "DEMAND_DRAFT")
    assert config.counters == ()
    assert config.max_amount is None and config.cash_max_amount is None
    assert config.allowed_charge_types == ()
    assert config.receipt_re.pattern == constants.DEFAULT_RECEIPT_PATTERN
    assert config.dd_max_age == timedelta(days=90)
    assert config.pending_horizon == timedelta(days=9)


def test_settings_defaults_match_the_spec():
    """base.py ships the documented defaults."""

    config = resolve_config()
    assert config.label == constants.DEFAULT_LABEL
    assert config.methods == constants.DEFAULT_METHODS
    assert config.instructions == constants.DEFAULT_INSTRUCTIONS


@override_settings(
    OFFLINE_PAYMENT_ENABLED=False,
    OFFLINE_PAYMENT_LABEL="Counter",
    OFFLINE_PAYMENT_REFERENCE_PREFIX="CRT",
    OFFLINE_PAYMENT_VALIDITY_DAYS="10",
    OFFLINE_PAYMENT_RECORDING_GRACE_HOURS=0,
    OFFLINE_PAYMENT_METHODS="cash, pos",
    OFFLINE_PAYMENT_COUNTERS='[{"code": " EKM ", "label": "Ernakulam"}]',
    OFFLINE_PAYMENT_DEFAULT_COUNTER="EKM",
    OFFLINE_PAYMENT_MAX_AMOUNT="5000.00",
    OFFLINE_PAYMENT_CASH_MAX_AMOUNT="199999.00",
    OFFLINE_PAYMENT_ALLOWED_CHARGE_TYPES="COURT_FEE,EPOST_FEE",
)
def test_values_are_read_and_coerced():
    config = resolve_config()
    assert config.enabled is False
    assert config.label == "Counter"
    assert config.reference_prefix == "CRT"
    assert config.validity == timedelta(days=10)
    assert config.grace == timedelta(0)
    assert config.methods == ("CASH", "POS")
    assert config.counters == (Counter(code="EKM", label="Ernakulam"),)
    assert config.counter("EKM").label == "Ernakulam"
    assert config.counter("NOPE") is None
    assert config.max_amount == Decimal("5000.00")
    assert config.cash_max_amount == Decimal("199999.00")
    assert config.allowed_charge_types == ("COURT_FEE", "EPOST_FEE")
    assert config.validate() == []


def test_cache_is_cleared_when_a_setting_changes():
    first = resolve_config()
    assert resolve_config() is first
    with override_settings(OFFLINE_PAYMENT_LABEL="Changed"):
        assert resolve_config().label == "Changed"
    assert resolve_config().label == constants.DEFAULT_LABEL


def test_unrelated_settings_keep_the_cache():
    first = resolve_config()
    with override_settings(EGRAS_ENABLED=False):
        assert resolve_config() is first


def test_malformed_values_never_crash_loading():
    with override_settings(
        OFFLINE_PAYMENT_VALIDITY_DAYS="seven",
        OFFLINE_PAYMENT_COUNTERS="{not json",
        OFFLINE_PAYMENT_MAX_AMOUNT="lots",
        OFFLINE_PAYMENT_RECEIPT_PATTERN="([",
    ):
        config = resolve_config()
        # Safe fallbacks wherever a value is used; validate() reports each problem.
        assert config.validity == timedelta(days=7)
        assert config.counters == ()
        assert config.max_amount is None
        assert config.receipt_re is None
        assert {check for check, _ in config.validate()} >= {"E002", "E004", "E006", "E008"}


def test_counter_parsing_accepts_a_list():
    with override_settings(OFFLINE_PAYMENT_COUNTERS=COUNTERS):
        assert [c.code for c in resolve_config().counters] == ["EKM-CJM", "EKM-MC"]
