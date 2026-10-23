"""Tests for the preview, completeness check, status transitions and signing (spec 0021 §6–8)."""

import uuid

import pytest
from django.contrib.auth.models import Permission
from django.urls import reverse
from django.utils import timezone

from apps.cases.models import (
    Case,
    CaseEvidence,
    CaseParticipant,
    CaseStatus,
    ChequeBounceCase,
    ParticipantRole,
)
from apps.esign.constants import EntityType, ESignStatus
from apps.esign.models import ESignTransaction
from apps.files.tests.factories import make_file
from apps.parties.models import Person
from apps.parties.tests.factories import ADDRESS_DEFAULTS

from .conftest import DEMAND_NOTICE_INFO, RETURN_MEMO_INFO, error_codes
from .test_api import add_cheque, add_evidence, put_section, upload
from .test_participants import PERSON, add, add_complainant, remove

pytestmark = pytest.mark.django_db

REQUIRED_DOCUMENTS = ["BOUNCED_CHEQUE", "RETURN_MEMO", "LEGAL_DEMAND_NOTICE", "PROOF_OF_DISPATCH"]
# Required beside the cheque.
EVIDENCE = [("RETURN_MEMO", RETURN_MEMO_INFO), ("LEGAL_DEMAND_NOTICE", DEMAND_NOTICE_INFO)]

JURISDICTION = {"cheque_deposited_by_payee": False, "cause_of_action_date": "2024-02-20"}
PRAYER = {"final_relief": "Direct the accused to pay the cheque amount."}


def make_complete_case(client, case_id, pdf):
    """Fill a draft until it passes the completeness check; return the complainant."""
    for document_type in REQUIRED_DOCUMENTS:
        assert upload(client, case_id, pdf, document_type).status_code == 201
    complainant = add(client, case_id, person=PERSON, is_party_in_person=True).json()
    accused = add(client, case_id, "accused", person={**PERSON, "name": "Suresh Patel"})
    assert accused.status_code == 201
    assert add_cheque(client, case_id).status_code == 201
    for evidence_type, evidence_info in EVIDENCE:
        assert add_evidence(client, case_id, evidence_type, evidence_info).status_code == 201
    assert put_section(client, case_id, "jurisdiction_limitation", JURISDICTION).status_code == 200
    assert put_section(client, case_id, "adr_other_prayer", PRAYER).status_code == 200
    return complainant


def validate(client, case_id):
    response = client.post(reverse("case-validate", args=[case_id]))
    assert response.status_code == 200
    return response.json()


def fields_of(body):
    return {error["field"] for error in body["errors"]}


def submit(client, case_id, step):
    return client.post(reverse(f"case-submit-for-{step}", args=[case_id]))


def signed_document(user, case_id, entity_type=EntityType.CASE_FILING, completed_at=None):
    """Return the id of a file a completed e-sign of ``case_id``'s filing stored."""
    file = make_file(user=user)
    ESignTransaction.objects.create(
        module="cases",
        entity_type=entity_type.value,
        entity_id=str(case_id),
        signer=user,
        provider="mock",
        source_file_id=str(uuid.uuid4()),
        signed_file_id=str(file.id),
        status=ESignStatus.SUCCESS.value,
        completed_at=completed_at or timezone.now(),
        expires_at=timezone.now() + timezone.timedelta(minutes=15),
    )
    return file.id


def sign(client, case_id, participant_id, document_id):
    return client.post(
        reverse("case-participant-sign", args=[case_id, participant_id]),
        {"signature_document_id": str(document_id)},
        format="json",
    )


def set_status(case_id, case_status):
    Case.objects.filter(pk=case_id).update(status=case_status)


