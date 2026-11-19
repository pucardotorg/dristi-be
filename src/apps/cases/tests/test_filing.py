"""Tests for the preview, completeness check, status transitions and signing (spec 0021 §6–8)."""

import datetime
import uuid

import pytest
from django.contrib.auth.models import Permission
from django.db import IntegrityError, transaction
from django.urls import reverse
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.api.errors import BusinessError
from apps.cases.models import (
    Case,
    CaseContact,
    CaseDocument,
    CaseEvidence,
    CaseParticipant,
    CaseStatus,
    CaseType,
    ChequeBounceCase,
    ContactType,
    ParticipantRole,
    Representation,
)
from apps.cases.services import services
from apps.cases.services.filing import return_to_signing
from apps.esign.constants import EntityType, ESignStatus
from apps.esign.models import ESignTransaction
from apps.files.tests.factories import make_file
from apps.parties.models import Institution, Person
from apps.parties.tests.factories import ADDRESS_DEFAULTS

from .conftest import CHEQUE_INFO, DEMAND_NOTICE_INFO, RETURN_MEMO_INFO, error_codes
from .test_api import add_cheque, add_evidence, put_section, upload
from .test_participants import (
    INSTITUTION,
    MOBILE,
    PERSON,
    add,
    add_advocate,
    add_complainant,
    add_poa_holder,
    add_witness,
    end,
    make_advocate,
    patch,
    remove,
)

pytestmark = pytest.mark.django_db

REQUIRED_DOCUMENTS = ["BOUNCED_CHEQUE", "RETURN_MEMO", "LEGAL_DEMAND_NOTICE"]
ACCUSED_MOBILE = "+919812345678"
POA_MOBILE = "+919845012345"
# A second complainant's, which may not be the first's (PRD LIT-3).
SECOND_MOBILE = "+919811122233"
# Required beside the cheque.
EVIDENCE = [("RETURN_MEMO", RETURN_MEMO_INFO), ("LEGAL_DEMAND_NOTICE", DEMAND_NOTICE_INFO)]

JURISDICTION = {
    "cheque_deposited_by_payee": False,
    "drawer_bank_police_station": "Ernakulam Central",
    "other_complaints_pending": False,
    "cause_of_action_date": "2024-02-20",
    "complaint_filing_date": "2024-03-05",
}
PRAYER = {
    "adr_preference": "NO",
    "interim_relief": "Direct the accused to pay interim compensation.",
    "final_relief": "Direct the accused to pay the cheque amount.",
}
AFFIDAVIT = "<p>I, the complainant, state on oath that the facts above are true.</p>"
PIP_AFFIDAVIT = "<p>I request permission to appear and argue in person.</p>"


UNDELIVERED_NOTICE = {
    **{k: v for k, v in DEMAND_NOTICE_INFO.items() if k != "delivery_date"},
    "is_delivered": False,
    "return_date": "2024-02-05",
    "non_delivery_reason": "UNCLAIMED",
}


def put_affidavit(client, case_id, affidavit=AFFIDAVIT):
    return client.put(
        reverse("case-affidavit", args=[case_id]), {"affidavit": affidavit}, format="json"
    )


# The document type each evidence item's own scan is.
SCAN_TYPES = {
    "CHEQUE": "BOUNCED_CHEQUE",
    "RETURN_MEMO": "RETURN_MEMO",
    "LEGAL_DEMAND_NOTICE": "LEGAL_DEMAND_NOTICE",
}


def add_with_scan(client, case_id, pdf, evidence_type, evidence_info):
    """Add evidence with its own scan linked, as the filing screens save it."""
    scan = upload(client, case_id, pdf, SCAN_TYPES[evidence_type])
    assert scan.status_code == 201, scan.json()
    response = add_evidence(
        client,
        case_id,
        evidence_type,
        evidence_info,
        case_document_id=scan.json()["case_document_id"],
    )
    assert response.status_code == 201, response.json()
    return response


def make_complete_case(client, case_id, pdf):
    """Fill a draft until it passes the completeness check; return the complainant."""
    complainant = add(
        client,
        case_id,
        person=PERSON,
        is_party_in_person=True,
        party_in_person_affidavit=PIP_AFFIDAVIT,
    ).json()
    upload_identity_proof(client, case_id, pdf, complainant)
    # A number of their own: the complainant's may not be the accused's (PRD LIT-3).
    accused = add(
        client,
        case_id,
        "accused",
        person={**PERSON, "name": "Suresh Patel"},
        mobile_numbers=[ACCUSED_MOBILE],
    )
    assert accused.status_code == 201
    add_with_scan(client, case_id, pdf, "CHEQUE", CHEQUE_INFO)
    for evidence_type, evidence_info in EVIDENCE:
        response = add_with_scan(client, case_id, pdf, evidence_type, evidence_info)
    # The demand notice needs its proof of dispatch. DEMAND_NOTICE_INFO is
    # delivered, and is filed with its proof of delivery too, which is optional.
    notice_id = response.json()["case_evidence_id"]
    for document_type in ("PROOF_OF_DISPATCH", "PROOF_OF_DELIVERY_OF_DEMAND_NOTICE"):
        response = upload(client, case_id, pdf, document_type, case_evidence_id=notice_id)
        assert response.status_code == 201, response.json()
    assert put_section(client, case_id, "jurisdiction_limitation", JURISDICTION).status_code == 200
    assert put_section(client, case_id, "adr_other_prayer", PRAYER).status_code == 200
    assert put_affidavit(client, case_id).status_code == 200
    return complainant


def upload_identity_proof(client, case_id, pdf, participant):
    response = upload(
        client,
        case_id,
        pdf,
        "IDENTITY_PROOF",
        case_participant_id=participant["case_participant_id"],
    )
    assert response.status_code == 201, response.json()


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


def link_role(case_id, role, user):
    """Link the person of ``case_id``'s active ``role`` participant to ``user``, as a claim would."""
    participant = CaseParticipant.objects.active().get(case_id=case_id, role=role)
    Person.objects.filter(pk=participant.person_id).update(user=user)


def set_status(case_id, case_status):
    Case.objects.filter(pk=case_id).update(status=case_status)


