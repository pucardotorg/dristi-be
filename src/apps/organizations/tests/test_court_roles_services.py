"""Roles, assignments and change notification (spec 0029 #4, #5, #8; #12 "Roles", "Assignments", "Signal")."""

from contextlib import ExitStack
from unittest import mock

from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.organizations import selectors, services
from apps.organizations.models import (
    CourtRole,
    CourtRoleAction,
    CourtroomAssignment,
    RoleAssignment,
)
from apps.organizations.signals import court_access_changed
from apps.organizations.tests.court_factories import (
    TwoCourtsMixin,
    assign,
    make_role,
    make_user,
)

from . import court_actions as actions


class RoleTests(TwoCourtsMixin, TestCase):
    """Building roles from actions."""

    def setUp(self):
        self.make_courts()
        self.admin = make_user()

    def test_a_scope_on_an_unscoped_action_is_refused(self):
        role = make_role("CLERK")
        with self.assertRaises(ValidationError):
            services.set_role_actions(
                role, [(actions.SIGN, {"process_types": ["SUMMONS"]})], actor=self.admin
            )

    def test_an_empty_scope_list_is_refused(self):
        role = make_role("CLERK")
        with self.assertRaises(ValidationError):
            services.set_role_actions(
                role, [(actions.PROCESS_SIGN, {"process_types": []})], actor=self.admin
            )

    def test_an_unknown_scope_key_and_lowercase_codes_are_refused(self):
        role = make_role("CLERK")
        for scope in ({"courts": ["X"]}, {"channels": ["rpad"]}, ["SUMMONS"]):
            with self.subTest(scope=scope), self.assertRaises(ValidationError):
                services.set_role_actions(role, [(actions.PROCESS_SIGN, scope)], actor=self.admin)

    def test_an_unscoped_action_twice_is_refused(self):
        role = make_role("CLERK")
        with self.assertRaises(ValidationError):
            services.set_role_actions(role, [actions.SIGN, actions.SIGN], actor=self.admin)

    def test_a_scoped_action_may_be_listed_with_different_scopes(self):
        role = make_role(
            "CLERK",
            [
                (actions.PROCESS_SIGN, {"process_types": ["SUMMONS"]}),
                (actions.PROCESS_SIGN, {"process_types": ["WARRANT"], "channels": ["RPAD"]}),
            ],
        )
        self.assertEqual(role.actions.count(), 2)
        with self.assertRaises(ValidationError):
            services.set_role_actions(
                role,
                [
                    (actions.PROCESS_SIGN, {"process_types": ["SUMMONS"]}),
                    (actions.PROCESS_SIGN, {"process_types": ["SUMMONS"]}),
                ],
                actor=self.admin,
            )

    def test_an_undeclared_action_is_refused(self):
        role = make_role("CLERK")
        with self.assertRaises(ValidationError):
            services.set_role_actions(role, [("sample.nobody_declares", None)], actor=self.admin)
        row = CourtRoleAction(role=role, action="sample.nobody_declares")
        with self.assertRaises(ValidationError):
            row.full_clean()

    def test_a_role_of_establishment_a_cannot_be_assigned_at_b(self):
        role = make_role("EXCEPTION", [actions.FLAG], establishment=self.est_a)
        assign(make_user(), self.est_a, role)
        with self.assertRaises(ValidationError):
            services.assign_role(make_user(), self.est_b, role, actor=self.admin)
        services.assign_courtroom(user := make_user(), self.room_a1, actor=self.admin)
        services.assign_role(user, self.room_a1, role, actor=self.admin)

    def test_an_establishment_role_must_be_at_an_establishment(self):
        with self.assertRaises(ValidationError):
            make_role("BAD", establishment=self.room_a1)

    def test_adding_a_courtroom_action_to_a_role_assigned_at_an_establishment_is_refused(self):
        role = make_role("SCRUTINY", [actions.FLAG])
        assign(make_user(), self.est_a, role)
        with self.assertRaises(ValidationError):
            services.set_role_actions(role, [actions.FLAG, actions.SIGN], actor=self.admin)
        self.assertEqual(set(role.actions.values_list("action", flat=True)), {"testing.flag"})

    def test_editing_a_role_changes_every_holder_on_the_next_call_and_is_recorded(self):
        role = make_role("MAGISTRATE", [actions.SIGN])
        first, second = make_user(), make_user()
        assign(first, self.room_a1, role)
        assign(second, self.room_a2, role)
        self.assertFalse(selectors.can(first, actions.EDIT, self.room_a1.pk))

        changed = services.set_role_actions(role, [actions.EDIT], actor=self.admin)

        self.assertEqual(changed, {"testing.sign", "testing.edit"})
        # A fresh request has a fresh user object; nothing outlives the request.
        first.refresh_from_db()
        selectors.clear_cache(first)
        self.assertTrue(selectors.can(first, actions.EDIT, self.room_a1.pk))
        self.assertFalse(selectors.can(first, actions.SIGN, self.room_a1.pk))
        self.assertTrue(selectors.can(second, actions.EDIT, self.room_a2.pk))
        history = CourtRoleAction.history.filter(role_id=role.pk)
        self.assertEqual(
            sorted(history.values_list("history_type", "action")),
            [("+", "testing.edit"), ("+", "testing.sign"), ("-", "testing.sign")],
        )
        self.assertEqual(history.get(history_type="-").history_user, self.admin)

    def test_unchanged_rows_are_kept(self):
        role = make_role("MAGISTRATE", [actions.SIGN])
        row = role.actions.get()
        services.set_role_actions(role, [actions.SIGN, actions.EDIT], actor=self.admin)
        self.assertTrue(role.actions.filter(pk=row.pk).exists())

    def test_role_codes_are_unique_among_active_rows_per_establishment(self):
        make_role("TYPIST")
        with self.assertRaises(ValidationError):
            make_role("TYPIST")
        make_role("TYPIST", establishment=self.est_a)
        with self.assertRaises(ValidationError):
            make_role("TYPIST", establishment=self.est_a)
        old = CourtRole.objects.get(code="TYPIST", establishment__isnull=True)
        old.is_active = False
        services.save_role(old, actor=self.admin)
        make_role("TYPIST")

    def test_moving_a_role_away_from_its_assignments_is_refused(self):
        role = make_role("TYPIST", [actions.EDIT])
        assign(make_user(), self.room_b1, role)
        role.establishment = self.est_a
        with self.assertRaises(ValidationError):
            services.save_role(role, actor=self.admin)


