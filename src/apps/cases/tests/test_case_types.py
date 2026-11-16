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
    draft_schema,
    evidence_errors,
    limitation_deadline,
    section_errors,
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


def _keys(schema, found=None):
    """Return every key used anywhere in ``schema``."""
    found = set() if found is None else found
    if isinstance(schema, dict):
        for key, value in schema.items():
            found.add(key)
            _keys(value, found)
    elif isinstance(schema, list):
        for item in schema:
            _keys(item, found)
    return found


@pytest.mark.parametrize("case_type", list(CASE_TYPES))
def test_draft_schemas_ask_for_nothing(case_type):
    config = CASE_TYPES[case_type]
    schemas = [*config.section_schemas.values(), *config.evidence_schemas.values()]

    for schema in schemas:
        draft = draft_schema(schema)
        assert not {"required", "allOf"} & _keys(draft)
        # Everything else, the format rules included, is kept.
        assert draft["properties"].keys() == schema["properties"].keys()
        assert draft["additionalProperties"] is False


@pytest.mark.parametrize("case_type", list(CASE_TYPES))
def test_an_empty_section_or_evidence_item_is_a_valid_draft_but_not_complete(case_type):
    config = CASE_TYPES[case_type]

    for section, schema in config.section_schemas.items():
        assert section_errors(config, section, {}, complete=False) == []
        assert section_errors(config, section, {}) == [] or schema.get("required")
    for evidence_type in config.evidence_schemas:
        assert evidence_errors(config, evidence_type, {}, complete=False) == []
        assert evidence_errors(config, evidence_type, {})


def test_a_draft_still_refuses_malformed_values():
    config = CASE_TYPES[CaseType.CHEQUE_BOUNCE]

    problems = evidence_errors(config, EvidenceType.CHEQUE, {"cheque_number": "12"}, complete=False)

    assert [problem.path for problem in problems] == ["cheque_number"]
