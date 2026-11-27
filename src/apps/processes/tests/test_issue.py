"""Starting processes from an order item (spec 0028 #5, #6)."""

import uuid
from decimal import Decimal

import pytest

from apps.api.errors import BusinessError
from apps.cases.models import CaseContact, ContactType, ParticipantRole
from apps.locations.models import Location
from apps.locations.tests.factories import make_location, make_police_station
from apps.payments.models import DemandItem
from apps.processes import conf
from apps.processes.enums import DestinationKind, ProcessStatus, RecipientType, Side
from apps.processes.models import Process, ProcessEvent, ProcessRound

from .conftest import HEARING_DAY
from .factories import (
    MOBILE,
    accused,
    add_mobile,
    party,
    pay_fees,
    prepay,
    recipient,
    start,
)


def refusal(case, *recipients, **kwargs):
    with pytest.raises(BusinessError) as caught:
        start(case, *recipients, **kwargs)
    detail = caught.value.detail
    return caught.value.error.code, next(iter(detail)) if isinstance(detail, dict) else None


@pytest.fixture
def station():
    kerala = make_location(
        code="IN_KERALA", name="Kerala", location_type=Location.LocationType.STATE
    )
    return make_police_station(kerala)


class TestFanOut:
    def test_one_process_per_channel_and_destination(self, case):
        processes = start(case, recipient(accused(case), "SMS", "RPAD"))

        assert [(p.channel.code, p.destination_kind) for p in processes] == [
            ("SMS", DestinationKind.MOBILE),
            ("RPAD", DestinationKind.POSTAL),
        ]
        sms, rpad = processes
        assert sms.mobile == MOBILE
        assert rpad.address_id is not None
        assert {p.round_id for p in processes} == {processes[0].round_id}
        assert all(p.recipient_type == RecipientType.ACCUSED for p in processes)

    def test_a_postal_channel_fans_out_per_address(self, case):
        target = accused(case)
        added = {"line1": "2 Beach Road", "city": "Kochi", "state": "Kerala", "pincode": "682001"}
        processes = start(
            case,
            recipient(
                target, "RPAD", new_destinations=[{"kind": DestinationKind.POSTAL, "value": added}]
            ),
        )

        assert len(processes) == 2
        assert [p.destination_added for p in processes] == [False, True]
        on_record = CaseContact.objects.filter(
            case_participant=target, contact_type=ContactType.ADDRESS, is_active=True
        )
        assert on_record.count() == 2

    def test_an_added_mobile_is_saved_to_the_record(self, case):
        target = party(case, ParticipantRole.COMPLAINANT)
        (process,) = start(
            case,
            recipient(
                target,
                "SMS",
                new_destinations=[{"kind": DestinationKind.MOBILE, "value": "+919800000001"}],
            ),
        )

        assert (process.mobile, process.destination_added) == ("+919800000001", True)
        assert CaseContact.objects.filter(
            case_participant=target, contact_type=ContactType.MOBILE_NUMBER, value="+919800000001"
        ).exists()

    def test_a_police_channel_goes_to_the_station(self, case, station):
        (process,) = start(
            case,
            recipient(accused(case), "POLICE_ICOPS", police_station=station.code),
            item_code="ISSUE_OF_WARRANTS",
        )

        assert process.police_station == station
        assert process.status_label == "Pending steps"  # its ₹2 fee is due

    def test_the_party_taking_steps_defaults_to_the_other_side(self, case):
        (process,) = start(case, recipient(accused(case), "SMS"))

        assert process.party_taking_steps == Side.COMPLAINANT

    def test_the_round_takes_the_cases_next_hearing(self, case):
        (process,) = start(case, recipient(accused(case), "SMS"))

        assert process.round.hearing_date == HEARING_DAY
        assert process.expires_at == conf.start_of(HEARING_DAY)

    def test_a_redelivered_trigger_creates_nothing(self, case):
        item = uuid.uuid4()
        first = start(case, recipient(accused(case), "SMS"), order_item_id=item)
        again = start(case, recipient(accused(case), "SMS"), order_item_id=item)

        assert again == first
        assert Process.objects.count() == 1
        assert ProcessRound.objects.count() == 1

    def test_creation_is_recorded_as_an_event(self, case):
        (process,) = start(case, recipient(accused(case), "SMS"))

        event = ProcessEvent.objects.get(process=process)
        assert (event.from_status, event.to_status) == ("", process.status)