class AssignmentTests(TwoCourtsMixin, TestCase):
    """Courtroom lists and role assignments."""

    def setUp(self):
        self.make_courts()
        self.admin = make_user()
        self.user = make_user()
        self.magistrate = make_role("MAGISTRATE", [actions.SIGN, actions.REGISTER])
        self.scrutiny = make_role("SCRUTINY", [actions.FLAG, actions.FORWARD])

    def test_a_courtroom_role_needs_the_courtroom_on_the_list(self):
        with self.assertRaises(ValidationError):
            services.assign_role(self.user, self.room_a1, self.magistrate, actor=self.admin)
        services.assign_courtroom(self.user, self.room_a1, actor=self.admin)
        services.assign_role(self.user, self.room_a1, self.magistrate, actor=self.admin)

    def test_a_role_with_courtroom_actions_is_refused_at_an_establishment(self):
        with self.assertRaises(ValidationError):
            services.assign_role(self.user, self.est_a, self.magistrate, actor=self.admin)

    def test_a_role_cannot_be_held_at_a_non_court_or_inactive_organization(self):
        self.est_b.is_active = False
        self.est_b.save()
        with self.assertRaises(ValidationError):
            services.assign_role(self.user, self.est_b, self.scrutiny, actor=self.admin)
        inactive = make_role("OLD", [actions.FLAG])
        inactive.is_active = False
        services.save_role(inactive, actor=self.admin)
        with self.assertRaises(ValidationError):
            services.assign_role(self.user, self.est_a, inactive, actor=self.admin)

    def test_only_a_courtroom_goes_on_the_list(self):
        with self.assertRaises(ValidationError):
            services.assign_courtroom(self.user, self.est_a, actor=self.admin)

    def test_assigning_twice_keeps_one_row_and_revoked_ones_are_reactivated(self):
        first = services.assign_role(self.user, self.est_a, self.scrutiny, actor=self.admin)
        again = services.assign_role(self.user, self.est_a, self.scrutiny, actor=self.admin)
        self.assertEqual(first.pk, again.pk)
        services.revoke_role(self.user, self.est_a, self.scrutiny, actor=self.admin)
        reactivated = services.assign_role(self.user, self.est_a, self.scrutiny, actor=self.admin)
        self.assertEqual(reactivated.pk, first.pk)
        self.assertEqual(RoleAssignment.objects.filter(user=self.user).count(), 1)
        self.assertEqual(reactivated.updated_by, self.admin)

    def test_a_second_active_row_is_refused_by_the_model(self):
        services.assign_role(self.user, self.est_a, self.scrutiny, actor=self.admin)
        duplicate = RoleAssignment(user=self.user, organization=self.est_a, role=self.scrutiny)
        with self.assertRaises(ValidationError):
            duplicate.full_clean()

    def _race(self, model, winner_fields, *, validate):
        """Make a rival row land after the "already active?" check, before the save.

        ``_stamp`` runs in that gap, outside the save's savepoint, so the rival
        row survives the savepoint rollback, as a concurrent commit would.
        ``validate=True`` hits the constraint in ``full_clean`` (``ValidationError``);
        ``validate=False`` skips it so the database raises ``IntegrityError``.
        """
        real_stamp = services._stamp

        def rival_saves_first(instance, *args, **kwargs):
            model.objects.bulk_create([model(is_active=True, **winner_fields)])
            real_stamp(instance, *args, **kwargs)

        stack = ExitStack()
        stack.enter_context(mock.patch.object(services, "_stamp", side_effect=rival_saves_first))
        if not validate:
            stack.enter_context(mock.patch.object(model, "full_clean"))
        return stack

    def test_concurrent_role_assign_returns_the_winning_row(self):
        fields = {"user": self.user, "organization": self.est_a, "role": self.scrutiny}
        for validate in (True, False):  # ValidationError, then IntegrityError at save
            with self.subTest(validate=validate):
                RoleAssignment.objects.filter(user=self.user).delete()
                selectors.clear_cache(self.user)
                self.assertFalse(selectors.can(self.user, actions.FLAG, self.est_a.pk))  # memoised
                with (
                    self._race(RoleAssignment, fields, validate=validate),
                    mock.patch.object(services, "send_after_commit") as sent,
                ):
                    row = services.assign_role(
                        self.user, self.est_a, self.scrutiny, actor=self.admin
                    )
                sent.assert_not_called()  # the winning call already notified
                self.assertTrue(selectors.can(self.user, actions.FLAG, self.est_a.pk))
                winner = RoleAssignment.objects.get(user=self.user, is_active=True)
                self.assertEqual(row.pk, winner.pk)
                self.assertEqual(RoleAssignment.objects.filter(user=self.user).count(), 1)

    def test_concurrent_courtroom_assign_returns_the_winning_row(self):
        fields = {"user": self.user, "courtroom": self.room_a1}
        for validate in (True, False):
            with self.subTest(validate=validate):
                CourtroomAssignment.objects.filter(user=self.user).delete()
                with self._race(CourtroomAssignment, fields, validate=validate):
                    row = services.assign_courtroom(self.user, self.room_a1, actor=self.admin)
                winner = CourtroomAssignment.objects.get(user=self.user, is_active=True)
                self.assertEqual(row.pk, winner.pk)
                self.assertEqual(CourtroomAssignment.objects.filter(user=self.user).count(), 1)

    def test_removing_a_courtroom_revokes_the_roles_there(self):
        assign(self.user, self.room_a1, self.magistrate)
        assign(self.user, self.room_a2, self.magistrate)
        services.remove_courtroom(self.user, self.room_a1, actor=self.admin)
        self.assertFalse(
            RoleAssignment.objects.filter(organization=self.room_a1, is_active=True).exists()
        )
        self.assertTrue(
            RoleAssignment.objects.filter(organization=self.room_a2, is_active=True).exists()
        )
        self.assertFalse(
            CourtroomAssignment.objects.filter(courtroom=self.room_a1, is_active=True).exists()
        )
        self.assertTrue(selectors.can(self.user, actions.SIGN, self.room_a2.pk))
        self.assertFalse(selectors.can(self.user, actions.SIGN, self.room_a1.pk))

    def test_changes_are_recorded_in_history_with_the_actor(self):
        services.assign_role(self.user, self.est_a, self.scrutiny, actor=self.admin)
        services.revoke_role(self.user, self.est_a, self.scrutiny, actor=self.admin)
        history = RoleAssignment.history.filter(user_id=self.user.pk).order_by("history_date")
        self.assertEqual([h.is_active for h in history], [True, False])
        self.assertTrue(all(h.history_user == self.admin for h in history))


