"""Court role admin pages and seeding (spec 0029 #9.1, #11)."""

import tempfile
from io import StringIO
from pathlib import Path

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from apps.organizations.models import CourtRole, CourtroomAssignment, RoleAssignment
from apps.organizations.tests.court_factories import (
    TwoCourtsMixin,
    assign,
    make_role,
    make_user,
)

from . import court_actions as actions


def inline_data(rows, prefix="actions"):
    """POST data for the role's action inline."""
    data = {
        f"{prefix}-TOTAL_FORMS": str(len(rows)),
        f"{prefix}-INITIAL_FORMS": "0",
        f"{prefix}-MIN_NUM_FORMS": "0",
        f"{prefix}-MAX_NUM_FORMS": "1000",
    }
    for index, (code, scope) in enumerate(rows):
        data[f"{prefix}-{index}-action"] = code
        data[f"{prefix}-{index}-scope"] = scope or "null"
    return data


class CourtRoleAdminTests(TwoCourtsMixin, TestCase):
    """Roles and assignments are managed in admin, through the services."""

    def setUp(self):
        self.make_courts()
        self.admin = make_user(is_staff=True, is_superuser=True)
        self.client.force_login(self.admin)

    def test_create_a_role_with_actions_and_whole_groups(self):
        data = {
            "code": "BENCH_CLERK",
            "name": "Bench clerk",
            "establishment": "",
            "is_active": "on",
            "add_groups": ["Order drafter"],
            **inline_data(
                [("testing.process_sign", '{"process_types": ["SUMMONS"]}'), ("testing.sign", None)]
            ),
        }
        response = self.client.post(reverse("admin:organizations_courtrole_add"), data)
        self.assertEqual(response.status_code, 302)
        role = CourtRole.objects.get(code="BENCH_CLERK")
        self.assertEqual(
            sorted(role.actions.values_list("action", "scope")),
            [
                ("testing.edit", None),
                ("testing.process_sign", {"process_types": ["SUMMONS"]}),
                ("testing.sign", None),
            ],
        )
        self.assertEqual(role.created_by, self.admin)
        self.assertEqual(role.actions.first().history.first().history_user, self.admin)

    def test_an_invalid_action_set_is_shown_as_a_form_error(self):
        role = make_role("SCRUTINY", [actions.FLAG])
        assign(make_user(), self.est_a, role)
        data = {
            "code": "SCRUTINY",
            "name": "Scrutiny",
            "establishment": "",
            "is_active": "on",
            **inline_data([("testing.flag", None), ("testing.sign", None)]),
        }
        response = self.client.post(
            reverse("admin:organizations_courtrole_change", args=[role.pk]), data
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "cannot hold courtroom action")
        self.assertEqual(list(role.actions.values_list("action", flat=True)), ["testing.flag"])

    def test_roles_and_assignments_cannot_be_deleted(self):
        role = make_role("SCRUTINY", [actions.FLAG])
        response = self.client.get(reverse("admin:organizations_courtrole_delete", args=[role.pk]))
        self.assertEqual(response.status_code, 403)

    def test_role_change_page_says_whom_a_change_applies_to(self):
        role = make_role("TYPIST", [actions.EDIT])
        assign(make_user(), self.room_a1, role)
        assign(make_user(), self.room_b1, role)
        response = self.client.get(reverse("admin:organizations_courtrole_change", args=[role.pk]))
        self.assertContains(response, "2 user(s) at 2 organization(s).")

    def test_assign_a_courtroom_then_a_role_in_admin(self):
        user = make_user()
        role = make_role("TYPIST", [actions.EDIT])
        response = self.client.post(
            reverse("admin:organizations_roleassignment_add"),
            {"user": user.pk, "organization": self.room_a1.pk, "role": role.pk},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "courtroom list")

        response = self.client.post(
            reverse("admin:organizations_courtroomassignment_add"),
            {"user": user.pk, "courtroom": self.room_a1.pk},
        )
        self.assertEqual(response.status_code, 302)
        response = self.client.post(
            reverse("admin:organizations_roleassignment_add"),
            {"user": user.pk, "organization": self.room_a1.pk, "role": role.pk},
        )
        self.assertEqual(response.status_code, 302)
        assignment = RoleAssignment.objects.get(user=user)
        self.assertEqual(assignment.created_by, self.admin)

        # Removing the courtroom in admin also revokes the role there.
        listed = CourtroomAssignment.objects.get(user=user)
        response = self.client.post(
            reverse("admin:organizations_courtroomassignment_change", args=[listed.pk]), {}
        )
        self.assertEqual(response.status_code, 302)
        assignment.refresh_from_db()
        self.assertFalse(assignment.is_active)

    def test_resaving_an_old_inactive_row_keeps_the_current_access(self):
        # The services reuse one row per pair, so a stale inactive duplicate can only
        # come from outside them (shell, import); the admin must still leave access alone.
        user = make_user()
        role = make_role("TYPIST", [actions.EDIT])
        current_role = assign(user, self.room_a1, role)
        current_room = CourtroomAssignment.objects.get(user=user, is_active=True)
        stale_room = CourtroomAssignment.objects.create(
            user=user, courtroom=self.room_a1, is_active=False
        )
        stale_role = RoleAssignment.objects.create(
            user=user, organization=self.room_a1, role=role, is_active=False
        )

        for name, stale in (
            ("roleassignment", stale_role),
            ("courtroomassignment", stale_room),
        ):
            response = self.client.post(
                reverse(f"admin:organizations_{name}_change", args=[stale.pk]), {}
            )
            self.assertEqual(response.status_code, 302)

        current_role.refresh_from_db()
        current_room.refresh_from_db()
        self.assertTrue(current_role.is_active)
        self.assertTrue(current_room.is_active)

    def test_user_admin_shows_effective_actions(self):
        user = make_user()
        assign(user, self.room_a1, make_role("MAGISTRATE", [actions.SIGN, actions.REGISTER]))
        response = self.client.get(reverse("admin:users_user_change", args=[user.pk]))
        self.assertContains(response, "testing.register")
        self.assertContains(response, "Establishment A / Courtroom A1")


