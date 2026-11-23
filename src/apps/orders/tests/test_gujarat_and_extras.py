"""Gujarat's Roznamas in Pending orders, read-only fields and the number formatter."""

import pytest
from django.test import override_settings
from rest_framework.test import APIClient

from apps.api.errors import BusinessError
from apps.core.models import Configuration
from apps.orders.enums import OrderRole
from apps.orders.models import Order
from apps.orders.services import drafting, items, lifecycle, next_hearing, numbering, signing

from .factories import code, make_user

pytestmark = pytest.mark.django_db


def gujarat():
    Configuration.objects.update_or_create(
        config_set="tenant", config_key="state_code", defaults={"config_value": "GJ"}
    )


def triggered(case, staff, signer, type_code):
    order = drafting.create_outside_hearing(case_id=case.pk, actor=staff, order_type_code=type_code)
    drafting.edit_text(order.pk, "<p>x</p>", actor=staff)
    next_hearing.set_next_hearing(order.pk, state="NOT_LISTED_AGAIN", actor=staff)
    lifecycle.mark_complete(order.pk, actor=staff)
    lifecycle.send_for_signing(order.pk, actor=staff)
    signing.record_signed_file(order.pk, "signed", "DSC", actor=signer)
    return Order.objects.get(pk=order.pk)


def test_a_roznama_is_listed_under_awaiting_signature_from_triggering_until_signed(
    case, courtroom, staff, signer
):
    gujarat()
    normal = triggered(case, staff, signer, "NORMAL")
    roznama_type = triggered(case, staff, signer, "ROZNAMA")
    client = APIClient()
    client.force_authenticate(signer)
    body = client.get(
        "/api/v1/orders/pending/", {"court": str(courtroom.pk), "tab": "awaiting_signature"}
    ).json()
    (row,) = body["results"]
    # The Roznama-type order is signed once, as an order; only the normal order's Roznama waits.
    assert row["id"] == str(normal.pk)
    assert row["kind"] == "ROZNAMA" and row["my_action"] == "sign_roznama"
    assert row["stages"] == ["TRIGGERED", "AWAITING_SIGNATURE"]
    assert row["type"] == {"code": "NORMAL", "label": "Normal"}  # Gujarat has two types
    assert body["counts"]["triggered"] == 2
    assert roznama_type


def test_a_state_with_one_type_shows_no_type_on_its_rows(case, courtroom, drafter):
    drafting.create_outside_hearing(case_id=case.pk, actor=drafter)
    client = APIClient()
    client.force_authenticate(drafter)
    rows = client.get("/api/v1/orders/pending/", {"court": str(courtroom.pk)}).json()["results"]
    assert rows[0]["type"] is None


def test_a_person_cannot_type_into_a_read_only_field(order, filler):
    with pytest.raises(Exception) as excinfo:
        items.add(
            order.pk,
            "ACCEPT_APPLICATION",
            actor=filler,
            target_id=order.pk,
            values={"application_number": "A/1"},
        )
    assert "values.application_number" in excinfo.value.detail
    item = items.add(order.pk, "REJECT_APPLICATION", actor=filler, target_id=order.pk)
    with pytest.raises(Exception) as excinfo:
        items.update(order.pk, item.pk, {"application_number": "A/2"}, actor=filler)
    assert "values.application_number" in excinfo.value.detail
    assert BusinessError and code


def test_a_read_only_value_the_system_filled_survives_an_edit(case, drafter, setter, filler):
    from apps.hearings.tests.factories import schedule

    from .factories import TODAY

    schedule(case, TODAY.replace(day=19), "EVIDENCE_OF_COMPLAINANT")
    order = drafting.create_outside_hearing(case_id=case.pk, actor=drafter)
    next_hearing.set_next_hearing(
        order.pk, state="LISTED", date=TODAY.replace(day=26), purpose="ARGUMENTS", actor=setter
    )
    item = order.items.get()
    assert item.values["original_hearing_date"] == TODAY.replace(day=19).isoformat()
    items.update(order.pk, item.pk, {**item.values, "hearing_purpose": "ADR"}, actor=filler)
    item.refresh_from_db()
    assert item.values["original_hearing_date"] == TODAY.replace(day=19).isoformat()


def format_number(*, court_code, series, seq, year, state):
    return f"{state}-{series[0]}-{seq:05d}-{year}"


@override_settings(
    ORDERS_NUMBER_FORMATTER="apps.orders.tests.test_gujarat_and_extras.format_number"
)
def test_the_number_format_is_pluggable(order):
    assert numbering.allot(order, "ORDER") == "KL-O-00001-2026"
    assert numbering.allot(order, "ORDER") == "KL-O-00002-2026"
    assert numbering.allot(order, "ROZNAMA") == "KL-R-00001-2026"


def test_the_default_format_names_the_courtroom_series_number_and_year(order):
    assert numbering.allot(order, "ROZNAMA") == f"{order.court.code}/RZN/1/2026"
    assert OrderRole and make_user
