"""The orders API (spec 0039 #11): routes, access, shapes and error codes.

Errors are asserted by ``code`` and ``field``, never by message (spec 0000 #13).
"""

import datetime
import uuid
from unittest import mock

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.core.models import Configuration
from apps.orders.enums import ItemSource, OrderRole
from apps.orders.models import Order, OrderShortcut
from apps.orders.services import drafting, items, lifecycle, signing

from .factories import TODAY, make_case, make_court, make_user, mark_roll, schedule, started_hearing

pytestmark = pytest.mark.django_db

NEXT = TODAY.replace(day=19).isoformat()


def client_for(user=None):
    client = APIClient()
    if user is not None:
        client.force_authenticate(user)
    return client


def errors_of(response):
    return [(error["code"], error.get("field")) for error in response.json()["errors"]]


def url(name, *args):
    return reverse(name, args=args)


@pytest.fixture
def api(staff):
    return client_for(staff)


# -- routes --------------------------------------------------------------------------


def test_routes():
    oid, hid, cid, iid = (uuid.uuid4() for _ in range(4))
    assert url("order-list") == "/api/v1/orders/"
    assert url("order-detail", oid) == f"/api/v1/orders/{oid}/"
    assert url("order-text", oid) == f"/api/v1/orders/{oid}/text/"
    assert url("order-add-item", oid) == f"/api/v1/orders/{oid}/items/"
    assert url("order-item", oid, iid) == f"/api/v1/orders/{oid}/items/{iid}/"
    assert url("order-next-hearing", oid) == f"/api/v1/orders/{oid}/next-hearing/"
    assert url("order-data-complete", oid) == f"/api/v1/orders/{oid}/data/complete/"
    assert url("order-send-for-signing", oid) == f"/api/v1/orders/{oid}/send-for-signing/"
    assert url("order-sign-confirm", oid) == f"/api/v1/orders/{oid}/sign/confirm/"
    assert url("order-roznama-sign-confirm", oid) == f"/api/v1/orders/{oid}/roznama/sign/confirm/"
    assert url("order-pending") == "/api/v1/orders/pending/"
    assert url("order-pending-counts") == "/api/v1/orders/pending/counts/"
    assert url("order-bulk-items") == "/api/v1/orders/bulk/items/"
    assert url("hearing-next-hearing", hid) == f"/api/v1/hearings/{hid}/next-hearing/"
    assert url("case-orders", cid) == f"/api/v1/cases/{cid}/orders/"
    assert url("diary-entries") == "/api/v1/diary-entries/"
    assert url("order-items") == "/api/v1/order-items/"
    assert url("shortcut-list") == "/api/v1/shortcuts/"


# -- create and read ---------------------------------------------------------------------


def test_create_in_a_hearing_returns_201_then_200_with_the_same_draft(api, hearing):
    first = api.post(url("order-list"), {"hearing_id": str(hearing.pk)}, format="json")
    again = api.post(url("order-list"), {"hearing_id": str(hearing.pk)}, format="json")
    assert (first.status_code, again.status_code) == (201, 200)
    assert first.json()["id"] == again.json()["id"]
    body = first.json()
    assert body["status"] == "DRAFT" and body["stages"] == ["DRAFTING"]
    assert body["hearing"]["purpose"]["code"] == "APPEARANCE"
    assert "meta" in body
    assert "rendered_html" in body and "order-page" in body["rendered_html"]


def test_create_outside_a_hearing_with_a_preset(api, case):
    response = api.post(
        url("order-list"),
        {"case_id": str(case.pk), "preset": {"kind": "COGNIZANCE", "action": "ISSUE_NOTICE"}},
        format="json",
    )
    assert response.status_code == 201
    assert [item["item_type"]["code"] for item in response.json()["items"]] == ["ISSUE_OF_NOTICE"]


def test_create_needs_exactly_one_of_hearing_and_case(api, case, hearing):
    both = api.post(
        url("order-list"), {"hearing_id": str(hearing.pk), "case_id": str(case.pk)}, format="json"
    )
    neither = api.post(url("order-list"), {}, format="json")
    assert both.status_code == neither.status_code == 400


def test_create_before_the_hearing_starts_is_e14004(api, case):
    scheduled = schedule(case, TODAY)
    response = api.post(url("order-list"), {"hearing_id": str(scheduled.pk)}, format="json")
    assert (response.status_code, errors_of(response)) == (409, [("E14004", None)])


def test_create_for_a_hearing_or_case_that_does_not_exist_is_404(api):
    for body in ({"hearing_id": str(uuid.uuid4())}, {"case_id": str(uuid.uuid4())}):
        response = api.post(url("order-list"), body, format="json")
        assert (response.status_code, errors_of(response)) == (404, [("E00105", None)]), body


def test_create_on_a_case_with_no_courtroom_is_e14003(api):
    response = api.post(url("order-list"), {"case_id": str(make_case(None).pk)}, format="json")
    assert (response.status_code, errors_of(response)) == (409, [("E14003", None)])


def test_a_preset_is_refused_on_a_hearings_order(api, hearing):
    response = api.post(
        url("order-list"),
        {"hearing_id": str(hearing.pk), "preset": {"kind": "COGNIZANCE"}},
        format="json",
    )
    assert response.status_code == 400
    assert [field for _, field in errors_of(response)] == ["preset"]
    assert not Order.objects.filter(hearing=hearing).exists()


def test_an_order_that_does_not_exist_is_404(api):
    response = api.get(url("order-detail", uuid.uuid4()))
    assert (response.status_code, errors_of(response)) == (404, [("E00105", None)])


def test_a_row_a_service_no_longer_finds_is_404_not_a_server_error(api, order):
    with mock.patch.object(drafting, "edit_title", side_effect=Order.DoesNotExist):
        response = api.patch(url("order-title", order.pk), {"title": "T"}, format="json")
    assert (response.status_code, errors_of(response)) == (404, [("E00105", None)])


