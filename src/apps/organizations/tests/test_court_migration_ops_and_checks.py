"""Data-migration helpers and database system checks (spec 0029 #3.4, #9.3, #12)."""

import types
from unittest import mock

from django.apps import apps as global_apps
from django.db import DatabaseError, connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase

from apps.organizations import checks, migration_ops, services
from apps.organizations.models import CourtRoleAction, RoleAssignment
from apps.organizations.tests.court_factories import (
    TwoCourtsMixin,
    assign,
    make_courtroom,
    make_establishment,
    make_role,
    make_user,
)
from apps.organizations.tests.factories import make_organization

from . import court_actions as actions


def migration_apps():
    """The historical app registry at the latest migration, as a data migration sees it."""
    executor = MigrationExecutor(connection)
    return executor.loader.project_state(("organizations", "0003_court_roles")).apps


class MigrationOpsTests(TestCase):
    """The helpers run against historical models with codes no longer registered."""

    @classmethod
    def setUpTestData(cls):
        cls.apps = migration_apps()

    def setUp(self):
        self.drafter = make_role("DRAFTER", [actions.EDIT])
        self.signer = make_role("SIGNER", [actions.SIGN])
        self.process = make_role(
            "PROCESS",
            [
                (actions.PROCESS_SEND, {"channels": ["RPAD", "POLICE_NSTEP"]}),
                (actions.PROCESS_SEND, {"process_types": ["WARRANT"], "channels": ["SMS"]}),
                (actions.PROCESS_SIGN, {"process_types": ["SUMMONS"]}),
            ],
        )
        self.inactive = make_role("OLD_DRAFTER", [actions.EDIT])
        self.inactive.is_active = False
        services.save_role(self.inactive, actor=None)

    def codes(self, role):
        return sorted(role.actions.values_list("action", flat=True))

    def test_add_action_to_roles_with_copies_to_every_holder_and_is_idempotent(self):
        added = migration_ops.add_action_to_roles_with(self.apps, "sample.new", like="testing.edit")
        self.assertEqual(added, 2)
        self.assertEqual(self.codes(self.drafter), ["sample.new", "testing.edit"])
        self.assertEqual(self.codes(self.inactive), ["sample.new", "testing.edit"])
        self.assertEqual(self.codes(self.signer), ["testing.sign"])
        self.assertEqual(
            migration_ops.add_action_to_roles_with(self.apps, "sample.new", like="testing.edit"), 0
        )
        history = CourtRoleAction.history.filter(action="sample.new")
        self.assertEqual(history.count(), 2)
        self.assertTrue(all(h.history_type == "+" for h in history))
        self.assertTrue(all(h.history_change_reason.startswith("migration") for h in history))

    def test_add_action_copies_each_rows_scope(self):
        migration_ops.add_action_to_roles_with(
            self.apps, "sample.recall", like="testing.process_send"
        )
        scopes = list(
            CourtRoleAction.objects.filter(role=self.process, action="sample.recall")
            .order_by("created_at")
            .values_list("scope", flat=True)
        )
        self.assertCountEqual(
            scopes,
            [
                {"channels": ["POLICE_NSTEP", "RPAD"]},
                {"channels": ["SMS"], "process_types": ["WARRANT"]},
            ],
        )

    def test_remove_action_from_roles_clears_w004(self):
        CourtRoleAction.objects.create(role=self.drafter, action="sample.removed")
        self.assertIn("organizations.W004", [w.id for w in checks._undeclared_actions()])
        removed = migration_ops.remove_action_from_roles(self.apps, "sample.removed")
        self.assertEqual(removed, 1)
        self.assertEqual(checks._undeclared_actions(), [])
        self.assertEqual(
            CourtRoleAction.history.filter(action="sample.removed", history_type="-").count(), 1
        )

    def test_history_reason_names_the_calling_migration(self):
        def forwards(apps):
            return migration_ops.add_action_to_roles_with(apps, "sample.new", like="testing.edit")

        # Run it as if it were defined in a migration module.
        as_migration = types.FunctionType(
            forwards.__code__,
            {"__name__": "apps.sample.migrations.0007_add_new", "migration_ops": migration_ops},
        )
        as_migration(self.apps)
        reasons = set(
            CourtRoleAction.history.filter(action="sample.new").values_list(
                "history_change_reason", flat=True
            )
        )
        self.assertEqual(reasons, {"migration sample.0007_add_new"})

    def test_add_scope_code_with_refuses_an_unknown_axis(self):
        with self.assertRaises(ValueError):
            migration_ops.add_scope_code_with(self.apps, "courts", "X", like="Y")

    def test_add_scope_code_with(self):
        changed = migration_ops.add_scope_code_with(
            self.apps, "channels", "POLICE_X", like="POLICE_NSTEP"
        )
        self.assertEqual(changed, 1)
        scopes = [r.scope for r in CourtRoleAction.objects.filter(role=self.process)]
        self.assertIn({"channels": ["POLICE_NSTEP", "POLICE_X", "RPAD"]}, scopes)
        # Rows without the axis (process_sign has no channels) and without ``like`` are unchanged.
        self.assertIn({"process_types": ["SUMMONS"]}, scopes)
        self.assertIn({"channels": ["SMS"], "process_types": ["WARRANT"]}, scopes)
        self.assertEqual(
            migration_ops.add_scope_code_with(
                self.apps, "channels", "POLICE_X", like="POLICE_NSTEP"
            ),
            0,
        )
        self.assertEqual(CourtRoleAction.history.filter(history_type="~").count(), 1)


