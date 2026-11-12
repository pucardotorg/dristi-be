"""The hearings API (spec 0023 #10): routes, access, shapes, errors.

Errors are asserted by ``code`` and ``field``, never by message (spec 0000 #13).
"""

import email.utils
import uuid

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.cases.selectors import get_attendance_roll
from apps.hearings.enums import HearingRole
from apps.hearings.models import BulkRescheduleJob, CourtCalendarEntry
from apps.hearings.services import courtroom as court_service

from .factories import FRI, MON, SUN, TODAY, TUE, WED, hold, make_case, make_user, schedule

pytestmark = pytest.mark.django_db


def client_for(user=None):
    client = APIClient()
    if user is not None:
        client.force_authenticate(user)
    return client


def errors_of(response):
    return [(error["code"], error.get("field")) for error in response.json()["errors"]]


def http_date(moment):
    return email.utils.format_datetime(moment, usegmt=True)


@pytest.fixture
def hearing(case):
    return schedule(case, TODAY)


# Routes


def test_routes():
    hid, cid = uuid.uuid4(), uuid.uuid4()
    assert reverse("hearing-list") == "/api/v1/hearings/"
    assert reverse("hearing-detail", args=[hid]) == f"/api/v1/hearings/{hid}/"
    assert reverse("hearing-pass-over", args=[hid]) == f"/api/v1/hearings/{hid}/pass-over/"
    assert reverse("hearing-reorder") == "/api/v1/hearings/board/reorder/"
    assert reverse("hearing-scheduling-queue") == "/api/v1/hearings/scheduling-queue/"
    assert reverse("hearing-bulk-reschedule-preview") == "/api/v1/hearings/bulk-reschedule/preview/"
    assert reverse("hearing-purpose-list") == "/api/v1/hearing-purposes/"
    assert reverse("court-hearings-calendar", args=[cid]) == f"/api/v1/courts/{cid}/calendar/"
    assert (
        reverse("court-hearings-business-date", args=[cid])
        == f"/api/v1/courts/{cid}/business-date/"
    )
    assert reverse("case-hearings-list", args=[cid]) == f"/api/v1/cases/{cid}/hearings/"
    assert reverse("case-hearings-next", args=[cid]) == f"/api/v1/cases/{cid}/hearings/next/"


# Reads


class TestPurposesAndBusinessDate:
    def test_purposes_for_any_registered_user(self, stranger):
        response = client_for(stranger).get(reverse("hearing-purpose-list"))
        assert response.status_code == 200
        body = response.json()
        assert "meta" in body
        assert [p["sequence"] for p in body["data"]] == sorted(p["sequence"] for p in body["data"])

    def test_logged_out(self):
        response = client_for().get(reverse("hearing-purpose-list"))
        assert response.status_code == 403
        assert errors_of(response) == [("E00102", None)]

    def test_registration_unfinished(self, stranger):
        stranger.registration_status = "PENDING_PROFILE"
        stranger.save()
        response = client_for(stranger).get(reverse("hearing-purpose-list"))
        assert errors_of(response) == [("E01006", None)]

    def test_business_date(self, courtroom, stranger):
        response = client_for(stranger).get(
            reverse("court-hearings-business-date", args=[courtroom.pk])
        )
        assert response.status_code == 200
        assert response.json()["business_date"] == TODAY.isoformat()
        missing = client_for(stranger).get(
            reverse("court-hearings-business-date", args=[uuid.uuid4()])
        )
        assert errors_of(missing) == [("E00105", None)]