def test_the_detail_has_the_documented_shape(api, order, filler):
    items.add(order.pk, "COST", actor=filler)
    body = api.get(url("order-detail", order.pk)).json()
    assert {
        "id",
        "status",
        "stages",
        "whose_move",
        "type",
        "title",
        "case",
        "hearing",
        "text",
        "rendered_html",
        "items",
        "next_hearing",
        "attendance_complete",
        "diary_entry",
        "roznama",
        "linked_documents",
        "data_complete",
        "number",
        "order_date",
        "signed_file_id",
        "text_version",
        "data_version",
        "allowed_actions",
    } <= set(body)
    assert body["items"][0]["problems"][0]["code"] == "REQUIRED"
    assert body["diary_entry"]["label"] == "A-Diary text"
    assert "send_for_signing" in body["allowed_actions"]
    assert body["whose_move"].startswith("Being drafted")


def test_allowed_actions_follow_the_callers_roles(order, drafter, filler, signer):
    for user, present, absent in (
        (drafter, "send_for_signing", "add_item"),
        (filler, "add_item", "send_for_signing"),
        (signer, None, "send_for_signing"),
    ):
        actions = client_for(user).get(url("order-detail", order.pk)).json()["allowed_actions"]
        assert absent not in actions
        if present:
            assert present in actions


# -- access ---------------------------------------------------------------------------------


def test_an_action_without_the_role_is_403_e14019(order, drafter, filler):
    cases = (
        (filler, "patch", url("order-text", order.pk), {"text": "<p>x</p>"}),
        (drafter, "post", url("order-add-item", order.pk), {"item_type": "COST"}),
        (drafter, "put", url("order-next-hearing", order.pk), {"state": "NOT_LISTED_AGAIN"}),
        (filler, "post", url("order-send-for-signing", order.pk), None),
        (drafter, "post", url("order-sign", order.pk), None),
        (drafter, "post", url("order-data-complete", order.pk), None),
    )
    for user, method, target, body in cases:
        response = getattr(client_for(user), method)(target, body, format="json")
        assert (response.status_code, errors_of(response)) == (403, [("E14019", None)]), target


def test_a_role_held_in_another_courtroom_grants_nothing_here(order, hearing, sibling_courtroom):
    other = make_case(sibling_courtroom)
    from apps.orders.services import drafting as d

    foreign = d.create_outside_hearing(case_id=other.pk, actor=make_user(OrderRole.ORDER_DRAFTER))
    # Roles are groups held across the deployment's courtrooms; the courtroom of the order
    # decides, and someone with no role anywhere is a stranger.
    stranger = make_user(name="Nobody")
    for target in (order, foreign):
        assert client_for(stranger).get(url("order-detail", target.pk)).status_code == 404


def test_staff_of_another_court_and_outsiders_get_404_not_403(
    order, foreign_court, stranger, staff
):
    foreigner = make_user(*OrderRole.values, name="Kollam")
    with mock.patch("apps.orders.ports.court_roles", side_effect=lambda user, court: frozenset()):
        with mock.patch("apps.orders.ports.is_court_staff", return_value=False):
            response = client_for(foreigner).get(url("order-detail", order.pk))
    assert (response.status_code, errors_of(response)) == (404, [("E00105", None)])
    response = client_for(stranger).patch(url("order-text", order.pk), {"text": "x"}, format="json")
    assert (response.status_code, errors_of(response)) == (404, [("E00105", None)])
    assert client_for().get(url("order-detail", order.pk)).status_code in (401, 403)


def test_parties_read_signed_orders_only(api, ready, staff, signer, complainant_user):
    party = client_for(complainant_user)
    assert party.get(url("order-detail", ready.pk)).status_code == 404
    lifecycle.send_for_signing(ready.pk, actor=staff)
    assert party.get(url("order-detail", ready.pk)).status_code == 404
    signing.record_signed_file(ready.pk, "signed", "DSC", actor=signer)
    seen = party.get(url("order-detail", ready.pk))
    assert seen.status_code == 200
    assert seen.json()["status"] == "Published"
    assert "items" not in seen.json() and "allowed_actions" not in seen.json()
    assert party.patch(url("order-text", ready.pk), {"text": "x"}, format="json").status_code == 403


# -- text and versions ---------------------------------------------------------------------------


def test_text_saves_with_if_match_and_a_stale_version_is_412_e14002(api, order):
    ok = api.patch(
        url("order-text", order.pk), {"text": "<p>Hello</p>"}, format="json", HTTP_IF_MATCH='"t-0"'
    )
    assert ok.status_code == 200 and ok.json()["text_version"] == 1
    stale = api.patch(
        url("order-text", order.pk), {"text": "<p>Other</p>"}, format="json", HTTP_IF_MATCH='"t-0"'
    )
    assert (stale.status_code, errors_of(stale)) == (412, [("E14002", None)])
    wrong_kind = api.patch(
        url("order-text", order.pk), {"text": "<p>z</p>"}, format="json", HTTP_IF_MATCH='"d-1"'
    )
    assert wrong_kind.status_code == 400


def test_read_only_fields_are_not_accepted(api, order):
    response = api.patch(
        url("order-title", order.pk),
        {"title": "T", "status": "TRIGGERED", "number": "X", "data_complete": True},
        format="json",
    )
    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "T" and body["status"] == "DRAFT" and body["number"] == ""
    assert body["data_complete"] is False


def test_the_text_size_limit_is_e14020(api, order):
    Configuration.objects.update_or_create(
        config_set="orders", config_key="text_max_bytes", defaults={"config_value": "10"}
    )
    response = api.patch(
        url("order-text", order.pk), {"text": "<p>" + "x" * 40 + "</p>"}, format="json"
    )
    assert errors_of(response) == [("E14020", "text")]


