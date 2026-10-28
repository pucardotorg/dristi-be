"""Fixtures for the e-GRAS flow tests, driving 0017's payment APIs.

These mirror the payments suite's own fixtures (which are not visible outside
that package) and register e-GRAS as the default provider with a complete,
valid configuration.
"""

import itertools

import pytest
from django.conf import settings as django_settings
from django.contrib.auth import get_user_model

from addon.egras_payment_gateway import constants
from apps.cases.models import Case, CaseType
from apps.payments.enums import ChargeType, ReferenceType
from apps.payments.providers import registry
from apps.payments.services import DemandService
from apps.payments.tests.helpers import item

MOCK_PATH = "apps.payments.providers.mock.MockPaymentProvider"
REDIRECT = "https://app.example.com/payments/return"

_mobile = itertools.count(1)


@pytest.fixture(autouse=True)
def fresh_registry():
    """Each test resolves providers from its own settings."""

    registry.reset_cache()
    yield
    registry.reset_cache()


@pytest.fixture
def egras(settings):
    """Register e-GRAS as the default provider with a valid configuration."""

    settings.PAYMENT_PROVIDERS = {"mock": MOCK_PATH, "egras": constants.PROVIDER_PATH}
    settings.PAYMENT_DEFAULT_PROVIDER = "egras"
    settings.PAYMENT_UI_REDIRECT_URL = REDIRECT
    settings.EGRAS_PAYMENT_URL = "https://egras.invalid/echallan"
    settings.EGRAS_VERIFY_URL = "https://egras.invalid/grnstatus"
    settings.EGRAS_RETURN_URL = "https://dristi.invalid/api/v1/payments/providers/egras/_callback"
    settings.EGRAS_DEPT_CODE = "DRI"
    settings.EGRAS_DTO = "01"
    settings.EGRAS_STO = "02"
    settings.EGRAS_DDO = "DDO1"
    settings.EGRAS_SCHEME_MAP = {"COURT_FEE": "0030-01-501-01-00"}
    settings.EGRAS_BANK_OPTIONS = [
        {"code": "SBI", "label": "State Bank of India", "group": "NET_BANKING"}
    ]
    settings.EGRAS_DEFAULT_BANK = "SBI"
    registry.reset_cache()


@pytest.fixture
def user(db):
    """The signed-in payer."""

    from apps.users.models import RegistrationStatus, Role

    return get_user_model().objects.create_user(
        mobile_number=f"+9198{next(_mobile):08d}",
        name="Anjali Menon",
        email="anjali@example.com",
        role=Role.LITIGANT.value,
        registration_status=RegistrationStatus.COMPLETE.value,
        terms_version_accepted=django_settings.CURRENT_TERMS_VERSION,
    )


@pytest.fixture
def case_id(user):
    """A real case filed by the payer; raise_demand now requires one to exist."""

    return Case.objects.create(created_by=user, case_type=CaseType.CHEQUE_BOUNCE).pk


@pytest.fixture
def raise_demand(user, case_id):
    """Raise a demand of whole-rupee court-fee items that map to a scheme."""

    def factory(amount="100.00", *, charge_type=ChargeType.COURT_FEE, reference_id="order-1"):
        return DemandService.raise_demand(
            case=case_id,
            reference_type=ReferenceType.ORDER,
            reference_id=reference_id,
            items=[item(charge_type=charge_type, unit_amount=amount)],
            user_id=user.pk,
            actor=user,
        )

    return factory