class TestAffidavit:
    def test_first_put_on_a_draft_creates_the_case_and_the_preview_shows_it(self, client, draft):
        response = put_affidavit(client, draft)

        assert response.status_code == 200
        assert response.json()["case_id"] == draft
        assert response.json()["affidavit"] == AFFIDAVIT
        preview = client.get(reverse("case-detail", args=[draft])).json()
        assert preview["affidavit"] == AFFIDAVIT

    def test_it_reads_as_saved(self, client, draft):
        put_affidavit(client, draft)

        response = client.get(reverse("case-affidavit", args=[draft]))

        assert response.status_code == 200
        assert response.json()["affidavit"] == AFFIDAVIT

    def test_it_reads_null_before_it_is_saved(self, client, draft):
        put_section(client, draft, "adr_other_prayer", PRAYER)

        assert client.get(reverse("case-affidavit", args=[draft])).json()["affidavit"] is None

    def test_another_users_affidavit_is_not_found(self, client, client_for, other_user, draft):
        put_affidavit(client, draft)

        response = client_for(other_user).get(reverse("case-affidavit", args=[draft]))

        assert response.status_code == 404

    def test_a_put_replaces_the_affidavit(self, client, draft):
        put_affidavit(client, draft)

        put_affidavit(client, draft, "<p>Corrected.</p>")

        assert Case.objects.get(pk=draft).affidavit == "<p>Corrected.</p>"

    @pytest.mark.parametrize("affidavit", ["", "  ", "<p><br></p>", "<p>&nbsp;</p>", None])
    def test_an_empty_affidavit_is_saved_and_validate_asks_for_one(self, client, draft, affidavit):
        response = put_affidavit(client, draft, affidavit)

        assert response.status_code == 200, response.json()
        assert Case.objects.get(pk=draft).affidavit == response.json()["affidavit"]
        assert "affidavit" in fields_of(validate(client, draft))

    def test_a_submitted_case_cannot_change(self, client, draft):
        put_affidavit(client, draft)
        set_status(draft, CaseStatus.PENDING_SIGN)

        assert put_affidavit(client, draft, "<p>Changed.</p>").status_code == 409

    def test_other_users_cases_are_not_found(self, client, client_for, other_user, draft):
        put_affidavit(client, draft)

        assert put_affidavit(client_for(other_user), draft).status_code == 404


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
        assert first["addresses"] == complainant["addresses"]
        assert first["addresses"][0]["pincode"]
        assert sorted(e["evidence_type"] for e in body["evidence"]) == [
            "CHEQUE",
            "LEGAL_DEMAND_NOTICE",
            "RETURN_MEMO",
        ]
        assert sorted(d["document_type"] for d in body["documents"]) == sorted(
            [
                *REQUIRED_DOCUMENTS,
                "IDENTITY_PROOF",
                "PROOF_OF_DISPATCH",
                "PROOF_OF_DELIVERY_OF_DEMAND_NOTICE",
            ]
        )
        assert body["details"] == {
            "jurisdiction_limitation": JURISDICTION,
            "adr_other_prayer": PRAYER,
        }
        assert body["representations"] == []
        assert body["poa_mandates"] == []

    def test_a_permanent_address_is_shown_only_when_it_differs(self, client, draft):
        elsewhere = {**ADDRESS_DEFAULTS, "line1": "7 Temple Street", "pincode": "560004"}
        same = add_complainant(client, draft)
        differs = add(
            client, draft, person={**PERSON, "name": "Anita"}, permanent_address=elsewhere
        )

        body = client.get(reverse("case-detail", args=[draft])).json()

        by_id = {p["case_participant_id"]: p for p in body["participants"]}
        assert by_id[same["case_participant_id"]]["permanent_address"] is None
        shown = by_id[differs.json()["case_participant_id"]]["permanent_address"]
        assert shown["line1"] == "7 Temple Street"

    def test_a_permanent_address_changed_from_another_case_is_shown(self, client, user, draft):
        """The filer's own person appears in both filings; both previews follow it."""
        elsewhere = {**ADDRESS_DEFAULTS, "line1": "7 Temple Street", "pincode": "560004"}
        add(client, draft, self=True)
        client.get(reverse("case-detail", args=[draft]))  # cached
        other = services.start_draft(user, CaseType.CHEQUE_BOUNCE)["draft_session_id"]
        assert add(client, other, self=True, permanent_address=elsewhere).status_code == 201

        body = client.get(reverse("case-detail", args=[draft])).json()

        assert body["participants"][0]["permanent_address"]["line1"] == "7 Temple Street"

    def test_an_entity_type_filled_from_another_case_is_shown(self, client, user, draft):
        """The institution appears in both filings; both previews follow its filled type."""
        no_type = {k: v for k, v in INSTITUTION.items() if k != "entity_type"}
        add(client, draft, institution=no_type)
        before = client.get(reverse("case-detail", args=[draft])).json()  # cached
        assert before["participants"][0]["institution"]["entity_type"] is None
        other = services.start_draft(user, CaseType.CHEQUE_BOUNCE)["draft_session_id"]
        assert add(client, other, institution=INSTITUTION).status_code == 201

        body = client.get(reverse("case-detail", args=[draft])).json()

        assert body["participants"][0]["institution"]["entity_type"] == INSTITUTION["entity_type"]

    def test_representations_show_the_bar_registration_number(
        self, client, make_user, other_user, draft
    ):
        complainant = add_complainant(client, draft)
        advocate = make_advocate(make_user, user=other_user)
        add_advocate(client, draft, advocate.pk, [complainant["case_participant_id"]])

        body = client.get(reverse("case-detail", args=[draft])).json()

        assert body["representations"][0]["bar_registration_id"] == advocate.bar_registration_id

    def test_shows_the_frozen_copy_not_the_person(self, client, draft):
        complainant = add(
            client, draft, person=PERSON, email_addresses=["rajesh@example.com"]
        ).json()
        Person.objects.filter(pk=complainant["person_id"]).update(
            name="Renamed Later", email_address="later@example.com"
        )

        body = client.get(reverse("case-detail", args=[draft])).json()

        assert body["participants"][0]["name_at_filing"] == "Rajesh Kumar"
        assert body["participants"][0]["email_addresses"] == ["rajesh@example.com"]

    def test_shows_the_institution_as_entered(self, client, draft):
        response = add(client, draft, institution=INSTITUTION)
        Institution.objects.filter(pk=response.json()["institution_id"]).update(
            entity_name="Renamed Later"
        )

        body = client.get(reverse("case-detail", args=[draft])).json()

        (participant,) = body["participants"]
        assert participant["entity_name_at_filing"] == "ABC Pvt Ltd"

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

    def test_a_poa_holder_who_is_the_user_may_view(self, client, client_for, other_user, draft):
        complainant = add_complainant(client, draft)
        assert (
            add_poa_holder(client, draft, [complainant["case_participant_id"]]).status_code == 201
        )
        link_role(draft, ParticipantRole.POA_HOLDER, other_user)

        response = client_for(other_user).get(reverse("case-detail", args=[draft]))

        assert response.status_code == 200

    def test_an_accused_who_claimed_their_record_is_told_it_does_not_exist(
        self, client, client_for, other_user, draft
    ):
        add_complainant(client, draft)
        accused = add(client, draft, "accused", person={**PERSON, "name": "Suresh Patel"})
        assert accused.status_code == 201
        link_role(draft, ParticipantRole.ACCUSED, other_user)

        response = client_for(other_user).get(reverse("case-detail", args=[draft]))

        assert response.status_code == 404

    def test_a_witness_who_is_the_user_is_told_it_does_not_exist(
        self, client, client_for, other_user, draft
    ):
        add_complainant(client, draft)
        witness = add_witness(client, draft)
        assert witness.status_code == 201
        link_role(draft, ParticipantRole.WITNESS, other_user)

        response = client_for(other_user).get(reverse("case-detail", args=[draft]))

        assert response.status_code == 404

    def test_an_advocate_of_a_complainant_may_view(
        self, client, client_for, make_user, other_user, draft
    ):
        complainant = add_complainant(client, draft)
        advocate = make_advocate(make_user, user=other_user)
        response = add_advocate(client, draft, advocate.pk, [complainant["case_participant_id"]])
        assert response.status_code == 201

        response = client_for(other_user).get(reverse("case-detail", args=[draft]))

        assert response.status_code == 200

    def test_an_advocate_whose_representation_ended_is_told_it_does_not_exist(
        self, client, client_for, make_user, other_user, draft
    ):
        complainant = add_complainant(client, draft)
        advocate = make_advocate(make_user, user=other_user)
        add_advocate(client, draft, advocate.pk, [complainant["case_participant_id"]])
        representation = Representation.objects.get(case_id=draft, advocate=advocate)
        assert end(client, representation.pk).status_code == 204

        response = client_for(other_user).get(reverse("case-detail", args=[draft]))

        assert response.status_code == 404

    def test_an_advocate_of_the_accused_is_told_it_does_not_exist(
        self, client, client_for, make_user, other_user, draft
    ):
        add_complainant(client, draft)
        accused = add(client, draft, "accused", person={**PERSON, "name": "Suresh Patel"})
        advocate = make_advocate(make_user, user=other_user)
        response = add_advocate(client, draft, advocate.pk, [accused.json()["case_participant_id"]])
        assert response.status_code == 201

        response = client_for(other_user).get(reverse("case-detail", args=[draft]))

        assert response.status_code == 404

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


