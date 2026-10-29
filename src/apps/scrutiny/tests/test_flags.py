"""ScrutinyFlag constraints and consistency rules (spec 0024 #3.2, #3.5, #10)."""

import uuid

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.utils import timezone

from apps.cases.models import Case
from apps.cases.services.case_types import CaseType
from apps.scrutiny.enums import DocumentIssue, FlagStatus, FlagTarget, RoundDecision
from apps.scrutiny.models import ScrutinyFlag, ScrutinyRound

pytestmark = pytest.mark.django_db

User = get_user_model()


@pytest.fixture
def officer():
    return User.objects.create_user(mobile_number="+919000000001", name="Officer")


@pytest.fixture
def case(officer):
    return Case.objects.create(case_type=CaseType.CHEQUE_BOUNCE, created_by=officer)


def make_round(case, number=1, **kwargs):
    return ScrutinyRound.objects.create(
        case=case,
        stage="SCRUTINY",
        number=number,
        visit_id=uuid.uuid4(),
        establishment_id=uuid.uuid4(),
        **kwargs,
    )


def next_round(round_, officer):
    """Send the round back and open the case's next one."""
    round_.decision = RoundDecision.SENT_BACK
    round_.decided_by, round_.decided_at = officer, timezone.now()
    round_.save()
    return make_round(round_.case, number=round_.number + 1)


@pytest.fixture
def round_(case):
    return make_round(case)


def make_flag(round_, **kwargs):
    defaults = {
        "round": round_,
        "target_type": FlagTarget.FIELD,
        "target_ref": "CHQ-9[0]",
        "target_label": "Cheque return date",
        "section_id": "CHQ",
        "note": "Does not match the return memo.",
        "status": FlagStatus.DRAFT,
    }
    return ScrutinyFlag.objects.create(**{**defaults, **kwargs})


def document(round_, **kwargs):
    defaults = {
        "target_type": FlagTarget.DOCUMENT,
        "target_ref": str(uuid.uuid4()),
        "target_label": "Return memo",
        "section_id": "DCM",
        "reason_code": DocumentIssue.BLURRY_UNREADABLE,
        "note": "",
    }
    return make_flag(round_, **{**defaults, **kwargs})


def error_fields(excinfo):
    return set(excinfo.value.message_dict)


def test_each_target_type_saves(round_, officer):
    field = make_flag(round_, value_at_flag=5205000)
    make_flag(round_, target_type=FlagTarget.SECTION, target_ref="LDN", section_id="LDN")
    doc = document(round_, linked_flag=field)
    make_flag(round_, target_type=FlagTarget.OATH, target_ref=str(uuid.uuid4()), section_id="")
    assert round_.flags.count() == 4
    assert doc.linked_flag == field


def test_one_live_flag_per_target(round_):
    make_flag(round_)
    with pytest.raises(ValidationError) as excinfo:
        make_flag(round_)
    assert "__all__" in error_fields(excinfo)
    with pytest.raises(IntegrityError):
        ScrutinyFlag.objects.bulk_create(
            [ScrutinyFlag(round=round_, target_type="FIELD", target_ref="CHQ-9[0]", status="DRAFT")]
        )


def test_withdrawn_flag_frees_the_target(round_, officer):
    make_flag(round_, status=FlagStatus.WITHDRAWN)
    make_flag(round_, status=FlagStatus.WITHDRAWN)
    make_flag(round_)
    # The same target may be flagged in another round.
    make_flag(next_round(round_, officer))


@pytest.mark.parametrize(
    "fields, field",
    [
        ({"section_id": ""}, "section_id"),
        ({"target_type": FlagTarget.OATH, "section_id": "OTH"}, "section_id"),
        ({"note": "  "}, "note"),
        ({"target_type": FlagTarget.SECTION, "note": ""}, "note"),
        ({"target_type": FlagTarget.OATH, "section_id": "", "note": ""}, "note"),
        ({"reason_code": DocumentIssue.PAGE_MISSING}, "reason_code"),
        ({"target_type": FlagTarget.SECTION, "value_at_flag": "x"}, "value_at_flag"),
    ],
)
def test_target_rules(round_, fields, field):
    with pytest.raises(ValidationError) as excinfo:
        make_flag(round_, **fields)
    assert field in error_fields(excinfo)


