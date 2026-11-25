"""Steps on a process: envelope, send, outcome, recall, expiry (spec 0028 #4, #7.1, #8)."""

import datetime

import pytest
from django.utils import timezone

from apps.api.errors import BusinessError
from apps.payments.enums import DemandItemStatus
from apps.payments.models import DemandItem
from apps.processes import conf
from apps.processes import court_actions as actions
from apps.processes.enums import EventSource, ProcessStatus
from apps.processes.models import ProcessEvent
from apps.processes.services import dispatch, expiry, steps

from .conftest import HEARING_DAY
from .factories import accused, make_staff, mark_signed, pay_fees, recipient, start


def code_of(call, **kwargs):
    with pytest.raises(BusinessError) as caught:
        call(**kwargs)
    return caught.value.error.code


def statuses(process):
    return list(ProcessEvent.objects.filter(process=process).values_list("to_status", flat=True))


@pytest.fixture
def rpad(case):
    return start(case, recipient(accused(case), "RPAD"))[0]


@pytest.fixture
def sent(rpad, staff):
    mark_signed(rpad)
    return dispatch.send(process_id=rpad.pk, actor=staff)


class TestEnvelope:
    @pytest.mark.parametrize("pay_first", [True, False])
    def test_fee_and_envelope_in_either_order(self, rpad, staff, complainant_user, pay_first):
        if pay_first:
            pay_fees([rpad], complainant_user)
        steps.receive_envelope(process_id=rpad.pk, actor=staff)
        if not pay_first:
            pay_fees([rpad], complainant_user)
        rpad.refresh_from_db()

        assert rpad.status == ProcessStatus.PENDING_SIGNATURE
        assert rpad.envelope_received_by == staff

    def test_a_channel_with_no_envelope(self, case, staff):
        (sms,) = start(case, recipient(accused(case), "SMS"))

        assert code_of(steps.receive_envelope, process_id=sms.pk, actor=staff) == "E12009"

    def test_only_once(self, rpad, staff):
        steps.receive_envelope(process_id=rpad.pk, actor=staff)

        assert code_of(steps.receive_envelope, process_id=rpad.pk, actor=staff) == "E12001"

    def test_needs_the_action(self, rpad):
        clerk = make_staff(actions.SEND)

        assert code_of(steps.receive_envelope, process_id=rpad.pk, actor=clerk) == "E12015"


class TestSend:
    def test_marks_a_manual_channel_sent(self, sent, staff):
        assert (sent.status, sent.sent_by) == (ProcessStatus.SENT, staff)
        assert statuses(sent)[-1] == ProcessStatus.SENT

    def test_only_when_signed(self, rpad, staff):
        assert code_of(dispatch.send, process_id=rpad.pk, actor=staff) == "E12001"

    def test_a_system_channel_is_not_marked_by_hand(self, case, staff):
        (sms,) = start(case, recipient(accused(case), "SMS"))
        mark_signed(sms)

        assert code_of(dispatch.send, process_id=sms.pk, actor=staff) == "E12001"

    def test_a_proclamation_by_hand_is_published_and_executed_at_once(self, case, staff):
        (process,) = start(
            case, recipient(accused(case), "BY_HAND"), item_code="ISSUE_OF_PROCLAMATION"
        )
        mark_signed(process)

        process = dispatch.send(process_id=process.pk, actor=staff, published=True)

        assert (process.status, process.status_label) == (ProcessStatus.DELIVERED, "Executed")
        assert statuses(process)[-2:] == [ProcessStatus.SENT, ProcessStatus.DELIVERED]

    def test_only_a_proclamation_is_published(self, sent, rpad, staff):
        mark_signed(rpad)

        assert code_of(dispatch.send, process_id=rpad.pk, actor=staff, published=True) == "E12001"


