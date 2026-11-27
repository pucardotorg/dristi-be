"""The processes API (spec 0028 #11): routes, access, shapes, errors.

Errors are asserted by ``code`` and ``field``, never by message (spec 0000 #13).
"""

import datetime

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from apps.core.models import Configuration
from apps.hearings.tests.factories import make_case, make_user, schedule
from apps.locations.models import Location
from apps.locations.tests.factories import make_location, make_police_station
from apps.processes import conf
from apps.processes import court_actions as actions
from apps.processes.enums import ProcessStatus
from apps.processes.models import NonDeliveryReason, Process, ProcessType
from apps.processes.services import dispatch, expiry

from .conftest import HEARING_DAY
from .factories import (
    accused,
    add_mobile,
    address_ids,
    make_staff,
    mark_signed,
    recipient,
    start,
)

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
        assert rpad["item_fields"] == {}

    def test_rows_show_the_order_item_s_fields(self, staff, courtroom, case):
        fields = {"warrant_type": "BAILABLE", "bond_amount": "5000", "sureties": 1}
        start(
            case, recipient(accused(case), "BY_HAND"), item_code="ISSUE_OF_WARRANTS", fields=fields
        )

        (row,) = (
            client_for(staff).get(f"{BASE}/processes/", {"court": courtroom.pk}).json()["results"]
        )

        assert row["item_fields"] == {
            "warrant_type": "BAILABLE",
            "bond_amount": "5000.00",
            "sureties": 1,
        }

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
        assert body["by_status_channel"] == {ProcessStatus.PENDING_STEPS: {"SMS": 1, "RPAD": 1}}
        assert body["my_moves"] == 1

    def test_counts_split_a_status_by_channel(self, staff, courtroom, processes):
        """*To post* is SIGNED on RPAD; an SMS signed with it is not a cover to post."""
        for process in processes:
            mark_signed(process)

        body = client_for(staff).get(f"{BASE}/processes/counts/", {"court": courtroom.pk}).json()

        assert body["by_status_channel"] == {ProcessStatus.SIGNED: {"SMS": 1, "RPAD": 1}}

    def test_counts_split_by_hand_by_type(self, staff, courtroom, case):
        """*To publish* and *To hand over* are both SIGNED by hand; the type tells them apart."""
        for item_code in ("ISSUE_OF_PROCLAMATION", "ISSUE_OF_WARRANTS"):
            for process in start(case, recipient(accused(case), "BY_HAND"), item_code=item_code):
                mark_signed(process)

        body = client_for(staff).get(f"{BASE}/processes/counts/", {"court": courtroom.pk}).json()

        signed = ProcessStatus.SIGNED
        assert body["breakdown"] == [
            {"status": signed, "channel": "BY_HAND", "process_type": code, "count": 1}
            for code in ("PROCLAMATION", "WARRANT")
        ]
        assert body["by_status_channel"] == {signed: {"BY_HAND": 2}}

    def test_send_act_names_the_screen_s_button(self, staff, courtroom, case):
        start(case, recipient(accused(case), "SMS", "RPAD"))
        for item_code in ("ISSUE_OF_PROCLAMATION", "ISSUE_OF_WARRANTS"):
            start(case, recipient(accused(case), "BY_HAND"), item_code=item_code)

        rows = client_for(staff).get(f"{BASE}/processes/", {"court": courtroom.pk}).json()

        assert {
            (row["process_type"]["code"], row["channel"]["code"]): row["send_act"]
            for row in rows["results"]
        } == {
            ("SUMMONS", "SMS"): "send",
            ("SUMMONS", "RPAD"): "mark_posted",
            ("PROCLAMATION", "BY_HAND"): "mark_published",
            ("WARRANT", "BY_HAND"): "mark_handed_over",
        }

    def test_sorted_by_the_hearing_s_current_date(self, staff, courtroom, case, processes):
        later = make_case(courtroom, complainant_user=make_user(name="Another complainant"))
        add_mobile(accused(later))
        schedule(later, HEARING_DAY + datetime.timedelta(days=7))
        (other,) = start(later, recipient(accused(later), "SMS"))
        # The first case's hearing moves past the other's.
        moved_to = HEARING_DAY + datetime.timedelta(days=14)
        expiry.follow_hearing(hearing_id=processes[0].hearing_id, hearing_date=moved_to)
        query = {"court": courtroom.pk, "ordering": "hearing_date"}

        rows = client_for(staff).get(f"{BASE}/processes/", query).json()["results"]

        assert [row["id"] for row in rows][0] == str(other.pk)
        assert rows[-1]["hearing"]["date_at_issue"] == HEARING_DAY.isoformat()

    @pytest.mark.parametrize(
        ("flag", "value", "channels"),
        [
            ("envelope_due", "true", ["RPAD"]),
            ("envelope_due", "false", ["SMS"]),
            ("fee_paid", "false", ["SMS", "RPAD"]),
            ("fee_paid", "true", []),
        ],
    )
    def test_step_filters(self, staff, courtroom, processes, flag, value, channels):
        query = {"court": courtroom.pk, flag: value}

        rows = client_for(staff).get(f"{BASE}/processes/", query).json()["results"]

        assert [row["channel"]["code"] for row in rows] == channels

    def test_an_envelope_received_is_no_longer_due(self, staff, courtroom, processes):
        client_for(staff).post(f"{BASE}/processes/{processes[1].pk}/envelope/")
        query = {"court": courtroom.pk, "envelope_due": "true"}

        rows = client_for(staff).get(f"{BASE}/processes/", query).json()["results"]

        assert rows == []

    def test_rows_carry_each_stage_time(self, staff, courtroom, processes):
        client_for(staff).post(f"{BASE}/processes/{processes[1].pk}/envelope/")

        rows = client_for(staff).get(f"{BASE}/processes/", {"court": courtroom.pk}).json()
        rpad = rows["results"][1]

        assert rpad["envelope_received_at"] is not None
        assert (rpad["signed_at"], rpad["sent_at"]) == (None, None)


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
        assert len(body["done"]) == 2
        assert body["skipped"] == []

    def test_a_process_the_caller_cannot_see(self, stranger, processes):
        response = client_for(stranger).post(
            f"{BASE}/processes/recall/", {"process_ids": [str(processes[0].pk)]}, format="json"
        )

        assert response.status_code == 404


