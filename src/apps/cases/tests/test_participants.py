"""Tests for the party, participant, representation and POA mandate endpoints (spec 0021 §4)."""

import uuid

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.urls import reverse

from apps.cases.models import (
    Case,
    CaseContact,
    CaseParticipant,
    CaseStatus,
    CaseType,
    ParticipantRole,
    PoaMandate,
    Representation,
    Witness,
)
from apps.cases.services import services
from apps.parties.models import Institution, Person, VerificationLevel
from apps.parties.tests.factories import ADDRESS_DEFAULTS, make_institution
from apps.users.models import AdvocateProfile, ApprovalStatus

from .conftest import error_codes

pytestmark = pytest.mark.django_db

MOBILE = "+919876543210"
PERSON = {
    "name": "Rajesh Kumar",
    "date_of_birth": "1985-06-15",
    "gender": "MALE",
    "relation": "SON_OF",
    "relative_name": "Ram Kumar",
}

INSTITUTION = {
    "entity_type": "PRIVATE_LIMITED_COMPANY",
    "entity_name": "ABC Pvt Ltd",
    "pan": "AAACA1234A",
    "mobile_numbers": ["080-22334455"],
}


def add(client, case_id, role="complainant", **body):
    """Add a party; an institution, or else the individual, gets the default address."""
    if isinstance(body.get("institution"), dict):
        body["institution"] = {"addresses": [ADDRESS_DEFAULTS], **body["institution"]}
    elif body.get("person") or body.get("self"):
        body.setdefault("addresses", [ADDRESS_DEFAULTS])
    if body.get("person"):
        body.setdefault("mobile_numbers", [MOBILE])
    return client.post(reverse(f"case-{role}-list", args=[case_id]), body, format="json")


def add_complainant(client, case_id, **person):
    response = add(client, case_id, person={**PERSON, **person})
    assert response.status_code == 201, response.json()
    return response.json()


def listing(client, case_id, **params):
    return client.get(reverse("case-participant-list", args=[case_id]), params).json()


def patch(client, participant_id, body):
    url = reverse("case-participant-detail", args=[participant_id])
    return client.patch(url, body, format="json")


def remove(client, participant_id):
    return client.delete(reverse("case-participant-detail", args=[participant_id]))


def make_participant(case, role, ordinal=1, **fields):
    """Create a participant directly, for roles whose endpoints come later."""
    person = Person.objects.create(name=f"{role} {ordinal}")
    return CaseParticipant.objects.create(
        case=case,
        person=person,
        role=role,
        ordinal=ordinal,
        name_at_filing=person.name,
        **fields,
    )


class TestAddComplainant:
    def test_first_complainant_on_a_draft_creates_the_case(self, client, draft):
        body = add_complainant(client, draft)

        case = Case.objects.get(pk=draft)
        assert body["case_id"] == draft
        assert body["role"] == "COMPLAINANT"
        assert body["ordinal"] == 1
        assert body["name_at_filing"] == "Rajesh Kumar"
        assert body["mobile_numbers"] == [MOBILE]
        assert body["addresses"][0]["pincode"] == ADDRESS_DEFAULTS["pincode"]
        assert body["gender_at_filing"] == "MALE"
        assert body["age_at_filing"] >= 39
        assert body["is_active"] is True
        assert "created_by" not in body
        assert case.updated_by is not None

    def test_a_named_person_is_new_and_asserted_with_the_address(self, client, draft):
        body = add_complainant(client, draft)

        person = Person.objects.get(pk=body["person_id"])
        assert person.verification_level == VerificationLevel.ASSERTED
        assert person.user is None
        assert person.phone_number == MOBILE
        assert str(person.correspondence_address_id) == body["addresses"][0]["address_id"]

    def test_the_same_name_twice_is_never_matched(self, client, draft):
        add_complainant(client, draft)
        second = add_complainant(client, draft)

        assert second["ordinal"] == 2
        assert Person.objects.filter(name="Rajesh Kumar").count() == 2

    def test_identical_addresses_share_one_row(self, client, draft):
        first = add_complainant(client, draft)
        second = add_complainant(client, draft, name="Anita Kumar")

        assert first["addresses"][0]["address_id"] == second["addresses"][0]["address_id"]

    def test_self_creates_a_verified_person_from_the_account(self, client, user, draft):
        response = add(client, draft, self=True)

        assert response.status_code == 201
        person = Person.objects.get(user=user)
        assert response.json()["person_id"] == str(person.pk)
        assert person.verification_level == VerificationLevel.VERIFIED
        assert person.phone_number == user.mobile_number
        assert response.json()["name_at_filing"] == user.name

    def test_self_reuses_the_filers_person_unchanged(self, client, user, draft):
        add(client, draft, self=True)
        person = Person.objects.get(user=user)
        other = client.post(reverse("case-list"), {"case_type": "CHEQUE_BOUNCE"}, format="json")

        response = add(client, other.json()["draft_session_id"], self=True)

        assert response.json()["person_id"] == str(person.pk)
        assert Person.objects.filter(user=user).count() == 1

    def test_self_twice_on_one_case_is_400(self, client, draft):
        add(client, draft, self=True)

        response = add(client, draft, self=True)

        assert response.status_code == 400
        assert error_codes(response) == {"person": ["E07013"]}

    def test_person_and_self_together_is_400(self, client, draft):
        response = add(client, draft, self=True, person=PERSON)

        assert response.status_code == 400
        assert not Case.objects.exists()

    def test_nobody_named_is_400(self, client, draft):
        assert add(client, draft).status_code == 400

    def test_address_is_required(self, client, draft):
        response = client.post(
            reverse("case-complainant-list", args=[draft]),
            {"person": PERSON},
            format="json",
        )

        assert response.status_code == 400
        assert error_codes(response) == {"addresses": ["E00002"]}
        assert not Case.objects.exists()

    def test_invalid_mobile_number_is_400_and_creates_nothing(self, client, draft):
        response = add(client, draft, person=PERSON, mobile_numbers=[MOBILE, "98765"])

        assert response.status_code == 400
        assert error_codes(response) == {"mobile_numbers[1]": ["E00001"]}
        assert not Case.objects.exists()

    def test_a_party_in_person_affidavit_is_kept(self, client, draft):
        response = add(
            client,
            draft,
            person=PERSON,
            is_party_in_person=True,
            party_in_person_affidavit="<p>I request to appear in person.</p>",
        )

        assert response.status_code == 201
        assert response.json()["party_in_person_affidavit"] == (
            "<p>I request to appear in person.</p>"
        )

    def test_an_empty_party_in_person_affidavit_is_400(self, client, draft):
        response = add(
            client,
            draft,
            person=PERSON,
            is_party_in_person=True,
            party_in_person_affidavit="<p><br></p>",
        )

        assert error_codes(response) == {"party_in_person_affidavit": ["E00004"]}

    def test_gender_outside_the_list_is_400(self, client, draft):
        response = add(client, draft, person={**PERSON, "gender": "PREFER_NOT_TO_SAY"})

        assert error_codes(response) == {"person.gender": ["E00005"]}

    def test_invalid_pincode_is_400_and_creates_nothing(self, client, draft):
        response = add(
            client, draft, person=PERSON, addresses=[{**ADDRESS_DEFAULTS, "pincode": "012345"}]
        )

        assert response.status_code == 400
        assert error_codes(response) == {"addresses[0].pincode": ["E00001"]}
        assert not Case.objects.exists()
        assert not Person.objects.exists()


class TestInstitutions:
    NO_IDENTIFIER = {k: v for k, v in INSTITUTION.items() if k != "pan"}

    def test_the_filer_may_declare_they_give_no_pan_or_cin(self, client, draft):
        response = add(
            client, draft, institution={**self.NO_IDENTIFIER, "pan_cin_skip_declared": True}
        )

        assert response.status_code == 201, response.json()
        institution = Institution.objects.get(pk=response.json()["institution_id"])
        assert (institution.pan, institution.cin, institution.pan_cin_skip_declared) == (
            None,
            None,
            True,
        )

    def test_a_pan_a_cin_or_the_declaration_is_required(self, client, draft):
        response = add(client, draft, institution=self.NO_IDENTIFIER)

        assert response.status_code == 400
        assert error_codes(response) == {"institution.pan": ["E00002"]}
        assert not Institution.objects.exists()

    def test_an_accused_institution_needs_no_pan_cin_or_declaration(self, client, draft):
        """The accused's form asks for neither (PRD LIT-18a is the complainant's)."""
        add_complainant(client, draft)

        response = add(client, draft, role="accused", institution=self.NO_IDENTIFIER)

        assert response.status_code == 201, response.json()
        institution = Institution.objects.get(pk=response.json()["institution_id"])
        assert (institution.pan, institution.cin, institution.pan_cin_skip_declared) == (
            None,
            None,
            False,
        )

    def test_the_declaration_with_a_pan_is_refused_even_when_the_pan_exists(self, client, draft):
        """A match is reused without being saved, so the rule is checked before matching."""
        make_institution(pan="AAACA1234A")

        response = add(client, draft, institution={**INSTITUTION, "pan_cin_skip_declared": True})

        assert response.status_code == 400
        assert error_codes(response) == {"institution.pan_cin_skip_declared": ["E00001"]}

    def test_an_institution_alone(self, client, draft):
        response = add(
            client, draft, institution={**INSTITUTION, "email_addresses": ["legal@abc.example"]}
        )

        body = response.json()
        assert response.status_code == 201
        assert body["person_id"] is None
        assert body["name_at_filing"] == "ABC Pvt Ltd"
        assert body["entity_name_at_filing"] == "ABC Pvt Ltd"
        assert body["mobile_numbers"] == []
        assert body["addresses"] == []
        assert body["institution"]["mobile_numbers"] == ["080-22334455"]
        assert body["institution"]["email_addresses"] == ["legal@abc.example"]
        assert len(body["institution"]["addresses"]) == 1

    def test_a_person_acting_for_an_institution(self, client, draft):
        response = add(
            client,
            draft,
            institution={**INSTITUTION, "email_addresses": ["legal@abc.example"]},
            person=PERSON,
            email_addresses=["rajesh@example.com"],
            designation="Director",
        )

        body = response.json()
        assert response.status_code == 201
        assert body["designation_at_filing"] == "Director"
        assert body["name_at_filing"] == "Rajesh Kumar"
        assert body["email_addresses"] == ["rajesh@example.com"]
        assert body["institution"]["email_addresses"] == ["legal@abc.example"]
        contacts = CaseContact.objects.filter(case_participant_id=body["case_participant_id"])
        assert {str(contact.institution_id) for contact in contacts} == {body["institution_id"]}
        assert body["entity_name_at_filing"] == "ABC Pvt Ltd"
        person = Person.objects.get(pk=body["person_id"])
        assert str(person.institution_id) == body["institution_id"]
        assert person.designation == "Director"

    def test_designation_is_required_with_a_person(self, client, draft):
        response = add(client, draft, role="accused", institution=INSTITUTION, person=PERSON)

        assert response.status_code == 400
        assert error_codes(response) == {"designation": ["E00002"]}

    def test_designation_is_optional_for_a_complainant(self, client, draft):
        response = add(client, draft, institution=INSTITUTION, person=PERSON)

        assert response.status_code == 201
        assert response.json()["designation_at_filing"] is None

    def test_self_for_an_institution_leaves_the_filers_person_unchanged(self, client, user, draft):
        response = add(client, draft, institution=INSTITUTION, self=True, designation="Director")

        assert response.status_code == 201
        person = Person.objects.get(user=user)
        assert person.institution is None
        assert person.designation is None
        assert response.json()["designation_at_filing"] == "Director"

    def test_an_existing_pan_is_reused_without_changing_it(self, client, draft):
        """The case keeps the name this filer typed; ``institution`` shows the shared row."""
        existing = make_institution(pan="AAACA1234A", entity_name="Stored Name Ltd")

        response = add(
            client, draft, institution={**INSTITUTION, "pan": "aaaca 1234 a", "cin": None}
        )

        body = response.json()
        assert body["institution_id"] == str(existing.pk)
        assert body["name_at_filing"] == "ABC Pvt Ltd"
        assert body["entity_name_at_filing"] == "ABC Pvt Ltd"
        assert body["institution"]["entity_name"] == "Stored Name Ltd"
        existing.refresh_from_db()
        assert existing.entity_name == "Stored Name Ltd"
        assert Institution.objects.count() == 1

    def test_pan_and_cin_of_different_institutions_is_400(self, client, draft):
        make_institution(pan="AAACA1234A")
        make_institution(cin="U72200KA2010PTC052651", entity_name="Other Ltd")

        response = add(client, draft, institution={**INSTITUTION, "cin": "U72200KA2010PTC052651"})

        assert response.status_code == 400
        assert error_codes(response) == {"institution.cin": ["E00001"]}
        assert not Case.objects.exists()

    def test_invalid_pan_is_400(self, client, draft):
        response = add(client, draft, institution={**INSTITUTION, "pan": "NOTAPAN"})

        assert response.status_code == 400
        assert error_codes(response) == {"institution.pan": ["E00001"]}

    def test_an_institution_cannot_be_both_complainant_and_accused(self, client, draft):
        add(client, draft, institution=INSTITUTION)

        response = add(client, draft, role="accused", institution=INSTITUTION)

        assert response.status_code == 400
        assert error_codes(response) == {"institution": ["E07014"]}
        assert listing(client, draft, role="ACCUSED")["count"] == 0

    def test_an_institution_cannot_hold_a_role_twice(self, client, draft):
        add(client, draft, institution=INSTITUTION, person=PERSON, designation="Director")

        response = add(
            client,
            draft,
            institution=INSTITUTION,
            person={"name": "Second Director"},
            designation="Director",
        )

        assert response.status_code == 400
        assert error_codes(response) == {"institution": ["E07013"]}
        # The second director's person row was rolled back with the participant.
        assert not Person.objects.filter(name="Second Director").exists()

    def test_a_removed_institution_can_be_added_in_another_role(self, client, draft):
        first = add(client, draft, institution=INSTITUTION).json()
        remove(client, first["case_participant_id"])

        response = add(client, draft, role="accused", institution=INSTITUTION)

        assert response.status_code == 201
        assert response.json()["institution_id"] == first["institution_id"]

    def test_an_institution_cannot_be_accused_twice(self, client, draft):
        add(client, draft, role="accused", institution=INSTITUTION)

        response = add(client, draft, role="accused", institution=INSTITUTION)

        assert error_codes(response) == {"institution": ["E07013"]}

    def test_directors_can_be_accused_alongside_their_company(self, client, draft):
        company = add(client, draft, role="accused", institution=INSTITUTION)
        director = add(client, draft, role="accused", person={**PERSON, "name": "Director"})

        assert (company.status_code, director.status_code) == (201, 201)


