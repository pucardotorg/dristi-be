"""The processes API (spec 0028 #11): routes, access, shapes, errors.

Errors are asserted by ``code`` and ``field``, never by message (spec 0000 #13).
"""

import pytest
from rest_framework.test import APIClient

from apps.processes import court_actions as actions
from apps.processes.enums import ProcessStatus

from .factories import accused, make_staff, mark_signed, recipient, start

BASE = "/api/v1"


def client_for(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


def error(response):
    first = response.json()["errors"][0]
    return first["code"], first.get("field")


@pytest.fixture
def processes(case):
    return start(case, recipient(accused(case), "SMS", "RPAD"))


class TestList:
    def test_court_staff_list_their_courtroom(self, staff, courtroom, processes):
        response = client_for(staff).get(f"{BASE}/processes/", {"court": courtroom.pk})

        assert response.status_code == 200
        rows = response.json()["results"]
        assert [row["channel"]["code"] for row in rows] == ["SMS", "RPAD"]
        rpad = rows[1]
        assert rpad["allowed_actions"] == ["receive_envelope", "recall"]
        assert rpad["hearing"]["date_at_issue"] == rpad["hearing"]["current_date"] == "2026-11-20"
        assert rpad["case"]["display_number"].startswith("CC/")
        assert rpad["fee"] == {"court_fee": "2.00", "paid": False, "paid_at": None}

    def test_my_move_keeps_what_the_caller_can_do_next(self, courtroom, processes):
        receiver = make_staff(actions.RECEIVE_ENVELOPE)
        query = {"court": courtroom.pk, "my_move": "true"}

        rows = client_for(receiver).get(f"{BASE}/processes/", query).json()["results"]

        assert [row["channel"]["code"] for row in rows] == ["RPAD"]

    def test_filters(self, staff, courtroom, processes):
        query = {"court": courtroom.pk, "channel": ["SMS"], "status": [ProcessStatus.PENDING_STEPS]}

        rows = client_for(staff).get(f"{BASE}/processes/", query).json()["results"]

        assert [row["channel"]["code"] for row in rows] == ["SMS"]

    def test_someone_not_on_the_courtroom_is_told_it_does_not_exist(self, stranger, courtroom):
        response = client_for(stranger).get(f"{BASE}/processes/", {"court": courtroom.pk})

        assert (response.status_code, error(response)) == (404, ("E00105", None))

    def test_counts(self, staff, courtroom, processes):
        body = client_for(staff).get(f"{BASE}/processes/counts/", {"court": courtroom.pk}).json()

        assert body["by_status"] == {ProcessStatus.PENDING_STEPS: 2}
        assert body["by_channel"] == {"SMS": 1, "RPAD": 1}
        assert body["my_moves"] == 1


class TestOneProcess:
    def test_a_party_reads_it_with_no_actions(self, complainant_user, processes):
        response = client_for(complainant_user).get(f"{BASE}/processes/{processes[0].pk}/")

        assert response.status_code == 200
        body = response.json()
        assert body["allowed_actions"] == []
        assert [event["to_status"] for event in body["events"]] == [ProcessStatus.PENDING_STEPS]

    def test_a_stranger_is_told_it_does_not_exist(self, stranger, processes):
        response = client_for(stranger).get(f"{BASE}/processes/{processes[0].pk}/")

        assert response.status_code == 404

    def test_envelope(self, staff, processes):
        rpad = processes[1]

        response = client_for(staff).post(f"{BASE}/processes/{rpad.pk}/envelope/")

        assert response.status_code == 200
        assert response.json()["allowed_actions"] == ["recall"]

    def test_a_step_without_its_action(self, processes):
        sender = make_staff(actions.SEND)

        response = client_for(sender).post(f"{BASE}/processes/{processes[1].pk}/envelope/")

        assert (response.status_code, error(response)) == (403, ("E12015", None))

    def test_outcome_needs_a_reason(self, staff, processes):
        rpad = mark_signed(processes[1])
        client_for(staff).post(f"{BASE}/processes/{rpad.pk}/send/", {}, format="json")

        response = client_for(staff).post(
            f"{BASE}/processes/{rpad.pk}/outcome/",
            {"status": ProcessStatus.NOT_DELIVERED},
            format="json",
        )

        assert (response.status_code, error(response)) == (400, ("E12014", "reason"))


class TestRecall:
    def test_recalls_and_reports_skipped(self, staff, processes):
        response = client_for(staff).post(
            f"{BASE}/processes/recall/",
            {"process_ids": [str(p.pk) for p in processes], "comment": "Bail granted."},
            format="json",
        )

        assert response.status_code == 200
        body = response.json()
        assert len(body["recalled"]) == 2
        assert body["skipped"] == []

    def test_a_process_the_caller_cannot_see(self, stranger, processes):
        response = client_for(stranger).post(
            f"{BASE}/processes/recall/", {"process_ids": [str(processes[0].pk)]}, format="json"
        )

        assert response.status_code == 404


class TestRegister:
    def test_by_person_then_round_and_type(self, complainant_user, case, processes):
        response = client_for(complainant_user).get(f"{BASE}/cases/{case.pk}/processes/")

        assert response.status_code == 200
        (entry,) = response.json()["data"]
        assert entry["recipient"]["name"] == processes[0].recipient_name
        (group,) = entry["groups"]
        assert group["process_type"]["code"] == "SUMMONS"
        assert [p["channel"]["code"] for p in group["processes"]] == ["SMS", "RPAD"]

    def test_empty_before_any_process(self, complainant_user, case):
        response = client_for(complainant_user).get(f"{BASE}/cases/{case.pk}/processes/")

        assert (response.status_code, response.json()["data"]) == (200, [])


class TestMasters:
    def test_process_types_offer_only_available_channels(self, stranger):
        types = client_for(stranger).get(f"{BASE}/process-types/").json()["data"]

        summons = next(each for each in types if each["code"] == "SUMMONS")
        assert {channel["code"] for channel in summons["channels"]} == {
            "SMS",
            "RPAD",
            "POLICE_RPAD",
            "POLICE_ICOPS",
        }

    def test_non_delivery_reasons_of_the_state(self, stranger):
        reasons = client_for(stranger).get(f"{BASE}/non-delivery-reasons/").json()["data"]

        assert reasons[0] == {"code": "ADDRESSEE_NOT_AVAILABLE", "label": "Addressee not available"}