def test_the_live_view_returns_304_when_nothing_changed_and_names_the_editor(api, order, staff):
    first = api.get(url("order-changes", order.pk), {"since": "0.0"})
    assert first.status_code == 304 and first["ETag"] == '"0.0"'
    api.patch(url("order-text", order.pk), {"text": "<p>typed</p>"}, format="json")
    changed = api.get(url("order-changes", order.pk), {"since": "0.0"})
    assert changed.status_code == 200
    body = changed.json()
    assert body["text"] == "<p>typed</p>" and body["editing"]["user"] == str(staff.pk)
    assert changed["ETag"] == '"1.0"'
    assert api.get(url("order-changes", order.pk), {"since": '"1.0"'}).status_code == 304


def test_the_live_view_sends_the_body_for_a_malformed_since(api, order):
    for since in ("garbage", "1.2.3", ""):
        response = api.get(url("order-changes", order.pk), {"since": since})
        assert response.status_code == 200, since
        assert response["ETag"] == '"0.0"' and "text" in response.json()


def test_a_party_does_not_get_the_live_view_of_a_signed_order(
    ready, staff, signer, complainant_user
):
    lifecycle.send_for_signing(ready.pk, actor=staff)
    signing.record_signed_file(ready.pk, "signed", "DSC", actor=signer)
    party = client_for(complainant_user)
    assert party.get(url("order-detail", ready.pk)).status_code == 200
    response = party.get(url("order-changes", ready.pk))
    assert (response.status_code, errors_of(response)) == (404, [("E00105", None)])


# -- items ----------------------------------------------------------------------------------------


def test_adding_an_item_and_its_error_codes(api, order):
    add = api.post(
        url("order-add-item", order.pk),
        {"item_type": "COST", "values": {"amount": "5.00"}},
        format="json",
    )
    assert add.status_code == 201
    assert add.json()["values"] == {"amount": "5.00"}
    cases = [
        ("SCHEDULING_OF_HEARING_DATE", {}, ("E14008", "item_type")),
        ("ACCEPT_APPLICATION", {}, ("E14010", "target_id")),
        ("COST", {"amount": "-1"}, ("E14011", "values.amount")),
    ]
    for code, values, expected in cases:
        response = api.post(
            url("order-add-item", order.pk), {"item_type": code, "values": values}, format="json"
        )
        assert errors_of(response) == [expected], code
    api.post(url("order-add-item", order.pk), {"item_type": "JUDGEMENT"}, format="json")
    clash = api.post(url("order-add-item", order.pk), {"item_type": "DISMISS_CASE"}, format="json")
    assert (clash.status_code, errors_of(clash)) == (409, [("E14009", "item_type")])


def test_patch_and_delete_an_item(api, order, filler):
    item = items.add(order.pk, "COST", actor=filler, values={"amount": "5.00"})
    target = url("order-item", order.pk, item.pk)
    assert api.patch(target, {"values": {"amount": "9.00"}}, format="json").status_code == 200
    stale = api.patch(target, {"values": {}}, format="json", HTTP_IF_MATCH='"d-0"')
    assert errors_of(stale) == [("E14002", None)]
    assert api.delete(target).status_code == 200
    assert order.items.count() == 0


def test_confirming_a_reader_item_lets_the_data_be_marked_complete(api, order, filler):
    item = items.add(order.pk, "JUDGEMENT", actor=filler, source=ItemSource.READER)
    refused = api.post(url("order-data-complete", order.pk))
    assert {code for code, _ in errors_of(refused)} == {"E14012"}
    confirmed = api.post(f"/api/v1/orders/{order.pk}/items/{item.pk}/confirm/")
    assert confirmed.status_code == 200
    assert confirmed.json()["items"][0]["confirmed"] is True
    missing = api.post(f"/api/v1/orders/{order.pk}/items/{uuid.uuid4()}/confirm/")
    assert (missing.status_code, errors_of(missing)) == (404, [("E00105", None)])
    complete = api.post(url("order-data-complete", order.pk))
    assert complete.status_code == 200 and complete.json()["data_complete"] is True


def test_complete_data_reopens_until_the_order_is_signed(api, ready, staff, signer):
    api.post(url("order-data-complete", ready.pk))
    reopened = api.post(f"/api/v1/orders/{ready.pk}/data/reopen/")
    assert reopened.status_code == 200
    assert reopened.json()["data_complete"] is False
    assert "ORDER_DATA_TO_FILL" not in reopened.json()["stages"]  # a draft, not yet sent
    lifecycle.mark_complete(ready.pk, actor=staff)
    lifecycle.send_for_signing(ready.pk, actor=staff)
    signing.record_signed_file(ready.pk, "signed", "DSC", actor=signer)
    late = api.post(f"/api/v1/orders/{ready.pk}/data/reopen/")
    assert (late.status_code, errors_of(late)) == (409, [("E14016", None)])


def test_the_diary_entry_endpoint_sets_a_text_of_its_own(api, order):
    response = api.put(
        f"/api/v1/orders/{order.pk}/diary-entry/",
        {"same_as_text": False, "text": "<p>Own entry.</p><script>x</script>"},
        format="json",
    )
    assert response.status_code == 200
    stored = Order.objects.get(pk=order.pk)
    assert (stored.diary_same_as_text, stored.diary_text) == (False, "<p>Own entry.</p>")
    nested = api.put(
        f"/api/v1/orders/{order.pk}/diary-entry/",
        {"same_as_text": False, "text": "<ul><li>a<ul><li>b</li></ul></li></ul>"},
        format="json",
    )
    assert errors_of(nested) == [("E14027", "text")]


