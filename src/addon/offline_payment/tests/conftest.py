"""Fixtures for the offline addon tests.

The payments suite's own fixtures are reused for the database tests (flow,
coexistence) by importing them, so the addon tests drive the real 0017
services and APIs.
"""

import pytest

from addon.offline_payment import constants
from addon.offline_payment.config import reset_config_cache
from apps.payments.providers import registry

# Re-exported so pytest registers them for this package too.
from apps.payments.tests.conftest import (  # noqa: F401
    case_id,
    involve,
    make_case,
    make_user,
    raise_demand,
    user,
)

from .base import COUNTERS

MOCK_PATH = "apps.payments.providers.mock.MockPaymentProvider"
PAYABLE_TO = "Chief Judicial Magistrate, Ernakulam"


@pytest.fixture(autouse=True)
def fresh_offline_state():
    """Each test resolves providers and offline settings afresh."""

    registry.reset_cache()
    reset_config_cache()
    yield
    registry.reset_cache()
    reset_config_cache()


@pytest.fixture
def offline_config(settings):
    """A complete offline configuration (no provider registration)."""

    settings.OFFLINE_PAYMENT_ENABLED = True
    settings.OFFLINE_PAYMENT_REFERENCE_PREFIX = "OFL"
    settings.OFFLINE_PAYMENT_VALIDITY_DAYS = 7
    settings.OFFLINE_PAYMENT_RECORDING_GRACE_HOURS = 24
    settings.OFFLINE_PAYMENT_METHODS = ["CASH", "DEMAND_DRAFT", "POS"]
    settings.OFFLINE_PAYMENT_COUNTERS = COUNTERS
    settings.OFFLINE_PAYMENT_DEFAULT_COUNTER = ""
    settings.OFFLINE_PAYMENT_PAYABLE_TO = PAYABLE_TO
    settings.OFFLINE_PAYMENT_MAX_AMOUNT = ""
    settings.OFFLINE_PAYMENT_CASH_MAX_AMOUNT = ""
    settings.OFFLINE_PAYMENT_ALLOWED_CHARGE_TYPES = []
    settings.OFFLINE_PAYMENT_DD_MAX_AGE_DAYS = 90
    reset_config_cache()
    return settings


@pytest.fixture
def offline(offline_config):
    """Offline registered and selectable next to the mock, which stays the default."""

    settings = offline_config
    settings.PAYMENT_PROVIDERS = {"mock": MOCK_PATH, "offline": constants.PROVIDER_PATH}
    settings.PAYMENT_DEFAULT_PROVIDER = "mock"
    settings.PAYMENT_SELECTABLE_PROVIDERS = ["mock", "offline"]
    registry.reset_cache()
    return settings
