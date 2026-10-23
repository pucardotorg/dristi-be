"""Tests for the case filing endpoints (spec 0021 §2, §3, §5)."""

import dataclasses
import uuid

import pytest
from django.urls import reverse

from apps.cases.models import JOINABLE_STATUSES, Case, CaseDocument, CaseStatus, CaseType
from apps.cases.services import case_types
from apps.cases.services.case_types import DocumentType
from apps.files.models import File
from apps.organizations.models import OrganizationType
from apps.organizations.tests.factories import make_organization

from .conftest import (
    CHEQUE_INFO,
    DEMAND_NOTICE_INFO,
    RETURN_MEMO_INFO,
    error_codes,
    error_roots,
)

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


class TestCaseTypes:
    def test_list_describes_every_case_type(self, client):
        response = client.get(reverse("case-type-list"))

        assert response.status_code == 200
        assert [item["case_type"] for item in response.json()["data"]] == ["CHEQUE_BOUNCE"]

    def test_detail_lists_documents_and_evidence_schemas(self, client):
        body = client.get(reverse("case-type-detail", args=["CHEQUE_BOUNCE"])).json()

        assert body["label"] == "Cheque bounce"
        sections = {item["code"]: item["schema"] for item in body["sections"]}
        assert list(sections) == ["jurisdiction_limitation", "adr_other_prayer"]
        assert sections["adr_other_prayer"]["required"] == ["final_relief"]
        assert {"code": "REPLY_TO_DEMAND_NOTICE", "label": "Reply to demand notice"} in body[
            "document_types"
        ]
        cheque = next(item for item in body["evidence_types"] if item["code"] == "CHEQUE")
        assert "ifsc_code" in cheque["schema"]["required"]

    def test_unknown_case_type_is_404(self, client):
        assert client.get(reverse("case-type-detail", args=["CIVIL"])).status_code == 404


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
        assert error_codes(response) == {"case_type": ["E00005"]}

    def test_court_given_on_the_draft_is_set_on_the_case(self, client):
        court = make_organization(organization_type=OrganizationType.MAGISTRATE_COURT)
        response = client.post(
            reverse("case-list"),
            {"case_type": "CHEQUE_BOUNCE", "court_id": str(court.pk)},
            format="json",
        )
        assert response.status_code == 201
        assert response.json()["court_id"] == str(court.pk)

        draft = response.json()["draft_session_id"]
        add_cheque(client, draft)

        assert Case.objects.get(pk=draft).court == court

    def test_court_is_optional(self, client):
        response = client.post(reverse("case-list"), {"case_type": "CHEQUE_BOUNCE"}, format="json")
        assert response.status_code == 201
        assert response.json()["court_id"] is None

        draft = response.json()["draft_session_id"]
        add_cheque(client, draft)

        assert Case.objects.get(pk=draft).court is None

    @pytest.mark.parametrize(
        ("court_id", "code"), [(str(uuid.uuid4()), "E00011"), ("not-a-uuid", "E00001")]
    )
    def test_unknown_court_is_400(self, client, court_id, code):
        response = client.post(
            reverse("case-list"),
            {"case_type": "CHEQUE_BOUNCE", "court_id": court_id},
            format="json",
        )

        assert response.status_code == 400
        assert error_codes(response) == {"court_id": [code]}

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
        court = make_organization(organization_type=OrganizationType.MAGISTRATE_COURT)
        Case.objects.create(
            case_type=CaseType.CHEQUE_BOUNCE,
            created_by=other_user,
            case_number="CC/123/2024",
            status=CaseStatus.REGISTERED,
            court=court,
        )

        response = client_for(user).get(reverse("case-by-number", args=["CC/123/2024"]))

        assert response.status_code == 200
        assert response.json()["case_number"] == "CC/123/2024"
        assert response.json()["court_id"] == str(court.pk)

    def test_unregistered_case_is_not_found(self, client, user):
        Case.objects.create(
            case_type=CaseType.CHEQUE_BOUNCE,
            created_by=user,
            case_number="CC/9/2024",
            status=CaseStatus.UNDER_SCRUTINY,
        )

        assert client.get(reverse("case-by-number", args=["CC/9/2024"])).status_code == 404

    @pytest.mark.parametrize(
        "case_status", [s for s in CaseStatus.values if s not in JOINABLE_STATUSES]
    )
    def test_only_allow_listed_statuses_are_found(self, client, user, case_status):
        Case.objects.create(
            case_type=CaseType.CHEQUE_BOUNCE,
            created_by=user,
            case_number="CC/10/2024",
            status=case_status,
        )

        assert client.get(reverse("case-by-number", args=["CC/10/2024"])).status_code == 404


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

    @pytest.mark.parametrize(
        "document_type",
        [
            "PROOF_OF_DELIVERY_OF_DEMAND_NOTICE",
            "REPLY_TO_DEMAND_NOTICE",
            "VAKALATNAMA",
            "POA_DOCUMENT",
        ],
    )
    def test_cheque_bounce_document_types_are_accepted(self, client, draft, pdf, document_type):
        response = upload(client, draft, pdf, document_type=document_type)

        assert response.status_code == 201
        assert response.json()["document_type"] == document_type

    def test_unknown_document_type_is_400_and_creates_nothing(self, client, draft, pdf):
        response = upload(client, draft, pdf, document_type="UNKNOWN_TYPE")

        assert response.status_code == 400
        assert error_codes(response) == {"document_type": ["E00005"]}
        assert Case.objects.count() == File.objects.count() == 0

    def test_type_the_case_type_does_not_accept_is_400_and_creates_nothing(
        self, client, draft, pdf, monkeypatch
    ):
        # Cheque bounce accepts every known type today, so narrow its list to
        # exercise the per-case-type check.
        config = case_types.CASE_TYPES[CaseType.CHEQUE_BOUNCE]
        narrowed = dataclasses.replace(config, document_types=(DocumentType.BOUNCED_CHEQUE,))
        monkeypatch.setitem(case_types.CASE_TYPES, CaseType.CHEQUE_BOUNCE, narrowed)

        response = upload(client, draft, pdf, document_type="AFFIDAVIT")

        assert response.status_code == 400
        assert error_codes(response) == {"document_type": ["E07002"]}
        assert Case.objects.count() == File.objects.count() == 0

    def test_unsupported_file_type_is_400(self, client, draft, pdf):
        response = client.post(
            reverse("case-document-list", args=[draft]),
            {"file": pdf("notes.txt", "text/plain"), "document_type": "AFFIDAVIT"},
            format="multipart",
        )

        assert response.status_code == 400
        assert error_codes(response) == {"file": ["E00001"]}

    def test_unknown_id_is_404_and_stores_no_file(self, client, pdf):
        assert upload(client, uuid.uuid4(), pdf).status_code == 404
        assert File.objects.count() == 0

    def test_delete_is_soft(self, client, draft, pdf):
        document_id = upload(client, draft, pdf).json()["case_document_id"]

        response = client.delete(reverse("case-document-detail", args=[document_id]))

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
        detail = reverse("case-document-detail", args=[document_id])
        assert outsider.delete(detail).status_code == 404


