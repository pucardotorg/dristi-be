"""Rules that protect the filing: real uploads, drafts only, consistent links, history."""

import pytest
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError
from django.urls import reverse

from apps.cases.models import (
    Case,
    CaseDocument,
    CaseEvidence,
    CaseParticipant,
    CaseStatus,
    CaseType,
    ChequeBounceCase,
    ParticipantRole,
)
from apps.files.models import File
from apps.parties.tests.factories import make_address, make_institution, make_person

from .conftest import CHEQUE_INFO, error_codes

pytestmark = pytest.mark.django_db


def upload(client, case_id, file, document_type="BOUNCED_CHEQUE"):
    return client.post(
        reverse("case-document-list", args=[case_id]),
        {"file": file, "document_type": document_type},
        format="multipart",
    )


def add_cheque(client, case_id, **extra):
    return client.post(
        reverse("case-evidence-list", args=[case_id]),
        {"evidence_type": "CHEQUE", "evidence_info": CHEQUE_INFO, **extra},
        format="json",
    )


def submit(case_id):
    Case.objects.filter(pk=case_id).update(status=CaseStatus.UNDER_SCRUTINY)


class TestUploadsAreRealFiles:
    """The shared ``apps.files`` check decides by content, not by what the client claims."""

    @pytest.mark.parametrize(
        ("name", "content", "content_type"),
        [
            ("evil.pdf", b"MZ\x90\x00 an executable", "application/pdf"),  # wrong content
            ("script.exe", b"%PDF-1.4", "application/pdf"),  # wrong extension
            ("photo.png", b"%PDF-1.4", "image/png"),  # content of another type
        ],
    )
    def test_mislabelled_upload_is_rejected_and_nothing_is_stored(
        self, client, draft, name, content, content_type
    ):
        response = upload(client, draft, SimpleUploadedFile(name, content, content_type))

        assert response.status_code == 400
        assert error_codes(response) == {"file": ["E00001"]}
        assert Case.objects.count() == File.objects.count() == 0

    def test_oversized_upload_is_rejected(self, client, draft, pdf, settings):
        settings.FILE_MAX_SIZE_BYTES = 5

        response = upload(client, draft, pdf())

        assert response.status_code == 400
        assert error_codes(response) == {"file": ["E00001"]}

    def test_a_real_pdf_is_accepted(self, client, draft, pdf):
        assert upload(client, draft, pdf()).status_code == 201


class TestSubmittedCasesAreReadOnly:
    """Once a case leaves ``DRAFT_IN_PROGRESS`` its filing cannot change."""

    @pytest.fixture
    def submitted(self, client, draft, pdf):
        document_id = upload(client, draft, pdf()).json()["case_document_id"]
        evidence_id = add_cheque(client, draft).json()["case_evidence_id"]
        submit(draft)
        return {"case": draft, "document": document_id, "evidence": evidence_id}

    def test_cannot_upload(self, client, submitted, pdf):
        assert upload(client, submitted["case"], pdf()).status_code == 409

    def test_cannot_remove_a_document(self, client, submitted):
        url = reverse("case-document-detail", args=[submitted["document"]])

        assert client.delete(url).status_code == 409
        assert CaseDocument.objects.get(pk=submitted["document"]).is_active

    def test_cannot_add_evidence(self, client, submitted):
        assert add_cheque(client, submitted["case"]).status_code == 409

    def test_cannot_change_evidence(self, client, submitted):
        url = reverse("case-evidence-detail", args=[submitted["evidence"]])
        changed = {**CHEQUE_INFO, "amount": 1}

        response = client.patch(url, {"evidence_info": changed}, format="json")

        assert response.status_code == 409
        assert error_codes(response) == {None: ["E07001"]}
        assert CaseEvidence.objects.get(pk=submitted["evidence"]).evidence_info == CHEQUE_INFO

    def test_cannot_remove_evidence(self, client, submitted):
        url = reverse("case-evidence-detail", args=[submitted["evidence"]])

        assert client.delete(url).status_code == 409
        assert CaseEvidence.objects.get(pk=submitted["evidence"]).is_active

    def test_cannot_change_details(self, client, submitted):
        url = reverse("case-details-section", args=[submitted["case"], "adr_other_prayer"])

        response = client.put(url, {"final_relief": "changed after filing"}, format="json")

        assert response.status_code == 409

    def test_can_still_be_read(self, client, submitted):
        assert (
            client.get(reverse("case-evidence-list", args=[submitted["case"]])).status_code == 200
        )
        assert client.get(reverse("case-details", args=[submitted["case"]])).status_code == 200