class TestPreview:
    def test_assembles_the_whole_filing(self, client, draft, pdf):
        complainant = make_complete_case(client, draft, pdf)

        response = client.get(reverse("case-detail", args=[draft]))

        assert response.status_code == 200
        body = response.json()
        assert body["case_id"] == draft
        assert body["status"] == "DRAFT_IN_PROGRESS"
        assert [p["role"] for p in body["participants"]] == ["ACCUSED", "COMPLAINANT"]
        first = next(p for p in body["participants"] if p["role"] == "COMPLAINANT")
        assert first["case_participant_id"] == complainant["case_participant_id"]
        assert first["address"]["address_id"] == complainant["address_id"]
        assert first["address"]["pincode"]
        assert sorted(e["evidence_type"] for e in body["evidence"]) == [
            "CHEQUE",
            "LEGAL_DEMAND_NOTICE",
            "RETURN_MEMO",
        ]
        assert sorted(d["document_type"] for d in body["documents"]) == sorted(REQUIRED_DOCUMENTS)
        assert body["details"] == {
            "jurisdiction_limitation": JURISDICTION,
            "adr_other_prayer": PRAYER,
        }
        assert body["representations"] == []
        assert body["poa_mandates"] == []

    def test_shows_the_frozen_copy_not_the_person(self, client, draft):
        complainant = add_complainant(client, draft)
        Person.objects.filter(pk=complainant["person_id"]).update(name="Renamed Later")

        body = client.get(reverse("case-detail", args=[draft])).json()

        assert body["participants"][0]["name_at_filing"] == "Rajesh Kumar"

    def test_removed_rows_are_left_out(self, client, draft):
        complainant = add_complainant(client, draft)
        client.get(reverse("case-detail", args=[draft]))
        remove(client, complainant["case_participant_id"])

        body = client.get(reverse("case-detail", args=[draft])).json()

        assert body["participants"] == []

    def test_every_write_clears_the_cached_preview(self, client, draft):
        add_complainant(client, draft)
        assert len(client.get(reverse("case-detail", args=[draft])).json()["participants"]) == 1

        add_complainant(client, draft, name="Anita Kumar")

        assert len(client.get(reverse("case-detail", args=[draft])).json()["participants"]) == 2

    def test_a_cached_preview_answers_without_queries(
        self, client, draft, django_assert_num_queries
    ):
        add_complainant(client, draft)
        client.get(reverse("case-detail", args=[draft]))

        # The access check only.
        with django_assert_num_queries(1):
            client.get(reverse("case-detail", args=[draft]))

    def test_a_participant_who_is_the_user_may_view(self, client, client_for, other_user, draft):
        complainant = add_complainant(client, draft)
        Person.objects.filter(pk=complainant["person_id"]).update(user=other_user)

        response = client_for(other_user).get(reverse("case-detail", args=[draft]))

        assert response.status_code == 200

    def test_staff_with_the_view_permission_may_view(self, client, client_for, other_user, draft):
        add_complainant(client, draft)
        other_user.user_permissions.add(Permission.objects.get(codename="view_case"))

        response = client_for(other_user).get(reverse("case-detail", args=[draft]))

        assert response.status_code == 200

    def test_anyone_else_is_told_it_does_not_exist(self, client, client_for, other_user, draft):
        add_complainant(client, draft)

        response = client_for(other_user).get(reverse("case-detail", args=[draft]))

        assert response.status_code == 404

    def test_a_draft_with_no_case_yet_is_not_found(self, client, draft):
        assert client.get(reverse("case-detail", args=[draft])).status_code == 404


class TestValidate:
    def test_a_complete_case_is_valid(self, client, draft, pdf):
        make_complete_case(client, draft, pdf)

        body = validate(client, draft)

        assert body["is_valid"] is True
        assert body["errors"] == []

    def test_an_empty_case_reports_everything_missing(self, client, draft):
        put_section(client, draft, "adr_other_prayer", PRAYER)

        body = validate(client, draft)

        assert body["is_valid"] is False
        assert fields_of(body) == {
            "participants.complainants",
            "participants.accused",
            "evidence.CHEQUE",
            "evidence.RETURN_MEMO",
            "evidence.LEGAL_DEMAND_NOTICE",
            "details.jurisdiction_limitation",
            *(f"documents.{document_type}" for document_type in REQUIRED_DOCUMENTS),
        }

    def test_a_complainant_needs_an_advocate_or_to_appear_in_person(self, client, draft, pdf):
        make_complete_case(client, draft, pdf)
        second = add_complainant(client, draft, name="Anita Kumar")

        body = validate(client, draft)

        assert body["errors"] == [
            {
                "field": f"participants.{second['case_participant_id']}",
                "message": "Complainant #2 has no advocate and is not marked as party-in-person.",
            }
        ]

    def test_a_poa_mandate_needs_a_poa_document(self, client, draft, pdf):
        complainant = make_complete_case(client, draft, pdf)
        response = client.post(
            reverse("case-poa-holder-list", args=[draft]),
            {
                "person": {**PERSON, "name": "Mohan Das"},
                "address": ADDRESS_DEFAULTS,
                "represented_participant_ids": [complainant["case_participant_id"]],
            },
            format="json",
        )
        assert response.status_code == 201, response.json()

        assert fields_of(validate(client, draft)) == {"documents.POA_DOCUMENT"}

        upload(client, draft, pdf, "POA_DOCUMENT")
        assert validate(client, draft)["is_valid"] is True

    @pytest.mark.parametrize("evidence_type", ["RETURN_MEMO", "LEGAL_DEMAND_NOTICE"])
    def test_return_memo_and_demand_notice_evidence_are_required(
        self, client, draft, pdf, evidence_type
    ):
        make_complete_case(client, draft, pdf)
        CaseEvidence.objects.filter(case_id=draft, evidence_type=evidence_type).update(
            is_active=False
        )

        assert fields_of(validate(client, draft)) == {f"evidence.{evidence_type}"}

    def test_an_invalid_section_is_reported(self, client, draft, pdf):
        make_complete_case(client, draft, pdf)
        ChequeBounceCase.objects.filter(case_id=draft).update(adr_other_prayer={})

        assert fields_of(validate(client, draft)) == {"details.adr_other_prayer"}

    def test_other_users_cases_are_not_found(self, client, client_for, other_user, draft):
        add_complainant(client, draft)

        response = client_for(other_user).post(reverse("case-validate", args=[draft]))

        assert response.status_code == 404