class TestPartialDraft:
    """Every part of a filing can be saved half-filled; validate is what asks for the rest."""

    def test_a_draft_saved_piece_by_piece_with_gaps_is_not_ready(self, client, draft):
        responses = [
            add(client, draft, person={"gender": "MALE"}, addresses=[]),
            add(client, draft, "accused", person={}, addresses=[]),
            add_witness(client, draft, person={}, addresses=[]),
            add_evidence(client, draft, "CHEQUE", {}),
            put_section(client, draft, "jurisdiction_limitation", {}),
            put_section(client, draft, "adr_other_prayer", {}),
            put_affidavit(client, draft, ""),
        ]

        assert [response.status_code for response in responses] == [
            201,
            201,
            201,
            201,
            200,
            200,
            200,
        ]
        body = validate(client, draft)
        assert body["is_valid"] is False
        messages = {error["message"] for error in body["errors"]}
        assert {
            "Complainant #1 has no name.",
            "Complainant #1 has no address.",
            "Accused #1 has no name.",
            "Accused #1 has no address.",
            "Witness #1 has no name or designation.",
            "Witness #1 has no address.",
            "The affidavit is required.",
            "'final_relief' is a required property",
            "Cheque #1: 'amount' is a required property",
        } <= messages
        assert submit(client, draft, "signing").status_code == 400
        assert Case.objects.get(pk=draft).status == CaseStatus.DRAFT_IN_PROGRESS

    def test_an_accused_address_without_a_police_station_blocks_filing(self, client, draft, pdf):
        make_complete_case(client, draft, pdf)
        accused = CaseParticipant.objects.get(case_id=draft, role=ParticipantRole.ACCUSED)
        no_police_station = {k: v for k, v in ADDRESS_DEFAULTS.items() if k != "police_station"}
        url = reverse("case-participant-detail", args=[accused.pk])
        assert (
            client.patch(url, {"addresses": [no_police_station]}, format="json").status_code == 200
        )

        body = validate(client, draft)

        assert body["errors"] == [
            {
                "field": f"participants.{accused.pk}",
                "message": "Accused #1 has an address with no police station.",
            }
        ]
        response = submit(client, draft, "signing")
        assert response.status_code == 400
        assert error_codes(response) == {f"participants.{accused.pk}": ["E07005"]}

    def test_an_accused_institutions_officer_needs_no_designation(self, client, draft, pdf):
        """PRD ACC-15: optional for a person responsible for an accused institution."""
        make_complete_case(client, draft, pdf)
        response = add(
            client,
            draft,
            "accused",
            institution=INSTITUTION,
            person=PERSON,
            mobile_numbers=[ACCUSED_MOBILE],
            addresses=[ADDRESS_DEFAULTS],
        )
        assert response.status_code == 201, response.json()
        assert response.json()["designation_at_filing"] is None

        assert validate(client, draft)["is_valid"] is True

    def test_a_complainant_institution_needs_a_pan_a_cin_or_the_declaration(
        self, client, draft, pdf
    ):
        make_complete_case(client, draft, pdf)
        no_identifier = {k: v for k, v in INSTITUTION.items() if k != "pan"}
        response = add(client, draft, institution=no_identifier, is_party_in_person=True)
        assert response.status_code == 201, response.json()
        participant_id = response.json()["case_participant_id"]

        messages = [
            error["message"]
            for error in validate(client, draft)["errors"]
            if error["field"] == f"participants.{participant_id}"
        ]

        assert "Complainant #2: Enter a PAN or a CIN, or declare that neither is given." in (
            messages
        )

    def test_a_late_filing_without_a_condonation_reason_blocks_filing(self, client, draft, pdf):
        make_complete_case(client, draft, pdf)
        late = {**JURISDICTION, "complaint_filing_date": "2024-04-30"}
        assert put_section(client, draft, "jurisdiction_limitation", late).status_code == 200

        body = validate(client, draft)

        assert fields_of(body) == {"details.jurisdiction_limitation"}
        assert "condonation_reason" in body["errors"][0]["message"]


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
            "affidavit",
            # Scans and proofs of dispatch are asked for on their evidence
            # items, of which there are none.
        }

    def test_a_complainant_needs_an_advocate_or_to_appear_in_person(self, client, draft, pdf):
        make_complete_case(client, draft, pdf)
        second = add(
            client, draft, person={**PERSON, "name": "Anita Kumar"}, mobile_numbers=[SECOND_MOBILE]
        ).json()
        upload_identity_proof(client, draft, pdf, second)

        body = validate(client, draft)

        assert body["errors"] == [
            {
                "field": f"participants.{second['case_participant_id']}",
                "message": "Complainant #2 has no advocate and is not marked as party-in-person.",
            }
        ]

    def test_a_party_in_person_needs_their_affidavit(self, client, draft, pdf):
        complainant = make_complete_case(client, draft, pdf)
        url = reverse("case-participant-detail", args=[complainant["case_participant_id"]])
        client.patch(url, {"party_in_person_affidavit": None}, format="json")

        body = validate(client, draft)

        assert body["errors"] == [
            {
                "field": f"participants.{complainant['case_participant_id']}",
                "message": "Complainant #1 appears in person but has no party-in-person affidavit.",
            }
        ]

    @pytest.mark.parametrize("affidavit", [None, "<p><br></p>"])
    def test_the_case_affidavit_is_required(self, client, draft, pdf, affidavit):
        make_complete_case(client, draft, pdf)
        assert put_affidavit(client, draft, affidavit).status_code == 200

        assert fields_of(validate(client, draft)) == {"affidavit"}

    def test_an_empty_party_in_person_affidavit_is_reported(self, client, draft, pdf):
        complainant = make_complete_case(client, draft, pdf)
        CaseParticipant.objects.filter(pk=complainant["case_participant_id"]).update(
            party_in_person_affidavit="<p><br></p>"
        )

        assert fields_of(validate(client, draft)) == {
            f"participants.{complainant['case_participant_id']}"
        }

    def test_witnesses_are_optional(self, client, draft, pdf):
        make_complete_case(client, draft, pdf)

        assert not CaseParticipant.objects.filter(role=ParticipantRole.WITNESS).exists()
        assert validate(client, draft)["is_valid"] is True

    def test_a_witness_saved_before_the_rules_is_reported(self, client, draft, pdf):
        make_complete_case(client, draft, pdf)
        witness = add_witness(client, draft).json()
        # Stored another way than the API, which refuses each of these.
        CaseParticipant.objects.filter(pk=witness["case_participant_id"]).update(
            name_at_filing=None
        )
        CaseContact.objects.filter(case_participant_id=witness["case_participant_id"]).update(
            is_active=False
        )

        body = validate(client, draft)

        field = f"participants.{witness['case_participant_id']}"
        assert body["errors"] == [
            {"field": field, "message": "Witness #1 has no name or designation."},
            {"field": field, "message": "Witness #1 has no address."},
        ]

    def test_an_institution_is_served_at_its_own_address(self, client, draft, pdf):
        """The address of the person responsible for it does not stand in for it."""
        make_complete_case(client, draft, pdf)
        accused = add(
            client,
            draft,
            "accused",
            institution={**INSTITUTION, "mobile_numbers": ["080-22334455"]},
            person=PERSON,
            designation="Director",
            mobile_numbers=[ACCUSED_MOBILE],
            addresses=[ADDRESS_DEFAULTS],
        ).json()
        CaseContact.objects.filter(
            case_id=draft,
            institution_id=accused["institution_id"],
            case_participant__isnull=True,
            contact_type=ContactType.ADDRESS,
        ).update(is_active=False)

        assert validate(client, draft)["errors"] == [
            {
                "field": f"participants.{accused['case_participant_id']}",
                "message": "Accused #2 has no address.",
            }
        ]

    def test_a_witness_named_by_designation_alone_is_complete(self, client, draft, pdf):
        make_complete_case(client, draft, pdf)
        witness = add_witness(
            client,
            draft,
            person={},
            designation="Branch manager",
        )
        assert witness.status_code == 201, witness.json()

        assert validate(client, draft)["is_valid"] is True

    def test_a_party_with_no_name_is_reported(self, client, draft, pdf):
        complainant = make_complete_case(client, draft, pdf)
        CaseParticipant.objects.filter(pk=complainant["case_participant_id"]).update(
            name_at_filing=None
        )

        assert validate(client, draft)["errors"] == [
            {
                "field": f"participants.{complainant['case_participant_id']}",
                "message": "Complainant #1 has no name.",
            }
        ]

    @pytest.mark.parametrize(
        ("evidence_type", "evidence_info", "label"),
        [
            ("CHEQUE", CHEQUE_INFO, "Cheque"),
            ("RETURN_MEMO", RETURN_MEMO_INFO, "Return memo"),
            ("LEGAL_DEMAND_NOTICE", UNDELIVERED_NOTICE, "Legal demand notice"),
        ],
    )
    def test_each_evidence_item_needs_its_own_scan(
        self, client, draft, pdf, evidence_type, evidence_info, label
    ):
        make_complete_case(client, draft, pdf)
        # A cheque and its return memo come in pairs: the other half is filed whole.
        pair = {"CHEQUE": ("RETURN_MEMO", RETURN_MEMO_INFO), "RETURN_MEMO": ("CHEQUE", CHEQUE_INFO)}
        if evidence_type in pair:
            add_with_scan(client, draft, pdf, *pair[evidence_type])
        second = add_evidence(client, draft, evidence_type, evidence_info).json()
        if evidence_type == "LEGAL_DEMAND_NOTICE":
            # Its own proof of dispatch, so only the scan is missing.
            dispatch = upload(
                client,
                draft,
                pdf,
                "PROOF_OF_DISPATCH",
                case_evidence_id=second["case_evidence_id"],
            )
            assert dispatch.status_code == 201, dispatch.json()

        assert validate(client, draft)["errors"] == [
            {
                "field": f"documents.{SCAN_TYPES[evidence_type]}",
                "message": f"{label} #2 has no scan linked.",
            }
        ]

        scan = upload(client, draft, pdf, SCAN_TYPES[evidence_type]).json()
        url = reverse("case-evidence-detail", args=[second["case_evidence_id"]])
        linked = client.patch(url, {"case_document_id": scan["case_document_id"]}, format="json")
        assert linked.status_code == 200, linked.json()
        assert validate(client, draft)["is_valid"] is True

    def test_two_items_cannot_share_a_scan(self, client, draft, pdf):
        make_complete_case(client, draft, pdf)
        first = CaseEvidence.objects.get(case_id=draft, evidence_type="CHEQUE")

        response = add_evidence(
            client, draft, "CHEQUE", CHEQUE_INFO, case_document_id=str(first.case_document_id)
        )

        assert response.status_code == 400
        assert error_codes(response) == {"case_document_id": ["E07035"]}

    def test_the_database_refuses_a_shared_scan(self, client, draft, pdf):
        make_complete_case(client, draft, pdf)
        second = add_evidence(client, draft, "CHEQUE", CHEQUE_INFO).json()
        first = CaseEvidence.objects.get(case_id=draft, evidence_type="CHEQUE", ordinal=1)

        with pytest.raises(IntegrityError), transaction.atomic():
            CaseEvidence.objects.filter(pk=second["case_evidence_id"]).update(
                case_document_id=first.case_document_id
            )

    def test_a_poa_mandate_needs_a_poa_document(self, client, draft, pdf):
        complainant = make_complete_case(client, draft, pdf)
        response = client.post(
            reverse("case-poa-holder-list", args=[draft]),
            {
                "person": {**PERSON, "name": "Mohan Das"},
                "mobile_numbers": [POA_MOBILE],
                "addresses": [ADDRESS_DEFAULTS],
                "represented_participant_ids": [complainant["case_participant_id"]],
            },
            format="json",
        )
        assert response.status_code == 201, response.json()

        assert fields_of(validate(client, draft)) == {"documents.POA_DOCUMENT"}

        upload(
            client,
            draft,
            pdf,
            "POA_DOCUMENT",
            case_participant_id=complainant["case_participant_id"],
        )
        assert validate(client, draft)["is_valid"] is True

    def test_each_complainant_needs_their_own_identity_proof(self, client, draft, pdf):
        make_complete_case(client, draft, pdf)
        second = add(
            client,
            draft,
            person={**PERSON, "name": "Anil Rao"},
            mobile_numbers=[SECOND_MOBILE],
            is_party_in_person=True,
            party_in_person_affidavit=PIP_AFFIDAVIT,
        )
        # Not linked to anyone, so it counts for no complainant.
        upload(client, draft, pdf, "IDENTITY_PROOF")

        body = validate(client, draft)

        assert body["errors"] == [
            {
                "field": "documents.IDENTITY_PROOF",
                "message": "Complainant #2 has no identity proof.",
            }
        ]
        upload_identity_proof(client, draft, pdf, second.json())
        assert validate(client, draft)["is_valid"] is True

    def test_each_represented_complainant_needs_their_own_vakalatnama(
        self, client, make_user, draft, pdf
    ):
        make_complete_case(client, draft, pdf)
        second = add(
            client, draft, person={**PERSON, "name": "Anil Rao"}, mobile_numbers=[SECOND_MOBILE]
        ).json()
        upload_identity_proof(client, draft, pdf, second)
        advocate = make_advocate(make_user)
        assert (
            add_advocate(client, draft, advocate.pk, [second["case_participant_id"]]).status_code
            == 201
        )

        assert validate(client, draft)["errors"] == [
            {
                "field": "documents.VAKALATNAMA",
                "message": "Complainant #2 has an advocate but no vakalatnama.",
            }
        ]
        upload(client, draft, pdf, "VAKALATNAMA", case_participant_id=second["case_participant_id"])
        assert validate(client, draft)["is_valid"] is True

    def test_a_delivered_notice_needs_no_proof_of_delivery(self, client, draft, pdf):
        """PRD DCM-5: proof of delivery is optional."""
        make_complete_case(client, draft, pdf)
        CaseDocument.objects.filter(
            case_id=draft, document_type="PROOF_OF_DELIVERY_OF_DEMAND_NOTICE"
        ).update(is_active=False)

        assert validate(client, draft)["is_valid"] is True

    def test_a_notice_needs_its_proof_of_dispatch(self, client, draft, pdf):
        make_complete_case(client, draft, pdf)
        CaseDocument.objects.filter(case_id=draft, document_type="PROOF_OF_DISPATCH").update(
            is_active=False
        )

        assert validate(client, draft)["errors"] == [
            {
                "field": "documents.PROOF_OF_DISPATCH",
                "message": "Demand notice #1 has no proof of dispatch.",
            }
        ]

    def test_an_unlinked_proof_of_dispatch_counts_for_no_notice(self, client, draft, pdf):
        make_complete_case(client, draft, pdf)
        CaseDocument.objects.filter(case_id=draft, document_type="PROOF_OF_DISPATCH").update(
            case_evidence=None
        )

        assert validate(client, draft)["errors"] == [
            {
                "field": "documents.PROOF_OF_DISPATCH",
                "message": "Demand notice #1 has no proof of dispatch.",
            }
        ]

    def test_each_notice_needs_its_own_proof_of_dispatch(self, client, draft, pdf):
        """PRD DCM-4: one per demand notice; another notice's does not count."""
        make_complete_case(client, draft, pdf)
        second = add_with_scan(client, draft, pdf, "LEGAL_DEMAND_NOTICE", UNDELIVERED_NOTICE).json()

        assert validate(client, draft)["errors"] == [
            {
                "field": "documents.PROOF_OF_DISPATCH",
                "message": "Demand notice #2 has no proof of dispatch.",
            }
        ]

        response = upload(
            client, draft, pdf, "PROOF_OF_DISPATCH", case_evidence_id=second["case_evidence_id"]
        )
        assert response.status_code == 201, response.json()
        assert validate(client, draft)["is_valid"] is True

    def test_an_undelivered_notice_needs_no_proof_of_delivery(self, client, draft, pdf):
        make_complete_case(client, draft, pdf)
        CaseDocument.objects.filter(
            case_id=draft, document_type="PROOF_OF_DELIVERY_OF_DEMAND_NOTICE"
        ).update(is_active=False)
        notice = CaseEvidence.objects.get(case_id=draft, evidence_type="LEGAL_DEMAND_NOTICE")
        undelivered = {
            **DEMAND_NOTICE_INFO,
            "is_delivered": False,
            "return_date": "2024-02-10",
            "non_delivery_reason": "ADDRESSEE_NOT_AVAILABLE",
        }
        undelivered.pop("delivery_date")
        response = client.patch(
            reverse("case-evidence-detail", args=[notice.pk]),
            {"evidence_info": undelivered},
            format="json",
        )
        assert response.status_code == 200, response.json()

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

    def test_a_scan_of_the_wrong_type_is_reported(self, client, draft, pdf):
        """Linked before the rule existed, or through a path that skipped it."""
        make_complete_case(client, draft, pdf)
        dispatch = upload(client, draft, pdf, "PROOF_OF_DISPATCH").json()
        CaseEvidence.objects.filter(case_id=draft, evidence_type="CHEQUE").update(
            case_document_id=dispatch["case_document_id"]
        )

        assert fields_of(validate(client, draft)) == {"evidence.CHEQUE"}

    @pytest.mark.parametrize("relief", ["", "<p><br></p>", "<p>&nbsp;</p>"])
    @pytest.mark.parametrize("key", ["interim_relief", "final_relief"])
    def test_relief_with_no_visible_text_blocks_filing(self, client, draft, pdf, key, relief):
        make_complete_case(client, draft, pdf)
        row = ChequeBounceCase.objects.get(case_id=draft)
        ChequeBounceCase.objects.filter(case_id=draft).update(
            adr_other_prayer={**row.adr_other_prayer, key: relief}
        )

        body = validate(client, draft)

        assert fields_of(body) == {"details.adr_other_prayer"}

    @pytest.mark.parametrize(
        ("section", "key", "field"),
        [
            (
                "jurisdiction_limitation",
                "other_complaints_pending",
                "details.jurisdiction_limitation",
            ),
            ("adr_other_prayer", "adr_preference", "details.adr_other_prayer"),
            ("adr_other_prayer", "interim_relief", "details.adr_other_prayer"),
        ],
    )
    def test_a_section_answer_left_out_blocks_filing(self, client, draft, pdf, section, key, field):
        make_complete_case(client, draft, pdf)
        row = ChequeBounceCase.objects.get(case_id=draft)
        data = {k: v for k, v in getattr(row, section).items() if k != key}
        ChequeBounceCase.objects.filter(case_id=draft).update(**{section: data})

        body = validate(client, draft)

        assert any(
            f"'{key}' is a required property" in error["message"] for error in body["errors"]
        )
        assert fields_of(body) == {field}

    def test_whether_the_accused_replied_is_required(self, client, draft, pdf):
        make_complete_case(client, draft, pdf)
        notice = CaseEvidence.objects.get(case_id=draft, evidence_type="LEGAL_DEMAND_NOTICE")
        info = {k: v for k, v in notice.evidence_info.items() if k != "accused_replied"}
        # Saved without it: a draft may be partial.
        response = client.patch(
            reverse("case-evidence-detail", args=[notice.pk]),
            {"evidence_info": info},
            format="json",
        )
        assert response.status_code == 200, response.json()

        body = validate(client, draft)

        assert fields_of(body) == {"evidence.LEGAL_DEMAND_NOTICE"}
        assert "'accused_replied' is a required property" in body["errors"][0]["message"]

    def test_a_return_before_presentation_is_reported_when_written_another_way(
        self, client, draft, pdf
    ):
        make_complete_case(client, draft, pdf)
        memo = CaseEvidence.objects.get(case_id=draft, evidence_type="RETURN_MEMO")
        CaseEvidence.objects.filter(pk=memo.pk).update(
            evidence_info={**memo.evidence_info, "return_date": "2024-01-10"}
        )

        body = validate(client, draft)

        assert fields_of(body) == {"evidence.RETURN_MEMO"}
        assert "return date cannot be before the presentation date" in body["errors"][0]["message"]

    @pytest.mark.parametrize("key", ["delivery_date", "return_date"])
    def test_a_notice_dated_before_dispatch_is_reported_when_written_another_way(
        self, client, draft, pdf, key
    ):
        make_complete_case(client, draft, pdf)
        notice = CaseEvidence.objects.get(case_id=draft, evidence_type="LEGAL_DEMAND_NOTICE")
        CaseEvidence.objects.filter(pk=notice.pk).update(
            evidence_info={**notice.evidence_info, key: "2024-01-30"}
        )

        body = validate(client, draft)

        assert fields_of(body) == {"evidence.LEGAL_DEMAND_NOTICE"}
        assert "cannot be before the dispatch date" in body["errors"][0]["message"]

    def test_presentation_before_the_cheque_date_is_saved_and_reported(self, client, draft, pdf):
        make_complete_case(client, draft, pdf)
        memo = CaseEvidence.objects.get(case_id=draft, evidence_type="RETURN_MEMO")
        # The cheque is dated 2024-01-15; the memo is another item, so this saves.
        response = client.patch(
            reverse("case-evidence-detail", args=[memo.pk]),
            {
                "evidence_info": {
                    **RETURN_MEMO_INFO,
                    "presentation_date": "2024-01-10",
                    "return_date": "2024-01-12",
                }
            },
            format="json",
        )
        assert response.status_code == 200, response.json()

        assert validate(client, draft)["errors"] == [
            {
                "field": "evidence.RETURN_MEMO",
                "message": (
                    "Return memo #1: the presentation date cannot be before the date of cheque #1."
                ),
            }
        ]

    def test_presentation_on_the_cheque_date_is_valid(self, client, draft, pdf):
        make_complete_case(client, draft, pdf)
        memo = CaseEvidence.objects.get(case_id=draft, evidence_type="RETURN_MEMO")
        CaseEvidence.objects.filter(pk=memo.pk).update(
            evidence_info={**memo.evidence_info, "presentation_date": CHEQUE_INFO["cheque_date"]}
        )

        assert validate(client, draft)["is_valid"] is True

    def test_a_memo_is_compared_with_the_cheque_of_its_own_number(self, client, draft, pdf):
        make_complete_case(client, draft, pdf)
        add_with_scan(client, draft, pdf, "CHEQUE", {**CHEQUE_INFO, "cheque_date": "2024-01-20"})
        # Memo #1 is presented 01-18, before cheque #2's date but after cheque #1's;
        # cheque #2 has no memo yet.
        assert validate(client, draft)["errors"] == [
            {"field": "evidence.RETURN_MEMO", "message": "Cheque #2 has no return memo."}
        ]

        add_with_scan(
            client,
            draft,
            pdf,
            "RETURN_MEMO",
            {**RETURN_MEMO_INFO, "presentation_date": "2024-01-18", "return_date": "2024-01-22"},
        )

        assert validate(client, draft)["errors"] == [
            {
                "field": "evidence.RETURN_MEMO",
                "message": (
                    "Return memo #2: the presentation date cannot be before the date of cheque #2."
                ),
            }
        ]

    def test_each_cheque_needs_its_own_return_memo(self, client, draft, pdf):
        make_complete_case(client, draft, pdf)
        add_with_scan(client, draft, pdf, "CHEQUE", CHEQUE_INFO)
        add_with_scan(client, draft, pdf, "CHEQUE", CHEQUE_INFO)

        assert validate(client, draft)["errors"] == [
            {"field": "evidence.RETURN_MEMO", "message": "Cheque #2 has no return memo."},
            {"field": "evidence.RETURN_MEMO", "message": "Cheque #3 has no return memo."},
        ]

        add_with_scan(client, draft, pdf, "RETURN_MEMO", RETURN_MEMO_INFO)
        assert validate(client, draft)["errors"] == [
            {"field": "evidence.RETURN_MEMO", "message": "Cheque #3 has no return memo."},
        ]

        add_with_scan(client, draft, pdf, "RETURN_MEMO", RETURN_MEMO_INFO)
        assert validate(client, draft)["is_valid"] is True

    def test_a_return_memo_needs_a_cheque_of_the_same_number(self, client, draft, pdf):
        make_complete_case(client, draft, pdf)
        add_with_scan(client, draft, pdf, "RETURN_MEMO", RETURN_MEMO_INFO)

        assert validate(client, draft)["errors"] == [
            {
                "field": "evidence.RETURN_MEMO",
                "message": "Return memo #2 has no cheque of the same number.",
            }
        ]

    def test_a_removed_cheque_leaves_its_memo_unmatched(self, client, draft, pdf):
        make_complete_case(client, draft, pdf)
        CaseEvidence.objects.filter(case_id=draft, evidence_type="CHEQUE").update(is_active=False)

        body = validate(client, draft)

        assert {
            "field": "evidence.CHEQUE",
            "message": "At least one cheque evidence is required.",
        } in (body["errors"])
        assert {
            "field": "evidence.RETURN_MEMO",
            "message": "Return memo #1 has no cheque of the same number.",
        } in body["errors"]

    def test_a_notice_needs_a_cheque_returned_on_or_before_its_dispatch(self, client, draft, pdf):
        make_complete_case(client, draft, pdf)
        # The memo is returned 2024-01-22; the notice is dispatched before that.
        notice = CaseEvidence.objects.get(case_id=draft, evidence_type="LEGAL_DEMAND_NOTICE")
        response = client.patch(
            reverse("case-evidence-detail", args=[notice.pk]),
            {
                "evidence_info": {
                    **DEMAND_NOTICE_INFO,
                    "dispatch_date": "2024-01-21",
                    "delivery_date": "2024-01-25",
                }
            },
            format="json",
        )
        assert response.status_code == 200, response.json()

        assert validate(client, draft)["errors"] == [
            {
                "field": "evidence.LEGAL_DEMAND_NOTICE",
                "message": (
                    "Demand notice #1: at least one cheque must have been returned on or "
                    "before the dispatch date."
                ),
            }
        ]

    def test_a_notice_dispatched_on_the_return_date_is_valid(self, client, draft, pdf):
        make_complete_case(client, draft, pdf)
        notice = CaseEvidence.objects.get(case_id=draft, evidence_type="LEGAL_DEMAND_NOTICE")
        CaseEvidence.objects.filter(pk=notice.pk).update(
            evidence_info={
                **notice.evidence_info,
                "dispatch_date": RETURN_MEMO_INFO["return_date"],
                "delivery_date": "2024-01-25",
            }
        )

        assert validate(client, draft)["is_valid"] is True

    def test_one_returned_cheque_is_enough_for_a_notice(self, client, draft, pdf):
        make_complete_case(client, draft, pdf)
        # A second cheque returned after the dispatch date (2024-02-01).
        add_with_scan(client, draft, pdf, "CHEQUE", {**CHEQUE_INFO, "cheque_date": "2024-01-15"})
        add_with_scan(
            client,
            draft,
            pdf,
            "RETURN_MEMO",
            {**RETURN_MEMO_INFO, "presentation_date": "2024-02-10", "return_date": "2024-02-12"},
        )

        assert validate(client, draft)["is_valid"] is True

    def test_a_notice_is_not_faulted_while_no_return_date_is_given(self, client, draft, pdf):
        make_complete_case(client, draft, pdf)
        memo = CaseEvidence.objects.get(case_id=draft, evidence_type="RETURN_MEMO")
        info = {k: v for k, v in memo.evidence_info.items() if k != "return_date"}
        CaseEvidence.objects.filter(pk=memo.pk).update(evidence_info=info)

        body = validate(client, draft)

        # Only the memo's own missing date is reported.
        assert [error["message"] for error in body["errors"]] == [
            "Return memo #1: 'return_date' is a required property"
        ]

    def test_a_late_filing_without_a_condonation_reason_is_reported(self, client, draft, pdf):
        # Written another way (the admin, a shell, a rule added since saving).
        make_complete_case(client, draft, pdf)
        section = {**JURISDICTION, "complaint_filing_date": "2024-04-30"}
        ChequeBounceCase.objects.filter(case_id=draft).update(jurisdiction_limitation=section)

        assert fields_of(validate(client, draft)) == {"details.jurisdiction_limitation"}

    def test_other_users_cases_are_not_found(self, client, client_for, other_user, draft):
        add_complainant(client, draft)

        response = client_for(other_user).post(reverse("case-validate", args=[draft]))

        assert response.status_code == 404


