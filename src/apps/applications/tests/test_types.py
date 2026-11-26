"""Type specs: form context, rendering, edit litigant control (spec 0033 #3.4, #3.5, #6.2)."""

import datetime

import pytest

from apps.applications import ports
from apps.applications.models import ApplicationType
from apps.applications.services import rendering
from apps.applications.types import registry
from apps.applications.types.base import FilerContext
from apps.applications.types.edit_litigant import compute_changes, current_details, phone_taken
from apps.cases.models import ParticipantRole

from .factories import (
    add_party,
    client_for,
    errors_of,
    make_user,
    schedule_hearing,
    set_config,
    submitted,
)

pytestmark = pytest.mark.django_db

TODAY = datetime.date(2026, 11, 12)


def ctx(world, user):
    return FilerContext(
        case_id=world.case.pk, user=user, access=ports.case_access(world.case.pk, user)
    )


def create(user, world, code, data, **extra):
    return client_for(user).post(
        f"/api/v1/cases/{world.case.pk}/applications/",
        {"application_type": code, "data": data, **extra},
        format="json",
    )


class TestEditLitigant:
    spec = registry.require("EDIT_LITIGANT_DETAILS")

    def test_control_own_litigants_by_default(self, world):
        context = self.spec.form_context(ctx(world, world.a1))
        ids = [item["participant_id"] for item in context["editable_litigants"]]
        assert ids == [str(world.complainant.pk)]
        current = context["editable_litigants"][0]["current"]
        assert current["name"] == "Prateek Agrawal"

    def test_control_own_side_and_any(self, world):
        second = add_party(world.case, ParticipantRole.COMPLAINANT, "Unrepresented", ordinal=2)
        set_config("applications", "edit_litigant_details", '{"editable": "OWN_SIDE"}')
        ids = self.spec.editable_ids(world.case.pk, "COMPLAINANT", set())
        assert set(ids) == {world.complainant.pk, second.pk}
        set_config("applications", "edit_litigant_details", '{"editable": "ANY"}')
        assert world.accused.pk in self.spec.editable_ids(world.case.pk, "COMPLAINANT", set())

    def test_side_not_allowed_to_raise(self, world):
        set_config("applications", "edit_litigant_details", '{"raised_by_sides": ["ACCUSED"]}')
        assert self.spec.unavailable_reason(ctx(world, world.a1)) is not None
        assert self.spec.unavailable_reason(ctx(world, world.b1)) is None

    def test_clerk_edits_their_advocates_litigants(self, world):
        assert self.spec.unavailable_reason(ctx(world, world.c1)) is None

    def test_t33_litigant_the_control_forbids(self, world):
        response = create(
            world.a1,
            world,
            "EDIT_LITIGANT_DETAILS",
            {"participant_id": str(world.accused.pk)},
            raised_by=str(world.a1.pk),
        )
        assert errors_of(response) == [("E13024", "data.participant_id")]

    def test_t34_complainant_phone_used_by_the_accused(self, world):
        phone = "+919811112222"
        add_party(world.case, ParticipantRole.ACCUSED, "Accused two", ordinal=2, phone=phone)
        response = create(
            world.a1,
            world,
            "EDIT_LITIGANT_DETAILS",
            {"participant_id": str(world.complainant.pk), "details": {"phone_number": phone}},
            raised_by=str(world.a1.pk),
        )
        assert errors_of(response) == [("E13025", "data.details.phone_number")]
        assert phone_taken(world.case.pk, world.complainant.pk, world.a1.mobile_number)

    def test_t35_changing_nothing_is_incomplete(self, world):
        current = current_details(world.complainant)
        response = create(
            world.a1,
            world,
            "EDIT_LITIGANT_DETAILS",
            {
                "participant_id": str(world.complainant.pk),
                "litigant_type": "INDIVIDUAL",
                "details": {
                    "name": current["name"],
                    "age": 30,
                    "phone_number": "+919800000009",
                    "addresses": current["addresses"],
                },
            },
            raised_by=str(world.a1.pk),
            litigant=str(world.complainant.pk),
            details="<p>x</p>",
        )
        app_id = response.json()["id"]
        client_for(world.a1).patch(
            f"/api/v1/applications/{app_id}/",
            {
                "data": {
                    "participant_id": str(world.complainant.pk),
                    "litigant_type": "INDIVIDUAL",
                    "details": {},
                }
            },
            format="json",
        )
        result = client_for(world.a1).post(f"/api/v1/applications/{app_id}/proceed-to-sign/")
        assert ("E13008", "data.details.name") in errors_of(result)

    def test_t35_individual_to_institution_is_a_change(self, world):
        changes = compute_changes(
            world.complainant, {"litigant_type": "INSTITUTION", "details": {}}
        )
        assert changes == {"litigant_type": {"from": "INDIVIDUAL", "to": "INSTITUTION"}}
        assert compute_changes(None, {}) == {}

    def test_institution_complainant_needs_its_representative(self, world):
        response = create(
            world.a1,
            world,
            "EDIT_LITIGANT_DETAILS",
            {
                "participant_id": str(world.complainant.pk),
                "litigant_type": "INSTITUTION",
                "details": {
                    "entity_type": "LLP",
                    "entity_name": "Acme",
                    "addresses": [{"city": "Kollam"}],
                    "representative": {"name": "R"},
                },
            },
            raised_by=str(world.a1.pk),
            litigant=str(world.complainant.pk),
            details="<p>x</p>",
        )
        result = client_for(world.a1).post(
            f"/api/v1/applications/{response.json()['id']}/proceed-to-sign/"
        )
        found = errors_of(result)
        assert ("E13008", "data.details.representative.phone_number") in found

    def test_accused_address_needs_a_police_station(self, world):
        set_config("applications", "edit_litigant_details", '{"editable": "ANY"}')
        response = create(
            world.b1,
            world,
            "EDIT_LITIGANT_DETAILS",
            {
                "participant_id": str(world.accused.pk),
                "litigant_type": "INDIVIDUAL",
                "details": {
                    "name": "D",
                    "phone_number": "+919800000002",
                    "email": "d@x.in",
                    "addresses": [{"city": "K"}],
                },
            },
            raised_by=str(world.b1.pk),
            litigant=str(world.accused.pk),
            details="<p>x</p>",
        )
        result = client_for(world.b1).post(
            f"/api/v1/applications/{response.json()['id']}/proceed-to-sign/"
        )
        assert ("E13008", "data.details.addresses[0].police_station") in errors_of(result)

    def test_render_entries_show_the_changes(self, world):
        application = submitted(
            world,
            "EDIT_LITIGANT_DETAILS",
            data={
                "participant_id": str(world.complainant.pk),
                "litigant_type": "INDIVIDUAL",
                "changes": {
                    "addresses": {"from": [], "to": ["x"]},
                    "age": {"from": None, "to": 30},
                },
            },
        )
        entries = self.spec.render_entries(application)
        assert entries[0] == {"term": "Litigant", "value": "Prateek Agrawal"}
        assert {"term": "Age", "value": " → 30"} in entries


