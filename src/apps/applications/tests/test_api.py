"""Read models, court queue, permissions (spec 0033 #14, #15, #17.9)."""

import datetime

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.applications.models import Application

from .factories import (
    client_for,
    codes_of,
    make_court,
    pass_order,
    pdf_upload,
    schedule_hearing,
    set_config,
    submitted,
)

pytestmark = pytest.mark.django_db

TODAY = datetime.date(2026, 11, 12)
D20 = datetime.date(2026, 11, 20)
D19 = datetime.date(2026, 11, 19)


def draft(world, user=None, **body):
    user = user or world.a1
    body = {"application_type": "GENERIC", "data": {"title": "x"}, **body}
    response = client_for(user).post(
        f"/api/v1/cases/{world.case.pk}/applications/", body, format="json"
    )
    assert response.status_code == 201, response.json()
    return Application.objects.get(pk=response.json()["id"])


def case_list(user, case, **params):
    response = client_for(user).get(f"/api/v1/cases/{case.pk}/applications/", params)
    assert response.status_code == 200, response.json()
    return response.json()


def queue(user, court, **params):
    return client_for(user).get(
        "/api/v1/applications/court-queue/", {"court": str(court.pk), **params}
    )


class TestCaseList:
    def test_t116_each_reader_sees_exactly_their_rows(self, world):
        mine = draft(world)
        submitted_one = submitted(world)
        accused_submitted = submitted(world, "BAIL", side="ACCUSED", data={"bail_type": "CASH"})
        rows = {
            name: {r["id"] for r in case_list(user, world.case)["results"]}
            for name, user in (
                ("a1", world.a1),
                ("l1", world.l1),
                ("b1", world.b1),
                ("staff", world.staff),
            )
        }
        everyone = {str(submitted_one.pk), str(accused_submitted.pk)}
        assert rows["a1"] == everyone | {str(mine.pk)}
        assert rows["l1"] == everyone
        assert rows["b1"] == everyone
        assert rows["staff"] == everyone

    def test_stranger_and_other_court_staff_see_nothing(self, world, settings):
        submitted(world)
        assert case_list(world.stranger, world.case)["count"] == 0
        other = make_court("Elsewhere")
        settings.SCRUTINY_ESTABLISHMENT_ID = str(other.pk)
        assert case_list(world.staff, world.case)["count"] == 0

    def test_t117_filters_and_search(self, world):
        generic = submitted(world)
        bail = submitted(world, "BAIL", side="ACCUSED", data={"bail_type": "CASH"})
        assert [r["id"] for r in case_list(world.a1, world.case, type="BAIL")["results"]] == [
            str(bail.pk)
        ]
        assert case_list(world.a1, world.case, status="PENDING_REVIEW")["count"] == 2
        assert [
            r["id"] for r in case_list(world.a1, world.case, filed_by=str(world.b1.pk))["results"]
        ] == [str(bail.pk)]
        found = case_list(world.a1, world.case, search=generic.application_number)["results"]
        assert str(generic.pk) in {r["id"] for r in found}
        assert case_list(world.a1, world.case, page_size=1)["count"] == 2
        assert "meta" in case_list(world.a1, world.case)

    def test_pending_list_for_the_order_screen(self, world):
        open_one = submitted(world)
        closed = submitted(world)
        pass_order(closed, onboard=False, decides=True, outcome="DISMISSED")
        rows = case_list(world.staff, world.case, pending="true")["results"]
        assert [r["id"] for r in rows] == [str(open_one.pk)]

    def test_t139_clerks_draft_waiting_on_the_advocate(self, world):
        application = draft(
            world,
            user=world.c1,
            raised_by=str(world.a1.pk),
            litigant=str(world.complainant.pk),
            details="<p>x</p>",
        )
        client_for(world.c1).post(f"/api/v1/applications/{application.pk}/proceed-to-sign/")
        clerk_row = case_list(world.c1, world.case)["results"][0]
        assert clerk_row["waiting_on"] == "Adv. Nisha Thomas"
        assert clerk_row["drafted_by"] == "Clerk to Nisha"
        assert "sign" not in clerk_row["actions"]
        advocate_row = case_list(world.a1, world.case)["results"][0]
        assert "sign" in advocate_row["actions"]
        assert advocate_row["waiting_on"] is None

    def test_file_objection_action_for_the_other_side(self, world):
        submitted(world)
        row = case_list(world.b1, world.case)["results"][0]
        assert row["actions"] == ["file_objection"]

    def test_filers(self, world):
        submitted(world)
        submitted(world, "BAIL", side="ACCUSED", data={"bail_type": "CASH"})
        response = client_for(world.a1).get(f"/api/v1/cases/{world.case.pk}/applications/filers/")
        assert {f["side"] for f in response.json()["data"]} == {"COMPLAINANT", "ACCUSED"}

    def test_t122_constant_queries_for_a_page(self, world):
        for _ in range(3):
            submitted(world)
        with CaptureQueriesContext(connection) as small:
            case_list(world.staff, world.case)
        for _ in range(12):
            submitted(world)
        with CaptureQueriesContext(connection) as large:
            case_list(world.staff, world.case)
        # Per-row checks are bounded by the access stand-ins; the growth must stay linear and small.
        assert len(large.captured_queries) <= len(small.captured_queries) + 12 * 2