class TestAddAccused:
    def test_accused_have_their_own_ordinals(self, client, draft):
        add_complainant(client, draft)

        response = add(client, draft, role="accused", person={**PERSON, "name": "John Doe"})

        assert response.status_code == 201
        assert response.json()["role"] == "ACCUSED"
        assert response.json()["ordinal"] == 1

    def test_self_is_not_accepted(self, client, draft):
        response = add(client, draft, role="accused", self=True)

        assert response.status_code == 400
        assert error_codes(response) == {"self": ["E07019"]}


class TestFilingSnapshot:
    """The institution as its row stores it, and the disability answer as the case records it."""

    def test_a_complainant_institution_is_shown_in_full(self, client, draft):
        body = add(
            client, draft, institution={**INSTITUTION, "email_addresses": ["a@abc.in"]}
        ).json()

        institution = body["institution"]
        assert institution.pop("addresses")[0]["pincode"] == ADDRESS_DEFAULTS["pincode"]
        assert institution == {
            "entity_name": "ABC Pvt Ltd",
            "entity_type": "PRIVATE_LIMITED_COMPANY",
            "pan": "AAACA1234A",
            "cin": None,
            "pan_cin_skip_declared": False,
            "mobile_numbers": ["080-22334455"],
            "email_addresses": ["a@abc.in"],
        }

    def test_an_accused_institution_has_no_pan_or_cin(self, client, draft):
        add_complainant(client, draft)

        body = add(client, draft, role="accused", institution=INSTITUTION).json()

        institution = body["institution"]
        assert institution["entity_type"] == "PRIVATE_LIMITED_COMPANY"
        assert institution["mobile_numbers"] == ["080-22334455"]
        assert institution["pan"] is None
        assert institution["cin"] is None
        assert institution["pan_cin_skip_declared"] is None

    def test_a_representative_keeps_the_institutions_own_contact(self, client, draft):
        body = add(
            client, draft, institution=INSTITUTION, person=PERSON, designation="Director"
        ).json()

        assert body["mobile_numbers"] == [MOBILE]
        assert body["institution"]["mobile_numbers"] == ["080-22334455"]

    def test_an_individual_has_no_institution(self, client, draft):
        assert add_complainant(client, draft)["institution"] is None

    @pytest.mark.parametrize("sent", [None, False, True])
    def test_disability_is_the_persons_answer(self, client, draft, sent):
        body = add_complainant(
            client, draft, **({} if sent is None else {"disability_status": sent})
        )

        assert body["disability_status"] is sent
        assert Person.objects.get(pk=body["person_id"]).disability_status is sent

    def test_disability_can_be_changed_and_cleared_on_the_person(self, client, draft):
        body = add_complainant(client, draft, disability_status=True)

        cleared = patch(client, body["case_participant_id"], {"disability_status": None})

        assert cleared.status_code == 200, cleared.json()
        assert cleared.json()["disability_status"] is None
        assert Person.objects.get(pk=body["person_id"]).disability_status is None

    def test_an_institution_alone_has_no_disability_answer(self, client, draft):
        body = add(client, draft, institution=INSTITUTION).json()

        response = patch(client, body["case_participant_id"], {"disability_status": True})

        assert response.status_code == 400
        assert error_codes(response) == {"disability_status": ["E07023"]}
        assert body["disability_status"] is None

    def test_a_person_another_user_claimed_keeps_their_answer(self, client, other_user, draft):
        body = add_complainant(client, draft, disability_status=True)
        Person.objects.filter(pk=body["person_id"]).update(user=other_user)

        response = patch(client, body["case_participant_id"], {"disability_status": False})

        assert response.status_code == 400
        assert error_codes(response) == {"disability_status": ["E07023"]}

    def test_relinking_shows_the_new_institution(self, client, draft):
        body = add(client, draft, institution=INSTITUTION, person=PERSON, designation="Director")
        corrected = {**INSTITUTION, "pan": "AAACB5678B", "entity_type": "LLP"}

        response = patch(client, body.json()["case_participant_id"], {"institution": corrected})

        assert response.status_code == 200, response.json()
        assert response.json()["institution"]["entity_type"] == "LLP"
        assert response.json()["institution"]["pan"] == "AAACB5678B"


class TestContacts:
    """Mobile numbers, emails and addresses are ``CaseContact`` rows (spec 0020 §4.6)."""

    def test_lists_keep_their_order_and_the_first_is_the_primary(self, client, draft):
        second = {**ADDRESS_DEFAULTS, "line1": "7 Temple Street"}

        body = add(
            client,
            draft,
            person=PERSON,
            mobile_numbers=["+919800000002", MOBILE],
            addresses=[second, ADDRESS_DEFAULTS],
        ).json()

        assert body["mobile_numbers"] == ["+919800000002", MOBILE]
        assert [a["line1"] for a in body["addresses"]] == ["7 Temple Street", "12 MG Road"]
        person = Person.objects.get(pk=body["person_id"])
        assert person.phone_number == "+919800000002"
        assert person.correspondence_address.line1 == "7 Temple Street"

    def test_an_institutions_contacts_belong_to_each_case(self, client, user, draft):
        """One institution is shared between filings; its contacts are not."""
        add(client, draft, institution=INSTITUTION)
        other_draft = services.start_draft(user, CaseType.CHEQUE_BOUNCE)["draft_session_id"]

        other = add(
            client, other_draft, institution={**INSTITUTION, "mobile_numbers": ["080-99998888"]}
        ).json()
        first = listing(client, draft)["results"][0]

        assert Institution.objects.count() == 1
        assert first["institution"]["mobile_numbers"] == ["080-22334455"]
        assert other["institution"]["mobile_numbers"] == ["080-99998888"]

    def test_an_institution_alone_needs_its_own_address(self, client, draft):
        response = add(
            client,
            draft,
            institution={**INSTITUTION, "addresses": []},
            addresses=[ADDRESS_DEFAULTS],
        )

        assert response.status_code == 400
        assert error_codes(response) == {
            "institution.addresses": ["E00002"],
            "addresses": ["E07023"],
        }

    def test_an_accused_institutions_address_needs_a_police_station(self, client, draft):
        add_complainant(client, draft)
        institution = {**INSTITUTION, "addresses": [{**ADDRESS_DEFAULTS, "police_station": ""}]}

        response = add(client, draft, role="accused", institution=institution)

        assert error_codes(response) == {"institution.addresses[0].police_station": ["E00002"]}

    def test_institution_contacts_change_without_re_linking(self, client, draft):
        """An accused company with no PAN or CIN keeps its row: nothing to match a new one by."""
        add_complainant(client, draft)
        no_identifier = {k: v for k, v in INSTITUTION.items() if k != "pan"}
        accused = add(client, draft, role="accused", institution=no_identifier).json()
        institutions = Institution.objects.count()

        response = patch(
            client,
            accused["case_participant_id"],
            {"institution_contacts": {"mobile_numbers": ["080-1111", "080-2222"]}},
        )

        assert response.status_code == 200, response.json()
        assert response.json()["institution_id"] == accused["institution_id"]
        assert response.json()["institution"]["mobile_numbers"] == ["080-1111", "080-2222"]
        assert response.json()["institution"]["addresses"] == accused["institution"]["addresses"]
        assert Institution.objects.count() == institutions

    def test_institution_contacts_follow_the_rules(self, client, draft):
        add_complainant(client, draft)
        accused = add(client, draft, role="accused", institution=INSTITUTION).json()

        response = patch(
            client,
            accused["case_participant_id"],
            {"institution_contacts": {"addresses": [{**ADDRESS_DEFAULTS, "police_station": ""}]}},
        )

        assert error_codes(response) == {
            "institution_contacts.addresses[0].police_station": ["E00002"]
        }

    def test_institution_contacts_are_only_for_an_institution(self, client, draft):
        body = add_complainant(client, draft)

        response = patch(
            client, body["case_participant_id"], {"institution_contacts": {"mobile_numbers": []}}
        )

        assert error_codes(response) == {"institution_contacts": ["E07023"]}

    def test_a_list_cannot_be_sent_in_both_places(self, client, draft):
        body = add(client, draft, institution=INSTITUTION).json()

        response = patch(
            client,
            body["case_participant_id"],
            {
                "institution": INSTITUTION,
                "institution_contacts": {"mobile_numbers": ["080-1111"]},
            },
        )

        assert error_codes(response) == {"institution_contacts": ["E00001"]}

    def test_the_database_requires_an_owner(self, client, draft):
        body = add_complainant(client, draft)

        with pytest.raises(IntegrityError), transaction.atomic():
            CaseContact.objects.filter(case_participant_id=body["case_participant_id"]).update(
                case_participant=None, institution=None
            )

    def test_the_database_keeps_values_and_addresses_apart(self, client, draft):
        body = add_complainant(client, draft)

        with pytest.raises(IntegrityError), transaction.atomic():
            CaseContact.objects.filter(
                case_participant_id=body["case_participant_id"], contact_type="ADDRESS"
            ).update(value="12 MG Road")

    def test_the_database_refuses_the_same_value_twice_for_one_owner(self, client, draft):
        body = add_complainant(client, draft)
        contact = CaseContact.objects.get(
            case_participant_id=body["case_participant_id"], contact_type="MOBILE_NUMBER"
        )

        with pytest.raises(IntegrityError), transaction.atomic():
            CaseContact.objects.create(
                case_id=contact.case_id,
                case_participant_id=contact.case_participant_id,
                contact_type="MOBILE_NUMBER",
                value=MOBILE,
                ordinal=2,
            )


