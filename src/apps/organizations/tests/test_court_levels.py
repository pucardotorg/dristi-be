"""Court levels on organizations (spec 0029 #2, #12 "Levels")."""

import uuid

from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.organizations import selectors, services
from apps.organizations.enums import CourtLevel
from apps.organizations.models import Organization, OrganizationType, establishment_id_of
from apps.organizations.tests.court_factories import (
    assign,
    make_courtroom,
    make_establishment,
    make_role,
    make_user,
)
from apps.organizations.tests.factories import make_organization

from . import court_actions as actions


class CourtLevelValidationTests(TestCase):
    """The hierarchy between establishments and courtrooms."""

    def setUp(self):
        self.district = make_organization(
            code="DISTRICT", organization_type=OrganizationType.DISTRICT_COURT
        )
        self.est = make_establishment("EST", parent=self.district)

    def test_courtroom_under_an_establishment_is_valid(self):
        room = make_courtroom("EST_CR1", self.est)
        self.assertEqual(room.court_level, CourtLevel.COURTROOM)

    def test_courtroom_without_a_parent_is_refused(self):
        with self.assertRaises(ValidationError) as ctx:
            make_organization(code="LONE_CR", court_level=CourtLevel.COURTROOM)
        self.assertIn("court_level", ctx.exception.message_dict)

    def test_courtroom_under_a_non_establishment_is_refused(self):
        with self.assertRaises(ValidationError):
            make_organization(code="BAD_CR", court_level=CourtLevel.COURTROOM, parent=self.district)

    def test_establishment_under_a_courtroom_is_refused(self):
        room = make_courtroom("EST_CR1", self.est)
        with self.assertRaises(ValidationError):
            make_establishment("NESTED", parent=room)

    def test_establishment_under_an_establishment_is_refused(self):
        with self.assertRaises(ValidationError):
            make_establishment("NESTED", parent=self.est)

    def test_blank_level_is_stored_as_null(self):
        org = make_organization(code="BLANK", court_level="")
        self.assertIsNone(Organization.objects.get(pk=org.pk).court_level)

    def test_level_cannot_change_while_staff_are_assigned(self):
        room = make_courtroom("EST_CR1", self.est)
        assign(make_user(), room, make_role("TYPIST", [actions.EDIT]))
        room.refresh_from_db()
        room.court_level = None
        with self.assertRaises(ValidationError) as ctx:
            room.save()
        self.assertIn("court_level", ctx.exception.message_dict)

    def test_establishment_level_cannot_change_while_it_has_courtrooms(self):
        make_courtroom("EST_CR1", self.est)
        self.est.refresh_from_db()
        self.est.court_level = None
        with self.assertRaises(ValidationError) as ctx:
            self.est.save()
        self.assertIn("court_level", ctx.exception.message_dict)

    def test_an_inactive_staffed_courtroom_still_blocks_the_level_change(self):
        room = make_courtroom("EST_CR1", self.est)
        services.assign_courtroom(make_user(), room, actor=None)
        room.is_active = False
        room.save()
        self.est.refresh_from_db()
        self.est.court_level = None
        with self.assertRaises(ValidationError) as ctx:
            self.est.save()
        self.assertIn("court_level", ctx.exception.message_dict)

    def test_establishment_level_can_change_once_its_courtrooms_are_gone(self):
        room = make_courtroom("EST_CR1", self.est)
        room.is_active = False
        room.court_level = None
        room.save()
        self.est.refresh_from_db()
        self.est.court_level = None
        self.est.save()
        self.assertIsNone(Organization.objects.get(pk=self.est.pk).court_level)

    def test_staffed_courtroom_cannot_move_to_another_establishment(self):
        room = make_courtroom("EST_CR1", self.est)
        other = make_establishment("OTHER", parent=self.district)
        services.assign_courtroom(make_user(), room, actor=None)
        room.refresh_from_db()
        room.parent = other
        with self.assertRaises(ValidationError) as ctx:
            room.save()
        self.assertIn("parent", ctx.exception.message_dict)

    def test_empty_courtroom_can_move(self):
        room = make_courtroom("EST_CR1", self.est)
        other = make_establishment("OTHER", parent=self.district)
        room.parent = other
        room.save()
        self.assertEqual(Organization.objects.get(pk=room.pk).parent_id, other.pk)

    def test_establishment_with_staff_can_move_between_non_court_parents(self):
        assign(make_user(), self.est, make_role("SCRUTINY", [actions.FLAG]))
        other_district = make_organization(
            code="DISTRICT2", organization_type=OrganizationType.DISTRICT_COURT
        )
        self.est.refresh_from_db()
        self.est.parent = other_district
        self.est.save()
        self.assertEqual(Organization.objects.get(pk=self.est.pk).parent_id, other_district.pk)

    def test_level_can_change_without_assignments(self):
        org = make_organization(code="LATER", parent=self.district)
        org.court_level = CourtLevel.ESTABLISHMENT
        org.save()
        self.assertEqual(Organization.objects.get(pk=org.pk).court_level, CourtLevel.ESTABLISHMENT)

    def test_level_change_is_not_checked_when_the_stored_row_is_gone(self):
        # A loaded instance whose row was deleted meanwhile has nothing stored
        # to compare against, so only the hierarchy rules apply.
        org = make_organization(code="GONE", parent=self.district)
        Organization.objects.filter(pk=org.pk).delete()
        org.court_level = CourtLevel.ESTABLISHMENT
        org.clean()
        self.assertFalse(Organization.objects.filter(pk=org.pk).exists())


class CourtroomsSelectorTests(TestCase):
    """``selectors.courtrooms`` and ``establishment_of``."""

    def test_lists_active_courtrooms_by_name_without_fallback(self):
        est = make_establishment("EST")
        self.assertFalse(selectors.courtrooms(est.pk).exists())
        b = make_courtroom("EST_B", est, name="B room")
        a = make_courtroom("EST_A", est, name="A room")
        make_courtroom("EST_C", est, name="C room", is_active=False)
        self.assertEqual(list(selectors.courtrooms(est.pk)), [a, b])

    def test_establishment_of(self):
        est = make_establishment("EST")
        room = make_courtroom("EST_CR", est)
        other = make_organization(code="OTHER")
        self.assertEqual(selectors.establishment_of(est.pk), est)
        self.assertEqual(selectors.establishment_of(room.pk), est)
        self.assertIsNone(selectors.establishment_of(other.pk))
        self.assertIsNone(selectors.establishment_of(None))
        self.assertIsNone(selectors.establishment_of(uuid.uuid4()))

    def test_active_establishment_of(self):
        est = make_establishment("EST")
        room = make_courtroom("EST_CR", est)
        other = make_organization(code="OTHER")
        self.assertEqual(selectors.active_establishment_of(est.pk), est)
        self.assertEqual(selectors.active_establishment_of(room.pk), est)
        self.assertIsNone(selectors.active_establishment_of(other.pk))
        self.assertIsNone(selectors.active_establishment_of(None))
        est.is_active = False
        est.save()
        self.assertIsNone(selectors.active_establishment_of(est.pk))
        self.assertIsNone(selectors.active_establishment_of(room.pk))

    def test_establishment_id_of(self):
        est = make_establishment("EST")
        room = make_courtroom("EST_CR", est)
        self.assertEqual(establishment_id_of(est), est.pk)
        self.assertEqual(establishment_id_of(room), est.pk)
        self.assertIsNone(establishment_id_of(make_organization(code="OTHER")))
        self.assertIsNone(establishment_id_of(None))
