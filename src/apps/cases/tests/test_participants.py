"""Tests for the party, participant, representation and POA mandate endpoints (spec 0021 §4)."""

import uuid

import pytest
from django.urls import reverse

from apps.cases.models import (
    Case,
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
from apps.parties.tests.factories import ADDRESS_DEFAULTS, make_address, make_institution
from apps.users.models import AdvocateProfile, ApprovalStatus

from .conftest import error_codes

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
        assert error_codes(response) == {"address": ["E00002"]}
        assert not Case.objects.exists()

    def test_invalid_person_is_400_and_creates_nothing(self, client, draft):
        response = add(client, draft, person={**PERSON, "phone_number": "98765"})

        assert response.status_code == 400
        assert error_codes(response) == {"person.phone_number": ["E00001"]}
        assert not Case.objects.exists()

    def test_invalid_pincode_is_400_and_creates_nothing(self, client, draft):
        response = add(
            client, draft, person=PERSON, address={**ADDRESS_DEFAULTS, "pincode": "012345"}
        )

        assert response.status_code == 400
        assert error_codes(response) == {"address.pincode": ["E00001"]}
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
        assert error_codes(response) == {"is_party_in_person": ["E07022"]}


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
    body.setdefault("what_will_witness_prove", "Saw the cheque being signed")
    body.setdefault("side", side)
    url = reverse("case-witness-list", args=[case_id])
    return client.post(url, {k: v for k, v in body.items() if v is not None}, format="json")


class TestAddWitness:
    def test_creates_a_participant_and_a_witness_row_without_an_address(self, client, draft):
        response = add_witness(client, draft, additional_details={"lang": "kn"})

        assert response.status_code == 201, response.json()
        body = response.json()
        assert body["role"] == "WITNESS"
        assert body["ordinal"] == 1
        assert body["name_at_filing"] == "Meena Rao"
        assert body["address_id"] is None
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
        assert error_codes(again) == {"side": ["E07017"]}

    def test_a_witness_may_have_a_designation(self, client, draft):
        response = add_witness(client, draft, designation="Branch manager")

        assert response.status_code == 201, response.json()
        assert response.json()["designation_at_filing"] == "Branch manager"

    def test_a_witness_address_needs_a_police_station(self, client, draft):
        address = {**ADDRESS_DEFAULTS, "police_station": ""}

        response = add_witness(client, draft, address=address)

        assert response.status_code == 400
        assert error_codes(response) == {"address.police_station": ["E00002"]}

    @pytest.mark.parametrize(
        "change, field, code",
        [
            ({"what_will_witness_prove": "   "}, "what_will_witness_prove", "E00004"),
            ({"institution": INSTITUTION}, "institution", "E07024"),
            ({"is_party_in_person": True}, "is_party_in_person", "E07024"),
            ({"side": None}, "side", "E00002"),
            ({"side": "JUDGE"}, "side", "E00005"),
            ({"called_by_participant_id": str(uuid.uuid4())}, "called_by_participant_id", "E07024"),
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
                {"address": {**ADDRESS_DEFAULTS, "police_station": ""}},
                "address.police_station",
                "E00002",
            ),
        ],
    )
    def test_invalid_changes_are_400(self, client, witness, change, field, code):
        response = patch(client, witness["case_participant_id"], change)

        assert response.status_code == 400
        assert error_codes(response) == {field: [code]}

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
    body.setdefault("address", ADDRESS_DEFAULTS)
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
        assert error_codes(response) == {"address": ["E00002"]}

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


class TestPoliceStation:
    """Only accused and witness addresses need a police station."""

    def test_a_complainant_address_may_leave_it_out(self, client, draft):
        response = add(client, draft, person=PERSON, address=NO_POLICE_STATION)

        assert response.status_code == 201, response.json()
        participant = CaseParticipant.objects.get(pk=response.json()["case_participant_id"])
        assert participant.address.police_station == ""

    def test_a_poa_holder_address_may_leave_it_out(self, client, draft):
        complainant = add_complainant(client, draft)

        response = add_poa_holder(
            client, draft, [complainant["case_participant_id"]], address=NO_POLICE_STATION
        )

        assert response.status_code == 201, response.json()

    @pytest.mark.parametrize(
        "address", [NO_POLICE_STATION, {**ADDRESS_DEFAULTS, "police_station": " "}]
    )
    def test_an_accused_address_needs_it(self, client, draft, address):
        add_complainant(client, draft)

        response = add(
            client, draft, "accused", person={**PERSON, "name": "Suresh"}, address=address
        )

        assert response.status_code == 400
        assert error_codes(response) == {"address.police_station": ["E00002"]}

    def test_changing_an_accused_address_needs_it(self, client, draft):
        add_complainant(client, draft)
        accused = add(client, draft, "accused", person={**PERSON, "name": "Suresh"}).json()

        response = patch(client, accused["case_participant_id"], {"address": NO_POLICE_STATION})

        assert response.status_code == 400
        assert error_codes(response) == {"address.police_station": ["E00002"]}


class TestDisabilityStatus:
    def test_a_person_may_state_a_disability(self, client, draft):
        body = add_complainant(client, draft, disability_status="VISUAL")

        assert Person.objects.get(pk=body["person_id"]).disability_status == "VISUAL"

    def test_an_unknown_value_is_400(self, client, draft):
        response = add(client, draft, person={**PERSON, "disability_status": "SOMETIMES"})

        assert response.status_code == 400
        assert error_codes(response) == {"person.disability_status": ["E00005"]}