JURISDICTION = {
    "cheque_deposited_by_payee": True,
    "payee_ifsc_code": "HDFC0000512",
    "payee_bank_name": "HDFC Bank",
    "payee_bank_branch": "Kochi",
    "bank_police_station": "Ernakulam Central",
    "other_complaints_pending": False,
    "cause_of_action_date": "2024-02-21",
}


def put_section(client, case_id, section, data):
    return client.put(reverse("case-details-section", args=[case_id, section]), data, format="json")


class TestDetails:
    def test_first_put_on_a_draft_creates_the_case(self, client, draft):
        section = JURISDICTION

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

    @pytest.mark.parametrize(
        ("section", "data"),
        [
            # Deposited by the payee, but no payee bank details.
            (
                "jurisdiction_limitation",
                {"cheque_deposited_by_payee": True, "cause_of_action_date": "2024-02-21"},
            ),
            ("jurisdiction_limitation", {**JURISDICTION, "payee_ifsc_code": "HDFC512"}),
            ("jurisdiction_limitation", {**JURISDICTION, "limitation_notes": "typo"}),
            ("adr_other_prayer", {"adr_preference": "YES"}),  # no final relief
            ("adr_other_prayer", {"adr_preference": "SOMETIMES", "final_relief": "Convict"}),
        ],
    )
    def test_invalid_section_is_400_and_creates_nothing(self, client, draft, section, data):
        response = put_section(client, draft, section, data)

        assert response.status_code == 400
        assert error_roots(response) == {"data"}
        assert Case.objects.count() == 0

    def test_payee_bank_details_not_needed_when_not_deposited_by_payee(self, client, draft):
        data = {"cheque_deposited_by_payee": False, "cause_of_action_date": "2024-02-21"}

        assert put_section(client, draft, "jurisdiction_limitation", data).status_code == 200

    def test_adr_other_prayer_round_trip(self, client, draft):
        data = {
            "adr_preference": "MAYBE",
            "other_details": "",
            "interim_relief": "<p>Interim compensation under Section 143A.</p>",
            "final_relief": "<p>Take cognizance of the offence under Section 138.</p>",
        }

        assert put_section(client, draft, "adr_other_prayer", data).status_code == 200
        details = client.get(reverse("case-details", args=[draft])).json()
        assert details["adr_other_prayer"] == data

    def test_details_of_a_draft_with_no_case_yet_are_not_found(self, client, draft):
        assert client.get(reverse("case-details", args=[draft])).status_code == 404

    def test_case_without_a_detail_row_reads_empty_and_saves(self, client, user):
        # Created outside the API (admin, shell), so no detail row exists.
        case = Case.objects.create(case_type=CaseType.CHEQUE_BOUNCE, created_by=user)

        details = client.get(reverse("case-details", args=[case.pk])).json()
        details.pop("meta")
        assert details == {"jurisdiction_limitation": {}, "adr_other_prayer": {}}

        assert (
            put_section(client, case.pk, "jurisdiction_limitation", JURISDICTION).status_code == 200
        )
        details = client.get(reverse("case-details", args=[case.pk])).json()
        assert details["jurisdiction_limitation"] == JURISDICTION


