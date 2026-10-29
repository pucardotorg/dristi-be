"""Tests for linking documents to participants and evidence (spec 0021 §3, §5)."""

import uuid

import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse

from apps.cases.models import CaseDocument, CaseEvidence
from apps.files.models import File

from .conftest import DEMAND_NOTICE_INFO, RETURN_MEMO_INFO, error_codes
from .test_api import add_cheque, add_evidence, upload
from .test_participants import PERSON, add, add_complainant

pytestmark = pytest.mark.django_db


def add_notice(client, case_id):
    response = add_evidence(client, case_id, "LEGAL_DEMAND_NOTICE", DEMAND_NOTICE_INFO)
    assert response.status_code == 201, response.json()
    return response.json()


def uploaded(client, case_id, pdf, document_type, **extra):
    response = upload(client, case_id, pdf, document_type, **extra)
    assert response.status_code == 201, response.json()
    return response.json()


class TestEvidenceScanType:
    """An evidence item's own scan must be of its type: a cheque's is a bounced cheque."""

    @pytest.mark.parametrize(
        ("evidence_type", "info", "document_type"),
        [
            ("CHEQUE", None, "BOUNCED_CHEQUE"),
            ("RETURN_MEMO", RETURN_MEMO_INFO, "RETURN_MEMO"),
            ("LEGAL_DEMAND_NOTICE", DEMAND_NOTICE_INFO, "LEGAL_DEMAND_NOTICE"),
        ],
    )
    def test_the_matching_type_is_accepted(
        self, client, draft, pdf, evidence_type, info, document_type
    ):
        document = uploaded(client, draft, pdf, document_type)

        if evidence_type == "CHEQUE":
            response = add_cheque(client, draft, case_document_id=document["case_document_id"])
        else:
            response = add_evidence(
                client, draft, evidence_type, info, case_document_id=document["case_document_id"]
            )

        assert response.status_code == 201, response.json()

    @pytest.mark.parametrize(
        ("evidence_type", "info"),
        [
            ("CHEQUE", None),
            ("RETURN_MEMO", RETURN_MEMO_INFO),
            ("LEGAL_DEMAND_NOTICE", DEMAND_NOTICE_INFO),
        ],
    )
    def test_another_type_is_refused(self, client, draft, pdf, evidence_type, info):
        dispatch = uploaded(client, draft, pdf, "PROOF_OF_DISPATCH")

        if evidence_type == "CHEQUE":
            response = add_cheque(client, draft, case_document_id=dispatch["case_document_id"])
        else:
            response = add_evidence(
                client, draft, evidence_type, info, case_document_id=dispatch["case_document_id"]
            )

        assert response.status_code == 400
        assert error_codes(response) == {"case_document_id": ["E07029"]}
        assert not CaseEvidence.objects.filter(case_id=draft, evidence_type=evidence_type).exists()

    def test_relinking_to_another_type_is_refused(self, client, draft, pdf):
        cheque = add_cheque(client, draft).json()
        dispatch = uploaded(client, draft, pdf, "PROOF_OF_DISPATCH")

        response = client.patch(
            reverse("case-evidence-detail", args=[cheque["case_evidence_id"]]),
            {"case_document_id": dispatch["case_document_id"]},
            format="json",
        )

        assert response.status_code == 400
        assert error_codes(response) == {"case_document_id": ["E07029"]}
        assert CaseEvidence.objects.get(pk=cheque["case_evidence_id"]).case_document_id is None

    def test_the_model_refuses_it_too(self, client, draft, pdf):
        cheque = add_cheque(client, draft).json()
        dispatch = uploaded(client, draft, pdf, "PROOF_OF_DISPATCH")
        evidence = CaseEvidence.objects.get(pk=cheque["case_evidence_id"])
        evidence.case_document_id = dispatch["case_document_id"]

        with pytest.raises(ValidationError) as exc:
            evidence.full_clean()

        assert exc.value.error_dict["case_document"][0].code == "E07029"