class TestNameRequired:
    """Only a witness may be named by designation alone; every other party needs a name."""

    NAMELESS = {key: value for key, value in PERSON.items() if key != "name"}

    @pytest.mark.parametrize("role", ["complainant", "accused"])
    @pytest.mark.parametrize("name", [None, "", "   "])
    def test_a_party_needs_a_name(self, client, draft, role, name):
        person = self.NAMELESS if name is None else {**self.NAMELESS, "name": name}

        response = add(client, draft, role=role, person=person)

        assert response.status_code == 400
        assert error_codes(response) == {"person.name": ["E00002"]}

    def test_a_poa_holder_needs_a_name(self, client, draft):
        complainant = add_complainant(client, draft)

        response = add_poa_holder(
            client, draft, [complainant["case_participant_id"]], person=self.NAMELESS
        )

        assert response.status_code == 400
        assert error_codes(response) == {"person.name": ["E00002"]}

    def test_a_party_name_cannot_be_cleared(self, client, draft):
        body = add_complainant(client, draft)

        response = patch(client, body["case_participant_id"], {"name_at_filing": None})

        assert response.status_code == 400
        assert error_codes(response) == {"name_at_filing": ["E00002"]}


class TestListing:
    def test_lists_active_participants_by_role(self, client, draft):
        add_complainant(client, draft)
        add(client, draft, role="accused", person={**PERSON, "name": "John Doe"})

        everyone = listing(client, draft)
        accused = listing(client, draft, role="ACCUSED")

        assert everyone["count"] == 2
        assert [p["role"] for p in accused["results"]] == ["ACCUSED"]

    def test_unknown_role_is_400(self, client, draft):
        add_complainant(client, draft)

        response = client.get(reverse("case-participant-list", args=[draft]), {"role": "JUDGE"})

        assert response.status_code == 400


class TestUpdate:
    def test_changes_only_the_snapshot(self, client, draft):
        body = add_complainant(client, draft)

        response = patch(client, body["case_participant_id"], {"name_at_filing": "Rajesh S. Kumar"})

        assert response.status_code == 200
        assert response.json()["name_at_filing"] == "Rajesh S. Kumar"
        assert Person.objects.get(pk=body["person_id"]).name == "Rajesh Kumar"

    def test_party_in_person_affidavit_can_be_changed_and_cleared(self, client, draft):
        body = add_complainant(client, draft)
        participant_id = body["case_participant_id"]

        changed = patch(client, participant_id, {"party_in_person_affidavit": "<p>Text.</p>"})
        cleared = patch(client, participant_id, {"party_in_person_affidavit": None})

        assert changed.json()["party_in_person_affidavit"] == "<p>Text.</p>"
        assert cleared.json()["party_in_person_affidavit"] is None
        empty = patch(client, participant_id, {"party_in_person_affidavit": "<p>&nbsp;</p>"})
        assert error_codes(empty) == {"party_in_person_affidavit": ["E00004"]}

    def test_only_a_complainant_has_a_party_in_person_affidavit(self, client, draft):
        accused = add(
            client, draft, role="accused", person=PERSON, party_in_person_affidavit="<p>T</p>"
        )
        added = add(client, draft, role="accused", person=PERSON).json()
        changed = patch(
            client, added["case_participant_id"], {"party_in_person_affidavit": "<p>T</p>"}
        )

        assert error_codes(accused) == {"party_in_person_affidavit": ["E07023"]}
        assert error_codes(changed) == {"party_in_person_affidavit": ["E07023"]}

    def test_a_contact_list_is_replaced_on_the_case_only(self, client, draft):
        body = add(client, draft, person=PERSON, email_addresses=["rajesh@example.com"]).json()

        response = patch(
            client,
            body["case_participant_id"],
            {"email_addresses": ["rajesh.k@example.com", "rk@example.com"]},
        )

        assert response.status_code == 200, response.json()
        assert response.json()["email_addresses"] == ["rajesh.k@example.com", "rk@example.com"]
        assert response.json()["mobile_numbers"] == [MOBILE]
        assert Person.objects.get(pk=body["person_id"]).email_address == "rajesh@example.com"
        replaced = CaseContact.objects.get(value="rajesh@example.com")
        assert replaced.is_active is False

    def test_a_list_sent_unchanged_keeps_its_rows(self, client, draft):
        body = add_complainant(client, draft)
        before = set(CaseContact.objects.values_list("pk", flat=True))

        patch(client, body["case_participant_id"], {"mobile_numbers": [MOBILE]})

        assert set(CaseContact.objects.values_list("pk", flat=True)) == before

    @pytest.mark.parametrize(
        ("change", "field"),
        [
            ({"mobile_numbers": [MOBILE, MOBILE]}, "mobile_numbers[1]"),
            ({"email_addresses": ["a@x.in", "A@X.in"]}, "email_addresses[1]"),
            ({"addresses": [ADDRESS_DEFAULTS, ADDRESS_DEFAULTS]}, "addresses[1]"),
        ],
    )
    def test_a_contact_given_twice_is_400(self, client, draft, change, field):
        body = add_complainant(client, draft)

        response = patch(client, body["case_participant_id"], change)

        assert error_codes(response) == {field: ["E07033"]}

    def test_an_individual_cannot_be_left_without_an_address(self, client, draft):
        body = add_complainant(client, draft)

        response = patch(client, body["case_participant_id"], {"addresses": []})

        assert error_codes(response) == {"addresses": ["E00002"]}

    def test_an_institution_alone_has_no_contacts_of_its_own(self, client, draft):
        body = add(client, draft, institution=INSTITUTION).json()

        response = patch(client, body["case_participant_id"], {"mobile_numbers": [MOBILE]})

        assert error_codes(response) == {"mobile_numbers": ["E07023"]}

    def test_an_institutions_contacts_are_replaced_under_institution(self, client, draft):
        body = add(client, draft, institution=INSTITUTION).json()

        response = patch(
            client,
            body["case_participant_id"],
            {"institution": {**INSTITUTION, "mobile_numbers": ["080-1111", "080-2222"]}},
        )

        assert response.status_code == 200, response.json()
        assert response.json()["institution"]["mobile_numbers"] == ["080-1111", "080-2222"]
        assert len(response.json()["institution"]["addresses"]) == 1

    def test_an_individual_has_no_institution_details(self, client, draft):
        body = add_complainant(client, draft)

        assert body["entity_name_at_filing"] is None

    def test_institution_details_are_changed_on_the_snapshot_only(self, client, draft):
        body = add(
            client, draft, institution=INSTITUTION, person=PERSON, designation="Director"
        ).json()

        response = patch(
            client,
            body["case_participant_id"],
            {"entity_name_at_filing": "ABC Private Ltd"},
        )

        assert response.status_code == 200
        changed = response.json()
        assert changed["entity_name_at_filing"] == "ABC Private Ltd"
        assert changed["name_at_filing"] == "Rajesh Kumar"
        institution = Institution.objects.get(pk=body["institution_id"])
        assert institution.entity_name == "ABC Pvt Ltd"

    def test_an_institution_alone_refuses_two_different_names(self, client, draft):
        body = add(client, draft, institution=INSTITUTION).json()

        differ = patch(
            client,
            body["case_participant_id"],
            {"name_at_filing": "ABC Private Ltd", "entity_name_at_filing": "ABC Ltd"},
        )
        same = patch(
            client,
            body["case_participant_id"],
            {"name_at_filing": "ABC Private Ltd", "entity_name_at_filing": "ABC Private Ltd"},
        )

        assert error_codes(differ) == {"entity_name_at_filing": ["E00001"]}
        assert same.status_code == 200

    @pytest.mark.parametrize("field", ["name_at_filing", "entity_name_at_filing"])
    def test_an_institution_alone_keeps_both_names_the_same(self, client, draft, field):
        body = add(client, draft, institution=INSTITUTION).json()

        response = patch(client, body["case_participant_id"], {field: "ABC Private Ltd"})

        changed = response.json()
        assert changed["name_at_filing"] == "ABC Private Ltd"
        assert changed["entity_name_at_filing"] == "ABC Private Ltd"

    @pytest.mark.parametrize(
        ("change", "field", "code"),
        [
            ({"entity_name_at_filing": "ABC Pvt Ltd"}, "entity_name_at_filing", "E07023"),
            ({"email_addresses": ["not-an-email"]}, "email_addresses[0]", "E00001"),
        ],
    )
    def test_invalid_contact_and_institution_changes_are_400(
        self, client, draft, change, field, code
    ):
        body = add_complainant(client, draft)

        response = patch(client, body["case_participant_id"], change)

        assert error_codes(response) == {field: [code]}

    def test_a_new_address_is_a_new_row(self, client, draft):
        body = add_complainant(client, draft)

        response = patch(
            client,
            body["case_participant_id"],
            {"addresses": [{**ADDRESS_DEFAULTS, "line1": "456 New Street"}]},
        )

        assert response.json()["addresses"][0]["line1"] == "456 New Street"
        person = Person.objects.get(pk=body["person_id"])
        assert str(person.correspondence_address_id) == body["addresses"][0]["address_id"]

    @pytest.mark.parametrize(
        "change",
        [
            {"role": "ACCUSED"},
            {"person": {"name": "Someone"}},
            {},
            {"mobile_numbers": ["12345"]},
            {"designation_at_filing": "Director"},
            {"gender_at_filing": "PREFER_NOT_TO_SAY"},
        ],
    )
    def test_invalid_changes_are_400(self, client, draft, change):
        body = add_complainant(client, draft)

        assert patch(client, body["case_participant_id"], change).status_code == 400

    def test_party_in_person_is_refused_while_an_advocate_acts(self, client, make_user, draft):
        body = add_complainant(client, draft)
        advocate = AdvocateProfile.objects.create(
            user=make_user(),
            bar_registration_id="KA/1/2020",
            approval_status=ApprovalStatus.ACCEPTED,
        )
        Representation.objects.create(
            case_id=draft, advocate=advocate, case_participant_id=body["case_participant_id"]
        )

        response = patch(client, body["case_participant_id"], {"is_party_in_person": True})

        assert response.status_code == 400
        assert error_codes(response) == {"is_party_in_person": ["E07022"]}