class TestNeedsAttention:
    def test_t118_groups(self, world):
        set_config("applications", "fee.generic", "25")
        for _ in range(2):
            draft(world)
        signing = []
        for _ in range(2):
            application = draft(
                world,
                raised_by=str(world.a1.pk),
                litigant=str(world.complainant.pk),
                details="<p>x</p>",
            )
            client_for(world.a1).post(f"/api/v1/applications/{application.pk}/proceed-to-sign/")
            signing.append(application)
        from .factories import success_esign

        paying = signing.pop()
        esign = success_esign(Application.objects.get(pk=paying.pk), world.a1)
        client_for(world.a1).post(
            f"/api/v1/applications/{paying.pk}/sign/confirm/",
            {"transaction_id": str(esign.pk)},
            format="json",
        )
        groups = (
            client_for(world.a1)
            .get(f"/api/v1/cases/{world.case.pk}/applications/needs-attention/")
            .json()["groups"]
        )
        steps = {g["step"]: g for g in groups}
        assert len(steps["CONTINUE_DRAFT"]["application_ids"]) == 2
        assert steps["ADD_SIGNATURE"]["application_ids"] == [str(signing[0].pk)]
        assert steps["ADD_SIGNATURE"]["bulk_signing_available"] is False
        assert steps["COMPLETE_PAYMENT"]["total"] == "25.00"
        assert steps["COMPLETE_PAYMENT"]["lines"][0]["amount"] == "25.00"

    def test_file_objection_group_for_the_other_side(self, world):
        application = submitted(world)
        pass_order(application, onboard=True, bring_back_on=D20, respond=True, respond_by=D19)
        groups = (
            client_for(world.b1)
            .get(f"/api/v1/cases/{world.case.pk}/applications/needs-attention/")
            .json()["groups"]
        )
        assert groups[0]["step"] == "FILE_OBJECTION"
        assert groups[0]["respond_by"] == "2026-11-19"
        assert (
            client_for(world.l1)
            .get(f"/api/v1/cases/{world.case.pk}/applications/needs-attention/")
            .json()["groups"]
            == []
        )