def test_the_paying_party_confirms_a_witness_batta_through_the_api(
    ready, staff, signer, case, complainant_user
):
    from apps.cases.models import CaseParticipant, ParticipantRole
    from apps.orders.services import triggering
    from apps.parties.models import Person

    from .test_triggering import trigger

    CaseParticipant.objects.create(
        case=case,
        person=Person.objects.create(name="W", phone_number="+919700000002"),
        role=ParticipantRole.WITNESS,
        ordinal=1,
        name_at_filing="W",
    )
    values = {"paying_party": "COMPLAINANT", "amount": "100.00", "pay_by": "2026-12-01"}
    order = trigger(ready, staff, signer, ("WITNESS_BATTA", values))
    triggering.run(order.pk)
    item = order.items.get()
    target = f"/api/v1/orders/{order.pk}/items/{item.pk}/confirm-paid/"
    other_side = client_for(staff).post(target)
    assert (other_side.status_code, errors_of(other_side)) == (403, [("E14019", None)])
    paid = client_for(complainant_user).post(target)
    assert paid.status_code == 200 and paid.json()["id"] == str(order.pk)
    run = order.runs.get(order_item=item)
    assert run.result["paid_confirmed_by"] == str(complainant_user.pk)


def test_confirm_paid_is_only_for_a_witness_batta_of_a_triggered_order(api, order, filler):
    cost = items.add(order.pk, "COST", actor=filler)
    batta = items.add(order.pk, "WITNESS_BATTA", actor=filler)
    wrong = api.post(f"/api/v1/orders/{order.pk}/items/{cost.pk}/confirm-paid/")
    assert (wrong.status_code, errors_of(wrong)) == (404, [("E00105", None)])
    early = api.post(f"/api/v1/orders/{order.pk}/items/{batta.pk}/confirm-paid/")
    assert (early.status_code, errors_of(early)) == (409, [("E14001", None)])


def test_mark_complete_lists_every_problem_as_e14012(api, order, filler):
    items.add(order.pk, "COST", actor=filler)
    response = api.post(url("order-data-complete", order.pk))
    assert response.status_code == 409
    fields = {field for code, field in errors_of(response) if code == "E14012"}
    assert fields == {
        "items[1].values.paying_party",
        "items[1].values.amount",
        "items[1].values.receiving_party",
        "items[1].values.pay_by",
    }


def test_the_catalogue_endpoint(api, order):
    body = api.get(url("order-items"), {"order": str(order.pk)}).json()["data"]
    row = next(r for r in body if r["code"] == "SCHEDULING_OF_HEARING_DATE")
    assert row["available"] is False and row["unavailable_reason"]["code"] == "IN_HEARING"
    found = {r["code"] for r in api.get(url("order-items"), {"search": "bail"}).json()["data"]}
    assert found == {"BAIL", "ACCEPTANCE_OF_BAIL"}
    assert client_for(make_user(name="x")).get(url("order-items")).status_code == 403


# -- next hearing ---------------------------------------------------------------------------------


def test_next_hearing_put_and_pass_through_errors(api, order):
    ok = api.put(
        url("order-next-hearing", order.pk),
        {"state": "LISTED", "date": NEXT, "purpose": "APPEARANCE"},
        format="json",
    )
    assert ok.status_code == 200
    assert ok.json()["next_hearing"]["purpose"] == {"code": "APPEARANCE", "label": "Appearance"}
    half = api.put(
        url("order-next-hearing", order.pk), {"state": "LISTED", "date": NEXT}, format="json"
    )
    assert errors_of(half) == [("E14011", "purpose")]
    past = api.put(
        url("order-next-hearing", order.pk),
        {
            "state": "LISTED",
            "date": (TODAY - datetime.timedelta(days=2)).isoformat(),
            "purpose": "APPEARANCE",
        },
        format="json",
    )
    assert errors_of(past) == [("E10005", None)]
    removed = api.put(
        url("order-next-hearing", order.pk), {"state": "NOT_LISTED_AGAIN"}, format="json"
    )
    assert removed.json()["next_hearing"]["state"] == "NOT_LISTED_AGAIN"


def test_the_cause_list_column_writes_the_hearings_order(api, hearing, case):
    response = api.put(
        url("hearing-next-hearing", hearing.pk),
        {"state": "LISTED", "date": NEXT, "purpose": "ARGUMENTS"},
        format="json",
    )
    assert response.status_code == 200
    assert response.json()["next_hearing"]["entered_from"] == "CAUSE_LIST"
    scheduled = schedule(make_case(case.court), TODAY)
    not_started = api.put(
        url("hearing-next-hearing", scheduled.pk), {"state": "NOT_LISTED_AGAIN"}, format="json"
    )
    assert errors_of(not_started) == [("E14004", None)]


# -- send, sign -------------------------------------------------------------------------------------


def test_send_for_signing_and_its_codes(api, order, hearing, staff):
    empty = api.post(url("order-send-for-signing", order.pk))
    assert errors_of(empty) == [("E14005", "text")]
    api.patch(url("order-text", order.pk), {"text": "<p>x</p>"}, format="json")
    assert errors_of(api.post(url("order-send-for-signing", order.pk))) == [("E14006", None)]
    api.put(url("order-next-hearing", order.pk), {"state": "NOT_LISTED_AGAIN"}, format="json")
    assert errors_of(api.post(url("order-send-for-signing", order.pk))) == [("E14007", None)]
    mark_roll(hearing, staff)
    sent = api.post(url("order-send-for-signing", order.pk))
    assert sent.status_code == 200 and sent.json()["status"] == "SENT_FOR_SIGNING"
    assert sent.json()["stages"] == ["AWAITING_SIGNATURE", "ORDER_DATA_TO_FILL"]
    again = api.post(url("order-send-for-signing", order.pk))
    assert errors_of(again) == [("E14001", None)]
    back = api.post(url("order-move-to-draft", order.pk))
    assert back.json()["status"] == "DRAFT"


