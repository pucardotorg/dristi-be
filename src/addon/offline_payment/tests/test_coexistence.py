"""Offline and e-GRAS side by side (spec 0032 #12, #17.5).

e-GRAS HTTP is mocked as in 0022's flow tests. Neither addon knows the other.
"""

import json
import os
import subprocess
import sys
from pathlib import Path
from unittest import mock
from urllib.parse import parse_qs, urlparse

import pytest
import requests
from django.core.cache import cache
from django.urls import reverse
from rest_framework.test import APIClient

from addon.egras_payment_gateway import constants as egras_constants
from addon.egras_payment_gateway.tests.base import RESPONSE_KEY_FILE
from addon.offline_payment import constants
from apps.api import errors as api_errors
from apps.payments.enums import DemandStatus, PaymentStatus
from apps.payments.models import Payment
from apps.payments.providers import registry
from apps.payments.tests.helpers import assert_error, item, item_ids

pytestmark = pytest.mark.django_db

SRC_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def both(offline):
    """e-GRAS the default, offline selectable next to it."""

    settings = offline
    settings.PAYMENT_PROVIDERS = {
        "egras": egras_constants.PROVIDER_PATH,
        "offline": constants.PROVIDER_PATH,
    }
    settings.PAYMENT_DEFAULT_PROVIDER = "egras"
    settings.PAYMENT_SELECTABLE_PROVIDERS = ["egras", "offline"]
    settings.PAYMENT_UI_REDIRECT_URL = "https://app.example.com/payments/return"
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
    settings.EGRAS_RESPONSE_KEY_PATH = RESPONSE_KEY_FILE
    registry.reset_cache()
    cache.clear()
    yield settings
    cache.clear()


@pytest.fixture
def clerk(make_user):
    from django.contrib.auth.models import Permission

    staff = make_user("Suresh K")
    staff.user_permissions.add(
        *Permission.objects.filter(
            content_type__app_label="payments",
            codename__in=["view_payment_collection", "record_payment_collection"],
        )
    )
    return type(staff).objects.get(pk=staff.pk)