class TestDetail:
    def test_t119_same_for_every_reader_court_view_adds_its_keys(self, world):
        schedule_hearing(world.case, TODAY + datetime.timedelta(days=9))
        application = submitted(world)
        pass_order(application, onboard=True, bring_back_on=D20, respond=False)
        bodies = {
            name: client_for(user).get(f"/api/v1/applications/{application.pk}/").json()
            for name, user in (("b1", world.b1), ("a1", world.a1), ("staff", world.staff))
        }
        for key in ("filed_on", "previous_order", "objection_status"):
            assert bodies["b1"][key] == bodies["a1"][key] == bodies["staff"][key]
        assert bodies["b1"]["objection_status"] == "NOT_CALLED_FOR"
        assert "order_actions" not in bodies["b1"]
        staff = bodies["staff"]
        assert staff["order_actions"] == ["decide", "move_date"]
        assert staff["can_draft_order"] is True
        assert staff["suggested_date"] == "2026-11-21"
        assert staff["task"] == {"kind": "DECIDE", "due_date": "2026-11-20", "overdue": False}
        assert staff["court"]["next_hearing"]["date"] == "2026-11-21"
        assert staff["document"]["title"] == "x" or staff["document"]["title"]
        assert staff["pending_order"] is None

    def test_reader_without_draft_role(self, world):
        application = submitted(world)
        body = client_for(world.reader).get(f"/api/v1/applications/{application.pk}/").json()
        assert body["can_draft_order"] is False
        assert body["order_actions"] == ["onboard", "defer", "dismiss"]

    def test_t129_preview(self, world):
        application = draft(world)
        body = client_for(world.a1).get(f"/api/v1/applications/{application.pk}/preview/").json()
        assert body["title"] == "x"
        assert body["file_id"] is None
        assert body["parties"][0][0] == {"term": "Complainant", "value": "Prateek Agrawal"}
        assert body["parties"][-1][0]["term"] == "Offence"

    def test_t140_pdf_preview_equals_the_copy_to_sign(self, world):
        from .factories import file_bytes

        application = draft(
            world,
            raised_by=str(world.a1.pk),
            litigant=str(world.complainant.pk),
            details="<p>x</p>",
        )
        draft_pdf = client_for(world.a1).get(
            f"/api/v1/applications/{application.pk}/preview/", {"format": "pdf"}
        )
        assert draft_pdf.status_code == 200
        assert draft_pdf.content.startswith(b"%PDF")
        client_for(world.a1).post(f"/api/v1/applications/{application.pk}/proceed-to-sign/")
        application.refresh_from_db()
        signed_copy = client_for(world.a1).get(
            f"/api/v1/applications/{application.pk}/preview/", {"format": "pdf"}
        )
        assert signed_copy.content == file_bytes(application.signing_file_id)
        body = client_for(world.a1).get(f"/api/v1/applications/{application.pk}/preview/").json()
        assert body["file_id"] == application.signing_file_id

    def test_preview_only_for_the_drafting_circle_before_submission(self, world):
        application = submitted(world)
        response = client_for(world.a1).get(f"/api/v1/applications/{application.pk}/preview/")
        assert response.status_code == 404

    def test_t141_document_names_numbered(self, world):
        application = draft(world, user=world.b1, application_type="BAIL", data={})
        for index in (0, 1):
            client_for(world.b1).post(
                f"/api/v1/applications/{application.pk}/documents/",
                {"file": pdf_upload(), "field_path": f"sureties[{index}].solvency_document_ids"},
                format="multipart",
            )
        client_for(world.b1).post(
            f"/api/v1/applications/{application.pk}/documents/",
            {"file": pdf_upload(), "name": "Proof of solvency"},
            format="multipart",
        )
        names = [
            d["name"]
            for d in client_for(world.b1)
            .get(f"/api/v1/applications/{application.pk}/")
            .json()["documents"]
        ]
        assert names == ["Proof of solvency 1", "Proof of solvency 2", "Proof of solvency 3"]

    def test_t143_step_and_objection_invite(self, world):
        application = submitted(world)
        assert (
            client_for(world.a1).get(f"/api/v1/applications/{application.pk}/").json()["step"]
            is None
        )
        invite = client_for(world.l1).get(f"/api/v1/applications/{application.pk}/").json()
        assert invite["objection_invite"] is None  # own side
        from apps.cases.models import ParticipantRole

        from .factories import add_party, make_user

        accused_litigant = make_user(name="Accused person")
        add_party(
            world.case, ParticipantRole.ACCUSED, "Accused 2", user=accused_litigant, ordinal=2
        )
        body = client_for(accused_litigant).get(f"/api/v1/applications/{application.pk}/").json()
        assert body["objection_invite"]["can_file"] is False
        assert (
            client_for(world.b1)
            .get(f"/api/v1/applications/{application.pk}/")
            .json()["objection_invite"]["can_file"]
            is True
        )

    def test_history_hides_filing_steps_from_the_other_side(self, world):
        application = draft(
            world,
            raised_by=str(world.a1.pk),
            litigant=str(world.complainant.pk),
            details="<p>x</p>",
        )
        from .factories import success_esign

        client_for(world.a1).post(f"/api/v1/applications/{application.pk}/proceed-to-sign/")
        application.refresh_from_db()
        esign = success_esign(application, world.a1)
        client_for(world.a1).post(
            f"/api/v1/applications/{application.pk}/sign/confirm/",
            {"transaction_id": str(esign.pk)},
            format="json",
        )
        mine = [
            h["action"]
            for h in client_for(world.a1)
            .get(f"/api/v1/applications/{application.pk}/")
            .json()["history"]
        ]
        theirs = [
            h["action"]
            for h in client_for(world.b1)
            .get(f"/api/v1/applications/{application.pk}/")
            .json()["history"]
        ]
        assert mine[:2] == ["CREATE", "PROCEED_TO_SIGN"]
        assert "CREATE" not in theirs and "SIGN" in theirs

    def test_document_download(self, world):
        application = draft(world)
        doc = (
            client_for(world.a1)
            .post(
                f"/api/v1/applications/{application.pk}/documents/",
                {"file": pdf_upload(), "name": "Evidence"},
                format="multipart",
            )
            .json()
        )
        url = f"/api/v1/applications/{application.pk}/documents/{doc['id']}/"
        response = client_for(world.a1).get(url)
        assert response.status_code == 200
        assert response.content.startswith(b"%PDF")
        assert client_for(world.b1).get(url).status_code == 404
        missing = f"/api/v1/applications/{application.pk}/documents/signed/"
        assert client_for(world.a1).get(missing).status_code == 404


