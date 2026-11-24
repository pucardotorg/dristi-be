"""Selectors and the check helper (spec 0029 #6, #7; #12 "Selectors", "Check helper")."""

from django.contrib.auth.models import AnonymousUser, Group
from django.core.exceptions import ImproperlyConfigured
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from apps.api.errors import PERMISSION_DENIED, BusinessError
from apps.organizations import access, selectors, services
from apps.organizations.models import CourtRoleAction
from apps.organizations.tests.court_factories import (
    TwoCourtsMixin,
    assign,
    make_role,
    make_user,
)

from . import court_actions as actions

ALL_CHANNELS = ["SMS", "RPAD", "POLICE_RPAD"]


class SelectorTests(TwoCourtsMixin, TestCase):
    """Two establishments, two courtrooms each, several users."""

    def setUp(self):
        self.make_courts()
        self.magistrate_role = make_role("MAGISTRATE", [actions.SIGN, actions.REGISTER])
        self.magistrate = make_user()
        assign(self.magistrate, self.room_a1, self.magistrate_role)

    def test_a_mixed_level_role_at_a_courtroom(self):
        user = self.magistrate
        self.assertTrue(selectors.can(user, actions.SIGN, self.room_a1.pk))
        self.assertTrue(selectors.can(user, actions.REGISTER, self.est_a.pk))
        self.assertFalse(selectors.can(user, actions.SIGN, self.room_a2.pk))
        self.assertFalse(selectors.can(user, actions.REGISTER, self.room_a1.pk))
        self.assertFalse(selectors.can(user, actions.REGISTER, self.est_b.pk))
        self.assertFalse(selectors.can(user, actions.SIGN, self.room_b1.pk))
        self.assertEqual(selectors.actions_of(user, self.room_a1.pk), {"testing.sign"})
        self.assertEqual(selectors.actions_of(user, self.est_a.pk), {"testing.register"})
        self.assertEqual(selectors.actions_of(user, self.room_a2.pk), frozenset())

    def test_part_of_a_prd_role(self):
        user = make_user()
        assign(user, self.est_a, make_role("SEND_BACK_ONLY", [actions.SEND_BACK]))
        self.assertTrue(selectors.can(user, actions.SEND_BACK, self.est_a.pk))
        self.assertFalse(selectors.can(user, actions.FORWARD, self.est_a.pk))

    def test_actions_of_never_includes_another_establishment(self):
        user = make_user()
        assign(user, self.est_a, make_role("SCRUTINY", [actions.FORWARD]))
        assign(user, self.est_b, make_role("REGISTRAR", [actions.REGISTER]))
        self.assertEqual(selectors.actions_of(user, self.est_a.pk), {"testing.forward"})
        self.assertEqual(selectors.actions_of(user, self.est_b.pk), {"testing.register"})

    def test_two_roles_union(self):
        user = make_user()
        assign(user, self.room_a1, make_role("TYPIST", [actions.EDIT]))
        assign(user, self.room_a1, make_role("SIGNER", [actions.SIGN]))
        self.assertEqual(
            selectors.actions_of(user, self.room_a1.pk), {"testing.edit", "testing.sign"}
        )

    def test_scopes_match_row_by_row(self):
        user = make_user()
        assign(
            user,
            self.room_a1,
            make_role(
                "SUMMONS_RPAD",
                [(actions.PROCESS_SIGN, {"process_types": ["SUMMONS"], "channels": ["RPAD"]})],
            ),
        )
        assign(
            user,
            self.room_a1,
            make_role(
                "WARRANT_POLICE",
                [
                    (
                        actions.PROCESS_SIGN,
                        {"process_types": ["WARRANT"], "channels": ["POLICE_RPAD"]},
                    )
                ],
            ),
        )
        room = self.room_a1.pk
        sign = actions.PROCESS_SIGN
        self.assertTrue(selectors.can(user, sign, room, process_type="SUMMONS", channel="RPAD"))
        self.assertTrue(
            selectors.can(user, sign, room, process_type="WARRANT", channel="POLICE_RPAD")
        )
        self.assertFalse(
            selectors.can(user, sign, room, process_type="SUMMONS", channel="POLICE_RPAD")
        )
        self.assertFalse(selectors.can(user, sign, room, process_type="NOTICE", channel="RPAD"))

    def test_a_missing_axis_matches_everything_and_a_list_only_its_codes(self):
        user = make_user()
        assign(
            user,
            self.room_a1,
            make_role("SENDER", [(actions.PROCESS_SEND, {"channels": ALL_CHANNELS})]),
        )
        room = self.room_a1.pk
        send = actions.PROCESS_SEND
        self.assertTrue(selectors.can(user, send, room, process_type="ANYTHING", channel="SMS"))
        # A channel added later matches nothing until a migration adds it.
        self.assertFalse(selectors.can(user, send, room, channel="EPOST"))

    def test_a_null_scope_covers_everything(self):
        user = make_user()
        assign(user, self.room_a1, make_role("ALL_SIGN", [actions.PROCESS_SIGN]))
        self.assertTrue(
            selectors.can(
                user, actions.PROCESS_SIGN, self.room_a1.pk, process_type="WARRANT", channel="X"
            )
        )

    def test_action_holders_respects_scope_and_the_level_rule(self):
        scoped = make_user()
        assign(
            scoped,
            self.room_a1,
            make_role("SUMMONS", [(actions.PROCESS_SIGN, {"process_types": ["SUMMONS"]})]),
        )
        everything = make_user()
        assign(everything, self.room_a1, make_role("ALL", [actions.PROCESS_SIGN]))
        holders = selectors.action_holders(
            self.room_a1.pk, actions.PROCESS_SIGN, process_type="WARRANT"
        )
        self.assertEqual(list(holders), [everything])
        holders = selectors.action_holders(
            self.room_a1.pk, actions.PROCESS_SIGN, process_type="SUMMONS"
        )
        self.assertEqual(set(holders), {scoped, everything})

        # An establishment action held through a courtroom role counts at the establishment.
        registrar = make_user()
        assign(registrar, self.est_a, make_role("REGISTRAR", [actions.REGISTER]))
        self.assertEqual(
            set(selectors.action_holders(self.est_a.pk, actions.REGISTER)),
            {self.magistrate, registrar},
        )
        self.assertFalse(selectors.action_holders(self.est_b.pk, actions.REGISTER).exists())
        self.assertFalse(selectors.action_holders(self.room_a1.pk, actions.REGISTER).exists())
        self.assertFalse(selectors.action_holders(self.est_a.pk, actions.SIGN).exists())
        self.assertEqual(
            list(selectors.action_holders(self.room_a1.pk, actions.SIGN)), [self.magistrate]
        )

    def test_establishments_of(self):
        user = make_user()
        assign(user, self.est_a, make_role("SCRUTINY", [actions.FLAG]))
        assign(user, self.est_b, make_role("REGISTRAR", [actions.REGISTER]))
        self.assertEqual(list(selectors.establishments_of(user)), [self.est_a, self.est_b])
        self.assertEqual(
            list(selectors.establishments_of(user, actions.SCRUTINY_STAGE)), [self.est_a]
        )
        self.assertEqual(list(selectors.establishments_of(self.magistrate)), [self.est_a])

    def test_courtroom_list_and_staff(self):
        user = make_user()
        services.assign_courtroom(user, self.room_a2, actor=None)
        self.assertEqual(list(selectors.courtrooms_of(user)), [self.room_a2])
        self.assertEqual(list(selectors.courtrooms_of(self.magistrate)), [self.room_a1])
        self.assertEqual(list(selectors.staff_of_courtroom(self.room_a2.pk)), [user])
        # On the list, with no action there.
        self.assertEqual(selectors.actions_of(user, self.room_a2.pk), frozenset())

    def test_is_court_reader_before_and_after_a_courtroom(self):
        staff = make_user()
        services.assign_courtroom(staff, self.room_a2, actor=None)
        officer = make_user()
        assign(officer, self.est_a, make_role("SCRUTINY", [actions.FLAG]))
        # No courtroom yet: those allowed any establishment action there.
        self.assertTrue(selectors.is_court_reader(officer, self.est_a.pk))
        self.assertTrue(selectors.is_court_reader(self.magistrate, self.est_a.pk))
        self.assertFalse(selectors.is_court_reader(staff, self.est_a.pk))
        self.assertFalse(selectors.is_court_reader(officer, self.est_b.pk))
        # With a courtroom: its list.
        self.assertTrue(selectors.is_court_reader(staff, self.est_a.pk, self.room_a2.pk))
        self.assertFalse(selectors.is_court_reader(officer, self.est_a.pk, self.room_a2.pk))
        self.assertFalse(selectors.is_court_reader(self.magistrate, self.est_a.pk, self.room_a2.pk))

    def test_inactive_things_are_ignored(self):
        def fresh():
            selectors.clear_cache(self.magistrate)
            return selectors.can(self.magistrate, actions.SIGN, self.room_a1.pk)

        self.assertTrue(fresh())
        self.magistrate_role.is_active = False
        services.save_role(self.magistrate_role, actor=None)
        self.assertFalse(fresh())
        self.magistrate_role.is_active = True
        services.save_role(self.magistrate_role, actor=None)
        self.assertTrue(fresh())

        self.room_a1.is_active = False
        self.room_a1.save()
        self.assertFalse(fresh())
        self.assertFalse(selectors.action_holders(self.room_a1.pk, actions.SIGN).exists())
        self.room_a1.is_active = True
        self.room_a1.save()

        self.magistrate.is_active = False
        self.magistrate.save()
        self.assertFalse(fresh())
        self.assertFalse(selectors.action_holders(self.room_a1.pk, actions.SIGN).exists())
        self.assertFalse(selectors.staff_of_courtroom(self.room_a1.pk).exists())

    def test_an_inactive_establishment_grants_no_establishment_action(self):
        self.est_a.is_active = False
        self.est_a.save()
        selectors.clear_cache(self.magistrate)
        self.assertFalse(selectors.can(self.magistrate, actions.REGISTER, self.est_a.pk))

    def test_a_superuser_or_group_member_with_no_assignment_is_allowed_nothing(self):
        superuser = make_user(is_superuser=True, is_staff=True)
        group = Group.objects.create(name="SCRUTINY_OFFICER")
        superuser.groups.add(group)
        self.assertFalse(selectors.can(superuser, actions.FLAG, self.est_a.pk))
        self.assertEqual(selectors.actions_of(superuser, self.est_a.pk), frozenset())
        self.assertNotIn(superuser, selectors.action_holders(self.est_a.pk, actions.REGISTER))

    def test_undeclared_codes_are_ignored(self):
        CourtRoleAction.objects.create(role=self.magistrate_role, action="sample.removed")
        selectors.clear_cache(self.magistrate)
        self.assertEqual(selectors.actions_of(self.magistrate, self.room_a1.pk), {"testing.sign"})

    def test_an_undeclared_action_argument_raises(self):
        with self.assertRaises(ImproperlyConfigured):
            selectors.can(self.magistrate, "sample.removed", self.room_a1.pk)
        with self.assertRaises(ImproperlyConfigured):
            selectors.action_holders(self.room_a1.pk, "sample.removed")

    def test_grants_are_memoised_per_user_object(self):
        selectors.clear_cache(self.magistrate)
        with CaptureQueriesContext(connection) as first:
            selectors.can(self.magistrate, actions.SIGN, self.room_a1.pk)
        self.assertLessEqual(len(first), 2)
        with self.assertNumQueries(0):
            selectors.can(self.magistrate, actions.SIGN, self.room_a1.pk)
            selectors.actions_of(self.magistrate, self.est_a.pk)
            selectors.is_court_reader(self.magistrate, self.est_a.pk)

    def test_queries_do_not_grow_with_roles(self):
        user = make_user()
        for index in range(5):
            assign(user, self.room_a1, make_role(f"ROLE_{index}", [actions.EDIT, actions.REGISTER]))
        selectors.clear_cache(user)
        with self.assertNumQueries(2):
            selectors.grants_of(user)
        # The organization, the candidate rows, then the users.
        with self.assertNumQueries(3):
            list(selectors.action_holders(self.est_a.pk, actions.REGISTER))


