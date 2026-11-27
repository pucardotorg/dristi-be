"""Filing: offering types, creating and editing drafts (spec 0033 #6.1-#6.3, #17.1)."""

import datetime

import pytest

from apps.applications.models import Application, ApplicationTransition
from apps.cases.models import CaseStatus, ParticipantRole

from .factories import (
    add_party,
    client_for,
    codes_of,
    errors_of,
    make_advocate,
    make_case,
    make_user,
    office,
    represent,
    schedule_hearing,
    set_config,
    submitted,
)

pytestmark = pytest.mark.django_db

TODAY = datetime.date(2026, 11, 12)


def create(user, case, **body):
    body.setdefault("application_type", "GENERIC")
    return client_for(user).post(f"/api/v1/cases/{case.pk}/applications/", body, format="json")


def patch(user, application_id, version=None, **body):
    headers = {"HTTP_IF_MATCH": str(version)} if version is not None else {}
    return client_for(user).patch(
        f"/api/v1/applications/{application_id}/", body, format="json", **headers
    )


def types_for(user, case):
    response = client_for(user).get(f"/api/v1/cases/{case.pk}/application-types/")
    assert response.status_code == 200, response.json()
    return response.json()


def form(user, case, code):
    return client_for(user).get(f"/api/v1/cases/{case.pk}/application-types/{code}/form/")


class TestCreate:
    def test_t01_advocate_creates_a_draft_with_only_the_type(self, world):
        response = create(world.a1, world.case)
        assert response.status_code == 201, response.json()
        body = response.json()
        assert body["status"] == "DRAFT"
        assert body["side"] == "COMPLAINANT"
        assert body["version"] == 0
        application = Application.objects.get(pk=body["id"])
        assert application.created_by == world.a1
        assert (
            ApplicationTransition.objects.filter(application=application, action="CREATE").count()
            == 1
        )

    def test_t02_clerk_drafts_and_form_defaults_to_their_advocate(self, world):
        response = create(world.c1, world.case)
        assert response.status_code == 201, response.json()
        assert response.json()["side"] == "COMPLAINANT"
        defaults = form(world.c1, world.case, "GENERIC").json()["defaults"]
        assert defaults == {"raised_by": str(world.a1.pk), "litigant": str(world.complainant.pk)}

    def test_t03_clerk_for_two_advocates_gets_no_default(self, world):
        a2 = make_advocate("Second advocate")
        second = add_party(world.case, ParticipantRole.COMPLAINANT, "Second", ordinal=2)
        represent(world.case, a2, second)
        office(world.c1, a2)
        assert form(world.c1, world.case, "GENERIC").json()["defaults"] == {
            "raised_by": None,
            "litigant": None,
        }

    def test_advocate_defaults_to_themselves(self, world):
        defaults = form(world.a1, world.case, "GENERIC").json()["defaults"]
        assert defaults == {"raised_by": str(world.a1.pk), "litigant": str(world.complainant.pk)}

    @pytest.mark.parametrize("who", ["l1", "h1"])
    def test_t04_t05_litigant_and_poa_holder_cannot_draft(self, world, who):
        response = create(getattr(world, who), world.case)
        assert response.status_code == 403
        assert codes_of(response) == ["E13004"]

    def test_t05_poa_change_not_offered(self, world):
        response = create(world.a1, world.case, application_type="POA_CHANGE")
        assert errors_of(response) == [("E13002", "application_type")]

    def test_t06_complainant_side_cannot_raise_bail(self, world):
        response = create(world.a1, world.case, application_type="BAIL")
        assert errors_of(response) == [("E13002", "application_type")]

    def test_t07_accused_side_cannot_raise_delay_condonation(self, world):
        response = create(world.b1, world.case, application_type="DELAY_CONDONATION")
        assert errors_of(response) == [("E13002", "application_type")]

    def test_t08_advance_needs_a_scheduled_hearing(self, world):
        response = create(world.a1, world.case, application_type="ADVANCE_HEARING")
        assert errors_of(response) == [("E13002", "application_type")]
        hearing = schedule_hearing(world.case, TODAY + datetime.timedelta(days=9))
        response = create(
            world.a1,
            world.case,
            application_type="ADVANCE_HEARING",
            hearing_id="00000000-0000-0000-0000-000000000000",
        )
        assert response.status_code == 201, response.json()
        assert Application.objects.get(pk=response.json()["id"]).hearing_id == hearing.pk

    def test_t10_case_not_registered(self, world):
        case = make_case(world.court, status=CaseStatus.UNDER_SCRUTINY)
        party = add_party(case, ParticipantRole.COMPLAINANT, "X")
        represent(case, world.a1, party)
        response = create(world.a1, case)
        assert response.status_code == 409
        assert codes_of(response) == ["E13003"]

    def test_t11_raised_by_from_the_other_side(self, world):
        response = create(world.a1, world.case, raised_by=str(world.b1.pk))
        assert errors_of(response) == [("E13005", "raised_by")]

    def test_t12_litigant_not_represented_by_raised_by(self, world):
        second = add_party(world.case, ParticipantRole.COMPLAINANT, "Second", ordinal=2)
        response = create(world.a1, world.case, raised_by=str(world.a1.pk), litigant=str(second.pk))
        assert errors_of(response) == [("E13006", "litigant")]

    def test_litigant_of_the_other_side(self, world):
        response = create(world.a1, world.case, litigant=str(world.accused.pk))
        assert errors_of(response) == [("E13006", "litigant")]

    def test_t13_unknown_data_key(self, world):
        response = create(world.a1, world.case, data={"title": "x", "colour": "red"})
        assert errors_of(response) == [("E13009", "data.colour")]

    def test_type_with_no_fields_refuses_any_key(self, world):
        response = create(world.a1, world.case, application_type="CASE_SETTLEMENT", data={"x": 1})
        assert errors_of(response) == [("E13009", "data.x")]

    def test_wrong_shape_is_a_common_code(self, world):
        response = create(world.a1, world.case, data={"title": 5})
        assert errors_of(response) == [("E00001", "data.title")]

    def test_t14_draft_saved_half_filled_and_reloaded(self, world):
        body = {"details": "<p>Half</p>", "data": {"title": "Half done"}}
        created = create(world.a1, world.case, **body).json()
        reloaded = client_for(world.a1).get(f"/api/v1/applications/{created['id']}/").json()
        assert reloaded["details"] == "<p>Half</p>"
        assert reloaded["data"] == {"title": "Half done"}

    def test_t15_details_sanitised(self, world):
        html = (
            '<p style="text-align:center" onclick="x()">Hi<script>alert(1)</script></p>'
            '<p style="color:red">red</p>'
        )
        details = create(world.a1, world.case, details=html).json()["details"]
        assert details == '<p style="text-align: center">Hi</p><p>red</p>'

    def test_details_over_the_limit(self, world):
        set_config("applications", "details_max_bytes", "20")
        response = create(world.a1, world.case, details="<p>" + "x" * 50 + "</p>")
        assert errors_of(response) == [("E00006", "details")]

    def test_unknown_case(self, world):
        response = client_for(world.a1).post(
            "/api/v1/cases/00000000-0000-0000-0000-000000000000/applications/",
            {"application_type": "GENERIC"},
            format="json",
        )
        assert response.status_code == 404

    def test_objection_through_the_generic_endpoint_needs_a_target(self, world):
        response = create(world.b1, world.case, application_type="OBJECTION")
        assert errors_of(response) == [("E13002", "application_type")]