def ids(processes):
    return [str(process.pk) for process in processes]


class TestBulk:
    """Steps on a selection: all or nothing on access, skipped where they no longer apply."""

    def test_receive_a_pile_of_envelopes(self, staff, processes):
        response = client_for(staff).post(
            f"{BASE}/processes/envelope/", {"process_ids": ids(processes)}, format="json"
        )

        assert response.status_code == 200
        body = response.json()
        assert [row["channel"]["code"] for row in body["done"]] == ["RPAD"]
        assert [row["channel"]["code"] for row in body["skipped"]] == ["SMS"]

    def test_mark_a_selection_sent(self, staff, processes):
        signed = [mark_signed(process) for process in processes]

        response = client_for(staff).post(
            f"{BASE}/processes/send/", {"process_ids": ids(signed)}, format="json"
        )

        assert response.status_code == 200
        assert {row["status"] for row in response.json()["done"]} == {ProcessStatus.SENT}

    def test_one_process_without_the_action_refuses_them_all(self, case, processes):
        signed = [mark_signed(process) for process in processes]
        receiver = make_staff(actions.RECEIVE_ENVELOPE)

        response = client_for(receiver).post(
            f"{BASE}/processes/send/", {"process_ids": ids(signed)}, format="json"
        )

        assert (response.status_code, error(response)) == (403, ("E12015", None))
        statuses = Process.objects.filter(pk__in=[p.pk for p in signed]).values_list("status")
        assert set(statuses) == {(ProcessStatus.SIGNED,)}

    def test_an_unseen_process_refuses_them_all(self, stranger, processes):
        response = client_for(stranger).post(
            f"{BASE}/processes/envelope/", {"process_ids": ids(processes)}, format="json"
        )

        assert response.status_code == 404

    def test_too_many(self, staff, processes):
        Configuration.objects.create(
            config_set="processes", config_key="bulk_max", config_value="1"
        )

        response = client_for(staff).post(
            f"{BASE}/processes/envelope/", {"process_ids": ids(processes)}, format="json"
        )

        assert (response.status_code, error(response)) == (400, ("E12016", "process_ids"))

    def test_a_process_listed_twice(self, staff, processes):
        response = client_for(staff).post(
            f"{BASE}/processes/envelope/",
            {"process_ids": ids(processes[:1]) * 2},
            format="json",
        )

        assert (response.status_code, error(response)[1]) == (400, "process_ids")

    def sent(self, staff, processes):
        signed = [mark_signed(process) for process in processes]
        client_for(staff).post(
            f"{BASE}/processes/send/", {"process_ids": ids(signed)}, format="json"
        )
        return signed

    def test_record_a_pile_of_returns_on_one_date(self, staff, processes):
        sms, rpad = self.sent(staff, processes)
        outcomes = [
            {
                "process_id": str(rpad.pk),
                "status": ProcessStatus.NOT_DELIVERED,
                "reason": "REFUSED",
            },
            {"process_id": str(sms.pk), "status": ProcessStatus.DELIVERED},
        ]

        returned_on = conf.court_date().isoformat()

        response = client_for(staff).post(
            f"{BASE}/processes/outcome/",
            {"outcome_date": returned_on, "outcomes": outcomes},
            format="json",
        )

        assert response.status_code == 200
        body = response.json()
        (done,) = body["done"]
        assert (done["status"], done["reason"]["code"]) == (ProcessStatus.NOT_DELIVERED, "REFUSED")
        assert done["outcome_date"] == returned_on
        # SMS reports its own outcome.
        assert [row["channel"]["code"] for row in body["skipped"]] == ["SMS"]

    def test_a_refused_return_names_its_place_and_records_none(self, staff, processes):
        _, rpad = self.sent(staff, processes)
        outcomes = [{"process_id": str(rpad.pk), "status": ProcessStatus.NOT_DELIVERED}]

        response = client_for(staff).post(
            f"{BASE}/processes/outcome/", {"outcomes": outcomes}, format="json"
        )

        assert (response.status_code, error(response)) == (400, ("E12014", "outcomes[0].reason"))
        rpad.refresh_from_db()
        assert rpad.status == ProcessStatus.SENT


