"""Scrutiny endpoints (spec 0024 #8, #10 API)."""

import pytest
from rest_framework.test import APIClient

from apps.cases.models import CaseStatus
from apps.scrutiny import ports
from apps.scrutiny.enums import FlagStatus, FlagTarget

from .factories import add_courtroom, answer, draft_field, open_round

pytestmark = pytest.mark.django_db


def client_for(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


def error_codes(response):
    """Return a standard error body as ``{field: [code, ...]}`` (spec 0000 §9.1)."""
    codes = {}
    for error in response.json()["errors"]:
        codes.setdefault(error.get("field"), []).append(error["code"])
    return codes


def url(case, *parts):
    return "/".join(["/api/v1/scrutiny", str(case.pk), *parts]) + "/"


def version(case):
    case.refresh_from_db()
    return str(ports.workflow_version(case))


# Lists and reads


def test_scrutiny_list(case, officer):
    response = client_for(officer).get("/api/v1/scrutiny/")
    assert response.status_code == 200
    body = response.json()
    assert (body["count"], body["counts"]) == (1, {"registry": 1, "advocate": 0, "closed": 0})
    row = body["results"][0]
    assert (row["case_id"], row["stage"], row["with"]) == (str(case.pk), "AWAITING_SCRUTINY", None)
    assert "meta" in body


def test_lists_need_a_court_role(case, filer):
    response = client_for(filer).get("/api/v1/scrutiny/")
    assert (response.status_code, error_codes(response)) == (403, {None: ["E09008"]})


def test_list_refuses_an_unknown_tab(case, officer):
    response = client_for(officer).get("/api/v1/scrutiny/", {"tab": "archive"})
    assert (response.status_code, error_codes(response)) == (400, {"tab": ["E00005"]})


def test_detail_carries_its_version(case, officer):
    response = client_for(officer).get(url(case))
    assert response.status_code == 200
    assert response["ETag"] == f'"{response.json()["workflow_version"]}"'
    assert response.json()["allowed_actions"][0] == "start"


def test_outsiders_are_told_the_case_does_not_exist(case, filer):
    for path in (url(case), url(case, "history")):
        response = client_for(filer).get(path)
        assert (response.status_code, error_codes(response)) == (404, {None: ["E00105"]})


# Flags


def test_draft_returns_the_marked_dates(case, officer):
    response = client_for(officer).post(
        url(case, "flags"),
        {"target_type": FlagTarget.FIELD, "target_ref": "CHQ-9[0]", "note": "Return date?"},
        format="json",
    )
    assert response.status_code == 201
    refs = [flag["target_ref"] for flag in response.json()["data"]]
    assert refs == ["CHQ-9[0]", "LDN-2[0]", "LDN-6[0]", "JUR-9", "JUR-10"]


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        (
            {"target_type": "FIELD", "target_ref": "XYZ-1[0]", "note": "x"},
            {"target_ref": ["E09003"]},
        ),
        ({"target_type": "SECTION", "target_ref": "LDN"}, {"note": ["E09004"]}),
        ({"target_type": "PARTY", "target_ref": "LDN", "note": "x"}, {"target_type": ["E00005"]}),
    ],
)
def test_draft_refusals(case, officer, body, expected):
    response = client_for(officer).post(url(case, "flags"), body, format="json")
    assert error_codes(response) == expected


def test_draft_needs_the_scrutiny_officer_role(case, registerer):
    response = client_for(registerer).post(
        url(case, "flags"), {"target_type": "SECTION", "target_ref": "LDN", "note": "x"}
    )
    assert (response.status_code, error_codes(response)) == (403, {None: ["E09008"]})


def test_edit_and_withdraw_a_draft(case, officer):
    flag = draft_field(case, officer, "CHQ-3[0]")[0]
    client = client_for(officer)
    response = client.patch(url(case, "flags", str(flag.pk)), {"note": "Amount?"}, format="json")
    assert (response.status_code, response.json()["note"]) == (200, "Amount?")
    response = client.delete(url(case, "flags", str(flag.pk)))
    assert response.status_code == 204
    flag.refresh_from_db()
    assert flag.status == FlagStatus.WITHDRAWN


def test_raised_flag_cannot_be_edited(case, officer):
    flag = draft_field(case, officer, "CHQ-3[0]")[0]
    client = client_for(officer)
    client.post(url(case, "send-back"))
    enter_scrutiny_again(case, officer)
    response = client.patch(url(case, "flags", str(flag.pk)), {"note": "x"}, format="json")
    assert error_codes(response) == {None: ["E09002"]}


def enter_scrutiny_again(case, officer):
    case.refresh_from_db()
    case.status = CaseStatus.UNDER_SCRUTINY
    case.save()


# Decisions


def test_send_back_checks_if_match(case, officer):
    draft_field(case, officer, "CHQ-3[0]")
    client = client_for(officer)
    response = client.post(url(case, "send-back"), HTTP_IF_MATCH="1")
    assert (response.status_code, error_codes(response)) == (412, {None: ["E08005"]})
    response = client.post(url(case, "send-back"), HTTP_IF_MATCH=f'"{version(case)}"')
    assert response.status_code == 200
    assert response.json()["case_status"] == CaseStatus.PENDING_CORRECTION
    assert response.json()["round"]["decision"] == "SENT_BACK"


def test_send_back_needs_a_draft(case, officer):
    response = client_for(officer).post(url(case, "send-back"))
    assert (response.status_code, error_codes(response)) == (400, {None: ["E09005"]})


def test_forward_follows_roles_and_courtrooms(case, officer, officer_registerer, establishment):
    response = client_for(officer_registerer).post(url(case, "forward"), {}, format="json")
    assert (response.status_code, error_codes(response)) == (409, {None: ["E09007"]})

    room = add_courtroom(establishment, "Courtroom 1")
    add_courtroom(establishment, "Courtroom 2")
    client = client_for(officer)
    response = client.post(url(case, "forward"), {}, format="json")
    assert error_codes(response) == {"courtroom_id": ["E09017"]}
    response = client.post(url(case, "forward"), {"courtroom_id": str(room.pk)}, format="json")
    assert (response.status_code, response.json()["case_status"]) == (
        200,
        CaseStatus.PENDING_REGISTRATION,
    )


def test_register_at_scrutiny_numbers_the_case(case, officer_registerer):
    response = client_for(officer_registerer).post(url(case, "register"), {}, format="json")
    assert response.status_code == 200
    assert response.json()["case_number"].startswith("CC/1/")


def test_edit_title(case, officer):
    response = client_for(officer).patch(
        url(case, "title"), {"complainant": "Prateek", "accused": "Deepak"}, format="json"
    )
    assert (response.status_code, response.json()) == (
        200,
        {"complainant": "Prateek", "accused": "Deepak", "meta": response.json()["meta"]},
    )


def test_start_and_resolve(case, officer, filer):
    flag = draft_field(case, officer, "CHQ-3[0]")[0]
    client = client_for(officer)
    client.post(url(case, "send-back"))
    answer(flag, filer)
    enter_scrutiny_again(case, officer)
    response = client.post(url(case, "start"))
    assert (response.status_code, response.json()["started_by"]["name"]) == (200, "Biju B")
    carried = open_round(case).flags.get()
    response = client.post(url(case, "flags", str(carried.pk), "resolve"))
    assert (response.status_code, response.json()["status"]) == (200, FlagStatus.RESOLVED)