class TestEdit:
    @pytest.fixture
    def draft(self, world):
        return create(world.a1, world.case, data={"title": "First"}).json()

    def test_t16_clerk_edits_other_side_and_litigant_do_not_see_it(self, world, draft):
        assert patch(world.c1, draft["id"], details="<p>by clerk</p>").status_code == 200
        for who in (world.b1, world.l1):
            response = patch(who, draft["id"], details="<p>x</p>")
            assert response.status_code == 404
            assert codes_of(response) == ["E00105"]

    def test_t17_stale_if_match(self, world, draft):
        assert patch(world.a1, draft["id"], version=0, details="<p>1</p>").status_code == 200
        response = patch(world.a1, draft["id"], version=0, details="<p>2</p>")
        assert response.status_code == 412
        assert codes_of(response) == ["E13026"]

    def test_malformed_if_match_is_stale(self, world, draft):
        response = client_for(world.a1).patch(
            f"/api/v1/applications/{draft['id']}/",
            {"details": "x"},
            format="json",
            HTTP_IF_MATCH="abc",
        )
        assert codes_of(response) == ["E13026"]

    def test_version_bumps_and_etag(self, world, draft):
        response = patch(world.a1, draft["id"], version=0, details="<p>1</p>")
        assert response.json()["version"] == 1
        assert response["ETag"] == '"1"'

    def test_t18_edit_in_pending_signature(self, world):
        body = {
            "raised_by": str(world.a1.pk),
            "litigant": str(world.complainant.pk),
            "details": "<p>Original</p>",
            "data": {"title": "T"},
        }
        app_id = create(world.a1, world.case, **body).json()["id"]
        client_for(world.a1).post(f"/api/v1/applications/{app_id}/proceed-to-sign/")
        application = Application.objects.get(pk=app_id)
        assert application.status == "PENDING_SIGNATURE"
        response = patch(world.a1, app_id, details="<p>changed</p>")
        assert response.status_code == 409
        assert codes_of(response) == ["E13001"]
        after = Application.objects.get(pk=app_id)
        assert after.details == "<p>Original</p>"
        assert after.signing_file_id == application.signing_file_id

    def test_edit_after_submission(self, world):
        application = submitted(world)
        assert codes_of(patch(world.a1, application.pk, details="<p>x</p>")) == ["E13001"]

    def test_t19_litigant_change_to_the_other_side(self, world, draft):
        response = patch(world.a1, draft["id"], litigant=str(world.accused.pk))
        assert errors_of(response) == [("E13006", "litigant")]

    def test_type_is_fixed(self, world, draft):
        patch(world.a1, draft["id"], application_type="BAIL")
        assert Application.objects.get(pk=draft["id"]).application_type.code == "GENERIC"

    def test_read_only_fields_ignored(self, world, draft):
        patch(world.a1, draft["id"], status="ACCEPTED", application_number="X/1")
        application = Application.objects.get(pk=draft["id"])
        assert application.status == "DRAFT"
        assert application.application_number is None

    def test_changing_raised_by_clears_a_litigant_they_do_not_represent(self, world, draft):
        a2 = make_advocate("Second advocate")
        second = add_party(world.case, ParticipantRole.COMPLAINANT, "Second", ordinal=2)
        represent(world.case, a2, second)
        patch(world.a1, draft["id"], raised_by=str(world.a1.pk), litigant=str(world.complainant.pk))
        response = patch(world.a1, draft["id"], raised_by=str(a2.pk))
        assert response.status_code == 200, response.json()
        assert Application.objects.get(pk=draft["id"]).raised_on_behalf_of is None

    def test_t121_removed_from_the_case_loses_access_at_once(self, world, draft):
        world.a1.advocate_profile.representations.update(is_active=False)
        response = patch(world.a1, draft["id"], details="<p>x</p>")
        assert response.status_code == 404