class TestOutcomeFile:
    """A return's supporting file, stored through ``apps.files`` (``DSP-08``)."""

    def sent(self, staff, process):
        process = mark_signed(process)
        client_for(staff).post(f"{BASE}/processes/{process.pk}/send/", {}, format="json")
        return process

    def upload(self, user, process, name="card.pdf", content=b"%PDF-1.4 card"):
        upload = SimpleUploadedFile(name, content, content_type="application/pdf")
        return client_for(user).post(
            f"{BASE}/processes/{process.pk}/outcome-file/", {"file": upload}, format="multipart"
        )

    def test_upload_then_record_with_it(self, staff, processes):
        rpad = self.sent(staff, processes[1])

        uploaded = self.upload(staff, rpad)
        assert uploaded.status_code == 201
        file_id = uploaded.json()["file_id"]
        response = client_for(staff).post(
            f"{BASE}/processes/{rpad.pk}/outcome/",
            {"status": ProcessStatus.DELIVERED, "file_id": file_id},
            format="json",
        )

        assert response.status_code == 200
        assert response.json()["outcome_file_id"] == file_id

    def test_a_file_of_another_process_is_refused(self, staff, case, processes):
        rpad = self.sent(staff, processes[1])
        (other,) = start(case, recipient(accused(case), "RPAD"))
        file_id = self.upload(staff, self.sent(staff, other)).json()["file_id"]

        response = client_for(staff).post(
            f"{BASE}/processes/{rpad.pk}/outcome/",
            {"status": ProcessStatus.DELIVERED, "file_id": file_id},
            format="json",
        )

        assert (response.status_code, error(response)) == (400, ("E12019", "file_id"))

    def test_not_a_document(self, staff, processes):
        rpad = self.sent(staff, processes[1])

        response = self.upload(staff, rpad, name="card.pdf", content=b"not a pdf")

        assert (response.status_code, error(response)[1]) == (400, "file")

    def test_only_where_the_outcome_can_be_recorded(self, staff, processes):
        response = self.upload(staff, processes[1])  # not sent yet

        assert (response.status_code, error(response)[0]) == (409, "E12001")