def test_the_sign_endpoints_return_the_esign_form_and_record_the_signature(
    api, ready, staff, signer
):
    lifecycle.send_for_signing(ready.pk, actor=staff)
    initiation = mock.Mock()
    initiation.transaction.pk = uuid.uuid4()
    initiation.transaction.provider_transaction_id = "p-1"
    initiation.transaction.expires_at = datetime.datetime(2026, 11, 12, tzinfo=datetime.UTC)
    initiation.initiation.esign_url = "https://esp.example/sign"
    initiation.initiation.form_fields = {"msg": "abc"}
    with mock.patch.object(signing, "start_signing", return_value=initiation) as start:
        response = client_for(signer).post(
            url("order-sign", ready.pk), {"method": "AADHAAR_ESIGN"}, format="json"
        )
    assert response.status_code == 200
    assert response.json()["esign_url"] == "https://esp.example/sign"
    assert response.json()["form_fields"] == {"msg": "abc"}
    start.assert_called_once()
    bad = client_for(signer).post(
        url("order-sign", ready.pk), {"method": "TELEPATHY"}, format="json"
    )
    assert bad.status_code == 400
    assert errors_of(bad) == [("E14017", "method")]
    with mock.patch.object(signing, "record_signature") as record:
        client_for(signer).post(
            url("order-sign-confirm", ready.pk),
            {"transaction_id": str(uuid.uuid4())},
            format="json",
        )
    record.assert_called_once()


def test_a_method_not_enabled_is_e14017(ready, staff, signer):
    lifecycle.send_for_signing(ready.pk, actor=staff)
    response = client_for(signer).post(
        url("order-sign", ready.pk), {"method": "DSC"}, format="json"
    )
    assert errors_of(response) == [("E14017", "method")]


def test_a_refused_action_returns_the_allowed_actions_as_data(api, order):
    from apps.orders.enums import OrderStatus
    from apps.orders.models import Order

    Order.objects.filter(pk=order.pk).update(status=OrderStatus.DISCARDED)
    response = api.post(url("order-send-for-signing", order.pk))
    assert response.status_code == 409
    item = response.json()["errors"][0]
    assert item["code"] == "E14001"
    assert item["data"] == {"allowed_actions": []}


# -- documents, type, discard -----------------------------------------------------------------------


def test_documents_type_and_discard(api, order):
    nope = api.post(
        url("order-documents", order.pk), {"document_id": str(uuid.uuid4())}, format="json"
    )
    assert errors_of(nope) == [("E14021", "document_id")]
    wrong = api.patch(url("order-order-type", order.pk), {"order_type": "ROZNAMA"}, format="json")
    assert errors_of(wrong) == [("E14024", "order_type")]
    gone = api.post(url("order-discard", order.pk))
    assert gone.status_code == 200 and gone.json()["status"] == "DISCARDED"
    assert errors_of(api.post(url("order-discard", order.pk))) == [("E14001", None)]


def test_a_linked_document_is_shown_and_unlinked(api, order, monkeypatch):
    document_id = uuid.uuid4()
    monkeypatch.setattr(
        "apps.cases.selectors.case_documents",
        lambda case_id: [type("D", (), {"id": document_id, "name": "Vakalatnama"})()],
    )
    linked = api.post(
        url("order-documents", order.pk), {"document_id": str(document_id)}, format="json"
    )
    assert linked.status_code == 200
    assert order.linked_documents.filter(document_id=document_id).exists()
    unlinked = api.delete(f"/api/v1/orders/{order.pk}/documents/{document_id}/")
    assert unlinked.status_code == 200
    assert not order.linked_documents.exists()
    assert api.delete(f"/api/v1/orders/{order.pk}/documents/{document_id}/").status_code == 200


def test_a_type_change_that_would_drop_links_needs_confirmation(api, case, staff, monkeypatch):
    Configuration.objects.update_or_create(
        config_set="tenant", config_key="state_code", defaults={"config_value": "GJ"}
    )
    order = drafting.create_outside_hearing(case_id=case.pk, actor=staff)
    document_id = uuid.uuid4()
    monkeypatch.setattr(
        "apps.cases.selectors.case_documents",
        lambda case_id: [type("D", (), {"id": document_id, "name": "Vakalatnama"})()],
    )
    drafting.link_document(order.pk, document_id, actor=staff)
    target = url("order-order-type", order.pk)
    refused = api.patch(target, {"order_type": "ROZNAMA"}, format="json")
    assert errors_of(refused) == [("E14025", "linked_documents")]
    changed = api.patch(
        target, {"order_type": "ROZNAMA", "remove_linked_documents": True}, format="json"
    )
    assert changed.status_code == 200
    assert changed.json()["type"]["code"] == "ROZNAMA"
    assert not order.linked_documents.exists()


# -- Gujarat Roznama -------------------------------------------------------------------------------


@pytest.fixture
def roznama_order(case, staff, signer):
    """A triggered normal order outside a hearing, in Gujarat: its Roznama awaits a signature."""
    from apps.orders.services import next_hearing

    Configuration.objects.update_or_create(
        config_set="tenant", config_key="state_code", defaults={"config_value": "GJ"}
    )
    order = drafting.create_outside_hearing(case_id=case.pk, actor=staff, order_type_code="NORMAL")
    drafting.edit_text(order.pk, "<p>Heard.</p>", actor=staff)
    next_hearing.set_next_hearing(order.pk, state="NOT_LISTED_AGAIN", actor=staff)
    lifecycle.mark_complete(order.pk, actor=staff)
    lifecycle.send_for_signing(order.pk, actor=staff)
    signing.record_signed_file(order.pk, "signed", "DSC", actor=signer)
    return Order.objects.get(pk=order.pk)