class TestDetail:
    def test_court_staff(self, hearing, controller):
        response = client_for(controller).get(reverse("hearing-detail", args=[hearing.pk]))
        assert response.status_code == 200
        body = response.json()
        assert body["allowed_actions"] == ["start", "pass_over"]
        assert body["heard_duration"] == "PT0S"
        assert {"attendance", "date_changes", "previous_hearing", "next_hearing", "meta"} <= set(
            body
        )
        assert body["case"]["display_number"] == hearing.case.case_number

    def test_party_reads_without_actions(self, hearing, complainant_user, advocate_user):
        for user in (complainant_user, advocate_user):
            body = client_for(user).get(reverse("hearing-detail", args=[hearing.pk])).json()
            assert "allowed_actions" not in body

    def test_party_never_sees_a_hold(self, case, complainant_user, controller):
        held = hold(case, MON).hearing
        assert (
            client_for(complainant_user).get(reverse("hearing-detail", args=[held.pk])).status_code
            == 404
        )
        assert (
            client_for(controller).get(reverse("hearing-detail", args=[held.pk])).status_code == 200
        )

    @pytest.mark.parametrize("who", ["stranger", "scrutiny_officer", "other_court_staff"])
    def test_others_get_not_found(self, hearing, stranger, who, foreign_court):
        user = {
            "stranger": stranger,
            "scrutiny_officer": make_user("SCRUTINY_OFFICER"),
            "other_court_staff": make_user(*HearingRole.values),
        }[who]
        if who == "other_court_staff":
            hearing = schedule(make_case(foreign_court), TODAY)
        response = client_for(user).get(reverse("hearing-detail", args=[hearing.pk]))
        assert (response.status_code, errors_of(response)) == (404, [("E00105", None)])


class TestBoard:
    def test_board(self, case, other_case, controller, courtroom):
        schedule(case, TODAY)
        schedule(other_case, MON)
        response = client_for(controller).get(reverse("hearing-list"), {"court": courtroom.pk})
        assert response.status_code == 200
        body = response.json()
        assert body["count"] == 1 and "meta" in body
        assert body["results"][0]["hearing_date"] == TODAY.isoformat()

    def test_court_required_and_staff_only(
        self, complainant_user, controller, courtroom, foreign_court
    ):
        assert errors_of(client_for(controller).get(reverse("hearing-list"))) == [
            ("E00002", "court")
        ]
        assert errors_of(
            client_for(complainant_user).get(reverse("hearing-list"), {"court": courtroom.pk})
        ) == [("E10018", None)]
        assert errors_of(
            client_for(controller).get(reverse("hearing-list"), {"court": foreign_court.pk})
        ) == [("E10018", None)]

    @pytest.mark.parametrize(
        ("params", "expected"),
        [
            ({"status": "NOPE"}, ("E00005", "status[0]")),
            ({"has_order": "DRAFTING"}, ("E00001", "has_order")),
            ({"stage": "ARGUMENTS"}, ("E00001", "stage")),
            ({"ordering": "wrong"}, ("E00005", "ordering")),
            ({"date_from": "2026-11-20", "date_to": "2026-11-16"}, ("E00001", "date_to")),
            ({"date_from": "2026-11-01", "date_to": "2027-03-01"}, ("E00001", "date_to")),
            ({"beyond_trial_target": "maybe"}, ("E00001", "beyond_trial_target")),
        ],
    )
    def test_invalid_filters(self, controller, courtroom, params, expected):
        response = client_for(controller).get(
            reverse("hearing-list"), {"court": courtroom.pk, **params}
        )
        assert response.status_code == 400
        assert errors_of(response)[0] == expected

    def test_whole_day_page(self, courtroom, controller):
        for _ in range(3):
            schedule(make_case(courtroom), TODAY)
        body = (
            client_for(controller)
            .get(reverse("hearing-list"), {"court": courtroom.pk, "page_size": 2})
            .json()
        )
        assert (len(body["results"]), body["count"]) == (2, 3)
        body = (
            client_for(controller)
            .get(reverse("hearing-list"), {"court": courtroom.pk, "page_size": 500})
            .json()
        )
        assert len(body["results"]) == 3 and body["next"] is None


class TestCurrent:
    def test_etag_and_304(self, hearing, controller, courtroom):
        url = reverse("hearing-current")
        client = client_for(controller)
        first = client.get(url, {"court": courtroom.pk})
        assert first.json()["data"] == []
        etag = first["ETag"]
        unchanged = client.get(url, {"court": courtroom.pk}, HTTP_IF_NONE_MATCH=etag)
        assert unchanged.status_code == 304 and unchanged.content == b""
        court_service.start(hearing_id=hearing.pk)
        changed = client.get(url, {"court": courtroom.pk}, HTTP_IF_NONE_MATCH=etag)
        assert changed.status_code == 200
        assert [h["id"] for h in changed.json()["data"]] == [str(hearing.pk)]
        assert changed["ETag"] != etag