class TestOfferedTypes:
    def test_t20_types_per_seat(self, world):
        schedule_hearing(world.case, TODAY + datetime.timedelta(days=9))
        complainant_types = {t["code"] for t in types_for(world.a1, world.case)["types"]}
        accused_types = {t["code"] for t in types_for(world.b1, world.case)["types"]}
        assert "DELAY_CONDONATION" in complainant_types and "BAIL" not in complainant_types
        assert "BAIL" in accused_types and "DELAY_CONDONATION" not in accused_types
        assert {"ADVANCE_HEARING", "POSTPONE_HEARING"} <= complainant_types
        assert "POA_CHANGE" not in complainant_types | accused_types
        assert "OBJECTION" not in accused_types  # nothing to object to yet
        submitted(world)
        assert "OBJECTION" in {t["code"] for t in types_for(world.b1, world.case)["types"]}
        assert "OBJECTION" not in {t["code"] for t in types_for(world.a1, world.case)["types"]}

    def test_party_in_person_on_a_second_case(self, world):
        case = make_case(world.court)
        p1 = make_user(name="P1")
        add_party(case, ParticipantRole.COMPLAINANT, "Complainant")
        add_party(case, ParticipantRole.ACCUSED, "P1", user=p1, in_person=True)
        codes = {t["code"] for t in types_for(p1, case)["types"]}
        assert "BAIL" in codes
        defaults = form(p1, case, "BAIL").json()["defaults"]
        assert defaults["raised_by"] == str(p1.pk)

    def test_inactive_type_never_offered(self, world):
        from apps.applications.models import ApplicationType

        ApplicationType.objects.filter(code="GENERIC").update(is_active=False)
        assert "GENERIC" not in {t["code"] for t in types_for(world.a1, world.case)["types"]}
        assert errors_of(create(world.a1, world.case)) == [("E13002", "application_type")]

    def test_t142_litigant_and_poa_holder_cannot_raise(self, world):
        for user in (world.l1, world.h1):
            body = types_for(user, world.case)
            assert (body["can_raise"], body["types"]) == (False, [])

    def test_stranger_does_not_find_the_case(self, world):
        response = client_for(world.stranger).get(
            f"/api/v1/cases/{world.case.pk}/application-types/"
        )
        assert response.status_code == 404

    def test_t133_suggested_by_stage_orders_only(self, world):
        set_config("applications", "suggested_by_stage", '{"": ["GENERIC"]}')
        types = types_for(world.a1, world.case)["types"]
        assert types[0]["code"] == "GENERIC" and types[0]["suggested"] is True
        assert all(not t["suggested"] for t in types[1:])

    def test_form_for_an_unavailable_type(self, world):
        response = form(world.a1, world.case, "BAIL")
        assert errors_of(response) == [("E13002", "application_type")]

    def test_form_lists_raised_by_options(self, world):
        body = form(world.a1, world.case, "CASE_TRANSFER").json()
        assert body["type"]["code"] == "CASE_TRANSFER"
        assert body["system_fields"] == {"current_court": world.court.name}
        option = body["raised_by_options"][0]
        assert option["user_id"] == str(world.a1.pk)
        assert option["kind"] == "ADVOCATE"
        assert option["litigants"][0]["participant_id"] == str(world.complainant.pk)

    def test_form_needs_a_drafter(self, world):
        assert codes_of(form(world.l1, world.case, "GENERIC")) == ["E13004"]