class DatabaseCheckTests(TwoCourtsMixin, TestCase):
    """W001, E001, W002, W003, W004."""

    def ids(self):
        return sorted(
            {message.id for message in checks.check_court_data(None, databases=["default"])}
        )

    def test_clean_data_has_no_findings(self):
        self.make_courts()
        assign(make_user(), self.room_a1, make_role("TYPIST", [actions.EDIT]))
        self.assertEqual(self.ids(), [])

    def test_skipped_without_databases(self):
        make_establishment("EMPTY")
        self.assertEqual(checks.check_court_data(None), [])

    def test_establishment_without_courtroom(self):
        make_establishment("EMPTY")
        self.assertEqual(self.ids(), ["organizations.W001"])

    def test_courtroom_with_a_wrong_parent(self):
        est = make_establishment("EST")
        room = make_courtroom("EST_CR", est)
        make_courtroom("EST_CR2", est)
        est_parent = make_organization(code="DIST")
        # Edited outside validation, as a bad data fix would.
        type(room).objects.filter(pk=room.pk).update(parent=est_parent)
        self.assertIn("organizations.E001", self.ids())

    def test_assignment_breaking_the_rules(self):
        self.make_courts()
        user = make_user()
        role = make_role("TYPIST", [actions.EDIT])
        assign(user, self.room_a1, role)
        # The courtroom list entry removed behind the services' back.
        user.courtroom_assignments.update(is_active=False)
        self.assertEqual(self.ids(), ["organizations.W002"])
        RoleAssignment.objects.update(is_active=False)
        self.assertEqual(self.ids(), [])

    def test_a_listed_courtroom_that_is_not_a_courtroom(self):
        self.make_courts()
        user = make_user()
        services.assign_courtroom(user, self.room_a1, actor=None)
        # Re-pointed behind the services' back, as a bad data fix would.
        user.courtroom_assignments.update(courtroom=self.est_a)
        self.assertEqual(self.ids(), ["organizations.W002"])

    def test_skipped_before_the_tables_exist(self):
        with mock.patch.object(checks, "_roles_without_actions", side_effect=DatabaseError):
            self.assertEqual(checks.check_court_data(None, databases=["default"]), [])

    def test_role_without_actions(self):
        make_role("EMPTY_ROLE")
        self.assertEqual(self.ids(), ["organizations.W003"])

    def test_undeclared_action(self):
        role = make_role("TYPIST", [actions.EDIT])
        CourtRoleAction.objects.create(role=role, action="sample.removed")
        self.assertEqual(self.ids(), ["organizations.W004"])


class HistoricalAppsTests(TestCase):
    """The helpers only touch models through the ``apps`` they are given."""

    def test_global_apps_work_too(self):
        role = make_role("DRAFTER", [actions.EDIT])
        migration_ops.add_action_to_roles_with(global_apps, "sample.other", like="testing.edit")
        self.assertTrue(role.actions.filter(action="sample.other").exists())