class TestInstitutionRelink:
    CORRECTED = {**INSTITUTION, "pan": "AAACB5678B", "entity_name": "ABC Private Ltd"}

    def test_an_accused_institution_relinks_without_a_pan_or_cin(self, client, draft):
        add_complainant(client, draft)
        accused = add(client, draft, role="accused", institution=INSTITUTION).json()
        renamed = {k: v for k, v in INSTITUTION.items() if k != "pan"}

        response = patch(
            client,
            accused["case_participant_id"],
            {"institution": {**renamed, "entity_name": "XYZ Traders"}},
        )

        assert response.status_code == 200, response.json()
        assert response.json()["institution_id"] != accused["institution_id"]

    def test_a_complainant_institution_still_needs_one_when_relinked(self, client, draft):
        body = add(client, draft, institution=INSTITUTION).json()
        renamed = {k: v for k, v in INSTITUTION.items() if k != "pan"}

        response = patch(client, body["case_participant_id"], {"institution": renamed})

        assert response.status_code == 400
        assert error_codes(response) == {"institution.pan": ["E00002"]}

    def test_a_corrected_pan_links_a_new_institution_and_keeps_the_participant(
        self, client, make_user, draft
    ):
        body = add(client, draft, institution=INSTITUTION).json()
        advocate = AdvocateProfile.objects.create(
            user=make_user(),
            bar_registration_id="KA/3/2020",
            approval_status=ApprovalStatus.ACCEPTED,
        )
        representation = Representation.objects.create(
            case_id=draft, advocate=advocate, case_participant_id=body["case_participant_id"]
        )

        response = patch(client, body["case_participant_id"], {"institution": self.CORRECTED})

        relinked = response.json()
        assert response.status_code == 200
        assert relinked["case_participant_id"] == body["case_participant_id"]
        assert relinked["ordinal"] == body["ordinal"]
        assert relinked["institution_id"] != body["institution_id"]
        assert relinked["name_at_filing"] == "ABC Private Ltd"
        assert Institution.objects.get(pk=relinked["institution_id"]).pan == "AAACB5678B"
        # The institution's contacts on this case follow it to the new row.
        assert relinked["institution"]["addresses"] == body["institution"]["addresses"]
        assert relinked["institution"]["mobile_numbers"] == ["080-22334455"]
        old = Institution.objects.get(pk=body["institution_id"])
        assert (old.pan, old.entity_name) == ("AAACA1234A", "ABC Pvt Ltd")
        representation.refresh_from_db()
        assert representation.is_active is True

    def test_an_existing_pan_is_linked_without_changing_it(self, client, draft):
        existing = make_institution(pan="AAACB5678B", entity_name="Stored Name Ltd")
        body = add(client, draft, institution=INSTITUTION).json()

        response = patch(
            client,
            body["case_participant_id"],
            {"institution": {**self.CORRECTED, "pan": "aaacb 5678 b"}},
        )

        assert response.json()["institution_id"] == str(existing.pk)
        existing.refresh_from_db()
        assert existing.entity_name == "Stored Name Ltd"

    def test_a_name_sent_with_it_wins(self, client, draft):
        body = add(client, draft, institution=INSTITUTION).json()

        response = patch(
            client,
            body["case_participant_id"],
            {"institution": self.CORRECTED, "name_at_filing": "ABC (India) Pvt Ltd"},
        )

        assert response.json()["name_at_filing"] == "ABC (India) Pvt Ltd"

    def test_a_person_acting_for_it_keeps_their_snapshot_and_row(self, client, draft):
        body = add(
            client, draft, institution=INSTITUTION, person=PERSON, designation="Director"
        ).json()

        response = patch(client, body["case_participant_id"], {"institution": self.CORRECTED})

        relinked = response.json()
        assert relinked["institution_id"] != body["institution_id"]
        assert relinked["entity_name_at_filing"] == "ABC Private Ltd"
        assert relinked["name_at_filing"] == "Rajesh Kumar"
        assert relinked["designation_at_filing"] == "Director"
        person = Person.objects.get(pk=body["person_id"])
        assert str(person.institution_id) == body["institution_id"]

    def test_an_individual_cannot_become_an_institution(self, client, draft):
        body = add_complainant(client, draft)

        response = patch(client, body["case_participant_id"], {"institution": INSTITUTION})

        assert response.status_code == 400
        assert error_codes(response) == {"institution": ["E07023"]}
        assert not Institution.objects.exists()

    def test_the_other_sides_institution_is_refused_and_nothing_changes(self, client, draft):
        body = add(client, draft, institution=INSTITUTION).json()
        add(client, draft, role="accused", institution=self.CORRECTED)

        response = patch(client, body["case_participant_id"], {"institution": self.CORRECTED})

        assert response.status_code == 400
        assert error_codes(response) == {"institution": ["E07014"]}
        participant = CaseParticipant.objects.get(pk=body["case_participant_id"])
        assert str(participant.institution_id) == body["institution_id"]

    def test_invalid_pan_is_400(self, client, draft):
        body = add(client, draft, institution=INSTITUTION).json()

        response = patch(
            client, body["case_participant_id"], {"institution": {**INSTITUTION, "pan": "NOTAPAN"}}
        )

        assert response.status_code == 400
        assert error_codes(response) == {"institution.pan": ["E00001"]}


class TestRemove:
    def test_remove_is_soft_and_renumbers_the_role(self, client, draft):
        first, second, third = (add_complainant(client, draft, name=n) for n in "ABC")

        assert remove(client, first["case_participant_id"]).status_code == 204

        removed = CaseParticipant.objects.get(pk=first["case_participant_id"])
        assert removed.is_active is False
        assert removed.end_date is not None
        remaining = listing(client, draft)["results"]
        assert [(p["name_at_filing"], p["ordinal"]) for p in remaining] == [("B", 1), ("C", 2)]

    def test_a_new_participant_takes_the_next_ordinal_after_a_removal(self, client, draft):
        first, _ = (
            add_complainant(client, draft, name="A"),
            add_complainant(client, draft, name="B"),
        )
        remove(client, first["case_participant_id"])

        assert add_complainant(client, draft, name="C")["ordinal"] == 2

    def test_ends_representations_and_mandates(self, client, make_user, draft):
        body = add_complainant(client, draft)
        add_complainant(client, draft, name="Co-complainant")
        case = Case.objects.get(pk=draft)
        participant = CaseParticipant.objects.get(pk=body["case_participant_id"])
        advocate = AdvocateProfile.objects.create(
            user=make_user(),
            bar_registration_id="KA/2/2020",
            approval_status=ApprovalStatus.ACCEPTED,
        )
        representation = Representation.objects.create(
            case=case, advocate=advocate, case_participant=participant
        )
        holder = make_participant(case, ParticipantRole.POA_HOLDER)
        mandate = PoaMandate.objects.create(
            case=case, poa_participant=holder, represented_participant=participant
        )

        remove(client, body["case_participant_id"])

        representation.refresh_from_db()
        mandate.refresh_from_db()
        holder.refresh_from_db()
        assert (representation.is_active, representation.to_date is not None) == (False, True)
        assert (mandate.is_active, mandate.revoked_at is not None) == (False, True)
        # The holder acted for no one else, so is removed too.
        assert holder.is_active is False

    def test_a_holder_who_still_acts_for_someone_stays(self, client, draft):
        first = add_complainant(client, draft, name="A")
        second = add_complainant(client, draft, name="B")
        case = Case.objects.get(pk=draft)
        holder = make_participant(case, ParticipantRole.POA_HOLDER)
        for represented in (first, second):
            PoaMandate.objects.create(
                case=case,
                poa_participant=holder,
                represented_participant_id=represented["case_participant_id"],
            )

        remove(client, first["case_participant_id"])

        holder.refresh_from_db()
        assert holder.is_active is True
        assert holder.poa_mandates_held.active().count() == 1

    def test_a_party_can_be_removed_while_their_side_has_witnesses(self, client, draft):
        body = add_complainant(client, draft)
        add_complainant(client, draft, name="Stays")
        witness = add_witness(client, draft).json()

        response = remove(client, body["case_participant_id"])

        assert response.status_code == 204
        assert CaseParticipant.objects.get(pk=witness["case_participant_id"]).is_active is True


def add_witness(client, case_id, side="COMPLAINANT", **body):
    body.setdefault("person", {**PERSON, "name": "Meena Rao"})
    body.setdefault("addresses", [ADDRESS_DEFAULTS])
    body.setdefault("mobile_numbers", [MOBILE])
    body.setdefault("what_will_witness_prove", "Saw the cheque being signed")
    body.setdefault("side", side)
    url = reverse("case-witness-list", args=[case_id])
    return client.post(url, {k: v for k, v in body.items() if v is not None}, format="json")


