"""Writes to a case sent back for correction, and document replacement (spec 0024 #5.1, #5.2)."""

import uuid

import pytest
from django.urls import reverse

from apps.cases import signals
from apps.cases.models import (
    Case,
    CaseDocument,
    CaseEvidence,
    CaseParticipant,
    CaseStatus,
    ParticipantRole,
)
from apps.cases.services import correction
from apps.parties.tests.factories import make_address, make_person

from .conftest import CHEQUE_INFO, DEMAND_NOTICE_INFO, RETURN_MEMO_INFO, error_codes
from .test_rules import add_cheque, upload

pytestmark = pytest.mark.django_db

JURISDICTION = {"cheque_deposited_by_payee": False, "cause_of_action_date": "2024-03-01"}


@pytest.fixture
def sent():
    """Collect the change signals sent during a test, as ``(name, kwargs)``."""
    found = []
    receivers = []
    for name, signal in (
        ("changed", signals.case_field_changed),
        ("replaced", signals.case_document_replaced),
    ):

        def receiver(sender, signal, name=name, **kwargs):
            found.append((name, kwargs))

        signal.connect(receiver, weak=False)
        receivers.append((signal, receiver))
    yield found
    for signal, receiver in receivers:
        signal.disconnect(receiver)


@pytest.fixture
def filing(client, draft, pdf):
    """A draft with a cheque linked to its scan, and jurisdiction filled in."""
    document_id = upload(client, draft, pdf()).json()["case_document_id"]
    evidence_id = add_cheque(client, draft, case_document_id=document_id).json()["case_evidence_id"]
    client.put(details_url(draft, "jurisdiction_limitation"), JURISDICTION, format="json")
    return {"case": draft, "document": document_id, "evidence": evidence_id}


def details_url(case_id, section):
    return reverse("case-details-section", args=[case_id, section])


def evidence_url(filing):
    return reverse("case-evidence-detail", args=[filing["evidence"]])


def replace_url(document_id):
    return reverse("case-document-replace", args=[document_id])


def send_back(case_id, **scope):
    """Put the case in correction with ``scope``, as scrutiny's send back does."""
    Case.objects.filter(pk=case_id).update(status=CaseStatus.PENDING_CORRECTION)
    scope = {"mode": "MARKED", "fields": [], "sections": [], "documents": [], **scope}
    correction.open_for_correction(Case.objects.get(pk=case_id), scope, uuid.uuid4())


def scope_of(case_id):
    return correction.get_scope(Case.objects.get(pk=case_id))


def change_cheque(client, filing, **info):
    return client.patch(
        evidence_url(filing), {"evidence_info": {**CHEQUE_INFO, **info}}, format="json"
    )


class TestReplacingADocument:
    """A document is replaced by a new upload of the same type, keeping its evidence links."""

    def test_in_a_draft(self, client, filing, pdf, sent):
        response = client.post(replace_url(filing["document"]), {"file": pdf()})

        assert response.status_code == 201
        new_id = response.json()["case_document_id"]
        assert response.json()["document_type"] == "BOUNCED_CHEQUE"
        assert not CaseDocument.objects.get(pk=filing["document"]).is_active
        assert str(CaseEvidence.objects.get(pk=filing["evidence"]).case_document_id) == new_id
        assert sent == []

    def test_needs_a_file(self, client, filing):
        response = client.post(replace_url(filing["document"]), {})

        assert error_codes(response) == {"file": ["E00002"]}
        assert CaseDocument.objects.get(pk=filing["document"]).is_active

    def test_not_after_submission(self, client, filing, pdf):
        Case.objects.filter(pk=filing["case"]).update(status=CaseStatus.PENDING_SIGN)

        response = client.post(replace_url(filing["document"]), {"file": pdf()})

        assert (response.status_code, error_codes(response)) == (409, {None: ["E07001"]})