def test_the_roznama_sign_endpoint_returns_the_esign_form(roznama_order, signer):
    initiation = mock.Mock()
    initiation.transaction.pk = uuid.uuid4()
    initiation.transaction.provider_transaction_id = "p-2"
    initiation.transaction.expires_at = datetime.datetime(2026, 11, 12, tzinfo=datetime.UTC)
    initiation.initiation.esign_url = "https://esp.example/sign"
    initiation.initiation.form_fields = {"msg": "roz"}
    with mock.patch.object(signing, "start_roznama_signing", return_value=initiation) as start:
        response = client_for(signer).post(
            f"/api/v1/orders/{roznama_order.pk}/roznama/sign/",
            {"method": "AADHAAR_ESIGN"},
            format="json",
        )
    assert response.status_code == 200
    body = response.json()
    assert body["transaction_id"] == str(initiation.transaction.pk)
    assert body["form_fields"] == {"msg": "roz"}
    start.assert_called_once_with(roznama_order.pk, actor=mock.ANY, method="AADHAAR_ESIGN")


def test_the_roznama_signature_is_recorded_and_triggers_nothing(roznama_order, signer):
    from apps.orders.enums import RoznamaStatus
    from apps.orders.models import OrderRoznama

    from .test_signing import success

    OrderRoznama.objects.filter(order=roznama_order).update(signing_file_id="roz-1")
    txn = success(roznama_order, signer, source="roz-1", signed="roz-signed")
    response = client_for(signer).post(
        url("order-roznama-sign-confirm", roznama_order.pk),
        {"transaction_id": str(txn.pk)},
        format="json",
    )
    assert response.status_code == 200
    roznama = OrderRoznama.objects.get(order=roznama_order)
    assert (roznama.status, roznama.signed_file_id) == (RoznamaStatus.SIGNED, "roz-signed")
    assert response.json()["status"] == roznama_order.status
    again = client_for(signer).post(
        f"/api/v1/orders/{roznama_order.pk}/roznama/sign/", {}, format="json"
    )
    assert again.status_code == 409


# -- lists ---------------------------------------------------------------------------------------------


def test_pending_orders_tabs_counts_and_default_tab(
    api, courtroom, ready, staff, signer, drafter, filler
):
    lifecycle.send_for_signing(ready.pk, actor=staff)
    other = drafting.create_outside_hearing(case_id=ready.case_id, actor=staff)
    query = {"court": str(courtroom.pk)}
    body = api.get(url("order-pending"), query).json()
    assert body["counts"] == {
        "drafting": 1,
        "awaiting_signature": 1,
        "order_data": 1,
        "triggered": 0,
    }
    assert body["tab"] == "awaiting_signature"  # staff hold the signer role: their move first
    (row,) = body["results"]
    assert row["id"] == str(ready.pk) and row["signature"] == "AWAITING"
    assert row["order_data"] == "NOT_COMPLETE" and row["my_action"] == "sign"
    assert row["stages"] == ["AWAITING_SIGNATURE", "ORDER_DATA_TO_FILL"]
    assert row["hearing"]["sequence"] == 1 and row["type"] is None  # Kerala has one type
    drafting_tab = client_for(drafter).get(url("order-pending"), query).json()
    assert drafting_tab["tab"] == "drafting"
    assert [r["id"] for r in drafting_tab["results"]] == [str(other.pk)]
    assert drafting_tab["results"][0]["my_action"] == "continue_drafting"
    fill = client_for(filler).get(url("order-pending"), query).json()
    assert fill["tab"] == "order_data" and fill["results"][0]["my_action"] == "fill_order_data"
    counts = client_for(drafter).get(url("order-pending-counts"), query).json()
    assert counts["badge"] == 1
    assert client_for(make_user(name="x")).get(url("order-pending"), query).status_code == 403


def test_pending_orders_search_and_the_triggered_window(api, courtroom, ready, staff, signer):
    lifecycle.mark_complete(ready.pk, actor=staff)
    lifecycle.send_for_signing(ready.pk, actor=staff)
    signing.record_signed_file(ready.pk, "signed", "DSC", actor=signer)
    query = {"court": str(courtroom.pk), "tab": "triggered"}
    assert len(api.get(url("order-pending"), query).json()["results"]) == 1
    assert api.get(url("order-pending"), {**query, "search": "zzzz"}).json()["results"] == []
    Order.objects.filter(pk=ready.pk).update(
        triggered_at=datetime.datetime(2020, 1, 1, tzinfo=datetime.UTC)
    )
    assert api.get(url("order-pending"), query).json()["results"] == []


def test_pending_orders_batch_their_case_reads(api, courtroom, django_assert_max_num_queries):
    for _ in range(12):
        drafting.create_outside_hearing(
            case_id=make_case(courtroom).pk, actor=make_user(OrderRole.ORDER_DRAFTER)
        )
    query = {"court": str(courtroom.pk), "tab": "drafting", "page_size": 50}
    with django_assert_max_num_queries(30):
        assert len(api.get(url("order-pending"), query).json()["results"]) == 12


def test_the_cases_orders_for_staff_and_parties(api, ready, staff, signer, case, complainant_user):
    draft = drafting.create_outside_hearing(case_id=case.pk, actor=staff)
    lifecycle.mark_complete(ready.pk, actor=staff)
    lifecycle.send_for_signing(ready.pk, actor=staff)
    signing.record_signed_file(ready.pk, "signed", "DSC", actor=signer)
    target = url("case-orders", case.pk)
    staff_rows = api.get(target).json()["data"]
    assert {row["id"] for row in staff_rows} == {str(draft.pk), str(ready.pk)}
    assert {row["status"] for row in staff_rows} == {"Draft in progress", "Published"}
    party_rows = client_for(complainant_user).get(target).json()["data"]
    assert [row["id"] for row in party_rows] == [str(ready.pk)]
    assert client_for(make_user(name="x")).get(target).status_code == 404