class TestOtherTypes:
    def test_poa_change_form_and_rules(self, world):
        spec = registry.require("POA_CHANGE")
        assert spec.unavailable_reason(ctx(world, world.h1)) is not None
        litigants = spec.form_context(ctx(world, world.h1))["litigants"]
        assert {item["has_poa_holder"] for item in litigants} == {True, False}
        ApplicationType.objects.filter(code="POA_CHANGE").update(is_active=True)
        application = submitted(world, "POA_CHANGE", data={"participant_ids": ["nope"]})
        problems = spec.validate(application, complete=True)
        assert {p.field for p in problems} == {"data.participant_ids[0]", "data.authorizations"}
        application.data = {"participant_ids": [str(world.complainant.pk)]}
        assert spec.render_entries(application)[0]["value"] == "Prateek Agrawal"
        with pytest.raises(ports.PortNotAvailable):
            spec.on_accept(application, order_id=None, values={})

    def test_production_of_documents_renders_types(self, world):
        spec = registry.require("PRODUCTION_OF_DOCUMENTS")
        application = submitted(
            world, "PRODUCTION_OF_DOCUMENTS", data={"documents": [{"document_type": "Bank"}]}
        )
        assert spec.render_entries(application) == [{"term": "Document 1", "value": "Bank"}]
        assert ("E13008", "data.documents[0].document_id") in [
            (p.code, p.field) for p in spec.validate(application, complete=True)
        ]

    def test_witness_entries(self, world):
        spec = registry.require("ADDITION_OF_WITNESS")
        application = submitted(
            world,
            "ADDITION_OF_WITNESS",
            data={
                "witnesses": [
                    {
                        "name": "W",
                        "what_will_prove": "Debt",
                        "addresses": [{"city": "Kollam", "police_station": "East"}],
                    }
                ]
            },
        )
        entries = spec.render_entries(application)
        assert {"term": "What they will prove", "value": "Debt"} in entries
        assert {"term": "Address", "value": "Kollam (Police station: East)"} in entries

    def test_warrant_by_hand_form_and_entries(self, world):
        spec = registry.require("WARRANT_BY_HAND")
        accused = spec.form_context(ctx(world, world.a1))["accused"]
        assert accused[0]["participant_id"] == str(world.accused.pk)
        assert accused[0]["addresses"]
        application = submitted(
            world,
            "WARRANT_BY_HAND",
            data={
                "accused_participant_id": str(world.accused.pk),
                "delivery_address": {"city": "Kollam"},
            },
        )
        assert spec.render_entries(application)[0] == {
            "term": "Accused",
            "value": "Deepak Choudhary",
        }

    def test_reschedule_form_and_entries(self, world):
        hearing = schedule_hearing(world.case, TODAY + datetime.timedelta(days=9))
        spec = registry.require("POSTPONE_HEARING")
        context = spec.form_context(ctx(world, world.a1))
        assert context["hearing"]["id"] == str(hearing.pk)
        assert context["reschedule_reasons"][0]["code"] == "PARTY_UNAVAILABLE"
        application = submitted(
            world,
            "POSTPONE_HEARING",
            data={"reason_code": "ILLNESS", "proposed_date": "bad"},
            hearing_id=hearing.pk,
        )
        assert ("E00001", "data.proposed_date") in [
            (p.code, p.field) for p in spec.validate(application, complete=False)
        ]
        application.data = {"reason_code": "ILLNESS", "proposed_date": "2026-11-01"}
        assert ("E00001", "data.proposed_date") in [
            (p.code, p.field) for p in spec.validate(application, complete=False)
        ]
        entries = spec.render_entries(application)
        assert entries[2] == {"term": "Reason for rescheduling", "value": "Illness"}

    def test_objection_form_lists_what_can_be_objected_to(self, world):
        target = submitted(world)
        spec = registry.require("OBJECTION")
        items = spec.form_context(ctx(world, world.b1))["objectable_applications"]
        assert [i["id"] for i in items] == [str(target.pk)]
        assert spec.form_context(ctx(world, world.stranger)) == {"objectable_applications": []}
        objection = submitted(world, "OBJECTION", side="ACCUSED", objection_to=target)
        assert spec.render_title(objection).startswith("Objection to Generic application")

    def test_bail_entries(self, world):
        spec = registry.require("BAIL")
        application = submitted(
            world,
            "BAIL",
            side="ACCUSED",
            data={
                "bail_type": "SURETY",
                "bail_amount": "50000",
                "number_of_sureties": 1,
                "sureties": [
                    {"name": "S", "parent_name": "P", "phone": "+91", "address": {"city": "K"}}
                ],
            },
        )
        entries = spec.render_entries(application)
        assert {"term": "Bail amount", "value": "Rs. 50,000"} in entries
        assert {"term": "Surety 1", "value": "S"} in entries

    def test_rendering_a_party_in_person_signatory(self, world):
        from .factories import make_case, represent  # noqa: F401

        p1 = make_user(name="Accused in person")
        party = add_party(
            world.case,
            ParticipantRole.ACCUSED,
            "Accused in person",
            user=p1,
            in_person=True,
            ordinal=2,
        )
        application = submitted(world, "BAIL", side="ACCUSED", data={"bail_type": "CASH"})
        application.raised_by = p1
        application.raised_on_behalf_of = party.pk
        signatory = rendering.build(application)["signatory"]
        assert signatory == {
            "signature": "Signature",
            "name": "Accused in person",
            "line": "Accused in person",
        }
        application.raised_by = None
        assert rendering.build(application)["signatory"]["name"] == ""


