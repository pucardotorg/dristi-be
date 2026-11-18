"""The drop-down options seeded into public configuration match their enums (issue #247).

The frontend builds its drop-downs from these rows, while the backend validates
the submitted codes against the enums. A drift between the two would offer
options the backend rejects, so every seeded list must equal its enum: the
same codes, labels and order.
"""

import json
import tomllib
from io import StringIO

import pytest
from django.conf import settings
from django.core.management import call_command
from django.urls import reverse
from rest_framework.test import APIClient

from apps.cases.services.case_types import (
    ModeOfService,
    NatureOfDebt,
    NonDeliveryReason,
    PaymentStatus,
    ReturnReason,
)
from apps.core import services
from apps.parties.models import EntityType

SEED_FILE = settings.BASE_DIR.parent / "data" / "seed" / "core" / "public_configurations.toml"

DROP_DOWNS = {
    ("efiling", "entity_type_drop_down"): EntityType,
    ("efiling_cheque_bounce", "return_reason_drop_down"): ReturnReason,
    ("efiling_cheque_bounce", "nature_of_debt_drop_down"): NatureOfDebt,
    ("efiling_cheque_bounce", "mode_of_service_drop_down"): ModeOfService,
    ("efiling_cheque_bounce", "non_delivery_reason_drop_down"): NonDeliveryReason,
    ("efiling_cheque_bounce", "payment_status_drop_down"): PaymentStatus,
}


def seed_rows():
    with SEED_FILE.open("rb") as file:
        return tomllib.load(file)["rows"]


def seeded_rows():
    return {(row["config_set"], row["config_key"]): row for row in seed_rows()}


def test_every_drop_down_is_seeded_once():
    pairs = [(row["config_set"], row["config_key"]) for row in seed_rows()]

    assert sorted(pairs) == sorted(DROP_DOWNS)


@pytest.mark.parametrize(
    ("pair", "choices"), DROP_DOWNS.items(), ids=[key for _, key in DROP_DOWNS]
)
def test_seeded_options_match_the_enum(pair, choices):
    row = seeded_rows()[pair]

    assert row["value_type"] == "json"
    assert list(json.loads(row["config_value"]).items()) == list(choices.choices)


@pytest.mark.django_db
def test_seed_loads_and_serves_the_options():
    call_command("seed", str(SEED_FILE), "--strict", stdout=StringIO())

    for (config_set, config_key), choices in DROP_DOWNS.items():
        assert services.get_public_json(config_set, config_key) == dict(choices.choices)

    url = reverse("public-configuration-by-set", kwargs={"config_set": "efiling_cheque_bounce"})
    response = APIClient().get(url)

    assert response.status_code == 200
    keys = {entry["config_key"] for entry in response.json()["results"]}
    assert keys == {key for set_, key in DROP_DOWNS if set_ == "efiling_cheque_bounce"}
