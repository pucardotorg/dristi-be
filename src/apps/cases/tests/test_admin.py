"""Tests for the cases admin."""

import pytest
from django.contrib.admin.sites import site
from django.test import RequestFactory

from apps.cases.models import (
    Case,
    CaseParticipant,
    CaseType,
    ChequeBounceCase,
    ParticipantRole,
    Witness,
    WitnessSide,
)
from apps.parties.models import Person

pytestmark = pytest.mark.django_db


class TestChequeBounceCaseAdmin:
    def readonly_fields(self, obj):
        request = RequestFactory().get("/")
        return site._registry[ChequeBounceCase].get_readonly_fields(request, obj)

    def test_case_is_editable_when_adding(self):
        assert "case" not in self.readonly_fields(None)

    def test_case_is_read_only_once_saved(self, user):
        case = Case.objects.create(case_type=CaseType.CHEQUE_BOUNCE, created_by=user)
        details = ChequeBounceCase.objects.create(case=case, created_by=user)

        assert "case" in self.readonly_fields(details)


class TestWitnessAdmin:
    def readonly_fields(self, obj):
        request = RequestFactory().get("/")
        return site._registry[Witness].get_readonly_fields(request, obj)

    def test_case_participant_is_editable_when_adding(self):
        assert "case_participant" not in self.readonly_fields(None)

    def test_case_participant_is_read_only_once_saved(self, user):
        """It is the primary key: changing it would overwrite another witness's row."""
        case = Case.objects.create(case_type=CaseType.CHEQUE_BOUNCE, created_by=user)
        participant = CaseParticipant.objects.create(
            case=case,
            person=Person.objects.create(name="Meena Rao"),
            role=ParticipantRole.WITNESS,
            ordinal=1,
            name_at_filing="Meena Rao",
        )
        witness = Witness.objects.create(case_participant=participant, side=WitnessSide.COMPLAINANT)

        assert "case_participant" in self.readonly_fields(witness)