def messages_on(body, participant):
    """Return what ``body`` reports on one participant."""
    field = f"participants.{participant['case_participant_id']}"
    return [error["message"] for error in body["errors"] if error["field"] == field]


def patch_participant(client, participant, body):
    url = reverse("case-participant-detail", args=[participant["case_participant_id"]])
    response = client.patch(url, body, format="json")
    assert response.status_code == 200, response.json()
    return response.json()


class TestInstitutionsAndAccusedContacts:
    """An institution's people, and an accused's contacts, as the completeness check asks."""

    NO_CONTACT_MESSAGE = (
        "has no mobile number or email, and {} contact details are not declared unknown."
    )

    def add_institution_complainant(self, client, draft, pdf, **body):
        response = add(
            client,
            draft,
            institution=INSTITUTION,
            is_party_in_person=True,
            party_in_person_affidavit=PIP_AFFIDAVIT,
            **body,
        )
        assert response.status_code == 201, response.json()
        upload_identity_proof(client, draft, pdf, response.json())
        return response.json()

    def add_person_responsible(self, client, draft, name, **body):
        body.setdefault("designation", "Director")
        body.setdefault("addresses", [ADDRESS_DEFAULTS])
        body.setdefault("mobile_numbers", [ACCUSED_MOBILE])
        response = add(client, draft, "accused", person={**PERSON, "name": name}, **body)
        assert response.status_code == 201, response.json()
        return response.json()

    def test_an_institution_complainant_with_its_representative_is_complete(
        self, client, draft, pdf
    ):
        make_complete_case(client, draft, pdf)

        self.add_institution_complainant(
            client,
            draft,
            pdf,
            person=PERSON,
            designation="Director",
            mobile_numbers=[SECOND_MOBILE],
            addresses=[ADDRESS_DEFAULTS],
        )

        assert validate(client, draft)["is_valid"] is True

    def test_an_institution_complainant_needs_an_authorised_representative(
        self, client, draft, pdf
    ):
        make_complete_case(client, draft, pdf)
        complainant = self.add_institution_complainant(client, draft, pdf)

        assert validate(client, draft)["errors"] == [
            {
                "field": f"participants.{complainant['case_participant_id']}",
                "message": "Complainant #2's institution has no authorised representative.",
            }
        ]
        response = submit(client, draft, "signing")
        assert response.status_code == 400
        assert error_codes(response) == {
            f"participants.{complainant['case_participant_id']}": ["E07005"]
        }

    def test_the_representative_needs_their_own_details(self, client, draft, pdf):
        """The institution's own number is not its representative's."""
        make_complete_case(client, draft, pdf)
        unnamed = {k: v for k, v in PERSON.items() if k not in ("name", "date_of_birth")}
        complainant = self.add_institution_complainant(
            client, draft, pdf, person=unnamed, mobile_numbers=[]
        )
        assert complainant["institution"]["mobile_numbers"] == INSTITUTION["mobile_numbers"]

        assert messages_on(validate(client, draft), complainant) == [
            "Complainant #2 has no name.",
            "Complainant #2 acts for an institution but has no address of their own.",
            "Complainant #2 has no mobile number.",
            "Complainant #2 has no age.",
            "Complainant #2 acts for an institution but has no designation.",
        ]

        patch_participant(
            client,
            complainant,
            {
                "name_at_filing": "Priya Sharma",
                "age_at_filing": 45,
                "designation_at_filing": "Director",
                "mobile_numbers": ["+919812345678"],
                "addresses": [ADDRESS_DEFAULTS],
            },
        )
        assert validate(client, draft)["is_valid"] is True

    def test_the_representatives_address_must_be_complete(self, client, draft, pdf):
        make_complete_case(client, draft, pdf)
        partial = {k: v for k, v in ADDRESS_DEFAULTS.items() if k != "city"}

        complainant = self.add_institution_complainant(
            client, draft, pdf, person=PERSON, designation="Director", addresses=[partial]
        )

        assert messages_on(validate(client, draft), complainant) == [
            "Complainant #2 has an incomplete address (missing city).",
        ]

    def test_an_accused_needs_a_phone_an_email_or_the_declaration(self, client, draft, pdf):
        make_complete_case(client, draft, pdf)
        accused = add(
            client, draft, "accused", person={**PERSON, "name": "Mohan"}, mobile_numbers=[]
        ).json()

        assert validate(client, draft)["errors"] == [
            {
                "field": f"participants.{accused['case_participant_id']}",
                "message": f"Accused #2 {self.NO_CONTACT_MESSAGE.format('their')}",
            }
        ]
        response = submit(client, draft, "signing")
        assert response.status_code == 400
        assert error_codes(response) == {
            f"participants.{accused['case_participant_id']}": ["E07005"]
        }

        patch_participant(client, accused, {"contact_details_unknown_declared": True})
        assert validate(client, draft)["is_valid"] is True

    @pytest.mark.parametrize(
        "contacts",
        [{"mobile_numbers": ["+919812345678"]}, {"email_addresses": ["mohan@example.com"]}],
    )
    def test_a_phone_or_an_email_is_enough_for_an_accused(self, client, draft, pdf, contacts):
        make_complete_case(client, draft, pdf)

        response = add(
            client,
            draft,
            "accused",
            person={**PERSON, "name": "Mohan"},
            **{"mobile_numbers": [], **contacts},
        )

        assert response.status_code == 201, response.json()
        assert validate(client, draft)["is_valid"] is True

    def test_an_accused_institution_and_each_person_are_reached_apart(self, client, draft, pdf):
        """PRD ACC-6/7, ACC-16/17: the institution, and each person responsible, on their own."""
        make_complete_case(client, draft, pdf)
        institution = {**INSTITUTION, "mobile_numbers": []}
        first = self.add_person_responsible(
            client, draft, "Ravi", institution=institution, mobile_numbers=[]
        )
        second = self.add_person_responsible(
            client, draft, "Asha", institution_id=first["institution_id"], mobile_numbers=[]
        )

        assert validate(client, draft)["errors"] == [
            {
                "field": f"participants.{first['case_participant_id']}",
                "message": f"Accused #2's institution {self.NO_CONTACT_MESSAGE.format('its')}",
            },
            {
                "field": f"participants.{first['case_participant_id']}",
                "message": f"Accused #2 {self.NO_CONTACT_MESSAGE.format('their')}",
            },
            {
                "field": f"participants.{second['case_participant_id']}",
                "message": f"Accused #3 {self.NO_CONTACT_MESSAGE.format('their')}",
            },
        ]

        # One person's declaration is theirs alone.
        patch_participant(client, second, {"contact_details_unknown_declared": True})
        assert fields_of(validate(client, draft)) == {
            f"participants.{first['case_participant_id']}"
        }
        patch_participant(client, first, {"mobile_numbers": ["+919845500001"]})
        assert messages_on(validate(client, draft), first) == [
            f"Accused #2's institution {self.NO_CONTACT_MESSAGE.format('its')}"
        ]

        # The institution's, sent through any of its people, is for it alone.
        patch_participant(
            client, second, {"institution_contacts": {"contact_details_unknown_declared": True}}
        )
        assert validate(client, draft)["is_valid"] is True

    @pytest.mark.parametrize(
        "contacts",
        [{"email_addresses": ["legal@abc.example"]}, {"mobile_numbers": ["080-22334455"]}],
    )
    def test_the_institutions_own_number_or_email_reaches_it(self, client, draft, pdf, contacts):
        make_complete_case(client, draft, pdf)
        institution = {**INSTITUTION, "mobile_numbers": []}
        first = self.add_person_responsible(client, draft, "Ravi", institution=institution)

        assert messages_on(validate(client, draft), first) == [
            f"Accused #2's institution {self.NO_CONTACT_MESSAGE.format('its')}"
        ]

        patch_participant(client, first, {"institution_contacts": contacts})
        assert validate(client, draft)["is_valid"] is True

    def test_a_persons_number_does_not_reach_the_institution(self, client, draft, pdf):
        make_complete_case(client, draft, pdf)
        institution = {**INSTITUTION, "mobile_numbers": []}
        first = self.add_person_responsible(client, draft, "Ravi", institution=institution)
        second = self.add_person_responsible(
            client, draft, "Asha", institution_id=first["institution_id"]
        )

        assert validate(client, draft)["errors"] == [
            {
                "field": f"participants.{first['case_participant_id']}",
                "message": f"Accused #2's institution {self.NO_CONTACT_MESSAGE.format('its')}",
            }
        ]
        assert messages_on(validate(client, draft), second) == []

    def test_the_institutions_number_does_not_reach_a_person(self, client, draft, pdf):
        make_complete_case(client, draft, pdf)
        first = self.add_person_responsible(
            client, draft, "Ravi", institution=INSTITUTION, mobile_numbers=[]
        )

        assert validate(client, draft)["errors"] == [
            {
                "field": f"participants.{first['case_participant_id']}",
                "message": f"Accused #2 {self.NO_CONTACT_MESSAGE.format('their')}",
            }
        ]

    def test_an_institution_alone_is_reached_by_its_own(self, client, draft, pdf):
        """An accused institution's participant with no person has no contacts of its own."""
        make_complete_case(client, draft, pdf)
        first = self.add_person_responsible(client, draft, "Ravi", institution=INSTITUTION)
        alone = add(client, draft, "accused", institution=INSTITUTION)
        assert alone.status_code == 201, alone.json()
        assert alone.json()["institution_id"] == first["institution_id"]

        assert validate(client, draft)["is_valid"] is True

    def test_an_accused_institution_names_at_least_one_person(self, client, draft, pdf):
        make_complete_case(client, draft, pdf)
        institution = add(client, draft, "accused", institution=INSTITUTION).json()

        assert validate(client, draft)["errors"] == [
            {
                "field": f"participants.{institution['case_participant_id']}",
                "message": "Accused #2's institution names no person responsible.",
            }
        ]

        self.add_person_responsible(
            client, draft, "Ravi", institution_id=institution["institution_id"]
        )
        assert validate(client, draft)["is_valid"] is True

    def test_each_person_responsible_needs_their_own_details(self, client, draft, pdf):
        make_complete_case(client, draft, pdf)
        first = self.add_person_responsible(client, draft, "Ravi", institution=INSTITUTION)
        second = self.add_person_responsible(
            client,
            draft,
            "Asha",
            institution_id=first["institution_id"],
            designation="",
            addresses=[],
        )
        # Stored another way than the API, which keeps the name it is sent.
        CaseParticipant.objects.filter(pk=second["case_participant_id"]).update(name_at_filing=None)

        body = validate(client, draft)

        assert messages_on(body, first) == []
        assert messages_on(body, second) == [
            "Accused #3 has no name.",
            "Accused #3 acts for an institution but has no address of their own.",
        ]