class TestModelRulesMatchTheApi:
    """``clean()`` enforces the registry, so the admin cannot save what the API refuses."""

    @pytest.fixture
    def case(self, user):
        return Case.objects.create(case_type="CHEQUE_BOUNCE", created_by=user)

    def test_evidence_info_must_match_its_schema(self, case):
        evidence = CaseEvidence(
            case=case, evidence_type="CHEQUE", ordinal=1, evidence_info={"garbage": True}
        )

        with pytest.raises(ValidationError) as exc:
            evidence.full_clean()

        assert "evidence_info" in exc.value.message_dict

    def test_valid_evidence_passes(self, case):
        CaseEvidence(
            case=case, evidence_type="CHEQUE", ordinal=1, evidence_info=CHEQUE_INFO
        ).full_clean()

    def test_linked_document_must_belong_to_the_same_case(self, case, user, client, pdf):
        other = Case.objects.create(case_type="CHEQUE_BOUNCE", created_by=user)
        document_id = upload(client, other.pk, pdf()).json()["case_document_id"]
        evidence = CaseEvidence(
            case=case,
            evidence_type="CHEQUE",
            ordinal=1,
            evidence_info=CHEQUE_INFO,
            case_document_id=document_id,
        )

        with pytest.raises(ValidationError) as exc:
            evidence.full_clean()

        assert "case_document" in exc.value.message_dict

    def test_filled_in_section_must_match_its_schema(self, case):
        detail = ChequeBounceCase(case=case, adr_other_prayer={"anything": 1})

        with pytest.raises(ValidationError) as exc:
            detail.full_clean()

        assert "adr_other_prayer" in exc.value.message_dict

    def test_late_filing_needs_a_condonation_reason(self, case):
        late = {
            "cheque_deposited_by_payee": False,
            "drawer_bank_police_station": "Ernakulam Central",
            "cause_of_action_date": "2024-02-21",
            "complaint_filing_date": "2024-04-30",
        }
        detail = ChequeBounceCase(case=case, jurisdiction_limitation=late)

        with pytest.raises(ValidationError) as exc:
            detail.full_clean()
        assert "jurisdiction_limitation" in exc.value.message_dict

        late["condonation_reason"] = "The complainant was hospitalised."
        detail.full_clean()

    def test_empty_sections_are_allowed(self, case):
        ChequeBounceCase(case=case).full_clean()

    def test_a_complainant_cannot_also_be_accused(self, case):
        person = make_person()

        def participant(role):
            return CaseParticipant(
                case=case,
                person=person,
                role=role,
                ordinal=1,
                name_at_filing=person.name,
                address=make_address(),
            )

        participant(ParticipantRole.COMPLAINANT).save()

        with pytest.raises(ValidationError, match="both a complainant and an accused"):
            participant(ParticipantRole.ACCUSED).full_clean()

    def test_an_institution_needs_its_name_on_the_case(self, case):
        participant = CaseParticipant(
            case=case,
            institution=make_institution(),
            role=ParticipantRole.COMPLAINANT,
            ordinal=1,
            name_at_filing="ABC Pvt Ltd",
            address=make_address(),
        )

        with pytest.raises(ValidationError) as exc:
            participant.full_clean()

        assert set(exc.value.message_dict) == {"entity_name_at_filing"}

    def test_an_individual_cannot_have_institution_details(self, case):
        participant = CaseParticipant(
            case=case,
            person=make_person(),
            role=ParticipantRole.COMPLAINANT,
            ordinal=1,
            name_at_filing="Rajesh Kumar",
            entity_name_at_filing="ABC Pvt Ltd",
            address=make_address(),
        )

        with pytest.raises(ValidationError) as exc:
            participant.full_clean()

        assert set(exc.value.message_dict) == {"entity_name_at_filing"}

    def test_only_a_complainant_has_a_party_in_person_affidavit(self, case):
        participant = CaseParticipant(
            case=case,
            person=make_person(),
            role=ParticipantRole.ACCUSED,
            ordinal=1,
            name_at_filing="Suresh Patel",
            party_in_person_affidavit="<p>T</p>",
            address=make_address(),
        )

        with pytest.raises(ValidationError) as exc:
            participant.full_clean()

        assert set(exc.value.message_dict) == {"party_in_person_affidavit"}

    def test_details_without_a_case_are_a_field_error_not_a_crash(self):
        with pytest.raises(ValidationError) as exc:
            ChequeBounceCase().full_clean()

        assert "case" in exc.value.message_dict


class TestRemovingADocumentUnlinksEvidence:
    def test_evidence_no_longer_points_at_a_removed_document(self, client, draft, pdf):
        document_id = upload(client, draft, pdf()).json()["case_document_id"]
        evidence_id = add_cheque(client, draft, case_document_id=document_id).json()[
            "case_evidence_id"
        ]

        client.delete(reverse("case-document-detail", args=[document_id]))

        assert CaseEvidence.objects.get(pk=evidence_id).case_document_id is None


