"""Fixtures shared by the scrutiny service and read-model tests."""

import pytest

from apps.cases.models import CaseDocument
from apps.cases.services.case_types import DocumentType
from apps.files.tests.factories import make_file

from .factories import (
    CASE_REGISTERER,
    SCRUTINY_OFFICER,
    add_courtroom,
    make_case,
    make_establishment,
    make_user,
)


@pytest.fixture
def officer(establishment):
    """A Scrutiny officer at the establishment."""
    return make_user(SCRUTINY_OFFICER, name="Biju B", at=establishment)


@pytest.fixture
def registerer(establishment):
    """A Case registerer at the establishment."""
    return make_user(CASE_REGISTERER, name="Magistrate", at=establishment)


@pytest.fixture
def officer_registerer(establishment):
    """Someone allowed both duties at the establishment (``SCR-11``)."""
    return make_user(SCRUTINY_OFFICER, CASE_REGISTERER, at=establishment)


@pytest.fixture
def filer():
    return make_user(name="Filer")


@pytest.fixture
def establishment():
    """The court establishment the case is filed in, with one courtroom."""
    court = make_establishment("EST", "Establishment")
    add_courtroom(court, "Main courtroom")
    return court


@pytest.fixture
def other_establishment():
    """A second establishment, where the officers here hold nothing, with one courtroom."""
    court = make_establishment("OTHER", "Other court")
    add_courtroom(court, "Other courtroom")
    return court


@pytest.fixture
def case(filer, establishment):
    return make_case(filer, establishment, filing_number="F/EST/2026/00001")


@pytest.fixture
def document(case, filer):
    return CaseDocument.objects.create(
        case=case, document=make_file(user=filer), document_type=DocumentType.AFFIDAVIT
    )
