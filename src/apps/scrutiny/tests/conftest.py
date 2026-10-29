"""Fixtures shared by the scrutiny service and read-model tests."""

import pytest

from apps.cases.models import CaseDocument
from apps.cases.services.case_types import DocumentType
from apps.files.tests.factories import make_file
from apps.organizations.models import Organization, OrganizationType
from apps.scrutiny.enums import CourtRole

from .factories import make_case, make_user


@pytest.fixture
def officer():
    return make_user(CourtRole.SCRUTINY_OFFICER, name="Biju B")


@pytest.fixture
def registerer():
    return make_user(CourtRole.CASE_REGISTERER, name="Magistrate")


@pytest.fixture
def officer_registerer():
    return make_user(CourtRole.SCRUTINY_OFFICER, CourtRole.CASE_REGISTERER)


@pytest.fixture
def filer():
    return make_user(name="Filer")


@pytest.fixture
def establishment():
    return Organization.objects.create(
        code="EST", name="Establishment", organization_type=OrganizationType.MAGISTRATE_COURT
    )


@pytest.fixture
def case(filer, establishment):
    return make_case(filer, establishment, filing_number="F/EST/2026/00001")


@pytest.fixture
def document(case, filer):
    return CaseDocument.objects.create(
        case=case, document=make_file(user=filer), document_type=DocumentType.AFFIDAVIT
    )
