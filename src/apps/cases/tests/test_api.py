"""Tests for the case filing endpoints (spec 0021 §2, §3, §5)."""

import uuid

import pytest
from django.urls import reverse

from apps.cases.models import Case, CaseDocument, CaseStatus, CaseType
from apps.files.models import File

from .conftest import CHEQUE_INFO

pytestmark = pytest.mark.django_db


def upload(client, case_id, pdf, document_type="BOUNCED_CHEQUE"):
    return client.post(
        reverse("case-document-list", args=[case_id]),
        {"file": pdf(), "document_type": document_type},
        format="multipart",
    )


def add_cheque(client, case_id, **extra):
    return client.post(
        reverse("case-evidence-list", args=[case_id]),
        {"evidence_type": "CHEQUE", "evidence_info": CHEQUE_INFO, **extra},
        format="json",
    )


class TestDraftsAndListing:
    def test_post_returns_a_draft_session_and_creates_no_case(self, client):
        response = client.post(reverse("case-list"), {"case_type": "CHEQUE_BOUNCE"}, format="json")

        assert response.status_code == 201
        assert response.json()["case_type"] == "CHEQUE_BOUNCE"
        uuid.UUID(response.json()["draft_session_id"])
        assert Case.objects.count() == 0

    def test_unknown_case_type_is_400(self, client):
        response = client.post(reverse("case-list"), {"case_type": "CIVIL"}, format="json")

        assert response.status_code == 400
        assert "case_type" in response.json()

    def test_list_shows_only_the_callers_cases(self, client, user, other_user, draft):
        add_cheque(client, draft)
        Case.objects.create(case_type=CaseType.CHEQUE_BOUNCE, created_by=other_user)

        response = client.get(reverse("case-list"), {"created_by": "me"})

        assert response.status_code == 200
        assert [case["case_id"] for case in response.json()["results"]] == [draft]

    def test_list_filters_by_status(self, client, user):
        Case.objects.create(case_type=CaseType.CHEQUE_BOUNCE, created_by=user)
        Case.objects.create(
            case_type=CaseType.CHEQUE_BOUNCE, created_by=user, status=CaseStatus.PENDING_SIGN
        )

        response = client.get(reverse("case-list"), {"status": "PENDING_SIGN,UNDER_SCRUTINY"})

        assert [case["status"] for case in response.json()["results"]] == ["PENDING_SIGN"]

    def test_list_rejects_unknown_status(self, client):
        assert client.get(reverse("case-list"), {"status": "NOPE"}).status_code == 400

    def test_requires_authentication(self, db):
        from rest_framework.test import APIClient

        assert APIClient().get(reverse("case-list")).status_code in (401, 403)


class TestByNumber:
    def test_any_user_finds_a_registered_case(self, client_for, user, other_user):
        Case.objects.create(
            case_type=CaseType.CHEQUE_BOUNCE,
            created_by=other_user,
            case_number="CC/123/2024",
            status=CaseStatus.REGISTERED,
        )

        response = client_for(user).get(reverse("case-by-number", args=["CC/123/2024"]))

        assert response.status_code == 200
        assert response.json()["case_number"] == "CC/123/2024"

    def test_unregistered_case_is_not_found(self, client, user):
        Case.objects.create(
            case_type=CaseType.CHEQUE_BOUNCE,
            created_by=user,
            case_number="CC/9/2024",
            status=CaseStatus.UNDER_SCRUTINY,
        )

        assert client.get(reverse("case-by-number", args=["CC/9/2024"])).status_code == 404


class TestDocuments:
    def test_first_upload_on_a_draft_creates_the_case(self, client, draft, pdf):
        response = upload(client, draft, pdf)

        assert response.status_code == 201
        body = response.json()
        assert body["case_id"] == draft
        assert body["document_type"] == "BOUNCED_CHEQUE"
        assert body["file_name"] == "cheque.pdf"
        assert Case.objects.filter(pk=draft).exists()

    def test_documents_round_trip(self, client, draft, pdf):
        upload(client, draft, pdf)
        upload(client, draft, pdf, document_type="RETURN_MEMO")

        everything = client.get(reverse("case-document-list", args=[draft]))
        memos = client.get(
            reverse("case-document-list", args=[draft]), {"document_type": "RETURN_MEMO"}
        )

        assert everything.json()["count"] == 2
        assert [doc["document_type"] for doc in memos.json()["results"]] == ["RETURN_MEMO"]

    @pytest.mark.parametrize("document_type", ["UNKNOWN_TYPE", "VAKALATNAMA"])
    def test_invalid_document_type_is_400_and_creates_nothing(
        self, client, draft, pdf, document_type
    ):
        response = upload(client, draft, pdf, document_type=document_type)

        assert response.status_code == 400
        assert "document_type" in response.json()
        assert Case.objects.count() == File.objects.count() == 0

    def test_unsupported_file_type_is_400(self, client, draft, pdf):
        response = client.post(
            reverse("case-document-list", args=[draft]),
            {"file": pdf("notes.txt", "text/plain"), "document_type": "AFFIDAVIT"},
            format="multipart",
        )

        assert response.status_code == 400
        assert "file" in response.json()

    def test_unknown_id_is_404_and_stores_no_file(self, client, pdf):
        assert upload(client, uuid.uuid4(), pdf).status_code == 404
        assert File.objects.count() == 0

    def test_delete_is_soft(self, client, draft, pdf):
        document_id = upload(client, draft, pdf).json()["case_document_id"]

        response = client.delete(reverse("case-document-detail", args=[draft, document_id]))

        assert response.status_code == 204
        assert client.get(reverse("case-document-list", args=[draft])).json()["count"] == 0
        assert CaseDocument.objects.get(pk=document_id).is_active is False
        assert File.objects.count() == 1

    def test_other_users_cannot_see_or_change_documents(
        self, client, client_for, other_user, draft, pdf
    ):
        document_id = upload(client, draft, pdf).json()["case_document_id"]
        outsider = client_for(other_user)

        assert outsider.get(reverse("case-document-list", args=[draft])).status_code == 404
        assert upload(outsider, draft, pdf).status_code == 404
        detail = reverse("case-document-detail", args=[draft, document_id])
        assert outsider.delete(detail).status_code == 404