class TestCountsQueueCalendarCase:
    def test_counts_and_queue(self, case, other_case, controller, courtroom):
        schedule(case, TODAY)
        counts = (
            client_for(controller).get(reverse("hearing-counts"), {"court": courtroom.pk}).json()
        )
        assert counts["by_status"]["SCHEDULED"] == 1
        queue = (
            client_for(controller)
            .get(reverse("hearing-scheduling-queue"), {"court": courtroom.pk})
            .json()
        )
        assert [item["case"]["id"] for item in queue["results"]] == [str(other_case.pk)]
        assert queue["count"] == counts["scheduling_queue"]

    def test_calendar(self, case, controller, courtroom):
        schedule(case, WED)
        response = client_for(controller).get(
            reverse("court-hearings-calendar", args=[courtroom.pk]),
            {"from": MON.isoformat(), "to": SUN.isoformat()},
        )
        days = {day["date"]: day for day in response.json()["data"]}
        assert days[WED.isoformat()]["listed"] == 1
        assert days[SUN.isoformat()]["sitting"] is False
        default = client_for(controller).get(
            reverse("court-hearings-calendar", args=[courtroom.pk])
        )
        assert len(default.json()["data"]) == 30

    def test_case_hearings(self, case, complainant_user, controller, stranger):
        listed = schedule(case, MON)
        held = hold(case, TUE).hearing
        party = (
            client_for(complainant_user).get(reverse("case-hearings-list", args=[case.pk])).json()
        )
        staff = client_for(controller).get(reverse("case-hearings-list", args=[case.pk])).json()
        assert [h["id"] for h in party["results"]] == [str(listed.pk)]
        assert {h["id"] for h in staff["results"]} == {str(listed.pk), str(held.pk)}
        assert (
            client_for(stranger).get(reverse("case-hearings-list", args=[case.pk])).status_code
            == 404
        )
        tile = (
            client_for(complainant_user).get(reverse("case-hearings-next", args=[case.pk])).json()
        )
        assert tile["hearing"]["id"] == str(listed.pk)


# Actions