def test_document_needs_reason_or_note(round_):
    with pytest.raises(ValidationError) as excinfo:
        document(round_, reason_code="")
    assert "note" in error_fields(excinfo)
    document(round_, reason_code="", note="Page 2 is from another cheque.")
    document(round_)


@pytest.mark.parametrize(
    "fields",
    [
        {"status": FlagStatus.RESOLVED},
        {"resolved_at": "now"},
    ],
)
def test_resolved_fields_set_exactly_when_resolved(round_, fields):
    fields = {k: timezone.now() if v == "now" else v for k, v in fields.items()}
    with pytest.raises(ValidationError) as excinfo:
        make_flag(round_, **fields)
    assert {"resolved_by", "resolved_at"} & error_fields(excinfo)


def test_auto_marked_by_links_field_flags_of_the_same_round(round_, officer):
    source = make_flag(round_, target_ref="CHQ-8[0]")
    make_flag(round_, auto_marked_by=source, note="Marked because presentation was flagged")
    section = make_flag(round_, target_type=FlagTarget.SECTION, target_ref="CHQ")
    for bad in ({"auto_marked_by": section, "target_ref": "LDN-2[0]"},):
        with pytest.raises(ValidationError) as excinfo:
            make_flag(round_, **{"target_ref": "LDN-6[0]", **bad})
        assert "auto_marked_by" in error_fields(excinfo)
    with pytest.raises(ValidationError) as excinfo:
        make_flag(next_round(round_, officer), target_ref="LDN-6[0]", auto_marked_by=source)
    assert "auto_marked_by" in error_fields(excinfo)


def test_deleting_source_deletes_auto_marked_flags(round_):
    source = make_flag(round_, target_ref="CHQ-8[0]")
    child = make_flag(round_, auto_marked_by=source)
    source.delete()
    assert not ScrutinyFlag.objects.filter(pk=child.pk).exists()


def test_linked_flag_pairs_field_and_document(round_):
    field = make_flag(round_)
    section = make_flag(round_, target_type=FlagTarget.SECTION, target_ref="LDN", section_id="LDN")
    with pytest.raises(ValidationError) as excinfo:
        make_flag(round_, target_ref="CHQ-1[0]", linked_flag=field)
    assert "linked_flag" in error_fields(excinfo)
    with pytest.raises(ValidationError) as excinfo:
        document(round_, linked_flag=section)
    assert "linked_flag" in error_fields(excinfo)

    doc = document(round_, linked_flag=field)
    # Removing one side keeps the other (#3.5).
    field.delete()
    doc.refresh_from_db()
    assert doc.linked_flag is None


def test_carried_from_same_target_in_another_round_of_the_case(round_, officer):
    first = make_flag(round_, status=FlagStatus.CARRIED)
    second_round = next_round(round_, officer)
    make_flag(second_round, carried_from=first)

    other_case = Case.objects.create(case_type=CaseType.CHEQUE_BOUNCE, created_by=officer)
    for target_round, fields in (
        (round_, {"target_ref": "CHQ-1[0]"}),
        (second_round, {"target_ref": "CHQ-1[0]"}),
        (make_round(other_case), {}),
    ):
        with pytest.raises(ValidationError) as excinfo:
            make_flag(target_round, carried_from=first, **fields)
        assert "carried_from" in error_fields(excinfo)


def test_carried_chain_protects_the_original(round_, officer):
    first = make_flag(round_, status=FlagStatus.CARRIED)
    make_flag(next_round(round_, officer), carried_from=first)
    with pytest.raises(Exception, match="protected"):
        first.delete()


def test_status_change_is_in_history(round_, officer):
    flag = make_flag(round_)
    flag.status = FlagStatus.RAISED
    flag.save()
    flag.status = FlagStatus.RESOLVED
    flag.resolved_by, flag.resolved_at = officer, timezone.now()
    flag.save()
    assert list(flag.history.values_list("status", flat=True)) == ["RESOLVED", "RAISED", "DRAFT"]