class TestMarkedScope:
    """``MARKED`` opens the flagged fields, sections and documents, and nothing else."""

    def test_a_flagged_field_is_corrected_and_announced(self, client, filing, user, sent):
        send_back(filing["case"], fields=["CHQ-3[0]"])

        response = change_cheque(client, filing, amount=60000.0)

        assert response.status_code == 200
        assert sent == [
            (
                "changed",
                {
                    "case_id": uuid.UUID(filing["case"]),
                    "field_ref": "CHQ-3[0]",
                    "section": "CHQ",
                    "old": 50000.0,
                    "new": 60000.0,
                    "actor": user,
                },
            )
        ]
        assert scope_of(filing["case"])["changed"] is True

    def test_an_unflagged_field_is_refused(self, client, filing, sent):
        send_back(filing["case"], fields=["CHQ-3[0]"])

        response = change_cheque(client, filing, amount=60000.0, cheque_number="111111")

        assert response.status_code == 409
        assert error_codes(response) == {"evidence_info.cheque_number": ["E07029"]}
        assert CaseEvidence.objects.get(pk=filing["evidence"]).evidence_info == CHEQUE_INFO
        assert sent == []
        assert "changed" not in scope_of(filing["case"])

    def test_a_write_that_changes_nothing_passes_silently(self, client, filing, sent):
        send_back(filing["case"], fields=["CHQ-3[0]"])

        assert change_cheque(client, filing).status_code == 200
        assert sent == []

    def test_a_required_field_is_open(self, client, filing, sent):
        send_back(filing["case"], required=["JUR-9"])
        changed = {**JURISDICTION, "cause_of_action_date": "2024-03-02"}

        response = client.put(
            details_url(filing["case"], "jurisdiction_limitation"), changed, format="json"
        )

        assert response.status_code == 200
        assert [(kwargs["field_ref"], kwargs["section"]) for _, kwargs in sent] == [
            ("JUR-9", "JUR")
        ]

    def test_a_details_value_outside_the_scope_is_refused(self, client, filing):
        send_back(filing["case"], fields=["JUR-9"])
        changed = {**JURISDICTION, "other_complaints_pending": True}

        response = client.put(
            details_url(filing["case"], "jurisdiction_limitation"), changed, format="json"
        )

        assert error_codes(response) == {"data.other_complaints_pending": ["E07029"]}

    def test_relinking_evidence_needs_its_section(self, client, filing):
        send_back(filing["case"], fields=["CHQ-3[0]"])

        response = client.patch(evidence_url(filing), {"case_document_id": None}, format="json")

        assert error_codes(response) == {"case_document_id": ["E07029"]}

    def test_adding_and_removing_need_the_section_open(self, client, filing, pdf):
        send_back(filing["case"], fields=["CHQ-3[0]"])
        case_id = filing["case"]
        document_url = reverse("case-document-detail", args=[filing["document"]])

        assert error_codes(add_cheque(client, case_id)) == {"evidence_type": ["E07029"]}
        assert error_codes(upload(client, case_id, pdf())) == {"document_type": ["E07029"]}
        assert error_codes(client.delete(evidence_url(filing))) == {None: ["E07029"]}
        assert error_codes(client.delete(document_url)) == {None: ["E07029"]}

    def test_an_open_section_takes_any_write_in_it(self, client, filing, sent):
        send_back(filing["case"], sections=["CHQ"])

        assert change_cheque(client, filing, cheque_number="111111").status_code == 200
        assert add_cheque(client, filing["case"]).status_code == 201
        assert [(kwargs["field_ref"], kwargs["section"]) for _, kwargs in sent] == [
            (None, "CHQ"),
            # The new cheque's own values, then the cheque as an item.
            ("CHQ-3[1]", "CHQ"),
            ("CHQ-1[1]", "CHQ"),
            (None, "CHQ"),
        ]

    def test_a_missing_record_flagged_by_its_values_can_be_added(self, client, filing, sent):
        send_back(filing["case"], fields=["CHQ-8[0]", "CHQ-9[0]"])
        evidence_list = reverse("case-evidence-list", args=[filing["case"]])

        response = client.post(
            evidence_list,
            {"evidence_type": "RETURN_MEMO", "evidence_info": RETURN_MEMO_INFO},
            format="json",
        )

        assert response.status_code == 201
        assert [kwargs["field_ref"] for _, kwargs in sent] == ["CHQ-8[0]", "CHQ-9[0]", None]
        response = client.post(
            evidence_list,
            {"evidence_type": "LEGAL_DEMAND_NOTICE", "evidence_info": DEMAND_NOTICE_INFO},
            format="json",
        )
        assert error_codes(response) == {"evidence_type": ["E07029"]}

    def test_a_party_needs_its_section(self, client, filing, sent):
        participant = CaseParticipant.objects.create(
            case_id=filing["case"],
            person=make_person(),
            role=ParticipantRole.COMPLAINANT,
            ordinal=1,
            name_at_filing="Prateek",
            address=make_address(),
        )
        url = reverse("case-participant-detail", args=[participant.pk])
        body = {"name_at_filing": "Prateek Agrawal"}

        send_back(filing["case"], sections=["ACC"])
        assert error_codes(client.patch(url, body, format="json")) == {None: ["E07029"]}

        send_back(filing["case"], sections=["LIT"])
        assert client.patch(url, body, format="json").status_code == 200
        assert [(kwargs["field_ref"], kwargs["section"]) for _, kwargs in sent] == [(None, "LIT")]

    def test_only_a_flagged_document_is_replaced(self, client, filing, pdf, user, sent):
        other = upload(client, filing["case"], pdf(), "AFFIDAVIT").json()["case_document_id"]
        send_back(filing["case"], documents=[filing["document"]])

        response = client.post(replace_url(other), {"file": pdf()})
        assert (response.status_code, error_codes(response)) == (409, {None: ["E07029"]})
        assert CaseDocument.objects.get(pk=other).is_active

        response = client.post(replace_url(filing["document"]), {"file": pdf()})
        assert response.status_code == 201
        assert sent == [
            (
                "replaced",
                {
                    "case_id": uuid.UUID(filing["case"]),
                    "old_document_id": uuid.UUID(filing["document"]),
                    "new_document_id": uuid.UUID(response.json()["case_document_id"]),
                    "actor": user,
                },
            )
        ]
        assert scope_of(filing["case"])["changed"] is True


class TestOtherStates:
    def test_all_opens_everything(self, client, filing):
        send_back(filing["case"], mode="ALL")

        assert change_cheque(client, filing, cheque_number="111111").status_code == 200
        assert add_cheque(client, filing["case"]).status_code == 201
        assert scope_of(filing["case"])["changed"] is True

    def test_correction_without_a_scope_takes_no_writes(self, client, filing):
        Case.objects.filter(pk=filing["case"]).update(status=CaseStatus.PENDING_CORRECTION)

        response = change_cheque(client, filing, amount=60000.0)

        assert (response.status_code, error_codes(response)) == (
            409,
            {"evidence_info.amount": ["E07029"]},
        )

    def test_a_case_back_in_signing_is_read_only_again(self, client, filing):
        send_back(filing["case"], mode="ALL")
        Case.objects.filter(pk=filing["case"]).update(status=CaseStatus.PENDING_SIGN)

        response = change_cheque(client, filing, amount=60000.0)

        assert (response.status_code, error_codes(response)) == (409, {None: ["E07001"]})
