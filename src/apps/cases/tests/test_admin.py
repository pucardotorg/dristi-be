"""Tests for the cases admin."""

import pytest
from django.contrib.admin.sites import site
from django.test import RequestFactory

from apps.cases.models import Case, CaseType, ChequeBounceCase

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
