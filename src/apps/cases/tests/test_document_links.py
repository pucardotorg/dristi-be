"""Tests for linking documents to participants and evidence (spec 0021 §3, §5)."""

import uuid

import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse

from apps.cases.models import Case, CaseDocument, CaseEvidence, CaseStatus
from apps.cases.services import services
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
        assert error_codes(response) == {"case_participant_id": ["E07010"]}

    def test_removing_the_participant_unlinks_their_documents(self, client, draft, pdf):
        complainant = add_complainant(client, draft)
        document = uploaded(
            client,
            draft,
            pdf,
            "IDENTITY_PROOF",
            case_participant_id=complainant["case_participant_id"],
        )

        client.delete(reverse("case-participant-detail", args=[complainant["case_participant_id"]]))

        # The document stays on the case, and can still be changed.
        renamed = change(client, document["case_document_id"], {"display_name": "Aadhaar"})
        assert renamed.status_code == 200, renamed.json()
        assert renamed.json()["case_participant_id"] is None


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

    def test_an_unknown_evidence_id_is_refused(self, client, draft, pdf):
        response = upload(
            client, draft, pdf, "PROOF_OF_DISPATCH", case_evidence_id=str(uuid.uuid4())
        )

        assert response.status_code == 400
        assert error_codes(response) == {"case_evidence_id": ["E07031"]}

    def test_a_scan_is_linked_from_its_evidence_not_here_and_no_file_is_stored(
        self, client, draft, pdf
    ):
        cheque = add_cheque(client, draft).json()
        files_before = File.objects.count()

        response = upload(
            client, draft, pdf, "BOUNCED_CHEQUE", case_evidence_id=cheque["case_evidence_id"]
        )

        assert response.status_code == 400
        assert error_codes(response) == {"case_evidence_id": ["E07030"]}
        assert File.objects.count() == files_before

    def test_removing_the_evidence_unlinks_its_papers(self, client, draft, pdf):
        notice = add_notice(client, draft)
        document = uploaded(
            client, draft, pdf, "PROOF_OF_DISPATCH", case_evidence_id=notice["case_evidence_id"]
        )

        client.delete(reverse("case-evidence-detail", args=[notice["case_evidence_id"]]))

        renamed = change(client, document["case_document_id"], {"display_name": "Speed post"})
        assert renamed.status_code == 200, renamed.json()
        assert renamed.json()["case_evidence_id"] is None

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


def change(client, case_document_id, body):
    url = reverse("case-document-detail", args=[case_document_id])
    return client.patch(url, body, format="json")