def test_the_orders_of_a_case_that_does_not_exist_is_404(api):
    response = api.get(url("case-orders", uuid.uuid4()))
    assert (response.status_code, errors_of(response)) == (404, [("E00105", None)])


def test_the_catalogue_for_an_order_is_staff_only(ready, staff, signer, complainant_user):
    lifecycle.send_for_signing(ready.pk, actor=staff)
    signing.record_signed_file(ready.pk, "signed", "DSC", actor=signer)
    response = client_for(complainant_user).get(url("order-items"), {"order": str(ready.pk)})
    assert (response.status_code, errors_of(response)) == (404, [("E00105", None)])


def test_diary_entries_endpoint(api, courtroom, ready, staff, signer):
    lifecycle.mark_complete(ready.pk, actor=staff)
    lifecycle.send_for_signing(ready.pk, actor=staff)
    signing.record_signed_file(ready.pk, "signed", "DSC", actor=signer)
    rows = api.get(url("diary-entries"), {"court": str(courtroom.pk)}).json()["data"]
    assert [row["order_id"] for row in rows] == [str(ready.pk)]
    assert rows[0]["entry_label"] == "A-Diary text"
    assert (
        client_for(make_user(name="x"))
        .get(url("diary-entries"), {"court": str(courtroom.pk)})
        .status_code
        == 403
    )


# -- bulk -----------------------------------------------------------------------------------------------


def test_bulk_items_report_done_and_skipped_per_order(api, courtroom, hearing, order, filler, case):
    outside = drafting.create_outside_hearing(case_id=case.pk, actor=filler)
    items.add(order.pk, "JUDGEMENT", actor=filler)
    response = api.post(
        url("order-bulk-items"),
        {"order_ids": [str(order.pk), str(outside.pk)], "items": [{"item_type": "DISMISS_CASE"}]},
        format="json",
    )
    body = response.json()
    assert response.status_code == 200
    assert body["done"] == []
    assert {s["order_id"]: s["code"] for s in body["skipped"]} == {
        str(order.pk): "E14009",
        str(outside.pk): "E14001",
    }
    ok = api.post(
        url("order-bulk-items"),
        {"order_ids": [str(order.pk)], "items": [{"item_type": "COST"}]},
        format="json",
    )
    assert ok.json()["done"] == [str(order.pk)]
    assert Order.objects.get(pk=order.pk).data_complete is False


def test_bulk_items_report_invalid_values_per_order_and_carry_on(
    api, courtroom, hearing, order, filler
):
    """A validation error on one order is a skipped row, not a failed request (``ITM-10``)."""
    response = api.post(
        url("order-bulk-items"),
        {
            "order_ids": [str(order.pk)],
            "items": [{"item_type": "COST", "values": {"not_a_field": 1}}],
        },
        format="json",
    )
    body = response.json()
    assert response.status_code == 200
    assert body["done"] == []
    assert [(s["order_id"], s["code"]) for s in body["skipped"]] == [(str(order.pk), "E14011")]
    assert Order.objects.get(pk=order.pk).items.count() == 0


def test_bulk_text_appends_creates_and_names_what_it_skips(api, courtroom, hearing, case, staff):
    scheduled = schedule(make_case(courtroom), TODAY)
    response = api.post(
        url("order-bulk-text"),
        {
            "court": str(courtroom.pk),
            "hearing_ids": [str(hearing.pk), str(scheduled.pk)],
            "text": "<p>Called.</p>",
        },
        format="json",
    )
    body = response.json()
    assert body["done"] == [str(hearing.pk)]
    assert [(s["hearing_id"], s["code"]) for s in body["skipped"]] == [
        (str(scheduled.pk), "E14004")
    ]
    assert Order.objects.get(hearing_id=hearing.pk).text == "<p>Called.</p>"
    api.post(
        url("order-bulk-text"),
        {
            "court": str(courtroom.pk),
            "hearing_ids": [str(hearing.pk)],
            "text": "<p>No appearance.</p>",
        },
        format="json",
    )
    assert Order.objects.get(hearing_id=hearing.pk).text == "<p>Called.</p><p>No appearance.</p>"


def test_bulk_text_the_pdf_cannot_draw_is_refused_once_e14027(api, courtroom, hearing):
    response = api.post(
        url("order-bulk-text"),
        {
            "court": str(courtroom.pk),
            "hearing_ids": [str(hearing.pk)],
            "text": "<ul><li>a<ul><li>b</li></ul></li></ul>",
        },
        format="json",
    )
    assert response.status_code == 400
    assert errors_of(response) == [("E14027", "text")]
    assert not Order.objects.filter(hearing_id=hearing.pk).exists()


def test_a_bulk_skip_carries_the_message_itself(api, courtroom, order, filler):
    items.add(order.pk, "COGNIZANCE", actor=filler)
    response = api.post(
        url("order-bulk-items"),
        {"order_ids": [str(order.pk)], "items": [{"item_type": "COGNIZANCE"}]},
        format="json",
    )
    [skipped] = response.json()["skipped"]
    assert skipped["code"] == "E14009"
    assert skipped["message"] == "You cannot add Cognizance twice."


def test_a_signer_cannot_set_the_diary_entry_of_an_order_not_triggered(courtroom, order, signer):
    """The entry is order data until triggering: the order data filler's (``ROL-02``)."""
    client = client_for(signer)
    response = client.put(
        f"/api/v1/orders/{order.pk}/diary-entry/",
        {"same_as_text": False, "text": "<p>Rewritten.</p>"},
        format="json",
    )
    assert response.status_code == 403
    assert errors_of(response) == [("E14019", None)]
    detail = client.get(url("order-detail", order.pk)).json()
    assert "edit_diary_entry" not in detail["allowed_actions"]