class TestDetails:
    def test_first_put_on_a_draft_creates_the_case(self, client, draft):
        section = {"jurisdiction_grounds": "Within territory", "limitation_compliance": True}

        response = client.put(
            reverse("case-details-section", args=[draft, "jurisdiction_limitation"]),
            section,
            format="json",
        )

        assert response.status_code == 200
        body = response.json()
        body.pop("meta")
        assert body == {"case_id": draft, "section": "jurisdiction_limitation", "data": section}
        details = client.get(reverse("case-details", args=[draft])).json()
        details.pop("meta")
        assert details == {"jurisdiction_limitation": section, "adr_other_prayer": {}}

    def test_unknown_section_is_400_and_creates_nothing(self, client, draft):
        response = client.put(
            reverse("case-details-section", args=[draft, "prayers"]), {}, format="json"
        )

        assert response.status_code == 400
        assert Case.objects.count() == 0

    def test_details_of_a_draft_with_no_case_yet_are_not_found(self, client, draft):
        assert client.get(reverse("case-details", args=[draft])).status_code == 404


class TestEvidence:
    def test_evidence_round_trip(self, client, draft):
        first = add_cheque(client, draft)
        second = add_cheque(client, draft)

        assert first.status_code == second.status_code == 201
        assert [first.json()["ordinal"], second.json()["ordinal"]] == [1, 2]

        evidence_id = first.json()["case_evidence_id"]
        detail = reverse("case-evidence-detail", args=[draft, evidence_id])
        changed = {**CHEQUE_INFO, "amount": 75000}
        patched = client.patch(detail, {"evidence_info": changed}, format="json")
        assert patched.status_code == 200
        assert patched.json()["evidence_info"]["amount"] == 75000

        assert client.delete(detail).status_code == 204
        listed = client.get(
            reverse("case-evidence-list", args=[draft]), {"evidence_type": "CHEQUE"}
        )
        assert [item["ordinal"] for item in listed.json()["results"]] == [2]

    @pytest.mark.parametrize(
        "evidence_info",
        [
            {key: value for key, value in CHEQUE_INFO.items() if key != "amount"},
            {**CHEQUE_INFO, "amount": -1},
            {**CHEQUE_INFO, "cheque_date": "15/01/2024"},
        ],
    )
    def test_invalid_evidence_info_is_400_and_creates_nothing(self, client, draft, evidence_info):
        response = client.post(
            reverse("case-evidence-list", args=[draft]),
            {"evidence_type": "CHEQUE", "evidence_info": evidence_info},
            format="json",
        )

        assert response.status_code == 400
        assert "evidence_info" in response.json()
        assert Case.objects.count() == 0

    def test_invalid_patch_is_400(self, client, draft):
        evidence_id = add_cheque(client, draft).json()["case_evidence_id"]

        response = client.patch(
            reverse("case-evidence-detail", args=[draft, evidence_id]),
            {"evidence_info": {"cheque_number": "1"}},
            format="json",
        )

        assert response.status_code == 400

    def test_links_a_document_of_the_same_case(self, client, draft, pdf):
        document_id = upload(client, draft, pdf).json()["case_document_id"]

        response = add_cheque(client, draft, case_document_id=document_id)

        assert response.status_code == 201
        assert response.json()["case_document_id"] == document_id

    def test_rejects_a_document_of_another_case(self, client, user, draft, pdf):
        other = Case.objects.create(case_type=CaseType.CHEQUE_BOUNCE, created_by=user)
        document_id = upload(client, other.pk, pdf).json()["case_document_id"]

        response = add_cheque(client, draft, case_document_id=document_id)

        assert response.status_code == 400
        assert "case_document_id" in response.json()

    def test_other_users_cannot_reach_evidence(self, client, client_for, other_user, draft):
        evidence_id = add_cheque(client, draft).json()["case_evidence_id"]
        outsider = client_for(other_user)
        detail = reverse("case-evidence-detail", args=[draft, evidence_id])

        assert outsider.get(reverse("case-evidence-list", args=[draft])).status_code == 404
        assert (
            outsider.patch(detail, {"evidence_info": CHEQUE_INFO}, format="json").status_code == 404
        )
        assert outsider.delete(detail).status_code == 404
