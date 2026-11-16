"""Initiation, instructions, options and callback (spec 0032 #5, #7, #17.1 INI-01 – INI-17)."""

import socket
from datetime import timedelta
from unittest import mock

import pytest

from addon.offline_payment import constants
from addon.offline_payment.provider import OfflinePaymentProvider
from apps.payments.providers.base import (
    ActionKind,
    ConfirmationMode,
    ProviderCallbackMalformed,
    ProviderPermanentError,
)

from .base import COUNTERS, ISSUED_AT, initiation_request
from .conftest import PAYABLE_TO
from .test_reference import ref

pytestmark = pytest.mark.usefixtures("offline_config")


@pytest.fixture
def provider():
    return OfflinePaymentProvider()


def details(initiation) -> dict:
    return {detail.key: detail.value for detail in initiation.action.details}


def keys(initiation) -> list:
    return [detail.key for detail in initiation.action.details]


def code_of(callable_, *args, **kwargs) -> ProviderPermanentError:
    with pytest.raises(ProviderPermanentError) as caught:
        callable_(*args, **kwargs)
    return caught.value


class TestInitiate:
    def test_ini_01_happy_path(self, provider):
        initiation = provider.initiate(initiation_request(options={"counter": "EKM-CJM"}))
        assert initiation.provider_payment_id == ref()
        assert initiation.action.kind == ActionKind.SHOW_INSTRUCTIONS
        assert initiation.action.url == "" and not initiation.action.form_fields
        assert keys(initiation) == [
            "reference",
            "amount",
            "valid_until",
            "counter",
            "counter_address",
            "counter_hours",
            "methods",
            "payable_to",
            "payments",
            "instructions",
        ]
        shown = details(initiation)
        assert shown["reference"] == ref()
        assert shown["amount"] == "₹ 707.50"
        assert shown["valid_until"] == "18 Nov 2026, 11:59 PM IST"
        assert shown["counter"] == COUNTERS[0]["label"]
        assert shown["counter_address"] == COUNTERS[0]["address"]
        assert shown["methods"] == "Cash, Demand draft, Card / UPI at the counter"
        assert shown["payable_to"] == PAYABLE_TO
        assert shown["payments"] == "PAY-2026-000456"

    def test_ini_02_replay_is_equal(self, provider):
        request = initiation_request(options={"counter": "EKM-CJM"})
        assert provider.initiate(request) == provider.initiate(request)

    def test_ini_03_disabled(self, provider, settings):
        settings.OFFLINE_PAYMENT_ENABLED = False
        error = code_of(provider.initiate, initiation_request(options={"counter": "EKM-CJM"}))
        assert error.code == constants.OFFLINE_DISABLED and error.field is None

    def test_replay_survives_the_kill_switch_cap_and_charge_filter(self, provider, settings):
        from dataclasses import replace

        request = initiation_request(options={"counter": "EKM-CJM"})
        issued = provider.initiate(request)
        settings.OFFLINE_PAYMENT_ENABLED = False
        settings.OFFLINE_PAYMENT_MAX_AMOUNT = "1.00"
        settings.OFFLINE_PAYMENT_ALLOWED_CHARGE_TYPES = ["EPOST_FEE"]
        assert provider.initiate(replace(request, replay=True)) == issued
        assert code_of(provider.initiate, request).code == constants.OFFLINE_DISABLED

    def test_ini_04_currency(self, provider):
        error = code_of(provider.initiate, initiation_request(currency="USD"))
        assert error.code == constants.OFFLINE_UNSUPPORTED_CURRENCY

    @pytest.mark.parametrize("amount", ["700.00", "0", "-707.50"])
    def test_ini_05_inconsistent_amount(self, provider, amount):
        error = code_of(provider.initiate, initiation_request(amount=amount))
        assert error.code == constants.OFFLINE_AMOUNT_INCONSISTENT

    def test_ini_06_max_amount(self, provider, settings):
        settings.OFFLINE_PAYMENT_MAX_AMOUNT = "707.50"
        options = {"counter": "EKM-CJM"}
        assert provider.initiate(initiation_request(options=options))
        error = code_of(
            provider.initiate, initiation_request(amounts=("700.01", "7.50"), options=options)
        )
        assert error.code == constants.OFFLINE_AMOUNT_TOO_LARGE

    def test_ini_07_allowed_charge_types(self, provider, settings):
        options = {"counter": "EKM-CJM"}
        mixed = initiation_request(charge_types=["COURT_FEE", "EPOST_FEE"], options=options)
        assert provider.initiate(mixed)  # an empty list allows all

        settings.OFFLINE_PAYMENT_ALLOWED_CHARGE_TYPES = ["COURT_FEE"]
        error = code_of(provider.initiate, mixed)
        assert error.code == constants.OFFLINE_CHARGE_NOT_ALLOWED
        assert provider.initiate(
            initiation_request(charge_types=["COURT_FEE", "COURT_FEE"], options=options)
        )

    def test_ini_08_unknown_counter(self, provider):
        error = code_of(provider.initiate, initiation_request(options={"counter": "NOPE"}))
        assert (error.code, error.field) == (constants.OFFLINE_INVALID_COUNTER, "counter")

    def test_ini_09_counter_default_or_required(self, provider, settings):
        error = code_of(provider.initiate, initiation_request())
        assert (error.code, error.field) == (constants.OFFLINE_COUNTER_REQUIRED, "counter")

        settings.OFFLINE_PAYMENT_DEFAULT_COUNTER = "EKM-MC"
        initiation = provider.initiate(initiation_request())
        assert details(initiation)["counter"] == COUNTERS[1]["label"]
        assert initiation.metadata["counter"] == "EKM-MC"
        # Empty address / hours are omitted.
        assert "counter_address" not in keys(initiation)
        assert "counter_hours" not in keys(initiation)

    def test_a_single_counter_needs_no_choice(self, provider, settings):
        settings.OFFLINE_PAYMENT_COUNTERS = COUNTERS[:1]
        assert details(provider.initiate(initiation_request()))["counter"] == COUNTERS[0]["label"]

    def test_ini_10_no_counters_configured(self, provider, settings):
        settings.OFFLINE_PAYMENT_COUNTERS = []
        initiation = provider.initiate(initiation_request())
        assert "counter" not in keys(initiation)
        assert initiation.metadata["counter"] == ""
        error = code_of(provider.initiate, initiation_request(options={"counter": "EKM-CJM"}))
        assert error.code == constants.OFFLINE_INVALID_COUNTER

    def test_ini_11_no_payable_to_without_demand_drafts(self, provider, settings):
        settings.OFFLINE_PAYMENT_METHODS = ["CASH"]
        initiation = provider.initiate(initiation_request(options={"counter": "EKM-CJM"}))
        assert "payable_to" not in keys(initiation)
        assert details(initiation)["methods"] == "Cash"

    def test_ini_12_amount_is_never_rounded(self, provider):
        initiation = provider.initiate(
            initiation_request(amounts=("707.5",), options={"counter": "EKM-CJM"})
        )
        assert details(initiation)["amount"] == "₹ 707.50"

    def test_ini_13_batch(self, provider):
        numbers = ("PAY-2026-000456", "PAY-2026-000457", "PAY-2026-000458")
        initiation = provider.initiate(
            initiation_request(payment_numbers=numbers, options={"counter": "EKM-CJM"})
        )
        assert details(initiation)["payments"] == ", ".join(numbers)

    def test_ini_14_metadata_is_not_personal(self, provider):
        initiation = provider.initiate(initiation_request(options={"counter": "EKM-CJM"}))
        assert set(initiation.metadata) == {"valid_until", "counter"}
        assert initiation.metadata["valid_until"].startswith("2026-11-18T23:59:59.999999")
        assert "Anjali" not in str(initiation)
        assert "3210" not in str(initiation)

    def test_ini_16_no_io(self, provider):
        def refuse(*args, **kwargs):
            raise AssertionError("network access")

        with (
            mock.patch.object(socket, "socket", refuse),
            mock.patch.object(socket, "create_connection", refuse),
        ):
            provider.initiate(initiation_request(options={"counter": "EKM-CJM"}))

    def test_date_comes_from_initiated_at_not_now(self, provider):
        later = initiation_request(
            initiated_at=ISSUED_AT + timedelta(days=1), options={"counter": "EKM-CJM"}
        )
        assert provider.initiate(later).provider_payment_id.split("-")[1] == "261112"

    def test_issued_event_is_logged(self, provider, caplog):
        caplog.set_level("INFO", logger="addon.offline_payment")
        provider.initiate(initiation_request(options={"counter": "EKM-CJM"}))
        assert "event=OFFLINE_REQUEST_ISSUED" in caplog.text
        assert "Anjali" not in caplog.text