class TestCourtroomActions:
    def test_tiers(self, hearing, filler, complainant_user, stranger):
        url = reverse("hearing-start", args=[hearing.pk])
        assert errors_of(client_for(filler).post(url)) == [("E10025", None)]
        assert errors_of(client_for(complainant_user).post(url)) == [("E10018", None)]
        assert errors_of(client_for(stranger).post(url)) == [("E00105", None)]

    def test_start_pass_over_end(self, hearing, controller):
        client = client_for(controller)
        started = client.post(reverse("hearing-start", args=[hearing.pk]))
        assert (started.status_code, started.json()["status"]) == (200, "IN_PROGRESS")
        assert (
            client.post(reverse("hearing-pass-over", args=[hearing.pk])).json()["status"]
            == "PASSED_OVER"
        )
        client.post(reverse("hearing-start", args=[hearing.pk]))
        ended = client.post(
            reverse("hearing-end", args=[hearing.pk]),
            {"adjournment_sought_by": "ACCUSED"},
            format="json",
        ).json()
        assert (ended["status"], ended["adjournment_sought_by"], ended["allowed_actions"]) == (
            "COMPLETED",
            "ACCUSED",
            [],
        )
        again = client.post(reverse("hearing-end", args=[hearing.pk]))
        assert errors_of(again) == [("E10001", None)]

    def test_end_validates_the_side(self, hearing, controller):
        court_service.start(hearing_id=hearing.pk)
        response = client_for(controller).post(
            reverse("hearing-end", args=[hearing.pk]),
            {"adjournment_sought_by": "JUDGE"},
            format="json",
        )
        assert errors_of(response) == [("E00005", "adjournment_sought_by")]

    def test_start_not_today(self, case, controller):
        future = schedule(case, MON)
        assert errors_of(
            client_for(controller).post(reverse("hearing-start", args=[future.pk]))
        ) == [("E10010", None)]

    def test_if_unmodified_since(self, hearing, controller):
        url = reverse("hearing-start", args=[hearing.pk])
        client = client_for(controller)
        stale = hearing.updated_at.replace(year=hearing.updated_at.year - 1)
        assert errors_of(client.post(url, HTTP_IF_UNMODIFIED_SINCE=http_date(stale))) == [
            ("E10002", None)
        ]
        assert errors_of(client.post(url, HTTP_IF_UNMODIFIED_SINCE="yesterday")) == [
            ("E00001", None)
        ]
        ok = client.post(url, HTTP_IF_UNMODIFIED_SINCE=http_date(hearing.updated_at))
        assert ok.status_code == 200

    def test_methods(self, hearing, controller):
        client = client_for(controller)
        assert client.post(reverse("hearing-list"), {}).status_code == 405
        assert client.delete(reverse("hearing-detail", args=[hearing.pk])).status_code == 405
        assert client.get(reverse("hearing-start", args=[hearing.pk])).status_code == 405

    def test_bulk_action_skips_offer_only_the_callers_actions(
        self, case, other_case, controller, courtroom
    ):
        waiting = schedule(case, TODAY)
        passed = schedule(other_case, TODAY)
        court_service.pass_over(hearing_id=passed.pk)
        response = client_for(controller).post(
            reverse("hearing-bulk-action"),
            {
                "court": str(courtroom.pk),
                "hearing_ids": [str(waiting.pk), str(passed.pk)],
                "action": "END",
            },
            format="json",
        )
        body = response.json()
        assert [d["hearing_id"] for d in body["done"]] == [str(waiting.pk)]
        assert body["skipped"] == [
            {"hearing_id": str(passed.pk), "code": "E10001", "allowed_actions": ["start"]}
        ]

    @pytest.mark.parametrize(
        ("payload", "expected"),
        [
            ({"hearing_ids": []}, ("E00013", "hearing_ids")),
            ({"action": "START"}, ("E00005", "action")),
        ],
    )
    def test_bulk_action_shape(self, hearing, controller, courtroom, payload, expected):
        body = {
            "court": str(courtroom.pk),
            "hearing_ids": [str(hearing.pk)],
            "action": "END",
            **payload,
        }
        response = client_for(controller).post(reverse("hearing-bulk-action"), body, format="json")
        assert errors_of(response)[0] == expected

    def test_reorder(self, case, other_case, controller, setter, courtroom):
        first, second = schedule(case, TODAY), schedule(other_case, TODAY)
        url = reverse("hearing-reorder")
        body = {
            "court": str(courtroom.pk),
            "hearing_date": TODAY.isoformat(),
            "hearing_ids": [str(second.pk), str(first.pk)],
        }
        assert errors_of(client_for(setter).post(url, body, format="json")) == [("E10025", None)]
        response = client_for(controller).post(url, body, format="json")
        assert [h["id"] for h in response.json()["data"]] == [str(second.pk), str(first.pk)]
        partial = client_for(controller).post(
            url, {**body, "hearing_ids": [str(first.pk)]}, format="json"
        )
        assert errors_of(partial) == [("E10019", "hearing_ids")]


class TestAttendance:
    def test_marks(self, case, hearing, filler, controller):
        court_service.start(hearing_id=hearing.pk)
        roll = get_attendance_roll(case.pk)
        marks = [
            {
                "attendee_type": e.type,
                "participant_id": str(e.participant_id),
                "mark": "PRESENT",
                "appearance_mode": "IN_PERSON",
            }
            for e in roll
        ]
        url = reverse("hearing-attendance", args=[hearing.pk])
        assert errors_of(client_for(controller).put(url, {"marks": marks}, format="json")) == [
            ("E10025", None)
        ]
        response = client_for(filler).put(url, {"marks": marks}, format="json")
        assert response.status_code == 200
        assert response.json()["attendance"]["complete"] is True
        assert response.json()["attendance"]["line"].startswith("Present:")

    @pytest.mark.parametrize(
        ("change", "expected"),
        [
            ({"participant_id": "00000000-0000-0000-0000-000000000000"}, ("E10011", "marks[0]")),
            ({"appearance_mode": ""}, ("E00001", "marks[0].appearance_mode")),
            ({"mark": "LATE"}, ("E00005", "marks[0].mark")),
        ],
    )
    def test_invalid_marks(self, case, hearing, filler, change, expected):
        court_service.start(hearing_id=hearing.pk)
        entry = get_attendance_roll(case.pk)[0]
        mark = {
            "attendee_type": entry.type,
            "participant_id": str(entry.participant_id),
            "mark": "PRESENT",
            "appearance_mode": "IN_PERSON",
            **change,
        }
        response = client_for(filler).put(
            reverse("hearing-attendance", args=[hearing.pk]), {"marks": [mark]}, format="json"
        )
        assert errors_of(response)[0] == expected

    def test_not_started(self, hearing, filler):
        response = client_for(filler).put(
            reverse("hearing-attendance", args=[hearing.pk]), {"marks": []}, format="json"
        )
        assert errors_of(response) == [("E10022", None)]