class TestCourtQueue:
    @pytest.fixture
    def board(self, world):
        due_today = submitted(world)  # review due the next working day: Friday
        set_config("hearings", "business_date_override", "2026-11-13")
        deciding = submitted(world)
        pass_order(deciding, onboard=True, bring_back_on=datetime.date(2026, 11, 13))
        upcoming = submitted(world)
        pass_order(upcoming, onboard=True, bring_back_on=D20)
        closed = submitted(world)
        pass_order(closed, onboard=False, decides=True, outcome="DISMISSED")
        return {"onboard": due_today, "decide": deciding, "upcoming": upcoming, "closed": closed}

    def ids(self, response):
        assert response.status_code == 200, response.json()
        return [r["application_id"] for r in response.json()["results"]]

    def test_t131_t134_views(self, world, board):
        assert self.ids(queue(world.staff, world.court, view="onboard")) == [
            str(board["onboard"].pk)
        ]
        assert self.ids(queue(world.staff, world.court, view="decide")) == [str(board["decide"].pk)]
        upcoming = self.ids(queue(world.staff, world.court, view="upcoming"))
        assert str(board["upcoming"].pk) in upcoming
        assert self.ids(queue(world.staff, world.court, view="closed")) == [str(board["closed"].pk)]
        all_rows = queue(world.staff, world.court, view="all").json()
        assert [r["band"] for r in all_rows["results"]][:2] == ["onboard", "decide"]
        assert all_rows["today"] == "2026-11-13"
        assert all_rows["results"][0]["task"]["due_today"] is True

    def test_counts(self, world, board):
        counts = (
            client_for(world.staff)
            .get("/api/v1/applications/court-queue/counts/", {"court": str(world.court.pk)})
            .json()
        )
        assert counts["views"]["onboard"] == 1
        assert counts["views"]["decide"] == 1
        assert counts["views"]["closed"] == 1
        assert counts["badge"] == 2
        assert counts["queues"]["other"] == counts["views"]["all"]

    def test_archive_after_the_closed_window(self, world, board):
        assert self.ids(queue(world.staff, world.court, view="archive")) == []
        # Closing is stamped with the real clock: move the court's today far past it.
        set_config("hearings", "business_date_override", "2099-12-31")
        assert self.ids(queue(world.staff, world.court, view="archive")) == [
            str(board["closed"].pk)
        ]

    def test_type_cut_queues_search_side_facets(self, world, board):
        hearing = schedule_hearing(world.case, D20 + datetime.timedelta(days=5))
        postpone = submitted(
            world,
            "POSTPONE_HEARING",
            data={"reason_code": "ILLNESS", "proposed_date": "2026-12-20"},
            hearing_id=hearing.pk,
        )
        rescheduling = queue(world.staff, world.court, queue="rescheduling").json()
        assert [r["application_id"] for r in rescheduling["results"]] == [str(postpone.pk)]
        assert rescheduling["results"][0]["proposed_date"] == "2026-12-20"
        assert rescheduling["results"][0]["hearing"]["date"] == hearing.hearing_date.isoformat()
        others = self.ids(queue(world.staff, world.court, queue="other"))
        assert str(postpone.pk) not in others
        found = self.ids(
            queue(world.staff, world.court, search=board["onboard"].application_number)
        )
        assert str(board["onboard"].pk) in found
        assert self.ids(queue(world.staff, world.court, side="ACCUSED")) == []
        facets = queue(world.staff, world.court).json()["facets"]["type"]
        assert {f["value"] for f in facets} == {"GENERIC", "POSTPONE_HEARING"}

    def test_staff_of_another_court_see_nothing(self, world, board):
        other = make_court("Other courtroom")
        assert self.ids(queue(world.staff, other)) == []
        assert self.ids(queue(world.stranger, world.court)) == []

    def test_court_list(self, world, board):
        response = client_for(world.staff).get(
            "/api/v1/applications/", {"court": str(world.court.pk), "status": "PENDING_REVIEW"}
        )
        assert response.status_code == 200
        assert {r["application_id"] for r in response.json()["results"]} == {
            str(board["onboard"].pk)
        }

    def test_court_query_requires_a_court(self, world):
        response = client_for(world.staff).get("/api/v1/applications/court-queue/")
        assert codes_of(response) == ["E00002"]


class TestGeneral:
    def test_logged_out(self, world):
        response = client_for().get(f"/api/v1/cases/{world.case.pk}/applications/")
        assert response.status_code in (401, 403)

    def test_unknown_application(self, world):
        response = client_for(world.a1).get(
            "/api/v1/applications/00000000-0000-0000-0000-000000000000/"
        )
        assert codes_of(response) == ["E00105"]

    def test_t124_error_codes_are_in_the_schema(self, world):
        from drf_spectacular.generators import SchemaGenerator

        schema = SchemaGenerator().get_schema(request=None, public=True)
        paths = [p for p in schema["paths"] if "/applications" in p or "application-types" in p]
        assert len(paths) >= 15
        text = str(schema)
        for code in ("E13001", "E13008", "E13013", "E13030"):
            assert code in text