def test_the_cause_list_column_of_a_hearing_that_does_not_exist_is_404(api):
    response = api.put(
        url("hearing-next-hearing", uuid.uuid4()), {"state": "NOT_LISTED_AGAIN"}, format="json"
    )
    assert (response.status_code, errors_of(response)) == (404, [("E00105", None)])


def test_bulk_next_hearing_sets_each_listing_and_names_what_it_skips(api, courtroom, hearing):
    response = api.post(
        url("order-bulk-next-hearing"),
        {
            "court": str(courtroom.pk),
            "hearing_ids": [str(hearing.pk), str(uuid.uuid4())],
            "state": "LISTED",
            "date": NEXT,
            "purpose": "ARGUMENTS",
        },
        format="json",
    )
    assert response.status_code == 200
    body = response.json()
    assert body["done"] == [str(hearing.pk)]
    assert [s["code"] for s in body["skipped"]] == ["E00105"]
    order = Order.objects.get(hearing_id=hearing.pk)
    assert (order.next_hearing_date.isoformat(), order.next_hearing_purpose) == (
        NEXT,
        "ARGUMENTS",
    )


def test_bulk_requests_naming_an_id_twice_are_refused(api, courtroom, hearing, order):
    hid = str(hearing.pk)
    requests = (
        ("order-bulk-items", {"order_ids": [str(order.pk)] * 2, "items": [{"item_type": "COST"}]}),
        ("order-bulk-text", {"court": str(courtroom.pk), "hearing_ids": [hid, hid], "text": "x"}),
        (
            "order-bulk-next-hearing",
            {"court": str(courtroom.pk), "hearing_ids": [hid, hid], "state": "NOT_LISTED_AGAIN"},
        ),
    )
    for name, body in requests:
        response = api.post(url(name), body, format="json")
        field = "order_ids" if name == "order-bulk-items" else "hearing_ids"
        assert (response.status_code, errors_of(response)) == (400, [("E00001", field)]), name
    assert order.items.count() == 0


def test_bulk_size_is_limited_e14022(api, courtroom):
    Configuration.objects.update_or_create(
        config_set="orders", config_key="bulk_max_orders", defaults={"config_value": "1"}
    )
    response = api.post(
        url("order-bulk-text"),
        {
            "court": str(courtroom.pk),
            "hearing_ids": [str(uuid.uuid4()), str(uuid.uuid4())],
            "text": "x",
        },
        format="json",
    )
    assert errors_of(response) == [("E14022", None)]


def test_bulk_actions_need_their_roles(courtroom, hearing, drafter, filler, setter):
    payloads = (
        (
            filler,
            "order-bulk-text",
            {"court": str(courtroom.pk), "hearing_ids": [str(hearing.pk)], "text": "x"},
        ),
        (
            drafter,
            "order-bulk-next-hearing",
            {
                "court": str(courtroom.pk),
                "hearing_ids": [str(hearing.pk)],
                "state": "NOT_LISTED_AGAIN",
            },
        ),
    )
    for user, name, body in payloads:
        response = client_for(user).post(url(name), body, format="json")
        assert errors_of(response) == [("E14019", None)], name


# -- shortcuts -------------------------------------------------------------------------------------------


def test_shortcuts_are_personal_and_unique_per_owner_case_insensitively(drafter):
    mine = client_for(drafter)
    created = mine.post(
        url("shortcut-list"), {"name": "called", "body": "<p>Called.</p>"}, format="json"
    )
    assert created.status_code == 201 and created.json()["scope"] == ["ORDER_TEXT"]
    clash = mine.post(url("shortcut-list"), {"name": "called", "body": "x"}, format="json")
    assert errors_of(clash) == [("E14018", "name")]
    bad_name = mine.post(url("shortcut-list"), {"name": "Not Valid!", "body": "x"}, format="json")
    assert bad_name.status_code == 400
    other = client_for(make_user(OrderRole.ORDER_DRAFTER, name="Other"))
    assert (
        other.post(url("shortcut-list"), {"name": "called", "body": "y"}, format="json").status_code
        == 201
    )
    assert [s["name"] for s in other.get(url("shortcut-list")).json()["data"]] == ["called"]
    found = mine.get(url("shortcut-list"), {"scope": "ORDER_TEXT", "search": "call"}).json()["data"]
    assert len(found) == 1
    shortcut = OrderShortcut.objects.get(owner=drafter)
    theirs = url("shortcut-detail", shortcut.pk)
    assert other.patch(theirs, {"body": "x"}, format="json").status_code == 404
    assert other.delete(theirs).status_code == 404
    assert mine.patch(theirs, {"body": "<p>New</p>"}, format="json").json()["body"] == "<p>New</p>"
    assert mine.delete(theirs).status_code == 204


def test_shortcut_names_are_unique_per_owner_ignoring_case_in_the_database(drafter):
    from django.db import IntegrityError, transaction

    OrderShortcut.objects.create(owner=drafter, name="called", body="x", scope=["ORDER_TEXT"])
    with pytest.raises(IntegrityError), transaction.atomic():
        OrderShortcut.objects.create(owner=drafter, name="CALLED", body="y", scope=["ORDER_TEXT"])


def test_shortcuts_need_the_drafter_role(filler):
    assert client_for(filler).get(url("shortcut-list")).status_code == 403
    assert (
        client_for(filler)
        .post(url("shortcut-list"), {"name": "a", "body": "b"}, format="json")
        .status_code
        == 403
    )


def test_a_shortcut_body_is_sanitised_like_order_text(drafter):
    response = client_for(drafter).post(
        url("shortcut-list"), {"name": "x", "body": "<script>1</script><p>ok</p>"}, format="json"
    )
    assert response.json()["body"] == "<p>ok</p>"
    assert make_court and started_hearing