class TestSubmitForSigning:
    def test_a_complete_draft_moves_to_pending_sign(self, client, draft, pdf):
        make_complete_case(client, draft, pdf)

        response = submit(client, draft, "signing")

        assert response.status_code == 200
        assert response.json()["status"] == "PENDING_SIGN"
        case = Case.objects.get(pk=draft)
        assert case.status == CaseStatus.PENDING_SIGN
        assert case.history.first().status == CaseStatus.PENDING_SIGN

    def test_an_incomplete_draft_is_refused_with_what_is_missing(self, client, draft):
        add_complainant(client, draft)

        response = submit(client, draft, "signing")

        assert response.status_code == 400
        assert error_codes(response)["participants.accused"] == ["E07005"]
        assert Case.objects.get(pk=draft).status == CaseStatus.DRAFT_IN_PROGRESS

    def test_a_submitted_case_cannot_be_submitted_again(self, client, draft, pdf):
        make_complete_case(client, draft, pdf)
        submit(client, draft, "signing")

        response = submit(client, draft, "signing")

        assert response.status_code == 409
        assert error_codes(response) == {None: ["E07004"]}

    def test_the_filing_is_frozen_and_the_preview_shows_the_new_status(self, client, draft, pdf):
        make_complete_case(client, draft, pdf)
        client.get(reverse("case-detail", args=[draft]))
        submit(client, draft, "signing")

        assert add_cheque(client, draft).status_code == 409
        body = client.get(reverse("case-detail", args=[draft])).json()
        assert body["status"] == "PENDING_SIGN"


