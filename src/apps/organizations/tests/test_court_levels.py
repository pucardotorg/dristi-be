"""Court levels on organizations (spec 0029 #2, #12 "Levels")."""

from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.organizations import selectors
from apps.organizations.enums import CourtLevel
from apps.organizations.models import Organization, OrganizationType
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

    def test_level_can_change_without_assignments(self):
        org = make_organization(code="LATER", parent=self.district)
        org.court_level = CourtLevel.ESTABLISHMENT
        org.save()
        self.assertEqual(Organization.objects.get(pk=org.pk).court_level, CourtLevel.ESTABLISHMENT)


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