class TestSurface:
    def test_identity(self, provider, settings):
        assert provider.name == "offline"
        assert provider.confirmation == ConfirmationMode.ATTESTED
        assert provider.label == "Pay at the court counter"
        settings.OFFLINE_PAYMENT_LABEL = "Pay at the counter"
        assert provider.label == "Pay at the counter"

    def test_timing(self, provider):
        assert provider.pending_horizon == timedelta(days=7, hours=24) + timedelta(days=1)
        assert provider.not_found_grace == provider.pending_horizon

    def test_ini_15_there_is_no_callback(self, provider):
        for payload in ({}, {"provider_payment_id": ref(), "status": "Success"}, {"x": "y"}):
            with pytest.raises(ProviderCallbackMalformed) as caught:
                provider.parse_callback(payload)
            assert caught.value.code == constants.OFFLINE_NO_CALLBACK

    def test_ini_17_options(self, provider, settings):
        options = provider.list_options()
        assert [o.code for o in options] == ["EKM-CJM", "EKM-MC"]
        assert {o.group for o in options} == {"COUNTER"}
        settings.OFFLINE_PAYMENT_COUNTERS = COUNTERS[:1]
        assert len(provider.list_options()) == 1
        settings.OFFLINE_PAYMENT_COUNTERS = []
        assert provider.list_options() == []

    def test_normalise_reference(self, provider):
        canonical = ref()
        assert provider.normalise_reference(canonical.lower().replace("-", "")) == canonical
        with pytest.raises(ProviderPermanentError) as caught:
            provider.normalise_reference(canonical[:-1] + "0")
        assert caught.value.code == constants.OFFLINE_REFERENCE_MALFORMED

    def test_attestation_methods_follow_the_settings(self, provider, settings):
        assert [m.code for m in provider.attestation_methods()] == ["CASH", "DEMAND_DRAFT", "POS"]
        settings.OFFLINE_PAYMENT_METHODS = ["POS", "CASH"]
        assert [m.code for m in provider.attestation_methods()] == ["POS", "CASH"]