class TestAddWitness:
    def test_the_participant_row_cannot_make_a_second_witness_for_a_side(self, client, draft):
        """Changing a witness's person (in the admin) is checked as adding one is."""
        first = add_witness(client, draft).json()
        second = add_witness(client, draft, person={**PERSON, "name": "Other"}).json()
        participant = CaseParticipant.objects.get(pk=second["case_participant_id"])
        participant.person_id = first["person_id"]

        with pytest.raises(ValidationError) as exc:
            participant.full_clean()

        assert exc.value.error_dict["person"][0].code == "E07032"

    def test_creates_a_participant_and_a_witness_row(self, client, draft):
        response = add_witness(client, draft, additional_details={"lang": "kn"})

        assert response.status_code == 201, response.json()
        body = response.json()
        assert body["role"] == "WITNESS"
        assert body["ordinal"] == 1
        assert body["name_at_filing"] == "Meena Rao"
        assert body["mobile_numbers"] == [MOBILE]
        assert len(body["addresses"]) == 1
        assert body["additional_details"] == {}
        assert body["witness"] == {
            "side": "COMPLAINANT",
            "what_will_witness_prove": "Saw the cheque being signed",
            "additional_details": {"lang": "kn"},
        }
        assert Witness.objects.filter(case_participant_id=body["case_participant_id"]).exists()

    def test_the_filer_can_be_a_witness_while_a_complainant(self, client, user, draft):
        add(client, draft, self=True)

        response = add_witness(client, draft, self=True, person=None)

        assert response.status_code == 201, response.json()
        assert response.json()["person_id"] == str(Person.objects.get(user=user).pk)

    def test_each_side_may_call_the_same_person_but_not_one_side_twice(self, client, draft):
        for side in ("COMPLAINANT", "ACCUSED"):
            response = add_witness(client, draft, side, self=True, person=None)
            assert response.status_code == 201, response.json()

        again = add_witness(client, draft, "COMPLAINANT", self=True, person=None)

        assert again.status_code == 400
        assert error_codes(again) == {"side": ["E07032"]}

    @pytest.mark.parametrize("statement", [None, "", "   "])
    def test_what_the_witness_will_prove_is_optional(self, client, draft, statement):
        body = {} if statement is None else {"what_will_witness_prove": statement}
        response = client.post(
            reverse("case-witness-list", args=[draft]),
            {
                "person": {**PERSON, "name": "Meena Rao"},
                "addresses": [ADDRESS_DEFAULTS],
                "side": "COMPLAINANT",
                **body,
            },
            format="json",
        )

        assert response.status_code == 201, response.json()
        assert response.json()["witness"]["what_will_witness_prove"] == ""

    def test_a_witness_may_have_a_designation(self, client, draft):
        response = add_witness(client, draft, designation="Branch manager")

        assert response.status_code == 201, response.json()
        assert response.json()["designation_at_filing"] == "Branch manager"

    def test_a_designation_is_enough_without_a_name(self, client, draft):
        response = add_witness(client, draft, person={}, designation="Branch manager")

        assert response.status_code == 201, response.json()
        assert response.json()["name_at_filing"] is None
        assert response.json()["designation_at_filing"] == "Branch manager"
        assert Person.objects.get(pk=response.json()["person_id"]).name is None

    @pytest.mark.parametrize("name", [None, "", "   "])
    def test_a_witness_needs_a_name_or_designation(self, client, draft, name):
        person = {} if name is None else {"name": name}

        response = add_witness(client, draft, person=person)

        assert response.status_code == 400
        assert error_codes(response) == {"person.name": ["E00002"]}

    def test_the_mobile_number_is_optional(self, client, draft):
        response = add_witness(client, draft, mobile_numbers=[])

        assert response.status_code == 201, response.json()
        assert response.json()["mobile_numbers"] == []

    def test_a_witness_needs_an_address(self, client, draft):
        response = client.post(
            reverse("case-witness-list", args=[draft]),
            {"person": {**PERSON, "name": "Meena Rao"}, "side": "COMPLAINANT"},
            format="json",
        )

        assert response.status_code == 400
        assert error_codes(response) == {"addresses": ["E00002"]}
        assert not CaseParticipant.objects.filter(role=ParticipantRole.WITNESS).exists()

    def test_a_witness_address_needs_a_police_station(self, client, draft):
        address = {**ADDRESS_DEFAULTS, "police_station": ""}

        response = add_witness(client, draft, addresses=[address])

        assert response.status_code == 400
        assert error_codes(response) == {"addresses[0].police_station": ["E00002"]}

    @pytest.mark.parametrize(
        "change, field, code",
        [
            ({"institution": INSTITUTION}, "institution", "E07024"),
            ({"is_party_in_person": True}, "is_party_in_person", "E07024"),
            ({"side": None}, "side", "E00002"),
            ({"side": "JUDGE"}, "side", "E00005"),
            ({"called_by_participant_id": str(uuid.uuid4())}, "called_by_participant_id", "E07024"),
            ({"party_in_person_affidavit": "<p>T</p>"}, "party_in_person_affidavit", "E07024"),
        ],
    )
    def test_invalid_bodies_are_400(self, client, draft, change, field, code):
        response = add_witness(client, draft, **change)

        assert response.status_code == 400
        assert error_codes(response) == {field: [code]}


class TestWitnessUpdate:
    @pytest.fixture
    def witness(self, client, draft):
        add_complainant(client, draft)
        return add_witness(client, draft).json()

    def test_listing_shows_the_witness_fields(self, client, draft, witness):
        rows = listing(client, draft)["results"]

        by_role = {row["role"]: row for row in rows}
        assert by_role["COMPLAINANT"]["witness"] is None
        assert by_role["WITNESS"]["witness"]["what_will_witness_prove"] == (
            "Saw the cheque being signed"
        )

    def test_changes_the_statement_side_designation_and_details(self, client, draft, witness):
        response = patch(
            client,
            witness["case_participant_id"],
            {
                "what_will_witness_prove": "Saw the notice served",
                "side": "ACCUSED",
                "additional_details": {"lang": "kn"},
                "name_at_filing": "Meena S. Rao",
                "designation_at_filing": "Clerk",
            },
        )

        assert response.status_code == 200, response.json()
        body = response.json()
        assert body["name_at_filing"] == "Meena S. Rao"
        assert body["designation_at_filing"] == "Clerk"
        assert body["additional_details"] == {}
        assert body["witness"] == {
            "side": "ACCUSED",
            "what_will_witness_prove": "Saw the notice served",
            "additional_details": {"lang": "kn"},
        }

    @pytest.mark.parametrize(
        ("change", "field", "code"),
        [
            ({"side": "JUDGE"}, "side", "E00005"),
            ({"is_party_in_person": True}, "is_party_in_person", "E07023"),
            (
                {"addresses": [{**ADDRESS_DEFAULTS, "police_station": ""}]},
                "addresses[0].police_station",
                "E00002",
            ),
        ],
    )
    def test_invalid_changes_are_400(self, client, witness, change, field, code):
        response = patch(client, witness["case_participant_id"], change)

        assert response.status_code == 400
        assert error_codes(response) == {field: [code]}

    def test_the_name_may_be_cleared_while_there_is_a_designation(self, client, witness):
        response = patch(
            client,
            witness["case_participant_id"],
            {"name_at_filing": None, "designation_at_filing": "Branch manager"},
        )

        assert response.status_code == 200, response.json()
        assert response.json()["name_at_filing"] is None

    def test_a_witness_keeps_a_name_or_designation(self, client, witness):
        response = patch(client, witness["case_participant_id"], {"name_at_filing": None})

        assert response.status_code == 400
        assert error_codes(response) == {"name_at_filing": ["E00002"]}

    def test_the_mobile_number_may_be_cleared(self, client, witness):
        response = patch(client, witness["case_participant_id"], {"mobile_numbers": []})

        assert response.status_code == 200, response.json()
        assert response.json()["mobile_numbers"] == []

    def test_witness_fields_are_refused_for_other_roles(self, client, draft, witness):
        complainant = listing(client, draft, role="COMPLAINANT")["results"][0]

        response = patch(
            client, complainant["case_participant_id"], {"what_will_witness_prove": "X"}
        )

        assert response.status_code == 400
        assert error_codes(response) == {"what_will_witness_prove": ["E07023"]}


class TestAccess:
    def test_other_users_cannot_reach_participants(self, client, client_for, other_user, draft):
        body = add_complainant(client, draft)
        outsider = client_for(other_user)

        assert add(outsider, draft, person=PERSON).status_code == 404
        assert outsider.get(reverse("case-participant-list", args=[draft])).status_code == 404
        assert (
            patch(outsider, body["case_participant_id"], {"name_at_filing": "X"}).status_code == 404
        )
        assert remove(outsider, body["case_participant_id"]).status_code == 404

    def test_unknown_case_is_404(self, client):
        assert add(client, uuid.uuid4(), person=PERSON).status_code == 404

    def test_submitted_case_cannot_change(self, client, draft):
        body = add_complainant(client, draft)
        Case.objects.filter(pk=draft).update(status=CaseStatus.PENDING_SIGN)

        assert add(client, draft, person=PERSON).status_code == 409
        assert (
            patch(client, body["case_participant_id"], {"name_at_filing": "X"}).status_code == 409
        )
        assert remove(client, body["case_participant_id"]).status_code == 409
        assert listing(client, draft)["count"] == 1


def add_poa_holder(client, case_id, represented_ids, **body):
    body.setdefault("person", {**PERSON, "name": "Suresh Patel"})
    body.setdefault("addresses", [ADDRESS_DEFAULTS])
    body.setdefault("represented_participant_ids", [str(pk) for pk in represented_ids])
    url = reverse("case-poa-holder-list", args=[case_id])
    return client.post(url, {k: v for k, v in body.items() if v is not None}, format="json")


def mandates(client, case_id):
    return client.get(reverse("case-poa-mandate-list", args=[case_id]))


def revoke(client, mandate_id):
    return client.delete(reverse("poa-mandate-detail", args=[mandate_id]))


class TestAddPoaHolder:
    def test_one_mandate_per_represented_party(self, client, draft):
        first = add_complainant(client, draft, name="A")
        second = add_complainant(client, draft, name="B")
        add_complainant(client, draft, name="C")

        response = add_poa_holder(
            client, draft, [first["case_participant_id"], second["case_participant_id"]]
        )

        assert response.status_code == 201, response.json()
        body = response.json()
        assert body["role"] == "POA_HOLDER"
        assert len(body["poa_mandate_ids"]) == 2
        holder = CaseParticipant.objects.get(pk=body["case_participant_id"])
        assert (holder.ordinal, holder.name_at_filing) == (1, "Suresh Patel")
        assert str(holder.person_id) == body["person_id"]
        assert holder.person.verification_level == VerificationLevel.ASSERTED
        rows = PoaMandate.objects.filter(pk__in=body["poa_mandate_ids"])
        assert {str(m.represented_participant_id) for m in rows} == {
            first["case_participant_id"],
            second["case_participant_id"],
        }
        assert all(m.is_active for m in rows)
        assert all(str(m.case_id) == draft and m.poa_participant == holder for m in rows)

    def test_an_accused_may_be_represented(self, client, draft):
        accused = add(client, draft, "accused", person=PERSON).json()

        response = add_poa_holder(client, draft, [accused["case_participant_id"]])

        assert response.status_code == 201, response.json()

    def test_a_complainant_filer_may_hold_for_a_co_complainant(self, client, draft):
        own = add(client, draft, self=True).json()
        co = add_complainant(client, draft, name="Co-complainant")

        response = add_poa_holder(
            client, draft, [co["case_participant_id"]], person=None, self=True
        )

        assert response.status_code == 201, response.json()
        body = response.json()
        assert body["person_id"] == own["person_id"]
        assert body["case_participant_id"] != own["case_participant_id"]

    def test_a_filer_cannot_hold_a_mandate_for_themselves(self, client, draft):
        own = add(client, draft, self=True).json()

        response = add_poa_holder(
            client, draft, [own["case_participant_id"]], person=None, self=True
        )

        assert response.status_code == 400
        assert error_codes(response) == {"represented_participant_ids": ["E07018"]}
        assert not CaseParticipant.objects.filter(role=ParticipantRole.POA_HOLDER).exists()

    @pytest.mark.parametrize(
        ("body", "field", "code"),
        [
            ({"institution": INSTITUTION}, "institution", "E07024"),
            ({"is_party_in_person": True}, "is_party_in_person", "E07024"),
            ({"represented_participant_ids": []}, "represented_participant_ids", "E00013"),
            (
                {"represented_participant_ids": ["not-a-uuid"]},
                "represented_participant_ids[0]",
                "E00001",
            ),
        ],
    )
    def test_invalid_bodies_are_400(self, client, draft, body, field, code):
        complainant = add_complainant(client, draft)

        response = add_poa_holder(client, draft, [complainant["case_participant_id"]], **body)

        assert response.status_code == 400
        assert error_codes(response) == {field: [code]}

    def test_address_is_required(self, client, draft):
        complainant = add_complainant(client, draft)
        url = reverse("case-poa-holder-list", args=[draft])
        body = {
            "person": PERSON,
            "represented_participant_ids": [complainant["case_participant_id"]],
        }

        response = client.post(url, body, format="json")

        assert response.status_code == 400
        assert error_codes(response) == {"addresses": ["E00002"]}

    def test_a_party_listed_twice_is_400(self, client, draft):
        complainant = add_complainant(client, draft)
        pk = complainant["case_participant_id"]

        response = add_poa_holder(client, draft, [pk, pk])

        assert response.status_code == 400
        assert error_codes(response) == {"represented_participant_ids": ["E07011"]}

    def test_only_a_complainant_or_accused_may_be_represented(self, client, draft):
        add_complainant(client, draft)
        witness = add_witness(client, draft).json()

        response = add_poa_holder(client, draft, [witness["case_participant_id"]])

        assert response.status_code == 400
        assert error_codes(response) == {"represented_participant_ids": ["E07016"]}

    def test_removed_or_other_case_parties_are_400(self, client, user, draft):
        removed = add_complainant(client, draft, name="Removed")
        add_complainant(client, draft, name="Stays")
        remove(client, removed["case_participant_id"])
        other_draft = services.start_draft(user, CaseType.CHEQUE_BOUNCE)["draft_session_id"]
        elsewhere = add_complainant(client, other_draft)

        for pk in (removed["case_participant_id"], elsewhere["case_participant_id"]):
            response = add_poa_holder(client, draft, [pk])

            assert response.status_code == 400
            assert error_codes(response) == {"represented_participant_ids": ["E07010"]}
        assert not CaseParticipant.objects.filter(role=ParticipantRole.POA_HOLDER).exists()

    def test_on_a_draft_with_no_parties_nothing_is_created(self, client, draft):
        response = add_poa_holder(client, draft, [uuid.uuid4()])

        assert response.status_code == 400
        assert not Case.objects.filter(pk=draft).exists()


