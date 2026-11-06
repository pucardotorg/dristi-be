"""Consistency checks for the case type registry."""

from datetime import date

import pytest

from apps.cases.models import ParticipantRole
from apps.cases.services.case_types import (
    CASE_TYPES,
    EVIDENCE_DOCUMENT_TYPES,
    EVIDENCE_SCAN_TYPES,
    PARTY_DOCUMENT_ROLES,
    CaseType,
    DocumentType,
    EvidenceType,
    limitation_deadline,
)


def test_every_case_type_is_configured():
    assert set(CASE_TYPES) == set(CaseType.values)


@pytest.mark.parametrize("case_type", list(CASE_TYPES))
def test_configured_codes_are_known(case_type):
    config = CASE_TYPES[case_type]

    assert set(config.document_types) <= set(DocumentType.values)
    assert set(config.evidence_schemas) <= set(EvidenceType.values)


@pytest.mark.parametrize("case_type", list(CASE_TYPES))
def test_sections_are_detail_model_fields(case_type):
    config = CASE_TYPES[case_type]
    field_names = {field.name for field in config.get_detail_model()._meta.fields}

    assert set(config.sections) <= field_names


def test_document_link_rules_use_known_codes():
    assert set(EVIDENCE_SCAN_TYPES) == set(EvidenceType.values)
    assert set(EVIDENCE_SCAN_TYPES.values()) <= set(DocumentType.values)
    for roles in PARTY_DOCUMENT_ROLES.values():
        assert set(roles) <= set(ParticipantRole.values)
    for evidence_types in EVIDENCE_DOCUMENT_TYPES.values():
        assert set(evidence_types) <= set(EvidenceType.values)


def test_an_evidence_scan_is_linked_from_the_evidence_only():
    """A scan in both tables could be recorded on two links that disagree."""
    assert not set(EVIDENCE_SCAN_TYPES.values()) & set(EVIDENCE_DOCUMENT_TYPES)


@pytest.mark.parametrize(
    ("arose", "deadline"),
    [
        (date(2025, 1, 10), date(2025, 2, 10)),  # 31 days: still in time
        (date(2025, 2, 1), date(2025, 3, 1)),  # 28 days: a day later is late
        (date(2025, 1, 31), date(2025, 2, 28)),  # a shorter month ends on its last day
        (date(2024, 1, 31), date(2024, 2, 29)),  # leap year
        (date(2024, 12, 15), date(2025, 1, 15)),  # across the year end
    ],
)
def test_the_limitation_period_is_one_calendar_month(arose, deadline):
    assert limitation_deadline(arose) == deadline