class TestMoves:
    def test_reschedule(self, case, setter, controller):
        hearing = schedule(case, MON)
        url = reverse("hearing-reschedule", args=[hearing.pk])
        body = {"hearing_date": WED.isoformat(), "reason_code": "PRESIDING_OFFICER_ON_LEAVE"}
        assert errors_of(client_for(controller).post(url, body, format="json")) == [
            ("E10025", None)
        ]
        response = client_for(setter).post(url, body, format="json")
        assert response.status_code == 200
        data = response.json()
        assert (data["hearing_date"], data["reschedule_count"], data["warnings"]) == (
            WED.isoformat(),
            1,
            [],
        )

    @pytest.mark.parametrize(
        ("body", "expected"),
        [
            (
                {"hearing_date": "2026-11-18", "reason_code": "PARTY_APPLICATION"},
                ("E10013", "reason_code"),
            ),
            (
                {"hearing_date": "2026-11-16", "reason_code": "NOT_REACHED"},
                ("E10012", "hearing_date"),
            ),
            (
                {"hearing_date": "2026-11-22", "reason_code": "NOT_REACHED"},
                ("E10006", "hearing_date"),
            ),
            (
                {"hearing_date": "2026-11-18", "purpose": "NOPE", "reason_code": "NOT_REACHED"},
                ("E10014", "purpose"),
            ),
            ({"reason_code": "NOT_REACHED"}, ("E00002", "hearing_date")),
        ],
    )
    def test_reschedule_errors(self, case, setter, body, expected):
        hearing = schedule(case, MON)
        response = client_for(setter).post(
            reverse("hearing-reschedule", args=[hearing.pk]), body, format="json"
        )
        assert errors_of(response)[0] == expected

    def test_cancel(self, case, setter, controller):
        hearing = schedule(case, MON)
        url = reverse("hearing-cancel", args=[hearing.pk])
        assert errors_of(client_for(controller).post(url)) == [("E10025", None)]
        body = client_for(setter).post(url).json()
        assert (body["status"], body["cancellation_reason"]) == ("CANCELLED", "LISTED_IN_ERROR")
        assert errors_of(client_for(setter).post(url)) == [("E10001", None)]

    def test_bulk_reschedule(
        self,
        case,
        other_case,
        setter,
        controller,
        stranger,
        courtroom,
        django_capture_on_commit_callbacks,
    ):
        hearings = [schedule(case, MON), schedule(other_case, MON)]
        body = {
            "court": str(courtroom.pk),
            "hearing_ids": [str(h.pk) for h in hearings],
            "mode": "TO_DATE",
            "target_date": FRI.isoformat(),
            "reason_code": "PRESIDING_OFFICER_ON_LEAVE",
        }
        url = reverse("hearing-bulk-reschedule-preview")
        assert errors_of(client_for(controller).post(url, body, format="json")) == [
            ("E10025", None)
        ]
        preview = client_for(setter).post(url, body, format="json").json()
        assert preview["status"] == "PREVIEWED" and len(preview["lines"]) == 2
        job_url = reverse("hearing-bulk-reschedule-detail", args=[preview["job_id"]])
        assert client_for(controller).get(job_url).status_code == 200
        assert client_for(stranger).get(job_url).status_code == 404
        confirm_url = reverse("hearing-bulk-reschedule-confirm", args=[preview["job_id"]])
        with django_capture_on_commit_callbacks(execute=False):
            confirmed = client_for(setter).post(confirm_url)
        assert (confirmed.status_code, confirmed.json()["status"]) == (202, "QUEUED")
        assert errors_of(client_for(setter).post(confirm_url)) == [("E10016", None)]

    def test_bulk_reschedule_refusals(self, case, setter, courtroom):
        hearing = schedule(case, MON)
        url = reverse("hearing-bulk-reschedule-preview")
        base = {
            "court": str(courtroom.pk),
            "hearing_ids": [str(hearing.pk)],
            "mode": "TO_DATE",
            "target_date": FRI.isoformat(),
            "reason_code": "NOT_REACHED",
        }
        cases = [
            ({"reason_code": "PARTY_APPLICATION"}, ("E10013", "reason_code")),
            ({"hearing_ids": [str(uuid.uuid4())]}, ("E00105", "hearing_ids")),
            ({"target_date": None}, ("E00001", "target_date")),
            ({"target_date": SUN.isoformat()}, ("E10006", "target_date")),
            ({"hearing_ids": []}, ("E00013", "hearing_ids")),
        ]
        for change, expected in cases:
            response = client_for(setter).post(url, {**base, **change}, format="json")
            assert errors_of(response)[0] == expected, change
        assert not BulkRescheduleJob.objects.exists()


