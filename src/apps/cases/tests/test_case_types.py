"""Consistency checks for the case type registry."""

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


def test_each_evidence_scan_type_may_be_linked_to_its_evidence():
    for evidence_type, document_type in EVIDENCE_SCAN_TYPES.items():
        assert evidence_type in EVIDENCE_DOCUMENT_TYPES[document_type]