class AccessTests(TwoCourtsMixin, TestCase):
    """``access.require`` and ``access.require_any``."""

    def setUp(self):
        self.make_courts()
        self.user = make_user()
        assign(self.user, self.est_a, make_role("SEND_BACK_ONLY", [actions.SEND_BACK]))
        assign(
            self.user,
            self.room_a1,
            make_role("SUMMONS", [(actions.PROCESS_SIGN, {"process_types": ["SUMMONS"]})]),
        )

    def test_require_passes_and_refuses_with_the_given_code(self):
        access.require(self.user, actions.SEND_BACK, self.est_a.pk, error=PERMISSION_DENIED)
        with self.assertRaises(BusinessError) as ctx:
            access.require(self.user, actions.FORWARD, self.est_a.pk, error=PERMISSION_DENIED)
        self.assertEqual(ctx.exception.error, PERMISSION_DENIED)

    def test_require_passes_scope(self):
        access.require(
            self.user,
            actions.PROCESS_SIGN,
            self.room_a1.pk,
            error=PERMISSION_DENIED,
            process_type="SUMMONS",
        )
        with self.assertRaises(BusinessError):
            access.require(
                self.user,
                actions.PROCESS_SIGN,
                self.room_a1.pk,
                error=PERMISSION_DENIED,
                process_type="WARRANT",
            )

    def test_require_refuses_no_user_and_anonymous(self):
        for user in (None, AnonymousUser()):
            with self.subTest(user=user), self.assertRaises(BusinessError):
                access.require(user, actions.SEND_BACK, self.est_a.pk, error=PERMISSION_DENIED)

    def test_require_any(self):
        access.require_any(
            self.user, actions.SCRUTINY_STAGE, self.est_a.pk, error=PERMISSION_DENIED
        )
        with self.assertRaises(BusinessError):
            access.require_any(
                self.user, (actions.FORWARD, actions.FLAG), self.est_a.pk, error=PERMISSION_DENIED
            )
        with self.assertRaises(BusinessError):
            access.require_any(
                self.user, actions.SCRUTINY_STAGE, self.est_b.pk, error=PERMISSION_DENIED
            )

    def test_require_any_refuses_a_scoped_action(self):
        with self.assertRaises(ImproperlyConfigured):
            access.require_any(
                self.user,
                (actions.FLAG, actions.PROCESS_SIGN),
                self.est_a.pk,
                error=PERMISSION_DENIED,
            )

    def test_combinations_are_checked_at_the_same_establishment(self):
        """SCR-11 across courts: forward at A, register only at B, is offered Forward at A."""
        officer = make_user()
        assign(officer, self.est_a, make_role("SCRUTINY", [actions.FORWARD]))
        assign(officer, self.est_b, make_role("REGISTRAR", [actions.REGISTER]))
        held = selectors.actions_of(officer, self.est_a.pk)
        decide = "register" if actions.REGISTER.code in held else "forward"
        self.assertEqual(decide, "forward")