class TestParticipantLinks:
    def test_an_identity_proof_is_linked_to_its_complainant(self, client, draft, pdf):
        complainant = add_complainant(client, draft)

        document = uploaded(
            client,
            draft,
            pdf,
            "IDENTITY_PROOF",
            case_participant_id=complainant["case_participant_id"],
        )

        assert document["case_participant_id"] == complainant["case_participant_id"]
        assert document["case_evidence_id"] is None

    def test_a_vakalatnama_may_be_linked_to_an_accused(self, client, draft, pdf):
        add_complainant(client, draft)
        accused = add(client, draft, "accused", person={**PERSON, "name": "Suresh"}).json()

        response = upload(
            client, draft, pdf, "VAKALATNAMA", case_participant_id=accused["case_participant_id"]
        )

        assert response.status_code == 201, response.json()

    def test_an_identity_proof_cannot_belong_to_an_accused(self, client, draft, pdf):
        add_complainant(client, draft)
        accused = add(client, draft, "accused", person={**PERSON, "name": "Suresh"}).json()

        response = upload(
            client, draft, pdf, "IDENTITY_PROOF", case_participant_id=accused["case_participant_id"]
        )

        assert response.status_code == 400
        assert error_codes(response) == {"case_participant_id": ["E07016"]}

    def test_a_cheque_scan_cannot_belong_to_a_participant(self, client, draft, pdf):
        complainant = add_complainant(client, draft)

        response = upload(
            client,
            draft,
            pdf,
            "BOUNCED_CHEQUE",
            case_participant_id=complainant["case_participant_id"],
        )

        assert response.status_code == 400
        assert error_codes(response) == {"case_participant_id": ["E07030"]}

    def test_a_participant_of_another_case_is_refused_and_nothing_is_kept(self, client, draft, pdf):
        add_complainant(client, draft)
        other = client.post(reverse("case-list"), {"case_type": "CHEQUE_BOUNCE"}, format="json")
        elsewhere = add_complainant(client, other.json()["draft_session_id"])
        files_before = File.objects.count()

        response = upload(
            client,
            draft,
            pdf,
            "IDENTITY_PROOF",
            case_participant_id=elsewhere["case_participant_id"],
        )

        assert response.status_code == 400
        assert error_codes(response) == {"case_participant_id": ["E07010"]}
        assert not CaseDocument.objects.filter(case_id=draft).exists()
        assert File.objects.filter(is_active=True).count() == files_before

    def test_an_unknown_participant_is_refused(self, client, draft, pdf):
        add_complainant(client, draft)

        response = upload(
            client, draft, pdf, "IDENTITY_PROOF", case_participant_id=str(uuid.uuid4())
        )

        assert response.status_code == 400
        assert list(error_codes(response)) == ["case_participant_id"]


class TestEvidenceLinks:
    @pytest.mark.parametrize(
        "document_type",
        ["PROOF_OF_DISPATCH", "PROOF_OF_DELIVERY_OF_DEMAND_NOTICE", "REPLY_TO_DEMAND_NOTICE"],
    )
    def test_notice_papers_are_linked_to_their_notice(self, client, draft, pdf, document_type):
        notice = add_notice(client, draft)

        document = uploaded(
            client, draft, pdf, document_type, case_evidence_id=notice["case_evidence_id"]
        )

        assert document["case_evidence_id"] == notice["case_evidence_id"]

    def test_notice_papers_cannot_be_linked_to_a_cheque(self, client, draft, pdf):
        cheque = add_cheque(client, draft).json()

        response = upload(
            client, draft, pdf, "PROOF_OF_DISPATCH", case_evidence_id=cheque["case_evidence_id"]
        )

        assert response.status_code == 400
        assert error_codes(response) == {"case_evidence_id": ["E07029"]}

    def test_a_type_with_no_evidence_cannot_be_linked(self, client, draft, pdf):
        notice = add_notice(client, draft)

        response = upload(
            client,
            draft,
            pdf,
            "OTHER_SUPPORTING_DOCUMENT",
            case_evidence_id=notice["case_evidence_id"],
        )

        assert response.status_code == 400
        assert error_codes(response) == {"case_evidence_id": ["E07030"]}

    def test_removed_evidence_cannot_be_linked(self, client, draft, pdf):
        notice = add_notice(client, draft)
        CaseEvidence.objects.filter(pk=notice["case_evidence_id"]).update(is_active=False)

        response = upload(
            client, draft, pdf, "PROOF_OF_DISPATCH", case_evidence_id=notice["case_evidence_id"]
        )

        assert response.status_code == 400
        assert error_codes(response) == {"case_evidence_id": ["E07031"]}


class TestDocumentDetails:
    def test_is_digital_and_display_name_are_kept_and_returned(self, client, draft, pdf):
        document = uploaded(
            client,
            draft,
            pdf,
            "OTHER_SUPPORTING_DOCUMENT",
            is_digital="true",
            display_name="  Bank statement, March  ",
        )

        assert document["is_digital"] is True
        assert document["display_name"] == "Bank statement, March"
        stored = CaseDocument.objects.get(pk=document["case_document_id"])
        assert stored.additional_details == {
            "is_digital": True,
            "display_name": "Bank statement, March",
        }

    def test_they_are_null_when_not_sent(self, client, draft, pdf):
        document = uploaded(client, draft, pdf, "BOUNCED_CHEQUE")

        assert document["is_digital"] is None
        assert document["display_name"] is None
        assert CaseDocument.objects.get(pk=document["case_document_id"]).additional_details == {}

    @pytest.mark.parametrize("document_type", ["IDENTITY_PROOF", "PROOF_OF_TRANSACTION"])
    def test_the_new_document_types_are_accepted(self, client, draft, pdf, document_type):
        assert upload(client, draft, pdf, document_type).status_code == 201