class CourtSeedTests(TestCase):
    """Levels, roles, actions and assignments load through the ``seed`` command."""

    FILES = {
        "1_orgs.toml": """
[seed]
model = "organizations.Organization"

[[rows]]
code = "SEED_EST"
organization_type = "magistrate_court"
name = "Seed establishment"
court_level = "ESTABLISHMENT"

[[rows]]
code = "SEED_EST_CR1"
organization_type = "magistrate_court"
name = "Courtroom 1"
parent = "SEED_EST"
court_level = "COURTROOM"
""",
        "2_roles.toml": """
[seed]
model = "organizations.CourtRole"

[[rows]]
code = "BENCH_CLERK"
name = "Bench clerk"

[[rows]]
code = "BENCH_CLERK"
name = "Bench clerk (seed court)"
establishment = "SEED_EST"
""",
        "3_actions.toml": """
[seed]
model = "organizations.CourtRoleAction"

[[rows]]
role = "BENCH_CLERK"
action = "testing.sign"

[[rows]]
role = "BENCH_CLERK"
action = "testing.process_sign"
scope = { process_types = ["SUMMONS"] }

[[rows]]
role = "BENCH_CLERK.SEED_EST"
action = "testing.edit"

[[rows]]
role = "BENCH_CLERK"
action = "sample.nobody_declares"
""",
        "4_list.toml": """
[seed]
model = "organizations.CourtroomAssignment"

[[rows]]
user = "+919100000001"
courtroom = "SEED_EST_CR1"
""",
        "5_assign.toml": """
[seed]
model = "organizations.RoleAssignment"

[[rows]]
user = "+919100000001"
organization = "SEED_EST_CR1"
role = "BENCH_CLERK.SEED_EST"
""",
    }

    def test_seed_and_reseed(self):
        user = make_user(mobile_number="+919100000001")
        with tempfile.TemporaryDirectory() as directory:
            for name, content in self.FILES.items():
                Path(directory, name).write_text(content, encoding="utf-8")
            out = StringIO()
            call_command("seed", directory, stdout=out)
            self.assertIn("created 9, unchanged 0, skipped 1", out.getvalue())
            out = StringIO()
            call_command("seed", directory, stdout=out)
            self.assertIn("created 0, unchanged 9, skipped 1", out.getvalue())

        deployment_wide = CourtRole.objects.get(code="BENCH_CLERK", establishment__isnull=True)
        self.assertEqual(
            sorted(deployment_wide.actions.values_list("action", flat=True)),
            ["testing.process_sign", "testing.sign"],
        )
        own = CourtRole.objects.get(code="BENCH_CLERK", establishment__code="SEED_EST")
        self.assertEqual(list(own.actions.values_list("action", flat=True)), ["testing.edit"])
        assignment = RoleAssignment.objects.get(user=user)
        self.assertEqual(assignment.role, own)