class TestCalendarEntries:
    def test_create_and_delete(self, setter, controller, courtroom):
        url = reverse("court-hearings-entries", args=[courtroom.pk])
        body = {"date": FRI.isoformat(), "entry_type": "HOLIDAY", "reason": "Onam"}
        assert errors_of(client_for(controller).post(url, body, format="json")) == [
            ("E10025", None)
        ]
        created = client_for(setter).post(url, body, format="json")
        assert created.status_code == 201
        entry_id = created.json()["id"]
        delete_url = reverse("court-hearings-calendar-entry", args=[courtroom.pk, entry_id])
        assert client_for(setter).delete(delete_url).status_code == 204
        assert client_for(setter).delete(delete_url).status_code == 404
        assert not CourtCalendarEntry.objects.exists()

    @pytest.mark.parametrize(
        ("body", "expected"),
        [
            ({"date": "2026-11-02", "entry_type": "HOLIDAY", "reason": "x"}, ("E10005", "date")),
            (
                {"date": "2026-11-20", "entry_type": "REDUCED_SITTING", "reason": "x"},
                ("E00001", "capacity_override"),
            ),
            (
                {
                    "date": "2026-11-20",
                    "entry_type": "HOLIDAY",
                    "reason": "x",
                    "capacity_override": 3,
                },
                ("E00001", "capacity_override"),
            ),
            (
                {"date": "2026-11-20", "entry_type": "FESTIVAL", "reason": "x"},
                ("E00005", "entry_type"),
            ),
        ],
    )
    def test_refusals(self, setter, courtroom, body, expected):
        response = client_for(setter).post(
            reverse("court-hearings-entries", args=[courtroom.pk]), body, format="json"
        )
        assert errors_of(response)[0] == expected

    def test_busy_day(self, case, setter, courtroom):
        schedule(case, FRI)
        response = client_for(setter).post(
            reverse("court-hearings-entries", args=[courtroom.pk]),
            {"date": FRI.isoformat(), "entry_type": "HOLIDAY", "reason": "x"},
            format="json",
        )
        assert errors_of(response) == [("E10017", "date")]


def test_schema_documents_the_hearings_errors(stranger):
    response = client_for(stranger).get("/api/schema/?format=json")
    schema = response.json()
    assert all(f"E100{n:02d}" in schema["info"]["description"] for n in range(1, 26))
    hearings_ops = [
        op
        for path, item in schema["paths"].items()
        if "/hearings" in path or path.startswith(("/api/v1/hearing-purposes", "/api/v1/courts/"))
        for method, op in item.items()
        if method in ("get", "post", "put", "delete")
    ]
    assert len(hearings_ops) == 23
    assert all(op["tags"] == ["hearings"] for op in hearings_ops)