class TestPoaMandates:
    def test_lists_active_mandates_with_the_holders_name(self, client, draft):
        first = add_complainant(client, draft, name="A")
        second = add_complainant(client, draft, name="B")
        created = add_poa_holder(
            client, draft, [first["case_participant_id"], second["case_participant_id"]]
        ).json()
        revoke(client, created["poa_mandate_ids"][1])

        response = mandates(client, draft)

        assert response.status_code == 200
        results = response.json()["results"]
        assert [m["poa_mandate_id"] for m in results] == [created["poa_mandate_ids"][0]]
        assert results[0]["poa_holder_name"] == "Suresh Patel"
        assert results[0]["poa_participant_id"] == created["case_participant_id"]
        assert results[0]["represented_participant_id"] == first["case_participant_id"]
        assert "created_by" not in results[0]

    def test_a_holder_cannot_be_a_party_in_person(self, client, draft):
        complainant = add_complainant(client, draft)
        created = add_poa_holder(client, draft, [complainant["case_participant_id"]]).json()

        response = patch(client, created["case_participant_id"], {"is_party_in_person": True})

        assert response.status_code == 400
        assert error_codes(response) == {"is_party_in_person": ["E07023"]}


class TestRevokeMandate:
    def test_revoking_one_of_two_keeps_the_holder(self, client, draft):
        first = add_complainant(client, draft, name="A")
        second = add_complainant(client, draft, name="B")
        created = add_poa_holder(
            client, draft, [first["case_participant_id"], second["case_participant_id"]]
        ).json()

        assert revoke(client, created["poa_mandate_ids"][0]).status_code == 204

        mandate = PoaMandate.objects.get(pk=created["poa_mandate_ids"][0])
        assert (mandate.is_active, mandate.revoked_at is not None) == (False, True)
        assert CaseParticipant.objects.get(pk=created["case_participant_id"]).is_active is True

    def test_revoking_the_last_removes_the_holder_and_renumbers(self, client, draft):
        complainant = add_complainant(client, draft)
        pk = complainant["case_participant_id"]
        first = add_poa_holder(client, draft, [pk]).json()
        second = add_poa_holder(client, draft, [pk], person={**PERSON, "name": "Other"}).json()

        revoke(client, first["poa_mandate_ids"][0])

        holder = CaseParticipant.objects.get(pk=first["case_participant_id"])
        assert (holder.is_active, holder.end_date is not None) == (False, True)
        assert CaseParticipant.objects.get(pk=second["case_participant_id"]).ordinal == 1

    def test_revoking_twice_is_404(self, client, draft):
        complainant = add_complainant(client, draft)
        created = add_poa_holder(client, draft, [complainant["case_participant_id"]]).json()
        mandate_id = created["poa_mandate_ids"][0]

        revoke(client, mandate_id)

        assert revoke(client, mandate_id).status_code == 404


class TestPoaAccess:
    def test_other_users_cannot_reach_mandates(self, client, client_for, other_user, draft):
        complainant = add_complainant(client, draft)
        created = add_poa_holder(client, draft, [complainant["case_participant_id"]]).json()
        mandate_id = created["poa_mandate_ids"][0]
        outsider = client_for(other_user)

        assert (
            add_poa_holder(outsider, draft, [complainant["case_participant_id"]]).status_code == 404
        )
        assert mandates(outsider, draft).status_code == 404
        assert revoke(outsider, mandate_id).status_code == 404

    def test_submitted_case_cannot_change(self, client, draft):
        complainant = add_complainant(client, draft)
        created = add_poa_holder(client, draft, [complainant["case_participant_id"]]).json()
        mandate_id = created["poa_mandate_ids"][0]
        Case.objects.filter(pk=draft).update(status=CaseStatus.PENDING_SIGN)

        assert (
            add_poa_holder(client, draft, [complainant["case_participant_id"]]).status_code == 409
        )
        assert revoke(client, mandate_id).status_code == 409
        assert mandates(client, draft).json()["count"] == 1

    def test_writes_touch_the_case(self, client, draft):
        complainant = add_complainant(client, draft)
        before = Case.objects.get(pk=draft).updated_at
        created = add_poa_holder(client, draft, [complainant["case_participant_id"]]).json()
        after_add = Case.objects.get(pk=draft).updated_at

        revoke(client, created["poa_mandate_ids"][0])

        assert before < after_add < Case.objects.get(pk=draft).updated_at


def make_advocate(make_user, status=ApprovalStatus.ACCEPTED, user=None):
    return AdvocateProfile.objects.create(
        user=user or make_user(),
        name="Adv. Sharma",
        bar_registration_id=f"KA/{uuid.uuid4().hex[:8]}/2020",
        approval_status=status,
    )


def add_advocate(client, case_id, advocate_id, client_ids):
    body = {"advocate_id": str(advocate_id), "client_participant_ids": client_ids}
    return client.post(reverse("case-advocate-list", args=[case_id]), body, format="json")


def representations(client, case_id):
    return client.get(reverse("case-representation-list", args=[case_id]))


def end(client, representation_id):
    return client.delete(reverse("representation-detail", args=[representation_id]))


class TestAddAdvocate:
    def test_one_representation_per_client(self, client, make_user, draft):
        clients = [add_complainant(client, draft, name=n)["case_participant_id"] for n in "ABC"]
        advocate = make_advocate(make_user)

        response = add_advocate(client, draft, advocate.pk, clients)

        assert response.status_code == 201, response.json()
        body = response.json()
        assert body["advocate_id"] == str(advocate.pk)
        rows = Representation.objects.filter(pk__in=body["representation_ids"])
        assert sorted(str(r.case_participant_id) for r in rows) == sorted(clients)
        assert all(r.is_active and r.to_date is None for r in rows)
        assert all(str(r.case_id) == draft and r.advocate == advocate for r in rows)

    def test_an_accused_may_be_represented(self, client, make_user, draft):
        accused = add(client, draft, "accused", person=PERSON).json()["case_participant_id"]

        response = add_advocate(client, draft, make_advocate(make_user).pk, [accused])

        assert response.status_code == 201, response.json()

    def test_a_client_may_have_several_advocates(self, client, make_user, draft):
        complainant = add_complainant(client, draft)["case_participant_id"]

        for _ in range(2):
            response = add_advocate(client, draft, make_advocate(make_user).pk, [complainant])
            assert response.status_code == 201, response.json()

    def test_the_same_advocate_twice_is_refused(self, client, make_user, draft):
        complainant = add_complainant(client, draft)["case_participant_id"]
        advocate = make_advocate(make_user)
        add_advocate(client, draft, advocate.pk, [complainant])

        response = add_advocate(client, draft, advocate.pk, [complainant])

        assert response.status_code == 400
        assert Representation.objects.filter(case_participant_id=complainant).count() == 1

    @pytest.mark.parametrize("status", [ApprovalStatus.PENDING, ApprovalStatus.REJECTED])
    def test_an_unapproved_advocate_is_refused(self, client, make_user, draft, status):
        complainant = add_complainant(client, draft)["case_participant_id"]

        response = add_advocate(client, draft, make_advocate(make_user, status).pk, [complainant])

        assert response.status_code == 400
        assert error_codes(response) == {"advocate": ["E07021"]}

    def test_an_unknown_advocate_is_refused(self, client, draft):
        complainant = add_complainant(client, draft)["case_participant_id"]

        response = add_advocate(client, draft, uuid.uuid4(), [complainant])

        assert response.status_code == 400
        assert error_codes(response) == {"advocate_id": ["E00011"]}

    def test_clients_are_required_once_each(self, client, make_user, draft):
        complainant = add_complainant(client, draft)["case_participant_id"]
        advocate = make_advocate(make_user)

        for client_ids, code in (([], "E00013"), ([complainant, complainant], "E07011")):
            response = add_advocate(client, draft, advocate.pk, client_ids)
            assert response.status_code == 400
            assert error_codes(response) == {"client_participant_ids": [code]}

    def test_a_poa_holder_cannot_be_a_client(self, client, make_user, draft):
        complainant = add_complainant(client, draft)["case_participant_id"]
        holder = add_poa_holder(client, draft, [complainant]).json()["case_participant_id"]

        response = add_advocate(client, draft, make_advocate(make_user).pk, [holder])

        assert response.status_code == 400
        assert error_codes(response) == {"client_participant_ids": ["E07016"]}

    def test_a_party_in_person_cannot_be_a_client(self, client, make_user, draft):
        complainant = add_complainant(client, draft)["case_participant_id"]
        patch(client, complainant, {"is_party_in_person": True})

        response = add_advocate(client, draft, make_advocate(make_user).pk, [complainant])

        assert response.status_code == 400
        assert error_codes(response) == {"client_participant_ids": ["E07022"]}

    def test_clients_must_be_active_and_on_the_case(self, client, make_user, user, draft):
        removed = add_complainant(client, draft, name="A")["case_participant_id"]
        add_complainant(client, draft, name="B")
        remove(client, removed)
        other_draft = services.start_draft(user, CaseType.CHEQUE_BOUNCE)["draft_session_id"]
        elsewhere = add_complainant(client, other_draft)["case_participant_id"]
        advocate = make_advocate(make_user)

        for client_id in (removed, elsewhere, str(uuid.uuid4())):
            response = add_advocate(client, draft, advocate.pk, [client_id])
            assert response.status_code == 400
            assert error_codes(response) == {"client_participant_ids": ["E07010"]}

    def test_an_advocate_cannot_represent_themselves(self, client, make_user, user, draft):
        own = add(client, draft, **{"self": True})
        assert own.status_code == 201, own.json()

        response = add_advocate(
            client,
            draft,
            make_advocate(make_user, user=user).pk,
            [own.json()["case_participant_id"]],
        )

        assert response.status_code == 400
        assert error_codes(response) == {"client_participant_ids": ["E07018"]}

    def test_an_advocate_cannot_represent_both_sides(self, client, make_user, draft):
        complainant = add_complainant(client, draft)["case_participant_id"]
        accused = add(client, draft, "accused", person=PERSON).json()["case_participant_id"]
        advocate = make_advocate(make_user)
        add_advocate(client, draft, advocate.pk, [complainant])

        response = add_advocate(client, draft, advocate.pk, [accused])

        assert response.status_code == 400
        assert error_codes(response) == {"client_participant_ids": ["E07014"]}
        assert not Representation.objects.filter(case_participant_id=accused).exists()

    def test_both_sides_in_one_request_is_refused(self, client, make_user, draft):
        complainant = add_complainant(client, draft)["case_participant_id"]
        accused = add(client, draft, "accused", person=PERSON).json()["case_participant_id"]

        response = add_advocate(client, draft, make_advocate(make_user).pk, [complainant, accused])

        assert response.status_code == 400
        assert error_codes(response) == {"client_participant_ids": ["E07014"]}
        assert not Representation.objects.filter(case_id=draft).exists()

    def test_the_other_side_after_ending_the_first(self, client, make_user, draft):
        complainant = add_complainant(client, draft)["case_participant_id"]
        accused = add(client, draft, "accused", person=PERSON).json()["case_participant_id"]
        advocate = make_advocate(make_user)
        created = add_advocate(client, draft, advocate.pk, [complainant]).json()
        end(client, created["representation_ids"][0])

        assert add_advocate(client, draft, advocate.pk, [accused]).status_code == 201

    def test_nothing_is_written_when_one_client_fails(self, client, make_user, draft):
        complainant = add_complainant(client, draft)["case_participant_id"]
        holder = add_poa_holder(client, draft, [complainant]).json()["case_participant_id"]

        response = add_advocate(client, draft, make_advocate(make_user).pk, [complainant, holder])

        assert response.status_code == 400
        assert not Representation.objects.filter(case_id=draft).exists()