class TestPorts:
    def test_state_code_from_a_district_jurisdiction(self, world):
        from apps.locations.models import Location

        state = Location.objects.create(code="IN_PB", name="Punjab", location_type="state")
        district = Location.objects.create(
            code="IN_PB_LDH", name="Ludhiana", location_type="district", parent=state
        )
        world.court.jurisdictions.add(district)
        assert ports.state_code(world.case) == "IN_PB"

    def test_state_code_default(self, world):
        set_config("applications", "default_state_code", "IN_GJ")
        assert ports.state_code(world.case) == "IN_GJ"

    def test_access_of_a_stranger_and_an_anonymous_user(self, world):
        from django.contrib.auth.models import AnonymousUser

        assert ports.case_access(world.case.pk, AnonymousUser()) == ports.NO_ACCESS
        assert ports.case_access(world.case.pk, world.stranger) == ports.NO_ACCESS
        assert ports.office_advocate_user_ids(AnonymousUser()) == []
        assert ports.is_court_reader(world.stranger, world.court.pk) is False
        assert ports.is_court_reader(world.staff, world.court.pk) is True

    def test_task_port_and_missing_contracts(self, world):
        application = submitted(world)
        ports.tasks.open("x", application)
        ports.tasks.complete("x", application)
        ports.tasks.expire("x", application)
        ports.tasks.reschedule("x", application, due_date=TODAY)
        for call in (
            lambda: ports.dispatch_case_event(world.case.pk, "E"),
            lambda: ports.add_witnesses(world.case.pk, None, [], source=None),
            lambda: ports.add_documents_from_application(world.case.pk, [], source=None),
        ):
            with pytest.raises(ports.PortNotAvailable):
                call()

    def test_unconfigured_establishment(self, world, settings):
        settings.SCRUTINY_ESTABLISHMENT_ID = "not-a-uuid"
        assert ports.is_court_reader(world.staff, world.court.pk) is False