class SignalTests(TwoCourtsMixin, TestCase):
    """``court_access_changed`` (#8.3)."""

    def setUp(self):
        self.make_courts()
        self.admin = make_user()
        self.user = make_user()
        self.received = []

        def receiver(sender, organization_ids, actions, **kwargs):
            self.received.append((organization_ids, actions))

        court_access_changed.connect(receiver, weak=False, dispatch_uid="test-receiver")
        self.addCleanup(court_access_changed.disconnect, dispatch_uid="test-receiver")

    def test_sent_once_after_commit(self):
        role = make_role("SCRUTINY", [actions.FLAG])
        self.received.clear()
        with self.captureOnCommitCallbacks(execute=True):
            services.assign_role(self.user, self.est_a, role, actor=self.admin)
        self.assertEqual(self.received, [([str(self.est_a.pk)], ["testing.flag"])])

    def test_not_sent_on_rollback(self):
        role = make_role("SCRUTINY", [actions.FLAG])
        self.received.clear()
        with self.captureOnCommitCallbacks(execute=False) as callbacks:
            services.assign_role(self.user, self.est_a, role, actor=self.admin)
        # The test transaction rolls back: the callback is captured, never run.
        self.assertEqual(len(callbacks), 1)
        self.assertEqual(self.received, [])

    def test_a_role_edit_is_sent_once_with_every_assigned_organization(self):
        role = make_role("MAGISTRATE", [actions.SIGN])
        assign(self.user, self.room_a1, role)
        assign(make_user(), self.room_b1, role)
        self.received.clear()
        with self.captureOnCommitCallbacks(execute=True):
            services.set_role_actions(role, [actions.SIGN, actions.REGISTER], actor=self.admin)
        self.assertEqual(len(self.received), 1)
        organization_ids, codes = self.received[0]
        # An establishment action held through courtrooms also reaches their establishments.
        self.assertEqual(
            set(organization_ids),
            {str(o.pk) for o in (self.room_a1, self.room_b1, self.est_a, self.est_b)},
        )
        self.assertEqual(codes, ["testing.register"])

    def test_a_courtroom_list_change_is_sent_without_actions(self):
        with self.captureOnCommitCallbacks(execute=True):
            services.assign_courtroom(self.user, self.room_a1, actor=self.admin)
        self.assertEqual(self.received, [([str(self.room_a1.pk)], None)])