class TestEvidence:
    def test_evidence_round_trip(self, client, draft):
        first = add_cheque(client, draft)
        second = add_cheque(client, draft)

        assert first.status_code == second.status_code == 201
        assert [first.json()["ordinal"], second.json()["ordinal"]] == [1, 2]

        evidence_id = first.json()["case_evidence_id"]
        detail = reverse("case-evidence-detail", args=[evidence_id])
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
            {**CHEQUE_INFO, "cheque_number": "1234567"},
            {**CHEQUE_INFO, "ifsc_code": "SBIN1234"},
            {**CHEQUE_INFO, "drawee_bank": "SBI"},  # unknown key
        ],
    )
    def test_invalid_evidence_info_is_400_and_creates_nothing(self, client, draft, evidence_info):
        response = client.post(
            reverse("case-evidence-list", args=[draft]),
            {"evidence_type": "CHEQUE", "evidence_info": evidence_info},
            format="json",
        )

        assert response.status_code == 400
        assert error_roots(response) == {"evidence_info"}
        assert Case.objects.count() == 0

    def test_invalid_value_error_names_its_field(self, client, draft):
        response = client.post(
            reverse("case-evidence-list", args=[draft]),
            {"evidence_type": "CHEQUE", "evidence_info": {**CHEQUE_INFO, "cheque_number": "12"}},
            format="json",
        )

        assert response.status_code == 400
        assert response.json()["errors"] == [
            {
                "code": "E00001",
                "message": "'12' does not match '^[0-9]{6}$'",
                "field": "evidence_info.cheque_number",
            }
        ]

    @pytest.mark.parametrize(
        ("evidence_type", "evidence_info"),
        [("RETURN_MEMO", RETURN_MEMO_INFO), ("LEGAL_DEMAND_NOTICE", DEMAND_NOTICE_INFO)],
    )
    def test_return_memo_and_demand_notice_are_accepted(
        self, client, draft, evidence_type, evidence_info
    ):
        response = client.post(
            reverse("case-evidence-list", args=[draft]),
            {"evidence_type": evidence_type, "evidence_info": evidence_info},
            format="json",
        )

        assert response.status_code == 201
        assert response.json()["evidence_info"] == evidence_info

    @pytest.mark.parametrize(
        "evidence_info",
        [
            # Delivered, but no delivery date.
            {k: v for k, v in DEMAND_NOTICE_INFO.items() if k != "delivery_date"},
            {**DEMAND_NOTICE_INFO, "is_delivered": "yes"},
            {**DEMAND_NOTICE_INFO, "mode_of_service": ""},
        ],
    )
    def test_invalid_demand_notice_is_400(self, client, draft, evidence_info):
        response = client.post(
            reverse("case-evidence-list", args=[draft]),
            {"evidence_type": "LEGAL_DEMAND_NOTICE", "evidence_info": evidence_info},
            format="json",
        )

        assert response.status_code == 400
        assert error_roots(response) == {"evidence_info"}

    def test_undelivered_demand_notice_needs_no_delivery_date(self, client, draft):
        info = {k: v for k, v in DEMAND_NOTICE_INFO.items() if k != "delivery_date"}

        response = client.post(
            reverse("case-evidence-list", args=[draft]),
            {
                "evidence_type": "LEGAL_DEMAND_NOTICE",
                "evidence_info": {**info, "is_delivered": False},
            },
            format="json",
        )

        assert response.status_code == 201

    def test_invalid_patch_is_400(self, client, draft):
        evidence_id = add_cheque(client, draft).json()["case_evidence_id"]

        response = client.patch(
            reverse("case-evidence-detail", args=[evidence_id]),
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
        assert error_codes(response) == {"case_document_id": ["E07003"]}

    def test_other_users_cannot_reach_evidence(self, client, client_for, other_user, draft):
        evidence_id = add_cheque(client, draft).json()["case_evidence_id"]
        outsider = client_for(other_user)
        detail = reverse("case-evidence-detail", args=[evidence_id])

        assert outsider.get(reverse("case-evidence-list", args=[draft])).status_code == 404
        assert (
            outsider.patch(detail, {"evidence_info": CHEQUE_INFO}, format="json").status_code == 404
        )
        assert outsider.delete(detail).status_code == 404