class TestOutcome:
    def test_not_delivered_with_a_reason(self, sent, staff):
        process = dispatch.record_outcome(
            process_id=sent.pk,
            actor=staff,
            status=ProcessStatus.NOT_DELIVERED,
            reason="REFUSED",
            comment="Refused at the door.",
        )

        assert (process.status, process.reason.code) == (ProcessStatus.NOT_DELIVERED, "REFUSED")
        assert process.outcome_date == conf.court_date()
        assert ProcessEvent.objects.filter(process=process).last().data == {"reason": "REFUSED"}

    @pytest.mark.parametrize("reason", ["", "NOT_A_REASON"])
    def test_a_negative_outcome_needs_a_listed_reason(self, sent, staff, reason):
        call = dispatch.record_outcome
        kwargs = {"status": ProcessStatus.NOT_DELIVERED, "reason": reason}

        assert code_of(call, process_id=sent.pk, actor=staff, **kwargs) == "E12014"

    @pytest.mark.parametrize("days", [1, -1])
    def test_the_date_is_between_sending_and_today(self, sent, staff, days):
        when = conf.court_date() + datetime.timedelta(days=days)
        call = dispatch.record_outcome

        code = code_of(
            call, process_id=sent.pk, actor=staff, status=ProcessStatus.DELIVERED, outcome_date=when
        )
        assert code == "E12018"

    def test_a_system_status_channel_reports_itself(self, case, staff):
        (sms,) = start(case, recipient(accused(case), "SMS"))
        mark_signed(sms, status=ProcessStatus.SENT, sent_at=timezone.now())

        code = code_of(
            dispatch.record_outcome, process_id=sms.pk, actor=staff, status=ProcessStatus.DELIVERED
        )
        assert code == "E12013"


class TestRecall:
    def test_recalls_and_cancels_the_unpaid_fee(self, rpad, staff):
        recalled, skipped = dispatch.recall(process_ids=[rpad.pk], actor=staff, comment="Bail.")

        rpad.refresh_from_db()
        assert ([p.pk for p in recalled], skipped) == ([rpad.pk], [])
        assert (rpad.status, rpad.remark) == (ProcessStatus.RECALLED, "Bail.")
        item = DemandItem.objects.get(pk=rpad.demand_item_id)
        assert item.status == DemandItemStatus.CANCELLED

    def test_skips_a_process_already_ended(self, sent, staff):
        dispatch.record_outcome(process_id=sent.pk, actor=staff, status=ProcessStatus.DELIVERED)

        recalled, skipped = dispatch.recall(process_ids=[sent.pk], actor=staff)

        assert (recalled, [p.pk for p in skipped]) == ([], [sent.pk])

    def test_all_or_nothing_on_access(self, case, rpad):
        sender = make_staff(actions.SEND)

        assert code_of(dispatch.recall, process_ids=[rpad.pk], actor=sender) == "E12015"
        rpad.refresh_from_db()
        assert rpad.status == ProcessStatus.PENDING_STEPS


class TestExpiry:
    def test_an_unsent_process_expires(self, rpad):
        rpad.expires_at = timezone.now() - datetime.timedelta(minutes=1)
        rpad.save(update_fields=["expires_at"])

        assert expiry.expire_due() == 1
        rpad.refresh_from_db()
        assert rpad.status == ProcessStatus.EXPIRED
        assert ProcessEvent.objects.filter(process=rpad).last().source == EventSource.SWEEP

    def test_a_sent_process_never_expires(self, sent):
        sent.expires_at = timezone.now() - datetime.timedelta(minutes=1)
        sent.save(update_fields=["expires_at"])

        assert expiry.expire_due() == 0

    def test_an_unsigned_process_follows_its_hearing(self, case):
        unsigned, signed = start(case, recipient(accused(case), "SMS", "RPAD"))
        mark_signed(signed)
        new_day = datetime.date(2026, 12, 4)

        expiry.follow_hearing(hearing_id=unsigned.hearing_id, hearing_date=new_day)

        unsigned.refresh_from_db()
        signed.refresh_from_db()
        assert unsigned.expires_at == conf.start_of(new_day)
        assert signed.expires_at == conf.start_of(HEARING_DAY)  # fixed on signing (EXP-01a)