class TestLinkingADocumentLater:
    """Evidence entered before its scan is uploaded can be linked afterwards."""

    @pytest.fixture
    def evidence_id(self, client, draft):
        return add_cheque(client, draft).json()["case_evidence_id"]

    def patch(self, client, evidence_id, body):
        return client.patch(
            reverse("case-evidence-detail", args=[evidence_id]), body, format="json"
        )

    def test_link_a_document(self, client, draft, pdf, evidence_id):
        document_id = upload(client, draft, pdf()).json()["case_document_id"]

        response = self.patch(client, evidence_id, {"case_document_id": document_id})

        assert response.status_code == 200
        assert response.json()["case_document_id"] == document_id
        assert CaseEvidence.objects.get(pk=evidence_id).evidence_info == CHEQUE_INFO

    def test_unlink_with_null(self, client, draft, pdf, evidence_id):
        document_id = upload(client, draft, pdf()).json()["case_document_id"]
        self.patch(client, evidence_id, {"case_document_id": document_id})

        response = self.patch(client, evidence_id, {"case_document_id": None})

        assert response.status_code == 200
        assert response.json()["case_document_id"] is None

    def test_document_of_another_case_is_rejected(self, client, user, pdf, evidence_id):
        other = Case.objects.create(case_type="CHEQUE_BOUNCE", created_by=user)
        document_id = upload(client, other.pk, pdf()).json()["case_document_id"]

        response = self.patch(client, evidence_id, {"case_document_id": document_id})

        assert response.status_code == 400
        assert error_codes(response) == {"case_document_id": ["E07003"]}

    def test_an_empty_patch_is_rejected(self, client, evidence_id):
        assert self.patch(client, evidence_id, {}).status_code == 400


class TestEveryWriteTouchesTheCase:
    """``updated_at`` moves on every change, as listings and edit checks rely on it."""

    def updated_at(self, case_id):
        return Case.objects.get(pk=case_id).updated_at

    @pytest.fixture
    def case_id(self, client, draft):
        add_cheque(client, draft)
        return draft

    def test_adding_evidence(self, client, case_id):
        before = self.updated_at(case_id)
        add_cheque(client, case_id)
        assert self.updated_at(case_id) > before

    def test_changing_evidence(self, client, case_id):
        evidence_id = CaseEvidence.objects.get(case_id=case_id).pk
        before = self.updated_at(case_id)
        client.patch(
            reverse("case-evidence-detail", args=[evidence_id]),
            {"evidence_info": {**CHEQUE_INFO, "amount": 2}},
            format="json",
        )
        assert self.updated_at(case_id) > before

    def test_removing_evidence(self, client, case_id):
        evidence_id = CaseEvidence.objects.get(case_id=case_id).pk
        before = self.updated_at(case_id)
        client.delete(reverse("case-evidence-detail", args=[evidence_id]))
        assert self.updated_at(case_id) > before

    def test_uploading_and_removing_a_document(self, client, case_id, pdf):
        before = self.updated_at(case_id)
        document_id = upload(client, case_id, pdf()).json()["case_document_id"]
        after_upload = self.updated_at(case_id)
        client.delete(reverse("case-document-detail", args=[document_id]))

        assert before < after_upload < self.updated_at(case_id)

    def test_saving_a_section(self, client, case_id):
        before = self.updated_at(case_id)
        client.put(
            reverse("case-details-section", args=[case_id, "adr_other_prayer"]),
            {"final_relief": "Convict the accused"},
            format="json",
        )
        assert self.updated_at(case_id) > before


class TestHistory:
    """Evidence, sections and documents change during a filing; every version is kept."""

    def test_evidence_changes_are_kept(self, client, draft):
        evidence_id = add_cheque(client, draft).json()["case_evidence_id"]
        client.patch(
            reverse("case-evidence-detail", args=[evidence_id]),
            {"evidence_info": {**CHEQUE_INFO, "amount": 75000}},
            format="json",
        )

        amounts = [
            version.evidence_info["amount"]
            for version in CaseEvidence.objects.get(pk=evidence_id).history.order_by("history_date")
        ]
        assert amounts == [CHEQUE_INFO["amount"], 75000]

    def test_section_changes_are_kept(self, client, draft):
        url = reverse("case-details-section", args=[draft, "adr_other_prayer"])
        client.put(url, {"final_relief": "First"}, format="json")
        client.put(url, {"final_relief": "Second"}, format="json")

        reliefs = [
            version.adr_other_prayer.get("final_relief")
            for version in ChequeBounceCase.objects.get(case_id=draft).history.order_by(
                "history_date"
            )
        ]
        assert reliefs == [None, "First", "Second"]

    def test_document_removal_is_kept(self, client, draft, pdf):
        document_id = upload(client, draft, pdf()).json()["case_document_id"]
        client.delete(reverse("case-document-detail", args=[document_id]))

        states = [
            version.is_active
            for version in CaseDocument.objects.get(pk=document_id).history.order_by("history_date")
        ]
        assert states == [True, False]


class TestCaseAlwaysHasAFiler:
    def test_case_requires_a_filer(self):
        with pytest.raises(IntegrityError), transaction.atomic():
            Case.objects.create(case_type=CaseType.CHEQUE_BOUNCE)

    def test_filer_with_a_case_cannot_be_deleted(self, user):
        Case.objects.create(case_type=CaseType.CHEQUE_BOUNCE, created_by=user)

        with pytest.raises(ProtectedError):
            user.delete()
