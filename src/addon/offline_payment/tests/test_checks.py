"""``manage.py check`` for the offline addon (spec 0032 #13.3)."""

import pytest
from django.test import override_settings

from addon.offline_payment import constants
from addon.offline_payment.checks import check_offline_payment_configuration
from apps.payments.providers import registry

from .base import COUNTERS
from .conftest import MOCK_PATH

MOCK_ONLY = {"mock": MOCK_PATH}


def ids(messages):
    return sorted(message.id for message in messages)


@pytest.fixture(autouse=True)
def registered(offline):
    """Offline registered and selectable with a valid configuration."""

    return offline


def test_valid_configuration_is_silent():
    assert check_offline_payment_configuration(None) == []


def test_silent_when_not_registered(settings):
    settings.PAYMENT_PROVIDERS = MOCK_ONLY
    settings.PAYMENT_SELECTABLE_PROVIDERS = []
    settings.OFFLINE_PAYMENT_REFERENCE_PREFIX = "bad prefix"
    settings.OFFLINE_PAYMENT_PAYABLE_TO = ""
    registry.reset_cache()
    assert check_offline_payment_configuration(None) == []


@pytest.mark.parametrize(
    ("overrides", "check_id"),
    [
        ({"OFFLINE_PAYMENT_REFERENCE_PREFIX": "O"}, "E001"),
        ({"OFFLINE_PAYMENT_REFERENCE_PREFIX": "OFFLN"}, "E001"),
        ({"OFFLINE_PAYMENT_REFERENCE_PREFIX": "Ofl"}, "E001"),
        ({"OFFLINE_PAYMENT_REFERENCE_PREFIX": "OF1"}, "E001"),
        ({"OFFLINE_PAYMENT_VALIDITY_DAYS": 0}, "E002"),
        ({"OFFLINE_PAYMENT_VALIDITY_DAYS": 91}, "E002"),
        ({"OFFLINE_PAYMENT_VALIDITY_DAYS": "x"}, "E002"),
        ({"OFFLINE_PAYMENT_RECORDING_GRACE_HOURS": -1}, "E002"),
        ({"OFFLINE_PAYMENT_RECORDING_GRACE_HOURS": 169}, "E002"),
        ({"OFFLINE_PAYMENT_METHODS": []}, "E003"),
        ({"OFFLINE_PAYMENT_METHODS": ["CASH", "CHEQUE"]}, "E003"),
        ({"OFFLINE_PAYMENT_METHODS": ["CASH", "CASH"]}, "E003"),
        ({"OFFLINE_PAYMENT_COUNTERS": "not json"}, "E004"),
        ({"OFFLINE_PAYMENT_COUNTERS": {"code": "x"}}, "E004"),
        ({"OFFLINE_PAYMENT_COUNTERS": ["EKM"]}, "E004"),
        ({"OFFLINE_PAYMENT_COUNTERS": [COUNTERS[0], COUNTERS[0]]}, "E004"),
        ({"OFFLINE_PAYMENT_COUNTERS": [{"code": "", "label": "x"}]}, "E004"),
        ({"OFFLINE_PAYMENT_COUNTERS": [{"code": "x", "label": ""}]}, "E004"),
        ({"OFFLINE_PAYMENT_DEFAULT_COUNTER": "NOPE"}, "E004"),
        ({"OFFLINE_PAYMENT_INSTRUCTIONS": "x" * 501}, "E004"),
        ({"OFFLINE_PAYMENT_PAYABLE_TO": ""}, "E005"),
        ({"OFFLINE_PAYMENT_MAX_AMOUNT": "0"}, "E006"),
        ({"OFFLINE_PAYMENT_MAX_AMOUNT": "-1"}, "E006"),
        ({"OFFLINE_PAYMENT_MAX_AMOUNT": "10.001"}, "E006"),
        ({"OFFLINE_PAYMENT_CASH_MAX_AMOUNT": "abc"}, "E006"),
        ({"OFFLINE_PAYMENT_ALLOWED_CHARGE_TYPES": ["COURT_FEE", "PARKING"]}, "E007"),
        ({"OFFLINE_PAYMENT_RECEIPT_PATTERN": "(["}, "E008"),
        ({"OFFLINE_PAYMENT_DD_MAX_AGE_DAYS": 0}, "E009"),
    ],
)
def test_each_check_fails_on_its_own(overrides, check_id):
    with override_settings(**overrides):
        assert ids(check_offline_payment_configuration(None)) == [f"offline_payment.{check_id}"]


def test_payable_to_is_optional_without_demand_drafts(settings):
    settings.OFFLINE_PAYMENT_METHODS = ["CASH", "POS"]
    settings.OFFLINE_PAYMENT_PAYABLE_TO = ""
    assert check_offline_payment_configuration(None) == []


def test_w001_registered_but_not_offered(settings):
    settings.PAYMENT_SELECTABLE_PROVIDERS = []
    registry.reset_cache()
    messages = check_offline_payment_configuration(None)
    assert ids(messages) == ["offline_payment.W001"]


def test_offline_as_the_default_needs_no_selectable_list(settings):
    settings.PAYMENT_DEFAULT_PROVIDER = constants.PROVIDER_NAME
    settings.PAYMENT_SELECTABLE_PROVIDERS = []
    registry.reset_cache()
    assert check_offline_payment_configuration(None) == []