class TestChangeDocument:
    def test_an_identity_proof_uploaded_first_is_linked_to_its_complainant_later(
        self, client, draft, pdf
    ):
        document = uploaded(client, draft, pdf, "IDENTITY_PROOF")
        complainant = add_complainant(client, draft)

        response = change(
            client,
            document["case_document_id"],
            {"case_participant_id": complainant["case_participant_id"]},
        )

        assert response.status_code == 200, response.json()
        assert response.json()["case_participant_id"] == complainant["case_participant_id"]
        assert response.json()["document_id"] == document["document_id"]
        assert File.objects.count() == 1

    def test_null_unlinks_and_a_field_left_out_is_kept(self, client, draft, pdf):
        complainant = add_complainant(client, draft)
        document = uploaded(
            client,
            draft,
            pdf,
            "IDENTITY_PROOF",
            case_participant_id=complainant["case_participant_id"],
            display_name="Aadhaar",
        )

        response = change(client, document["case_document_id"], {"case_participant_id": None})

        assert response.json()["case_participant_id"] is None
        assert response.json()["display_name"] == "Aadhaar"

    def test_notice_papers_are_linked_to_their_notice(self, client, draft, pdf):
        notice = add_notice(client, draft)
        document = uploaded(client, draft, pdf, "PROOF_OF_DISPATCH")

        response = change(
            client, document["case_document_id"], {"case_evidence_id": notice["case_evidence_id"]}
        )

        assert response.json()["case_evidence_id"] == notice["case_evidence_id"]

    def test_details_are_changed_trimmed_and_removed(self, client, draft, pdf):
        document = uploaded(client, draft, pdf, "OTHER_SUPPORTING_DOCUMENT", is_digital="true")

        renamed = change(
            client, document["case_document_id"], {"display_name": "  Ledger  "}
        ).json()
        cleared = change(
            client, document["case_document_id"], {"display_name": " ", "is_digital": None}
        ).json()

        assert (renamed["display_name"], renamed["is_digital"]) == ("Ledger", True)
        assert (cleared["display_name"], cleared["is_digital"]) == (None, None)
        stored = CaseDocument.objects.get(pk=document["case_document_id"])
        assert stored.additional_details == {}

    def test_a_link_that_does_not_fit_is_refused_and_nothing_changes(self, client, draft, pdf):
        complainant = add_complainant(client, draft)
        document = uploaded(client, draft, pdf, "BOUNCED_CHEQUE")

        response = change(
            client,
            document["case_document_id"],
            {"case_participant_id": complainant["case_participant_id"], "display_name": "Cheque"},
        )

        assert response.status_code == 400
        assert error_codes(response) == {"case_participant_id": ["E07030"]}
        stored = CaseDocument.objects.get(pk=document["case_document_id"])
        assert (stored.case_participant_id, stored.additional_details) == (None, {})

    def test_an_accused_cannot_own_an_identity_proof(self, client, draft, pdf):
        add_complainant(client, draft)
        accused = add(client, draft, "accused", person={**PERSON, "name": "Suresh"}).json()
        document = uploaded(client, draft, pdf, "IDENTITY_PROOF")

        response = change(
            client,
            document["case_document_id"],
            {"case_participant_id": accused["case_participant_id"]},
        )

        assert error_codes(response) == {"case_participant_id": ["E07016"]}

    @pytest.mark.parametrize(
        ("body", "code"),
        [
            ({"document_type": "RETURN_MEMO"}, {"document_type": ["E07024"]}),
            ({"document_id": str(uuid.uuid4())}, {"document_id": ["E07024"]}),
            ({}, {None: ["E00002"]}),
        ],
    )
    def test_the_file_and_type_cannot_change_and_a_change_is_needed(
        self, client, draft, pdf, body, code
    ):
        document = uploaded(client, draft, pdf, "BOUNCED_CHEQUE")

        response = change(client, document["case_document_id"], body)

        assert response.status_code == 400
        assert error_codes(response) == code

    def test_a_removed_document_is_not_found(self, client, draft, pdf):
        document = uploaded(client, draft, pdf, "OTHER_SUPPORTING_DOCUMENT")
        client.delete(reverse("case-document-detail", args=[document["case_document_id"]]))

        response = change(client, document["case_document_id"], {"display_name": "Ledger"})

        assert response.status_code == 404

    def test_a_form_body_is_refused(self, client, draft, pdf):
        """A form body would read ``is_digital`` left out as null, and erase it."""
        document = uploaded(client, draft, pdf, "OTHER_SUPPORTING_DOCUMENT", is_digital="true")
        url = reverse("case-document-detail", args=[document["case_document_id"]])

        response = client.patch(url, {"display_name": "Ledger"}, format="multipart")

        assert response.status_code == 415
        stored = CaseDocument.objects.get(pk=document["case_document_id"])
        assert stored.additional_details == {"is_digital": True}

    def test_a_document_removed_while_the_change_waits_stays_removed(
        self, client, draft, pdf, monkeypatch
    ):
        """The row is read again under the case lock, so a concurrent removal is not undone."""
        document = uploaded(client, draft, pdf, "OTHER_SUPPORTING_DOCUMENT")
        lock_case = services.lock_case

        def removed_first(case):
            CaseDocument.objects.filter(pk=document["case_document_id"]).update(is_active=False)
            return lock_case(case)

        monkeypatch.setattr(services, "lock_case", removed_first)

        response = change(client, document["case_document_id"], {"display_name": "Ledger"})

        # The simulated removal ran inside the request's transaction and is
        # rolled back with it; the 404 shows the row was read after the lock.
        assert response.status_code == 404
        stored = CaseDocument.objects.get(pk=document["case_document_id"])
        assert stored.additional_details == {}

    def test_details_that_are_not_an_object_are_refused(self, client, draft, pdf):
        """They are read by key; the admin would otherwise break the case's document list."""
        document = uploaded(client, draft, pdf, "OTHER_SUPPORTING_DOCUMENT")
        stored = CaseDocument.objects.get(pk=document["case_document_id"])
        stored.additional_details = ["scanned at the counter"]

        with pytest.raises(ValidationError) as exc:
            stored.full_clean()

        assert "additional_details" in exc.value.message_dict

    def test_a_submitted_case_cannot_change(self, client, draft, pdf):
        document = uploaded(client, draft, pdf, "OTHER_SUPPORTING_DOCUMENT")
        Case.objects.filter(pk=draft).update(status=CaseStatus.PENDING_SIGN)

        response = change(client, document["case_document_id"], {"display_name": "Ledger"})

        assert response.status_code == 409
        assert error_codes(response) == {None: ["E07001"]}
