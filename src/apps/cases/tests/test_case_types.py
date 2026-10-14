"""Consistency checks for the case type registry."""

import pytest

from apps.cases.services.case_types import CASE_TYPES, CaseType, DocumentType, EvidenceType


def test_every_case_type_is_configured():
    assert set(CASE_TYPES) == set(CaseType.values)


@pytest.mark.parametrize("case_type", list(CASE_TYPES))
def test_configured_codes_are_known(case_type):
    config = CASE_TYPES[case_type]

    assert set(config.document_types) <= set(DocumentType.values)
    assert set(config.evidence_schemas) <= set(EvidenceType.values)
    # Filed with their representation or mandate, never as case documents.
    assert DocumentType.VAKALATNAMA not in config.document_types
    assert DocumentType.POA_DOCUMENT not in config.document_types


@pytest.mark.parametrize("case_type", list(CASE_TYPES))
def test_sections_are_detail_model_fields(case_type):
    config = CASE_TYPES[case_type]
    field_names = {field.name for field in config.get_detail_model()._meta.fields}

    assert set(config.sections) <= field_names