class TestOrderRecipients:
    def url(self, case):
        return f"{BASE}/cases/{case.pk}/process-recipients/"

    def test_recipients_with_destinations_and_defaults(self, staff, case):
        response = client_for(staff).get(self.url(case))

        assert response.status_code == 200
        rows = {row["type"]: row for row in response.json()["data"]}
        accused_row = rows["ACCUSED"]
        assert accused_row["preselected"] is True
        assert accused_row["party_taking_steps"] == "COMPLAINANT"
        assert accused_row["mobiles"] == ["+919812345678"]
        assert [a["address_id"] for a in accused_row["addresses"]] == [
            str(each) for each in address_ids(accused(case))
        ]
        assert rows["COMPLAINANT"]["preselected"] is False
        assert rows["COMPLAINANT"]["party_taking_steps"] == "ACCUSED"

    def test_nothing_preselected_once_the_accused_has_joined(self, staff, case):
        person = accused(case).person
        person.user = make_staff(name="Accused")
        person.save(update_fields=["user"])

        rows = client_for(staff).get(self.url(case)).json()["data"]

        assert not any(row["preselected"] for row in rows)

    def test_the_police_station_of_an_earlier_round_is_prefilled(self, staff, case):
        kerala = make_location(
            code="IN_KERALA", name="Kerala", location_type=Location.LocationType.STATE
        )
        station = make_police_station(kerala)
        start(
            case,
            recipient(accused(case), "POLICE_RPAD", police_station=station.code),
            item_code="ISSUE_OF_WARRANTS",
        )

        rows = {row["type"]: row for row in client_for(staff).get(self.url(case)).json()["data"]}

        assert rows["ACCUSED"]["police_station"] == {"code": station.code, "name": station.name}
        assert rows["COMPLAINANT"]["police_station"] is None

    def test_a_party_cannot_read_the_contacts(self, complainant_user, case):
        response = client_for(complainant_user).get(self.url(case))

        assert (response.status_code, error(response)) == (404, ("E00105", None))


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

        assert reasons[0] == {
            "code": "ADDRESSEE_NOT_AVAILABLE",
            "label": "Addressee not available",
            "process_types": [],
        }


class TestReasonsPerType:
    @pytest.fixture
    def absconding(self):
        reason = NonDeliveryReason.objects.create(
            state_code="KL", code="ABSCONDING", label="Absconding", sequence=10
        )
        reason.process_types.set([ProcessType.objects.get(code="WARRANT")])
        return reason

    @pytest.mark.parametrize(("process_type", "listed"), [("WARRANT", True), ("SUMMONS", False)])
    def test_the_list_for_a_type(self, stranger, absconding, process_type, listed):
        response = client_for(stranger).get(
            f"{BASE}/non-delivery-reasons/", {"process_type": process_type}
        )

        codes = [reason["code"] for reason in response.json()["data"]]
        assert ("ABSCONDING" in codes) is listed
        assert "REFUSED" in codes  # names no type, so is for every type

    def test_an_outcome_takes_only_a_reason_for_its_type(self, staff, processes, absconding):
        rpad = mark_signed(processes[1])
        dispatch.send(process_id=rpad.pk, actor=staff)
        body = {"status": ProcessStatus.NOT_DELIVERED, "reason": "ABSCONDING"}

        response = client_for(staff).post(f"{BASE}/processes/{rpad.pk}/outcome/", body)

        assert (response.status_code, error(response)) == (400, ("E12014", "reason"))