class TestValidation:
    def test_a_type_may_not_name_this_recipient(self, case):
        complainant = party(case, ParticipantRole.COMPLAINANT)
        code, field = refusal(
            case, recipient(complainant, "BY_HAND"), item_code="ISSUE_OF_PROCLAMATION"
        )

        assert (code, field) == ("E12002", "values.recipients[0].recipient_id")

    def test_someone_not_on_the_case(self, case):
        code, field = refusal(case, {"recipient_id": str(uuid.uuid4()), "channels": ["SMS"]})

        assert (code, field) == ("E12002", "values.recipients[0].recipient_id")

    @pytest.mark.parametrize(
        ("item_code", "channel"),
        [
            ("ISSUE_OF_NOTICE", "POLICE_ICOPS"),  # not allowed for notice
            ("ISSUE_OF_SUMMONS", "EMAIL"),  # not available in Kerala at launch
            ("ISSUE_OF_SUMMONS", "FAX"),  # no such channel
        ],
    )
    def test_a_channel_not_allowed(self, case, item_code, channel):
        code, field = refusal(case, recipient(accused(case), channel), item_code=item_code)

        assert (code, field) == ("E12003", "values.recipients[0].channels[0]")

    def test_no_channel(self, case):
        code, field = refusal(case, recipient(accused(case)))

        assert (code, field) == ("E12003", "values.recipients[0].channels")

    def test_no_destination_of_the_channels_kind(self, case):
        complainant = party(case, ParticipantRole.COMPLAINANT)
        code, field = refusal(case, recipient(complainant, "SMS"))

        assert (code, field) == ("E12004", "values.recipients[0].channels")

    def test_an_address_not_on_the_record(self, case):
        values = recipient(accused(case), "RPAD", addresses=[str(uuid.uuid4())])
        code, field = refusal(case, values)

        assert (code, field) == ("E12004", "values.recipients[0].addresses[0]")

    @pytest.mark.parametrize("station_code", [None, "NOT_A_STATION"])
    def test_a_police_channel_needs_a_station_from_the_master(self, case, station_code):
        values = recipient(accused(case), "POLICE_RPAD", police_station=station_code)
        code, field = refusal(case, values, item_code="ISSUE_OF_WARRANTS")

        assert (code, field) == ("E12005", "values.recipients[0].police_station")

    def test_an_invalid_added_destination_writes_nothing(self, case):
        added = [{"kind": DestinationKind.MOBILE, "value": "12345"}]
        code, field = refusal(case, recipient(accused(case), "SMS", new_destinations=added))

        assert (code, field) == ("E12017", "values.recipients[0].new_destinations[0]")
        assert not Process.objects.exists()
        assert not ProcessRound.objects.exists()


