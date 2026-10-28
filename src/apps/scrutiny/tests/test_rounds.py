"""ScrutinyRound constraints and consistency rules (spec 0024 #3.1, #10)."""

import uuid

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.cases.models import Case
from apps.cases.services.case_types import CaseType
from apps.scrutiny.enums import RoundDecision, RoundStage, RoutingReason
from apps.scrutiny.models import ScrutinyRound

pytestmark = pytest.mark.django_db

User = get_user_model()


@pytest.fixture
def officer():
    return User.objects.create_user(mobile_number="+919000000001", name="Officer")


@pytest.fixture
def case(officer):
    return Case.objects.create(case_type=CaseType.CHEQUE_BOUNCE, created_by=officer)


ESTABLISHMENT_ID = uuid.uuid4()
COURTROOM_ID = uuid.uuid4()


def make_round(case, **kwargs):
    defaults = {
        "case": case,
        "establishment_id": ESTABLISHMENT_ID,
        "stage": RoundStage.SCRUTINY,
        "number": 1,
        "visit_id": uuid.uuid4(),
    }
    return ScrutinyRound.objects.create(**{**defaults, **kwargs})


def decided(user, decision, **kwargs):
    return {"decision": decision, "decided_by": user, "decided_at": timezone.now(), **kwargs}


def error_fields(excinfo):
    return set(excinfo.value.message_dict)


def test_full_lifecycle_saves(case, officer):
    """Scrutiny sent back, re-scrutiny forwarded, registration registered."""
    make_round(
        case,
        routing_reason=RoutingReason.RANDOM_CHECK,
        started_by=officer,
        started_at=timezone.now(),
        **decided(officer, RoundDecision.SENT_BACK),
    )
    make_round(
        case,
        number=2,
        routing_reason=RoutingReason.RESUBMITTED,
        courtroom_id=COURTROOM_ID,
        registration_type="ECC",
        **decided(
            officer,
            RoundDecision.FORWARDED,
            open_items_acknowledged=True,
            open_items_at_decision=2,
        ),
    )
    registration = make_round(
        case,
        stage=RoundStage.REGISTRATION,
        courtroom_id=COURTROOM_ID,
        registration_type="ECC",
    )
    assert registration.is_open
    registration.decision = RoundDecision.REGISTERED
    registration.decided_by = officer
    registration.decided_at = timezone.now()
    registration.save()

    assert list(case.scrutiny_rounds.values_list("stage", "number", "decision")) == [
        (RoundStage.SCRUTINY, 1, RoundDecision.SENT_BACK),
        (RoundStage.SCRUTINY, 2, RoundDecision.FORWARDED),
        (RoundStage.REGISTRATION, 1, RoundDecision.REGISTERED),
    ]
    assert registration.history.count() == 2


def test_one_open_round_per_case(case):
    make_round(case)
    with pytest.raises(ValidationError) as excinfo:
        make_round(case, stage=RoundStage.REGISTRATION)
    assert "__all__" in error_fields(excinfo)


def test_open_rounds_of_different_cases_coexist(case, officer):
    other = Case.objects.create(case_type=CaseType.CHEQUE_BOUNCE, created_by=officer)
    make_round(case)
    make_round(other)
    assert ScrutinyRound.objects.filter(decision="").count() == 2


def test_number_unique_per_case_and_stage(case, officer):
    make_round(case, **decided(officer, RoundDecision.SENT_BACK))
    with pytest.raises(ValidationError) as excinfo:
        make_round(case)
    assert "__all__" in error_fields(excinfo)


def test_visit_id_unique(case, officer):
    visit_id = uuid.uuid4()
    make_round(case, visit_id=visit_id, **decided(officer, "SENT_BACK"))
    with pytest.raises(ValidationError) as excinfo:
        make_round(case, number=2, visit_id=visit_id)
    assert "visit_id" in error_fields(excinfo)


def test_number_starts_at_one(case):
    with pytest.raises(ValidationError) as excinfo:
        make_round(case, number=0)
    assert "__all__" in error_fields(excinfo)


@pytest.mark.parametrize(
    "fields, field",
    [
        ({"decision": RoundDecision.SENT_BACK}, "decided_by"),
        ({"decided_at": "now"}, "decided_at"),
        ({"started_at": "now"}, "started_at"),
    ],
)
def test_paired_fields_set_together(case, fields, field):
    fields = {k: timezone.now() if v == "now" else v for k, v in fields.items()}
    with pytest.raises(ValidationError) as excinfo:
        make_round(case, **fields)
    assert field in error_fields(excinfo)


def test_registration_round_cannot_be_forwarded(case, officer):
    with pytest.raises(ValidationError) as excinfo:
        make_round(
            case,
            stage=RoundStage.REGISTRATION,
            **decided(officer, RoundDecision.FORWARDED),
        )
    assert "decision" in error_fields(excinfo)


@pytest.mark.parametrize(
    "fields",
    [
        {"open_items_acknowledged": True},
        {"open_items_acknowledged": True, "open_items_at_decision": 1},
    ],
)
def test_open_items_only_when_moving_on(case, officer, fields):
    with pytest.raises(ValidationError) as excinfo:
        make_round(case, **decided(officer, RoundDecision.SENT_BACK, **fields))
    assert "open_items_acknowledged" in error_fields(excinfo)


def test_open_items_need_acknowledgement(case, officer):
    with pytest.raises(ValidationError) as excinfo:
        make_round(
            case,
            **decided(officer, RoundDecision.REGISTERED, open_items_at_decision=1),
        )
    assert "open_items_acknowledged" in error_fields(excinfo)


def test_comment_only_on_registration_send_back(case, officer):
    with pytest.raises(ValidationError) as excinfo:
        make_round(case, comment="Fix it", **decided(officer, RoundDecision.SENT_BACK))
    assert "comment" in error_fields(excinfo)

    make_round(
        case,
        stage=RoundStage.REGISTRATION,
        comment="Fix it",
        **decided(officer, RoundDecision.SENT_BACK),
    )


@pytest.mark.parametrize("decision", ["", RoundDecision.SENT_BACK])
def test_scrutiny_court_chosen_only_at_forward_or_register(case, officer, decision):
    fields = decided(officer, decision) if decision else {}
    with pytest.raises(ValidationError) as excinfo:
        make_round(case, courtroom_id=COURTROOM_ID, registration_type="ECC", **fields)
    assert {"courtroom_id", "registration_type"} <= error_fields(excinfo)


def test_open_registration_round_carries_court(case):
    round_ = make_round(
        case,
        stage=RoundStage.REGISTRATION,
        courtroom_id=COURTROOM_ID,
        registration_type="ECC",
    )
    assert round_.is_open
