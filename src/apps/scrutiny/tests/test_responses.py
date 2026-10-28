"""ScrutinyFlagResponse consistency rules (spec 0024 #3.6, #5.2, #10)."""

import uuid

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db.models import ProtectedError
from django.utils import timezone

from apps.cases.models import Case
from apps.cases.services.case_types import CaseType
from apps.scrutiny.enums import DocumentIssue, FlagStatus, FlagTarget, ResponseKind
from apps.scrutiny.models import ScrutinyFlag, ScrutinyFlagResponse, ScrutinyRound

pytestmark = pytest.mark.django_db

User = get_user_model()


@pytest.fixture
def filer():
    return User.objects.create_user(mobile_number="+919000000002", name="Filer")


@pytest.fixture
def round_(filer):
    case = Case.objects.create(case_type=CaseType.CHEQUE_BOUNCE, created_by=filer)
    return ScrutinyRound.objects.create(
        case=case,
        stage="SCRUTINY",
        number=1,
        visit_id=uuid.uuid4(),
        establishment_id=uuid.uuid4(),
    )


def make_flag(round_, target_type=FlagTarget.FIELD, **kwargs):
    defaults = {
        FlagTarget.FIELD: {"target_ref": "CHQ-2[0]", "section_id": "CHQ", "note": "Check."},
        FlagTarget.SECTION: {"target_ref": "LDN", "section_id": "LDN", "note": "Check."},
        FlagTarget.DOCUMENT: {
            "target_ref": str(uuid.uuid4()),
            "section_id": "DCM",
            "reason_code": DocumentIssue.BLURRY_UNREADABLE,
        },
        FlagTarget.OATH: {"target_ref": str(uuid.uuid4()), "note": "Inaudible."},
    }[target_type]
    return ScrutinyFlag.objects.create(
        round=round_,
        target_type=target_type,
        target_label="Item",
        status=FlagStatus.RAISED,
        **{**defaults, **kwargs},
    )


@pytest.fixture
def field_flag(round_):
    return make_flag(round_)


def respond(flag, user, **kwargs):
    defaults = {"kind": ResponseKind.CORRECTED, "value_after": 5025000}
    return ScrutinyFlagResponse.objects.create(
        flag=flag, responded_by=user, responded_at=timezone.now(), **{**defaults, **kwargs}
    )


def error_fields(excinfo):
    return set(excinfo.value.message_dict)


def test_each_kind_saves(round_, field_flag, filer):
    respond(field_flag, filer)
    respond(make_flag(round_, FlagTarget.SECTION), filer, value_after={"LDN-2": "2026-03-20"})
    respond(
        make_flag(round_, FlagTarget.DOCUMENT),
        filer,
        kind=ResponseKind.REUPLOADED,
        value_after=None,
        document_id=uuid.uuid4(),
    )
    respond(
        make_flag(round_, FlagTarget.OATH),
        filer,
        kind=ResponseKind.EXPLAINED,
        value_after=None,
        note="Recorded again at re-signing.",
    )
    assert ScrutinyFlagResponse.objects.count() == 4


def test_several_responses_last_one_wins(field_flag, filer):
    respond(field_flag, filer, value_after=5205001)
    respond(field_flag, filer, value_after=5025000)
    assert field_flag.responses.last().value_after == 5025000


def test_correction_may_clear_the_value(field_flag, filer):
    respond(field_flag, filer, value_after=None)


@pytest.mark.parametrize(
    "fields, field",
    [
        ({"kind": ResponseKind.EXPLAINED, "value_after": None, "note": " "}, "note"),
        ({"kind": ResponseKind.EXPLAINED, "note": "No change needed."}, "value_after"),
        ({"document_id": uuid.uuid4()}, "document_id"),
    ],
)
def test_payload_matches_kind(field_flag, filer, fields, field):
    with pytest.raises(ValidationError) as excinfo:
        respond(field_flag, filer, **fields)
    assert field in error_fields(excinfo)


def test_reupload_needs_the_new_document(round_, filer):
    with pytest.raises(ValidationError) as excinfo:
        respond(
            make_flag(round_, FlagTarget.DOCUMENT),
            filer,
            kind=ResponseKind.REUPLOADED,
            value_after=None,
        )
    assert "document_id" in error_fields(excinfo)


@pytest.mark.parametrize(
    "target_type, kind",
    [
        (FlagTarget.DOCUMENT, ResponseKind.CORRECTED),
        (FlagTarget.OATH, ResponseKind.CORRECTED),
        (FlagTarget.FIELD, ResponseKind.REUPLOADED),
        (FlagTarget.SECTION, ResponseKind.REUPLOADED),
    ],
)
def test_kind_matches_the_flag_target(round_, filer, target_type, kind):
    fields = {"kind": kind}
    if kind == ResponseKind.REUPLOADED:
        fields.update(value_after=None, document_id=uuid.uuid4())
    with pytest.raises(ValidationError) as excinfo:
        respond(make_flag(round_, target_type), filer, **fields)
    assert "kind" in error_fields(excinfo)


def test_deleting_the_flag_deletes_its_responses(field_flag, filer):
    respond(field_flag, filer)
    field_flag.delete()
    assert not ScrutinyFlagResponse.objects.exists()


def test_responder_cannot_be_deleted(field_flag, filer):
    respond(field_flag, filer)
    with pytest.raises(ProtectedError):
        filer.delete()