class TestItemFields:
    """The item's other fields ride on every process it starts (``TPL-03``, ``TPL-04``)."""

    def test_every_process_of_the_item_carries_them(self, case):
        fields = {"notice_type": "DELAY_CONDONATION", "process_type_detail": ""}

        processes = start(
            case,
            recipient(accused(case), "SMS", "RPAD"),
            item_code="ISSUE_OF_NOTICE",
            fields=fields,
        )

        assert len(processes) == 2
        assert all(p.item_fields == {"notice_type": "DELAY_CONDONATION"} for p in processes)

    def test_a_bailable_warrant_keeps_its_bond_and_sureties(self, case):
        fields = {"warrant_type": "BAILABLE", "bond_amount": 10000, "sureties": 2}

        (process,) = start(
            case, recipient(accused(case), "BY_HAND"), item_code="ISSUE_OF_WARRANTS", fields=fields
        )

        assert process.item_fields == {
            "warrant_type": "BAILABLE",
            "bond_amount": "10000.00",
            "sureties": 2,
        }

    @pytest.mark.parametrize(
        ("fields", "field"),
        [
            ({}, "warrant_type"),
            ({"warrant_type": "MAYBE"}, "warrant_type"),
            ({"warrant_type": "BAILABLE", "sureties": 2}, "bond_amount"),
            ({"warrant_type": "BAILABLE", "bond_amount": "0", "sureties": 2}, "bond_amount"),
            ({"warrant_type": "BAILABLE", "bond_amount": "lots", "sureties": 2}, "bond_amount"),
            ({"warrant_type": "BAILABLE", "bond_amount": "500"}, "sureties"),
            ({"warrant_type": "BAILABLE", "bond_amount": "500", "sureties": 0}, "sureties"),
            ({"warrant_type": "BAILABLE", "bond_amount": "500", "sureties": "2"}, "sureties"),
            ({"warrant_type": "NON_BAILABLE", "bond_amount": "500"}, "bond_amount"),
            ({"warrant_type": "NON_BAILABLE", "sureties": 1}, "sureties"),
        ],
    )
    def test_a_warrant_s_fields_are_checked(self, case, fields, field):
        code, path = refusal(
            case,
            recipient(accused(case), "BY_HAND"),
            item_code="ISSUE_OF_WARRANTS",
            fields=fields,
        )

        assert (code, path) == ("E12020", f"values.{field}")
        assert not Process.objects.exists()


class TestFees:
    def test_without_a_pool_each_process_gets_a_demand_item(self, case):
        processes = start(case, recipient(accused(case), "SMS", "RPAD"))

        items = DemandItem.objects.filter(pk__in=[p.demand_item_id for p in processes])
        assert [p.court_fee for p in processes] == [Decimal("2.00")] * 2
        assert [p.fee_paid for p in processes] == [False, False]
        assert sorted(str(item.reference_id) for item in items) == sorted(
            str(p.pk) for p in processes
        )
        assert all(p.status == ProcessStatus.PENDING_STEPS for p in processes)

    def test_a_type_with_no_fee_needs_no_payment(self, case):
        (process,) = start(
            case, recipient(accused(case), "BY_HAND"), item_code="ISSUE_OF_PROCLAMATION"
        )

        assert (process.court_fee, process.fee_paid, process.demand_item_id) == (0, True, None)
        assert process.fee_paid_at is None
        assert process.status == ProcessStatus.PENDING_SIGNATURE

    def test_payment_moves_only_the_paid_process(self, case, complainant_user):
        sms, rpad = start(case, recipient(accused(case), "SMS", "RPAD"))

        pay_fees([sms, rpad], complainant_user)
        sms.refresh_from_db()
        rpad.refresh_from_db()

        assert sms.status == ProcessStatus.PENDING_SIGNATURE
        assert sms.fee_paid_at is not None
        # RPAD still waits for its envelope (STP-03).
        assert (rpad.fee_paid, rpad.status) == (True, ProcessStatus.PENDING_STEPS)

    def test_what_is_paid_for_one_process_is_not_drawn_again(self, case, complainant_user):
        first = start(case, recipient(accused(case), "SMS"))
        pay_fees(first, complainant_user)

        (later,) = start(case, recipient(accused(case), "SMS"))

        assert (later.fee_from_pool, later.fee_paid) == (0, False)

    def test_a_pool_left_over_covers_a_later_round(self, case, complainant_user):
        prepay(case, "3.00", complainant_user)
        complainant = party(case, ParticipantRole.COMPLAINANT)
        add_mobile(complainant, "+919800000002")

        to_accused, to_complainant = start(
            case, recipient(accused(case), "SMS"), recipient(complainant, "SMS")
        )

        assert (to_accused.fee_from_pool, to_accused.fee_paid) == (2, True)
        assert (to_complainant.fee_from_pool, to_complainant.fee_paid) == (1, False)
        assert DemandItem.objects.get(pk=to_complainant.demand_item_id).amount == 1