class TestRepresentations:
    def test_lists_active_representations_by_client(self, client, make_user, draft):
        accused = add(client, draft, "accused", person=PERSON).json()["case_participant_id"]
        first = add_complainant(client, draft, name="A")["case_participant_id"]
        second = add_complainant(client, draft, name="B")["case_participant_id"]
        advocate = make_advocate(make_user)
        created = add_advocate(client, draft, advocate.pk, [accused]).json()
        other = add_advocate(client, draft, make_advocate(make_user).pk, [second, first]).json()
        ended = add_advocate(client, draft, make_advocate(make_user).pk, [first]).json()
        end(client, ended["representation_ids"][0])

        response = representations(client, draft)

        assert response.status_code == 200
        results = response.json()["results"]
        assert [r["client_participant_id"] for r in results] == [accused, first, second]
        expected = {*created["representation_ids"], *other["representation_ids"]}
        assert {r["representation_id"] for r in results} == expected
        assert results[0]["advocate_name"] == "Adv. Sharma"
        assert results[0]["advocate_id"] == str(advocate.pk)
        assert "created_by" not in results[0]


class TestEndRepresentation:
    def test_end_is_soft(self, client, make_user, draft):
        complainant = add_complainant(client, draft)["case_participant_id"]
        created = add_advocate(client, draft, make_advocate(make_user).pk, [complainant]).json()
        representation_id = created["representation_ids"][0]

        assert end(client, representation_id).status_code == 204

        row = Representation.objects.get(pk=representation_id)
        assert (row.is_active, row.to_date is not None) == (False, True)
        assert end(client, representation_id).status_code == 404

    def test_the_advocate_can_be_added_again_after_ending(self, client, make_user, draft):
        complainant = add_complainant(client, draft)["case_participant_id"]
        advocate = make_advocate(make_user)
        created = add_advocate(client, draft, advocate.pk, [complainant]).json()
        end(client, created["representation_ids"][0])

        assert add_advocate(client, draft, advocate.pk, [complainant]).status_code == 201
        assert Representation.objects.filter(case_participant_id=complainant).count() == 2


class TestRepresentationAccess:
    def test_other_users_cannot_reach_representations(
        self, client, client_for, make_user, other_user, draft
    ):
        complainant = add_complainant(client, draft)["case_participant_id"]
        advocate = make_advocate(make_user)
        created = add_advocate(client, draft, advocate.pk, [complainant]).json()
        outsider = client_for(other_user)

        assert add_advocate(outsider, draft, advocate.pk, [complainant]).status_code == 404
        assert representations(outsider, draft).status_code == 404
        assert end(outsider, created["representation_ids"][0]).status_code == 404

    def test_submitted_case_cannot_change(self, client, make_user, draft):
        complainant = add_complainant(client, draft)["case_participant_id"]
        created = add_advocate(client, draft, make_advocate(make_user).pk, [complainant]).json()
        Case.objects.filter(pk=draft).update(status=CaseStatus.PENDING_SIGN)

        other = make_advocate(make_user)
        assert add_advocate(client, draft, other.pk, [complainant]).status_code == 409
        assert end(client, created["representation_ids"][0]).status_code == 409
        assert representations(client, draft).json()["count"] == 1

    def test_writes_touch_the_case(self, client, make_user, draft):
        complainant = add_complainant(client, draft)["case_participant_id"]
        before = Case.objects.get(pk=draft).updated_at
        created = add_advocate(client, draft, make_advocate(make_user).pk, [complainant]).json()
        after_add = Case.objects.get(pk=draft).updated_at

        end(client, created["representation_ids"][0])

        assert before < after_add < Case.objects.get(pk=draft).updated_at


NO_POLICE_STATION = {k: v for k, v in ADDRESS_DEFAULTS.items() if k != "police_station"}


class TestContactDetailsUnknown:
    """The filer may declare they do not know the accused's phone number or email."""

    def add_accused(self, client, draft, person=None, **body):
        add_complainant(client, draft)
        body.setdefault("mobile_numbers", [])
        return add(client, draft, "accused", person=person or {"name": "Suresh"}, **body)

    def test_an_accused_with_no_contact_may_be_declared(self, client, draft):
        response = self.add_accused(client, draft, contact_details_unknown_declared=True)

        assert response.status_code == 201, response.json()
        assert response.json()["contact_details_unknown_declared"] is True

    def test_it_is_false_unless_declared(self, client, draft):
        response = self.add_accused(client, draft)

        assert response.json()["contact_details_unknown_declared"] is False

    def test_it_cannot_come_with_a_phone_number(self, client, draft):
        response = self.add_accused(
            client,
            draft,
            mobile_numbers=["+919876500000"],
            contact_details_unknown_declared=True,
        )

        assert response.status_code == 400
        assert error_codes(response) == {"contact_details_unknown_declared": ["E00001"]}

    def test_a_complainant_may_not_send_it(self, client, draft):
        response = add(client, draft, person=PERSON, contact_details_unknown_declared=True)

        assert response.status_code == 400
        assert error_codes(response) == {"contact_details_unknown_declared": ["E07023"]}

    def test_it_can_be_declared_later(self, client, draft):
        accused = self.add_accused(client, draft).json()

        response = patch(
            client, accused["case_participant_id"], {"contact_details_unknown_declared": True}
        )

        assert response.status_code == 200, response.json()
        assert response.json()["contact_details_unknown_declared"] is True

    def test_the_database_refuses_it_for_other_roles(self, client, draft):
        complainant = add_complainant(client, draft)

        with pytest.raises(IntegrityError), transaction.atomic():
            CaseParticipant.objects.filter(pk=complainant["case_participant_id"]).update(
                contact_details_unknown_declared=True
            )