def client_for(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


def grn_xml(amount):
    return (
        f"<GrnDetails><GRN>1231234</GRN><Amount>{amount}</Amount><Status>Successfull</Status>"
        "<CIN>CIN123</CIN><Bankdate>12/10/2026</Bankdate></GrnDetails>"
    ).encode()


def mock_verify(content):
    response = mock.Mock(spec=requests.Response)
    response.content = content
    response.status_code = 200
    response.ok = True
    return mock.patch.object(requests, "post", return_value=response)


def court_fee_demand(raise_demand):
    return raise_demand(
        [
            item(charge_type="COURT_FEE", unit_amount="100.00"),
            item(charge_type="COURT_FEE", unit_amount="50.00"),
        ]
    )


def test_both_providers_are_listed(both, user):
    body = client_for(user).get(reverse("payments-providers")).json()
    assert body["default"] == "egras"
    assert [(p["name"], p["confirmation"]) for p in body["providers"]] == [
        ("egras", "PROVIDER"),
        ("offline", "ATTESTED"),
    ]
    egras, offline = body["providers"]
    assert egras["options"][0]["code"] == "SBI"
    assert offline["label"] == "Pay at the court counter"
    assert [o["code"] for o in offline["options"]] == ["EKM-CJM", "EKM-MC"]


def test_one_demand_paid_through_both(both, raise_demand, user, clerk):
    payer = client_for(user)
    demand = court_fee_demand(raise_demand)
    first, second = item_ids(demand)
    path = reverse("payments-demand-payments", kwargs={"demand_id": demand.pk})

    online = payer.post(
        path,
        {
            "client_request_id": "online",
            "demand_item_ids": [str(first)],
            "provider_options": {"bank": "SBI"},
        },
        format="json",
    )
    assert online.status_code == 201, online.content
    assert online.json()["provider"] == "egras"

    # The same item cannot be paid offline while the online payment is open.
    blocked = payer.post(
        path,
        {
            "client_request_id": "offline-0",
            "demand_item_ids": [str(first)],
            "provider": "offline",
            "provider_options": {"counter": "EKM-CJM"},
        },
        format="json",
    )
    assert blocked.status_code == 409

    offline = payer.post(
        path,
        {
            "client_request_id": "offline-1",
            "demand_item_ids": [str(second)],
            "provider": "offline",
            "provider_options": {"counter": "EKM-CJM"},
        },
        format="json",
    )
    assert offline.status_code == 201, offline.content
    ref = offline.json()["provider_payment_id"]

    # e-GRAS completes through its verified callback.
    egras_id = online.json()["provider_payment_id"]
    with mock_verify(grn_xml("100")):
        APIClient().post(
            reverse("payments-provider-callback", kwargs={"provider": "egras"}),
            {"Applicationnumber": egras_id, "status": "Success", "GRN": "1231234"},
        )
    # Offline completes through the desk.
    recorded = client_for(clerk).post(
        reverse("payments-collection-confirm", kwargs={"provider": "offline", "reference": ref}),
        {"amount": "50.00", "method": "CASH", "receipt_number": "R-1"},
        format="json",
    )
    assert recorded.status_code == 200, recorded.content

    assert set(Payment.objects.values_list("status", flat=True)) == {PaymentStatus.SUCCESS}
    demand.refresh_from_db()
    assert demand.status == DemandStatus.PAID


def test_egras_callback_with_an_offline_reference(both, raise_demand, user):
    payer = client_for(user)
    demand = court_fee_demand(raise_demand)
    created = payer.post(
        reverse("payments-demand-payments", kwargs={"demand_id": demand.pk}),
        {
            "client_request_id": "offline",
            "demand_item_ids": [str(i) for i in item_ids(demand)],
            "provider": "offline",
            "provider_options": {"counter": "EKM-CJM"},
        },
        format="json",
    ).json()
    with mock_verify(grn_xml("150")):
        response = APIClient().post(
            reverse("payments-provider-callback", kwargs={"provider": "egras"}),
            {
                "Applicationnumber": created["provider_payment_id"],
                "status": "Success",
                "GRN": "1",
            },
        )
    assert parse_qs(urlparse(response["Location"]).query)["status"] == ["UNKNOWN"]
    assert Payment.objects.get().status == PaymentStatus.PENDING


def test_offline_lookup_of_an_egras_number(both, raise_demand, user, clerk):
    payer = client_for(user)
    demand = court_fee_demand(raise_demand)
    created = payer.post(
        reverse("payments-demand-payments", kwargs={"demand_id": demand.pk}),
        {
            "client_request_id": "online",
            "demand_item_ids": [str(i) for i in item_ids(demand)],
            "provider_options": {"bank": "SBI"},
        },
        format="json",
    ).json()
    desk = client_for(clerk)
    egras_id = created["provider_payment_id"]
    # Not an offline reference at all: refused before any lookup (spec 0032 #9.2).
    assert_error(
        desk.get(
            reverse(
                "payments-collection-detail",
                kwargs={"provider": "offline", "reference": egras_id},
            )
        ),
        api_errors.INVALID,
        "reference",
    )
    # e-GRAS is not ATTESTED: whether the number exists is not revealed (#4.6).
    assert_error(
        desk.get(
            reverse(
                "payments-collection-detail", kwargs={"provider": "egras", "reference": egras_id}
            )
        ),
        api_errors.NOT_FOUND,
    )


def production_providers(**env) -> dict | str:
    environ = {
        **os.environ,
        "SECRET_KEY": "test",
        "ALLOWED_HOSTS": "example.com",
        "PAYMENT_DEFAULT_PROVIDER": "",
        "PAYMENT_REGISTERED_PROVIDERS": "",
        "PAYMENT_SELECTABLE_PROVIDERS": "",
        **env,
    }
    environ.pop("DJANGO_SETTINGS_MODULE", None)
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import json, config.settings.production as s; print(json.dumps(s.PAYMENT_PROVIDERS))",
        ],
        cwd=SRC_ROOT,
        env=environ,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode:
        return result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1])


@pytest.mark.parametrize(
    ("env", "expected"),
    [
        (
            {"PAYMENT_DEFAULT_PROVIDER": "egras", "PAYMENT_SELECTABLE_PROVIDERS": "egras,offline"},
            {"egras", "offline"},
        ),
        (
            {"PAYMENT_DEFAULT_PROVIDER": "egras", "PAYMENT_REGISTERED_PROVIDERS": "offline"},
            {"egras", "offline"},
        ),
        ({"PAYMENT_DEFAULT_PROVIDER": "offline"}, {"offline"}),
        ({}, set()),
    ],
)
def test_production_registration(env, expected):
    providers = production_providers(**env)
    assert isinstance(providers, dict), providers
    assert set(providers) == expected
    if "offline" in expected:
        assert providers["offline"] == constants.PROVIDER_PATH


def test_production_refuses_an_unknown_selectable_name():
    error = production_providers(PAYMENT_SELECTABLE_PROVIDERS="egras,cheque")
    assert isinstance(error, str) and "ImproperlyConfigured" in error and "cheque" in error


def test_egras_label_and_confirmation():
    from addon.egras_payment_gateway.provider import EGRASPaymentProvider
    from apps.payments.providers.base import ConfirmationMode

    assert EGRASPaymentProvider.label == "Pay online (net banking / UPI)"
    assert EGRASPaymentProvider.confirmation == ConfirmationMode.PROVIDER