class TestPoaHoldersAndNumbers:
    """A POA holder's own details (PRD LIT-11, LIT-13), and a complainant's own number (LIT-3)."""

    def add_poa_holder(self, client, draft, pdf, complainant, **body):
        """Add a POA holder for ``complainant``, with the POA document filed; return the holder."""
        response = add_poa_holder(client, draft, [complainant["case_participant_id"]], **body)
        assert response.status_code == 201, response.json()
        document = upload(
            client,
            draft,
            pdf,
            "POA_DOCUMENT",
            case_participant_id=complainant["case_participant_id"],
        )
        assert document.status_code == 201, document.json()
        return response.json()

    def add_second_complainant(self, client, draft, pdf, mobile_number, **body):
        body.setdefault("person", {**PERSON, "name": "Anita Kumar"})
        response = add(
            client,
            draft,
            mobile_numbers=[mobile_number],
            is_party_in_person=True,
            party_in_person_affidavit=PIP_AFFIDAVIT,
            **body,
        )
        assert response.status_code == 201, response.json()
        upload_identity_proof(client, draft, pdf, response.json())
        return response.json()

    def test_a_poa_holder_with_a_number_and_an_age_is_complete(self, client, draft, pdf):
        complainant = make_complete_case(client, draft, pdf)

        self.add_poa_holder(client, draft, pdf, complainant, mobile_numbers=[POA_MOBILE])

        assert validate(client, draft)["is_valid"] is True

    def answer_poa(self, client, complainant, given=True):
        response = patch(client, complainant["case_participant_id"], {"poa_given": given})
        assert response.status_code == 200, response.json()

    def test_a_poa_given_with_no_holder_is_incomplete(self, client, draft, pdf):
        complainant = make_complete_case(client, draft, pdf)
        self.answer_poa(client, complainant)

        assert validate(client, draft)["errors"] == [
            {
                "field": f"participants.{complainant['case_participant_id']}",
                "message": "Complainant #1 has given a power of attorney but has no POA holder.",
            },
            {
                "field": "documents.POA_DOCUMENT",
                "message": "Complainant #1 has given a power of attorney but has no POA document.",
            },
        ]

    def test_no_poa_given_or_not_answered_asks_for_nothing(self, client, draft, pdf):
        complainant = make_complete_case(client, draft, pdf)
        assert validate(client, draft)["is_valid"] is True

        self.answer_poa(client, complainant, given=False)

        assert validate(client, draft)["is_valid"] is True

    def test_a_poa_given_needs_the_holders_id_card_and_the_poa_document(self, client, draft, pdf):
        complainant = make_complete_case(client, draft, pdf)
        self.answer_poa(client, complainant)
        response = add_poa_holder(
            client,
            draft,
            [complainant["case_participant_id"]],
            mobile_numbers=[POA_MOBILE],
        )
        assert response.status_code == 201, response.json()
        holder = response.json()

        assert validate(client, draft)["errors"] == [
            {
                "field": "documents.POA_DOCUMENT",
                "message": "Complainant #1 acts through a POA holder but has no POA document.",
            },
            {
                "field": "documents.IDENTITY_PROOF",
                "message": "POA holder #1 has no identity proof.",
            },
        ]

        upload(
            client,
            draft,
            pdf,
            "POA_DOCUMENT",
            case_participant_id=complainant["case_participant_id"],
        )
        assert fields_of(validate(client, draft)) == {"documents.IDENTITY_PROOF"}

        upload_identity_proof(client, draft, pdf, holder)
        assert validate(client, draft)["is_valid"] is True

    def test_an_id_card_of_another_party_is_not_the_holders(self, client, draft, pdf):
        complainant = make_complete_case(client, draft, pdf)
        self.answer_poa(client, complainant)
        self.add_poa_holder(client, draft, pdf, complainant, mobile_numbers=[POA_MOBILE])

        # The complainant's own ID card is already filed.
        assert validate(client, draft)["errors"] == [
            {
                "field": "documents.IDENTITY_PROOF",
                "message": "POA holder #1 has no identity proof.",
            }
        ]

    def test_a_holder_for_two_complainants_is_asked_for_one_id_card(self, client, draft, pdf):
        first = make_complete_case(client, draft, pdf)
        second = self.add_second_complainant(client, draft, pdf, SECOND_MOBILE)
        self.answer_poa(client, first)
        self.answer_poa(client, second)
        response = add_poa_holder(
            client,
            draft,
            [first["case_participant_id"], second["case_participant_id"]],
            mobile_numbers=[POA_MOBILE],
        )
        assert response.status_code == 201, response.json()
        for complainant in (first, second):
            upload(
                client,
                draft,
                pdf,
                "POA_DOCUMENT",
                case_participant_id=complainant["case_participant_id"],
            )

        body = validate(client, draft)

        assert body["errors"] == [
            {
                "field": "documents.IDENTITY_PROOF",
                "message": "POA holder #1 has no identity proof.",
            }
        ]

    def test_a_holder_with_no_answer_given_is_not_asked_for_an_id_card(self, client, draft, pdf):
        complainant = make_complete_case(client, draft, pdf)

        self.add_poa_holder(client, draft, pdf, complainant, mobile_numbers=[POA_MOBILE])

        assert validate(client, draft)["is_valid"] is True

    def test_a_revoked_poa_leaves_the_answer_unmet(self, client, draft, pdf):
        complainant = make_complete_case(client, draft, pdf)
        self.answer_poa(client, complainant)
        holder = self.add_poa_holder(client, draft, pdf, complainant, mobile_numbers=[POA_MOBILE])
        upload_identity_proof(client, draft, pdf, holder)
        assert validate(client, draft)["is_valid"] is True

        for mandate_id in holder["poa_mandate_ids"]:
            assert (
                client.delete(reverse("poa-mandate-detail", args=[mandate_id])).status_code == 204
            )

        assert any(
            error["message"].endswith("has no POA holder.")
            for error in validate(client, draft)["errors"]
        )

    def test_a_poa_holder_needs_a_mobile_number_and_an_age(self, client, draft, pdf):
        complainant = make_complete_case(client, draft, pdf)
        no_age = {k: v for k, v in PERSON.items() if k != "date_of_birth"}
        holder = self.add_poa_holder(
            client, draft, pdf, complainant, person={**no_age, "name": "Mohan Das"}
        )

        body = validate(client, draft)

        assert body["errors"] == [
            {
                "field": f"participants.{holder['case_participant_id']}",
                "message": "POA holder #1 has no mobile number.",
            },
            {
                "field": f"participants.{holder['case_participant_id']}",
                "message": "POA holder #1 has no age.",
            },
        ]
        response = submit(client, draft, "signing")
        assert response.status_code == 400
        assert error_codes(response) == {
            f"participants.{holder['case_participant_id']}": ["E07005", "E07005"]
        }

        url = reverse("case-participant-detail", args=[holder["case_participant_id"]])
        response = client.patch(
            url, {"mobile_numbers": [POA_MOBILE], "age_at_filing": 52}, format="json"
        )
        assert response.status_code == 200, response.json()
        assert validate(client, draft)["is_valid"] is True

    def test_a_complainant_may_not_give_the_accuseds_number(self, client, draft, pdf):
        complainant = make_complete_case(client, draft, pdf)
        url = reverse("case-participant-detail", args=[complainant["case_participant_id"]])
        assert (
            client.patch(url, {"mobile_numbers": [ACCUSED_MOBILE]}, format="json").status_code
            == 200
        )

        assert validate(client, draft)["errors"] == [
            {
                "field": f"participants.{complainant['case_participant_id']}",
                "message": "Complainant #1's mobile number is also Accused #1's.",
            }
        ]

    def test_two_complainants_sharing_a_number_are_both_reported(self, client, draft, pdf):
        first = make_complete_case(client, draft, pdf)
        second = self.add_second_complainant(client, draft, pdf, MOBILE)

        assert validate(client, draft)["errors"] == [
            {
                "field": f"participants.{first['case_participant_id']}",
                "message": "Complainant #1's mobile number is also Complainant #2's.",
            },
            {
                "field": f"participants.{second['case_participant_id']}",
                "message": "Complainant #2's mobile number is also Complainant #1's.",
            },
        ]

    def test_any_of_a_complainants_numbers_is_compared(self, client, draft, pdf):
        complainant = make_complete_case(client, draft, pdf)
        url = reverse("case-participant-detail", args=[complainant["case_participant_id"]])
        response = client.patch(url, {"mobile_numbers": [MOBILE, ACCUSED_MOBILE]}, format="json")
        assert response.status_code == 200, response.json()

        assert validate(client, draft)["errors"] == [
            {
                "field": f"participants.{complainant['case_participant_id']}",
                "message": "Complainant #1's mobile number is also Accused #1's.",
            }
        ]

    def test_a_complainant_may_not_give_a_poa_holders_number(self, client, draft, pdf):
        complainant = make_complete_case(client, draft, pdf)
        self.add_poa_holder(client, draft, pdf, complainant, mobile_numbers=[MOBILE])

        assert validate(client, draft)["errors"] == [
            {
                "field": f"participants.{complainant['case_participant_id']}",
                "message": "Complainant #1's mobile number is also POA holder #1's.",
            }
        ]

    def test_a_number_written_with_grouping_is_still_the_same(self, client, draft, pdf):
        """An institution's number may be grouped; the grouping is not compared."""
        complainant = make_complete_case(client, draft, pdf)
        accused = add(
            client,
            draft,
            "accused",
            institution={**INSTITUTION, "mobile_numbers": ["+91 98765-43210"]},
            person={**PERSON, "name": "Ravi"},
            designation="Director",
            mobile_numbers=[ACCUSED_MOBILE],
            addresses=[ADDRESS_DEFAULTS],
        )
        assert accused.status_code == 201, accused.json()

        assert validate(client, draft)["errors"] == [
            {
                "field": f"participants.{complainant['case_participant_id']}",
                "message": "Complainant #1's mobile number is also Accused #2's institution's.",
            }
        ]

    def test_the_same_person_in_another_role_may_share_it(self, client, draft, pdf):
        """The filer, a complainant, is also the POA holder of a co-complainant."""
        first = make_complete_case(client, draft, pdf)
        filer = {"self": True, "mobile_numbers": [SECOND_MOBILE]}
        second = add(
            client,
            draft,
            is_party_in_person=True,
            party_in_person_affidavit=PIP_AFFIDAVIT,
            **filer,
        )
        assert second.status_code == 201, second.json()
        upload_identity_proof(client, draft, pdf, second.json())

        # The module's helper: ``self`` is a field of the request here.
        holder = add_poa_holder(client, draft, [first["case_participant_id"]], person=None, **filer)
        assert holder.status_code == 201, holder.json()
        upload(client, draft, pdf, "POA_DOCUMENT", case_participant_id=first["case_participant_id"])

        assert holder.json()["person_id"] == second.json()["person_id"]
        # The filer's account holds no age; each role states it.
        for participant in (second.json(), holder.json()):
            url = reverse("case-participant-detail", args=[participant["case_participant_id"]])
            assert client.patch(url, {"age_at_filing": 45}, format="json").status_code == 200
        assert validate(client, draft)["is_valid"] is True

    def test_a_complainant_may_not_give_an_advocates_number(self, client, make_user, draft, pdf):
        complainant = make_complete_case(client, draft, pdf)
        advocate = make_advocate(make_user)
        second = self.add_second_complainant(client, draft, pdf, SECOND_MOBILE)
        url = reverse("case-participant-detail", args=[second["case_participant_id"]])
        assert client.patch(url, {"is_party_in_person": False}, format="json").status_code == 200
        assert (
            add_advocate(client, draft, advocate.pk, [second["case_participant_id"]]).status_code
            == 201
        )
        upload(client, draft, pdf, "VAKALATNAMA", case_participant_id=second["case_participant_id"])
        assert validate(client, draft)["is_valid"] is True
        url = reverse("case-participant-detail", args=[complainant["case_participant_id"]])
        number = advocate.user.mobile_number
        assert client.patch(url, {"mobile_numbers": [number]}, format="json").status_code == 200

        assert validate(client, draft)["errors"] == [
            {
                "field": f"participants.{complainant['case_participant_id']}",
                "message": "Complainant #1: Please do not enter the advocate's number here.",
            }
        ]

    def test_a_witness_may_share_a_complainants_number(self, client, draft, pdf):
        make_complete_case(client, draft, pdf)

        assert add_witness(client, draft, mobile_numbers=[MOBILE]).status_code == 201

        assert validate(client, draft)["is_valid"] is True


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
        second = add(
            client,
            draft,
            person={**PERSON, "name": "Anil Rao"},
            mobile_numbers=[SECOND_MOBILE],
            is_party_in_person=True,
            party_in_person_affidavit=PIP_AFFIDAVIT,
        )
        upload_identity_proof(client, draft, pdf, second.json())
        assert submit(client, draft, "signing").status_code == 200
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

    def test_a_case_sent_back_to_signing_is_signed_again(self, client, user, draft, pending):
        participant_id = pending["case_participant_id"]
        sign(client, draft, participant_id, signed_document(user, draft))
        unused = signed_document(
            user, draft, completed_at=timezone.now() - timezone.timedelta(seconds=1)
        )
        case = Case.objects.get(pk=draft)
        with pytest.raises(BusinessError) as excinfo:
            return_to_signing(case)
        assert excinfo.value.error.code == "E07004"
        case.status = CaseStatus.PENDING_CORRECTION
        case.save()
        return_to_signing(case)
        assert Case.objects.get(pk=draft).status == CaseStatus.PENDING_SIGN
        participant = CaseParticipant.objects.get(pk=participant_id)
        assert (participant.has_signed, participant.signature_document_id) == (False, None)
        # A save while still pending signature is not a new submission.
        case.save()

        response = sign(client, draft, participant_id, unused)
        assert error_codes(response) == {"signature_document_id": ["E07028"]}
        response = sign(client, draft, participant_id, signed_document(user, draft))
        assert response.status_code == 200

    def test_an_incomplete_correction_is_not_sent_to_signing(self, client, user, draft, pending):
        participant_id = pending["case_participant_id"]
        sign(client, draft, participant_id, signed_document(user, draft))
        CaseEvidence.objects.filter(case_id=draft, evidence_type="CHEQUE").update(is_active=False)
        case = Case.objects.get(pk=draft)
        case.status = CaseStatus.PENDING_CORRECTION
        case.save()

        with pytest.raises(ValidationError) as excinfo:
            return_to_signing(case)

        assert excinfo.value.detail["evidence.CHEQUE"][0].code == "E07005"
        assert Case.objects.get(pk=draft).status == CaseStatus.PENDING_CORRECTION
        assert CaseParticipant.objects.get(pk=participant_id).has_signed is True

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

    def test_resubmission_keeps_the_first_filing_date(self, client, draft):
        add_complainant(client, draft)
        filed_at = timezone.now() - datetime.timedelta(days=6)
        Case.objects.filter(pk=draft).update(filed_at=filed_at)
        set_status(draft, CaseStatus.PENDING_PAYMENT)

        response = submit(client, draft, "scrutiny")

        assert response.status_code == 200
        assert Case.objects.get(pk=draft).filed_at == filed_at

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
