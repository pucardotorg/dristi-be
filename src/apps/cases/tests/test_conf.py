"""The natively digital e-filing switch (public configuration ``ui_efiling``)."""

from io import StringIO

import pytest
from django.conf import settings
from django.core.management import call_command
from django.urls import reverse
from rest_framework.test import APIClient

from apps.cases import conf
from apps.core.models import PublicConfiguration

CORE_PUBLIC_SEED = (
    settings.BASE_DIR.parent / "data" / "seed" / "core" / "public_configurations.toml"
)


def make(config_value, **kwargs):
    return PublicConfiguration.objects.create(
        config_set=conf.EFILING_UI_CONFIG_SET,
        config_key=conf.NATIVELY_DIGITAL_KEY,
        config_value=config_value,
        value_type=PublicConfiguration.ValueType.BOOLEAN,
        **kwargs,
    )


@pytest.mark.django_db
class TestNativelyDigitalOn:
    def test_missing_row_is_off(self):
        assert conf.natively_digital_on() is False

    def test_true_row_is_on(self):
        make("true")
        assert conf.natively_digital_on() is True

    def test_false_row_is_off(self):
        make("false")
        assert conf.natively_digital_on() is False

    def test_inactive_row_is_off(self):
        make("true", is_active=False)
        assert conf.natively_digital_on() is False

    def test_admin_edit_applies_to_next_read(self):
        row = make("true")
        assert conf.natively_digital_on() is True
        row.config_value = "false"
        row.save()
        assert conf.natively_digital_on() is False

    def test_upper_case_names_from_ticket_match(self):
        PublicConfiguration.objects.create(
            config_set="UI_EFILING",
            config_key="NATIVELY_DIGITAL_DOCUMENT_SUBMISSION_ON",
            config_value="true",
            value_type=PublicConfiguration.ValueType.BOOLEAN,
        )
        assert conf.natively_digital_on() is True


@pytest.mark.django_db
class TestCoreSeed:
    def seed(self):
        call_command("seed", str(CORE_PUBLIC_SEED), stdout=StringIO())

    def test_seed_turns_it_on(self):
        self.seed()
        row = PublicConfiguration.objects.get(
            config_set="ui_efiling", config_key="natively_digital_document_submission_on"
        )
        assert row.value_type == PublicConfiguration.ValueType.BOOLEAN
        assert row.is_active
        assert conf.natively_digital_on() is True

    def test_reseed_keeps_a_state_override(self):
        self.seed()
        PublicConfiguration.objects.filter(config_set="ui_efiling").update(config_value="false")
        self.seed()
        assert conf.natively_digital_on() is False

    def test_served_by_public_api(self):
        self.seed()
        client = APIClient()
        response = client.get(
            reverse(
                "public-configuration-by-key",
                kwargs={
                    "config_set": "ui_efiling",
                    "config_key": "natively_digital_document_submission_on",
                },
            )
        )
        assert response.status_code == 200
        assert response.json()["config_value"] == "true"
        assert response.json()["value_type"] == "boolean"