class TestPermanentAddress:
    """The person's permanent address: the residential one unless a different one is sent."""

    ELSEWHERE = {**ADDRESS_DEFAULTS, "line1": "7 Temple Street", "pincode": "560004"}

    def person_of(self, body):
        return Person.objects.get(pk=body["person_id"])

    def test_the_same_address_is_the_same_row(self, client, draft):
        person = self.person_of(add_complainant(client, draft))

        assert person.permanent_address_id == person.correspondence_address_id
        assert person.permanent_address_id is not None

    def test_a_different_address_is_its_own_row(self, client, draft):
        response = add(client, draft, person=PERSON, permanent_address=self.ELSEWHERE)

        assert response.status_code == 201, response.json()
        person = self.person_of(response.json())
        assert person.permanent_address_id != person.correspondence_address_id
        assert person.permanent_address.line1 == "7 Temple Street"

    def test_a_self_filer_gets_it_on_their_own_person(self, client, user, draft):
        response = add(client, draft, self=True, permanent_address=self.ELSEWHERE)

        assert response.status_code == 201, response.json()
        assert Person.objects.get(user=user).permanent_address.line1 == "7 Temple Street"

    def test_a_self_filer_keeps_theirs_when_none_is_sent(self, client, user, draft):
        add(client, draft, self=True, permanent_address=self.ELSEWHERE)
        other_draft = services.start_draft(user, CaseType.CHEQUE_BOUNCE)["draft_session_id"]

        response = add(client, other_draft, self=True)

        assert response.status_code == 201, response.json()
        assert Person.objects.get(user=user).permanent_address.line1 == "7 Temple Street"

    def test_a_self_filer_without_one_gets_the_address(self, client, user, draft):
        response = add(client, draft, self=True)

        assert response.status_code == 201, response.json()
        person = Person.objects.get(user=user)
        assert str(person.permanent_address_id) == response.json()["addresses"][0]["address_id"]

    def test_a_poa_holder_has_one(self, client, draft):
        complainant = add_complainant(client, draft)

        response = add_poa_holder(
            client, draft, [complainant["case_participant_id"]], permanent_address=self.ELSEWHERE
        )

        assert response.status_code == 201, response.json()
        holder = CaseParticipant.objects.get(pk=response.json()["case_participant_id"])
        assert holder.person.permanent_address.line1 == "7 Temple Street"

    def test_an_invalid_one_is_reported_under_its_own_name(self, client, draft):
        response = add(
            client, draft, person=PERSON, permanent_address={**self.ELSEWHERE, "pincode": "12"}
        )

        assert response.status_code == 400
        assert error_codes(response) == {"permanent_address.pincode": ["E00001"]}

    @pytest.mark.parametrize(
        ("role", "body"),
        [
            ("accused", {"person": {**PERSON, "name": "Suresh"}}),
            ("complainant", {"institution": INSTITUTION}),
        ],
    )
    def test_only_an_individual_complainant_sends_one(self, client, draft, role, body):
        add_complainant(client, draft, name="First")

        response = add(client, draft, role, permanent_address=self.ELSEWHERE, **body)

        assert response.status_code == 400
        assert error_codes(response) == {"permanent_address": ["E07023"]}

    def test_patch_sets_it_on_the_person_and_leaves_the_snapshot(self, client, draft):
        body = add_complainant(client, draft)

        response = patch(client, body["case_participant_id"], {"permanent_address": self.ELSEWHERE})

        assert response.status_code == 200, response.json()
        assert response.json()["addresses"] == body["addresses"]
        assert self.person_of(body).permanent_address.line1 == "7 Temple Street"

    def test_patch_sets_the_filers_own(self, client, user, draft):
        body = add(client, draft, self=True).json()

        response = patch(client, body["case_participant_id"], {"permanent_address": self.ELSEWHERE})

        assert response.status_code == 200, response.json()
        assert Person.objects.get(user=user).permanent_address.line1 == "7 Temple Street"

    @pytest.mark.parametrize(
        ("role", "body"),
        [
            ("accused", {"person": {**PERSON, "name": "Suresh"}}),
            ("complainant", {"institution": INSTITUTION}),
        ],
    )
    def test_patch_refuses_it_for_other_parties(self, client, draft, role, body):
        add_complainant(client, draft, name="First")
        participant = add(client, draft, role, **body).json()

        response = patch(
            client, participant["case_participant_id"], {"permanent_address": self.ELSEWHERE}
        )

        assert response.status_code == 400
        assert error_codes(response) == {"permanent_address": ["E07023"]}

    def test_patch_refuses_a_person_another_user_has_claimed(self, client, other_user, draft):
        body = add_complainant(client, draft)
        Person.objects.filter(pk=body["person_id"]).update(user=other_user)

        response = patch(client, body["case_participant_id"], {"permanent_address": self.ELSEWHERE})

        assert response.status_code == 400
        assert error_codes(response) == {"permanent_address": ["E07023"]}
        assert self.person_of(body).permanent_address.line1 != "7 Temple Street"

    def test_patch_lets_the_filing_advocate_change_their_clients(
        self, client, user, make_user, other_user, draft
    ):
        """An advocate filing for a registered client may update that client's record."""
        body = add_complainant(client, draft)
        Person.objects.filter(pk=body["person_id"]).update(user=other_user)
        advocate = make_advocate(make_user, user=user)
        add_advocate(client, draft, advocate.pk, [body["case_participant_id"]])

        response = patch(client, body["case_participant_id"], {"permanent_address": self.ELSEWHERE})

        assert response.status_code == 200, response.json()
        assert self.person_of(body).permanent_address.line1 == "7 Temple Street"

    def test_patch_lets_a_filing_complainant_change_a_co_complainants(
        self, client, other_user, draft
    ):
        add(client, draft, self=True)
        body = add_complainant(client, draft, name="Anita Kumar")
        Person.objects.filter(pk=body["person_id"]).update(user=other_user)

        response = patch(client, body["case_participant_id"], {"permanent_address": self.ELSEWHERE})

        assert response.status_code == 200, response.json()
        assert self.person_of(body).permanent_address.line1 == "7 Temple Street"

    def test_patch_null_makes_it_the_address_again(self, client, draft):
        response = add(client, draft, person=PERSON, permanent_address=self.ELSEWHERE)
        body = response.json()

        response = patch(client, body["case_participant_id"], {"permanent_address": None})

        assert response.status_code == 200, response.json()
        assert str(self.person_of(body).permanent_address_id) == body["addresses"][0]["address_id"]

    def test_patch_null_follows_an_address_changed_in_the_same_request(self, client, draft):
        body = add_complainant(client, draft)

        response = patch(
            client,
            body["case_participant_id"],
            {"addresses": [self.ELSEWHERE], "permanent_address": None},
        )

        assert response.status_code == 200, response.json()
        assert self.person_of(body).permanent_address.line1 == "7 Temple Street"

    @pytest.mark.parametrize(
        ("role", "body"),
        [
            ("accused", {"person": {**PERSON, "name": "Suresh"}}),
            ("complainant", {"institution": INSTITUTION}),
        ],
    )
    def test_patch_null_is_ignored_for_other_parties(self, client, draft, role, body):
        add_complainant(client, draft, name="First")
        participant = add(client, draft, role, **body).json()

        response = patch(client, participant["case_participant_id"], {"permanent_address": None})

        assert response.status_code == 200, response.json()

    def test_patch_reports_an_invalid_one_under_its_own_name(self, client, draft):
        body = add_complainant(client, draft)

        response = patch(
            client,
            body["case_participant_id"],
            {"permanent_address": {**self.ELSEWHERE, "pincode": "12"}},
        )

        assert response.status_code == 400
        assert error_codes(response) == {"permanent_address.pincode": ["E00001"]}

    def test_a_witness_cannot_send_one(self, client, draft):
        response = add_witness(client, draft, permanent_address=self.ELSEWHERE)

        assert response.status_code == 400
        assert error_codes(response) == {"permanent_address": ["E07024"]}


class TestPoliceStation:
    """Only accused and witness addresses need a police station."""

    def test_a_complainant_address_may_leave_it_out(self, client, draft):
        response = add(client, draft, person=PERSON, addresses=[NO_POLICE_STATION])

        assert response.status_code == 201, response.json()
        assert response.json()["addresses"][0]["police_station"] == ""

    def test_a_poa_holder_address_may_leave_it_out(self, client, draft):
        complainant = add_complainant(client, draft)

        response = add_poa_holder(
            client, draft, [complainant["case_participant_id"]], addresses=[NO_POLICE_STATION]
        )

        assert response.status_code == 201, response.json()

    @pytest.mark.parametrize(
        "address",
        [
            NO_POLICE_STATION,
            {**ADDRESS_DEFAULTS, "police_station": " "},
            # Invisible characters only, which the address stores as blank.
            {**ADDRESS_DEFAULTS, "police_station": "\u200b\ufeff"},
        ],
    )
    def test_an_accused_address_needs_it(self, client, draft, address):
        add_complainant(client, draft)

        response = add(
            client, draft, "accused", person={**PERSON, "name": "Suresh"}, addresses=[address]
        )

        assert response.status_code == 400
        assert error_codes(response) == {"addresses[0].police_station": ["E00002"]}

    def test_changing_an_accused_address_needs_it(self, client, draft):
        add_complainant(client, draft)
        accused = add(client, draft, "accused", person={**PERSON, "name": "Suresh"}).json()

        response = patch(client, accused["case_participant_id"], {"addresses": [NO_POLICE_STATION]})

        assert response.status_code == 400
        assert error_codes(response) == {"addresses[0].police_station": ["E00002"]}

    def test_the_model_refuses_an_accused_without_one(self, client, draft):
        """The admin runs ``full_clean``, so it cannot give an accused such an address either."""
        complainant = add(client, draft, person=PERSON, addresses=[NO_POLICE_STATION]).json()
        CaseParticipant.objects.filter(pk=complainant["case_participant_id"]).update(
            role=ParticipantRole.ACCUSED, resides_within_jurisdiction=True
        )
        contact = CaseContact.objects.get(
            case_participant_id=complainant["case_participant_id"], contact_type="ADDRESS"
        )

        with pytest.raises(ValidationError) as exc:
            contact.full_clean()

        assert exc.value.error_dict["address"][0].code == "E00002"


class TestDisabilityStatus:
    def test_a_person_may_state_a_disability(self, client, draft):
        body = add_complainant(client, draft, disability_status=True)

        assert Person.objects.get(pk=body["person_id"]).disability_status is True

    def test_left_out_it_is_not_answered(self, client, draft):
        body = add_complainant(client, draft)

        assert Person.objects.get(pk=body["person_id"]).disability_status is None

    def test_a_non_boolean_is_400(self, client, draft):
        response = add(client, draft, person={**PERSON, "disability_status": "SOMETIMES"})

        assert response.status_code == 400
        assert error_codes(response) == {"person.disability_status": ["E00001"]}


class TestJsonOnly:
    """A form body reads a boolean left out as false, so these endpoints take JSON only."""

    def test_a_form_body_is_refused(self, client, draft):
        url = reverse("case-complainant-list", args=[draft])

        response = client.post(url, {"person.name": "Rajesh"}, format="multipart")

        assert response.status_code == 415

    def test_a_form_patch_is_refused_and_changes_nothing(self, client, draft):
        add_complainant(client, draft)
        accused = add(client, draft, "accused", person={**PERSON, "name": "Suresh"}).json()
        url = reverse("case-participant-detail", args=[accused["case_participant_id"]])

        response = client.patch(url, {"name_at_filing": "S. Kumar"}, format="multipart")

        assert response.status_code == 415
        participant = CaseParticipant.objects.get(pk=accused["case_participant_id"])
        assert participant.resides_within_jurisdiction is True


class TestResidesWithinJurisdiction:
    """ "Does the accused reside within the jurisdiction of this court?" Yes by default."""

    def add_accused(self, client, draft, **body):
        add_complainant(client, draft)
        return add(client, draft, "accused", person={**PERSON, "name": "Suresh"}, **body)

    def test_an_accused_defaults_to_yes(self, client, draft):
        response = self.add_accused(client, draft)

        assert response.status_code == 201, response.json()
        assert response.json()["resides_within_jurisdiction"] is True

    def test_an_accused_may_reside_outside(self, client, draft):
        response = self.add_accused(client, draft, resides_within_jurisdiction=False)

        assert response.status_code == 201, response.json()
        assert response.json()["resides_within_jurisdiction"] is False

    def test_the_answer_can_be_changed(self, client, draft):
        accused = self.add_accused(client, draft).json()

        response = patch(
            client, accused["case_participant_id"], {"resides_within_jurisdiction": False}
        )

        assert response.status_code == 200, response.json()
        assert response.json()["resides_within_jurisdiction"] is False

    def test_it_is_empty_for_other_roles(self, client, draft):
        complainant = add_complainant(client, draft)

        assert complainant["resides_within_jurisdiction"] is None

    def test_a_complainant_may_not_send_it(self, client, draft):
        response = add(client, draft, person=PERSON, resides_within_jurisdiction=True)

        assert response.status_code == 400
        assert error_codes(response) == {"resides_within_jurisdiction": ["E07023"]}

    def test_it_cannot_be_set_on_a_complainant_later(self, client, draft):
        complainant = add_complainant(client, draft)

        response = patch(
            client, complainant["case_participant_id"], {"resides_within_jurisdiction": True}
        )

        assert response.status_code == 400
        assert error_codes(response) == {"resides_within_jurisdiction": ["E07023"]}

    def test_the_database_refuses_it_for_other_roles(self, client, draft):
        complainant = add_complainant(client, draft)
        participant = CaseParticipant.objects.get(pk=complainant["case_participant_id"])
        participant.resides_within_jurisdiction = True

        with pytest.raises(IntegrityError), transaction.atomic():
            participant.save()
