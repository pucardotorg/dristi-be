"""Tests for the complainant, accused and participant endpoints (spec 0021 §4.1, §4.2)."""

import uuid

import pytest
from django.urls import reverse

from apps.cases.models import (
    Case,
    CaseParticipant,
    CaseStatus,
    ParticipantRole,
    PoaMandate,
    Representation,
    Witness,
)
from apps.parties.models import Institution, Person, VerificationLevel
from apps.parties.tests.factories import ADDRESS_DEFAULTS, make_address, make_institution
from apps.users.models import AdvocateProfile, ApprovalStatus

pytestmark = pytest.mark.django_db

PERSON = {
    "name": "Rajesh Kumar",
    "phone_number": "+919876543210",
    "date_of_birth": "1985-06-15",
    "gender": "MALE",
    "relation": "SON_OF",
    "relative_name": "Ram Kumar",
}

INSTITUTION = {
    "entity_type": "PRIVATE_LIMITED_COMPANY",
    "entity_name": "ABC Pvt Ltd",
    "pan": "AAACA1234A",
    "contact_number": "080-22334455",
}


def add(client, case_id, role="complainant", **body):
    body.setdefault("address", ADDRESS_DEFAULTS)
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
        address=make_address(),
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
        assert body["phone_number_at_filing"] == "+919876543210"
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
        assert str(person.correspondence_address_id) == body["address_id"]

    def test_the_same_name_twice_is_never_matched(self, client, draft):
        add_complainant(client, draft)
        second = add_complainant(client, draft)

        assert second["ordinal"] == 2
        assert Person.objects.filter(name="Rajesh Kumar").count() == 2

    def test_identical_addresses_share_one_row(self, client, draft):
        first = add_complainant(client, draft)
        second = add_complainant(client, draft, name="Anita Kumar")

        assert first["address_id"] == second["address_id"]

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
        assert "person" in response.json()

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
        assert "address" in response.json()
        assert not Case.objects.exists()

    def test_invalid_person_is_400_and_creates_nothing(self, client, draft):
        response = add(client, draft, person={**PERSON, "phone_number": "98765"})

        assert response.status_code == 400
        assert "phone_number" in response.json()["person"]
        assert not Case.objects.exists()

    def test_invalid_pincode_is_400_and_creates_nothing(self, client, draft):
        response = add(
            client, draft, person=PERSON, address={**ADDRESS_DEFAULTS, "pincode": "012345"}
        )

        assert response.status_code == 400
        assert "pincode" in response.json()["address"]
        assert not Case.objects.exists()
        assert not Person.objects.exists()


class TestInstitutions:
    def test_an_institution_alone(self, client, draft):
        response = add(client, draft, institution=INSTITUTION)

        body = response.json()
        assert response.status_code == 201
        assert body["person_id"] is None
        assert body["name_at_filing"] == "ABC Pvt Ltd"
        assert body["phone_number_at_filing"] == "080-22334455"
        institution = Institution.objects.get(pk=body["institution_id"])
        assert str(institution.address_id) == body["address_id"]

    def test_a_person_acting_for_an_institution(self, client, draft):
        response = add(
            client, draft, institution=INSTITUTION, person=PERSON, designation="Director"
        )

        body = response.json()
        assert response.status_code == 201
        assert body["designation_at_filing"] == "Director"
        person = Person.objects.get(pk=body["person_id"])
        assert str(person.institution_id) == body["institution_id"]
        assert person.designation == "Director"

    def test_designation_is_required_with_a_person(self, client, draft):
        response = add(client, draft, institution=INSTITUTION, person=PERSON)

        assert response.status_code == 400
        assert "designation" in response.json()

    def test_self_for_an_institution_leaves_the_filers_person_unchanged(self, client, user, draft):
        response = add(client, draft, institution=INSTITUTION, self=True, designation="Director")

        assert response.status_code == 201
        person = Person.objects.get(user=user)
        assert person.institution is None
        assert person.designation is None
        assert response.json()["designation_at_filing"] == "Director"

    def test_an_existing_pan_is_reused_without_changing_or_showing_it(self, client, draft):
        existing = make_institution(pan="AAACA1234A", entity_name="Stored Name Ltd")

        response = add(
            client, draft, institution={**INSTITUTION, "pan": "aaaca 1234 a", "cin": None}
        )

        body = response.json()
        assert body["institution_id"] == str(existing.pk)
        assert body["name_at_filing"] == "ABC Pvt Ltd"
        assert "Stored Name" not in str(body)
        existing.refresh_from_db()
        assert existing.entity_name == "Stored Name Ltd"
        assert Institution.objects.count() == 1

    def test_pan_and_cin_of_different_institutions_is_400(self, client, draft):
        make_institution(pan="AAACA1234A")
        make_institution(cin="U72200KA2010PTC052651", entity_name="Other Ltd")

        response = add(client, draft, institution={**INSTITUTION, "cin": "U72200KA2010PTC052651"})

        assert response.status_code == 400
        assert "institution" in response.json()
        assert not Case.objects.exists()

    def test_invalid_pan_is_400(self, client, draft):
        response = add(client, draft, institution={**INSTITUTION, "pan": "NOTAPAN"})

        assert response.status_code == 400
        assert "pan" in response.json()["institution"]

    def test_an_institution_cannot_be_both_complainant_and_accused(self, client, draft):
        add(client, draft, institution=INSTITUTION)

        response = add(client, draft, role="accused", institution=INSTITUTION)

        assert response.status_code == 400
        assert response.json()["institution"] == [
            "An institution cannot be both a complainant and an accused on a case."
        ]
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
        assert response.json()["institution"] == [
            "This institution is already a complainant on this case."
        ]
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

        assert response.json()["institution"] == [
            "This institution is already an accused on this case."
        ]

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
        assert "self" in response.json()


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

    def test_a_new_address_is_a_new_row(self, client, draft):
        body = add_complainant(client, draft)

        response = patch(
            client,
            body["case_participant_id"],
            {"address": {**ADDRESS_DEFAULTS, "line1": "456 New Street"}},
        )

        assert response.json()["address_id"] != body["address_id"]
        person = Person.objects.get(pk=body["person_id"])
        assert str(person.correspondence_address_id) == body["address_id"]

    @pytest.mark.parametrize(
        "change",
        [
            {"role": "ACCUSED"},
            {"person": {"name": "Someone"}},
            {},
            {"phone_number_at_filing": "12345"},
            {"designation_at_filing": "Director"},
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
        assert "is_party_in_person" in response.json()


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

    def test_refused_while_a_witness_is_called_by_them(self, client, draft):
        body = add_complainant(client, draft)
        case = Case.objects.get(pk=draft)
        witness = make_participant(case, ParticipantRole.WITNESS)
        Witness.objects.create(
            case_participant=witness,
            called_by_participant_id=body["case_participant_id"],
            what_will_witness_prove="Saw the cheque being signed",
        )

        response = remove(client, body["case_participant_id"])

        assert response.status_code == 400
        assert response.json()["non_field_errors"] == [
            "Cannot be removed while an active witness is called by them."
        ]
        assert CaseParticipant.objects.get(pk=body["case_participant_id"]).is_active is True


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