class TestSign:
    @pytest.fixture
    def pending(self, client, draft, pdf):
        """A case pending signature; returns its complainant."""
        complainant = make_complete_case(client, draft, pdf)
        submit(client, draft, "signing")
        return complainant

    def test_records_the_signature(self, client, user, draft, pending):
        document_id = signed_document(user, draft)

        response = sign(client, draft, pending["case_participant_id"], document_id)

        assert response.status_code == 200
        body = response.json()
        assert body["has_signed"] is True
        completed_at = ESignTransaction.objects.get(signed_file_id=str(document_id)).completed_at
        assert body["signed_at"] == completed_at.isoformat().replace("+00:00", "Z")
        assert body["signature_document_id"] == str(document_id)
        participant = CaseParticipant.objects.get(pk=pending["case_participant_id"])
        assert participant.has_signed is True

    def test_signing_twice_is_refused(self, client, user, draft, pending):
        sign(client, draft, pending["case_participant_id"], signed_document(user, draft))

        response = sign(client, draft, pending["case_participant_id"], signed_document(user, draft))

        assert response.status_code == 409
        assert error_codes(response) == {None: ["E07007"]}

    def test_a_document_no_e_signature_produced_is_refused(self, client, user, draft, pending):
        response = sign(client, draft, pending["case_participant_id"], make_file(user=user).id)

        assert response.status_code == 400
        assert error_codes(response) == {"signature_document_id": ["E07009"]}

    def test_a_signature_of_another_case_is_refused(self, client, user, draft, pending):
        document_id = signed_document(user, uuid.uuid4())

        response = sign(client, draft, pending["case_participant_id"], document_id)

        assert response.status_code == 400
        assert error_codes(response) == {"signature_document_id": ["E07009"]}

    def test_a_signature_of_another_kind_of_document_is_refused(self, client, user, draft, pending):
        document_id = signed_document(user, draft, EntityType.ORDER)

        response = sign(client, draft, pending["case_participant_id"], document_id)

        assert response.status_code == 400

    def test_a_document_recorded_for_another_participant_is_refused(self, client, user, draft, pdf):
        first = make_complete_case(client, draft, pdf)
        second = add(client, draft, person={**PERSON, "name": "Anil Rao"}, is_party_in_person=True)
        submit(client, draft, "signing")
        document_id = signed_document(user, draft)
        sign(client, draft, first["case_participant_id"], document_id)

        response = sign(client, draft, second.json()["case_participant_id"], document_id)

        assert response.status_code == 400
        assert error_codes(response) == {"signature_document_id": ["E07026"]}
        assert (
            CaseParticipant.objects.get(pk=second.json()["case_participant_id"]).has_signed is False
        )

    def test_a_document_signed_by_another_user_is_refused(
        self, client, user, other_user, draft, pending
    ):
        Person.objects.filter(pk=pending["person_id"]).update(user=user)

        response = sign(
            client, draft, pending["case_participant_id"], signed_document(other_user, draft)
        )

        assert response.status_code == 400
        assert error_codes(response) == {"signature_document_id": ["E07027"]}

    def test_the_participants_own_signature_is_accepted(self, client, user, draft, pending):
        Person.objects.filter(pk=pending["person_id"]).update(user=user)

        response = sign(client, draft, pending["case_participant_id"], signed_document(user, draft))

        assert response.status_code == 200

    def test_a_signature_from_before_submission_is_refused(self, client, user, draft, pending):
        submitted_at = Case.objects.get(pk=draft).history.first().history_date
        document_id = signed_document(
            user, draft, completed_at=submitted_at - timezone.timedelta(seconds=1)
        )

        response = sign(client, draft, pending["case_participant_id"], document_id)

        assert response.status_code == 400
        assert error_codes(response) == {"signature_document_id": ["E07028"]}

    def test_the_accused_does_not_sign(self, client, user, draft, pending):
        accused = CaseParticipant.objects.get(case_id=draft, role=ParticipantRole.ACCUSED)

        response = sign(client, draft, accused.id, signed_document(user, draft))

        assert response.status_code == 400
        assert error_codes(response) == {"case_participant_id": ["E07008"]}

    def test_a_participant_of_another_case_is_not_found(self, client, user, draft, pending):
        response = sign(client, draft, uuid.uuid4(), signed_document(user, draft))

        assert response.status_code == 404

    def test_a_draft_cannot_be_signed(self, client, user, draft):
        complainant = add_complainant(client, draft)

        response = sign(
            client, draft, complainant["case_participant_id"], signed_document(user, draft)
        )

        assert response.status_code == 409


class TestSubmitForPaymentAndScrutiny:
    def test_payment_waits_for_every_signer(self, client, draft, pdf):
        complainant = make_complete_case(client, draft, pdf)
        submit(client, draft, "signing")

        response = submit(client, draft, "payment")

        assert response.status_code == 400
        participant = f"participants.{complainant['case_participant_id']}"
        assert error_codes(response) == {participant: ["E07006"]}

    def test_the_full_lifecycle(self, client, user, draft, pdf):
        complainant = make_complete_case(client, draft, pdf)
        assert submit(client, draft, "signing").status_code == 200
        sign(client, draft, complainant["case_participant_id"], signed_document(user, draft))

        payment = submit(client, draft, "payment")
        scrutiny = submit(client, draft, "scrutiny")

        assert payment.status_code == 200
        assert payment.json()["status"] == "PENDING_PAYMENT"
        assert scrutiny.status_code == 200
        assert scrutiny.json()["status"] == "UNDER_SCRUTINY"
        assert scrutiny.json()["filed_at"]

    @pytest.mark.parametrize(
        ("step", "wrong_status"),
        [
            ("payment", CaseStatus.DRAFT_IN_PROGRESS),
            ("scrutiny", CaseStatus.PENDING_SIGN),
            ("scrutiny", CaseStatus.UNDER_SCRUTINY),
        ],
    )
    def test_a_step_out_of_order_is_refused(self, client, draft, step, wrong_status):
        add_complainant(client, draft)
        set_status(draft, wrong_status)

        response = submit(client, draft, step)

        assert response.status_code == 409
        assert error_codes(response) == {None: ["E07004"]}
        assert Case.objects.get(pk=draft).status == wrong_status

    def test_other_users_cases_are_not_found(self, client, client_for, other_user, draft):
        add_complainant(client, draft)

        response = submit(client_for(other_user), draft, "signing")

        assert response.status_code == 404


def test_required_documents_are_described(client):
    body = client.get(reverse("case-type-detail", args=["CHEQUE_BOUNCE"])).json()

    assert body["required_document_types"] == REQUIRED_DOCUMENTS
