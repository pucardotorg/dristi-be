"""Superusers become bar-ID approvers on local and test setups (issue #260)."""

import os
from io import StringIO
from types import SimpleNamespace
from unittest.mock import patch

import dramatiq
from django.apps import apps as global_apps
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.core.management.sql import emit_post_migrate_signal
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework import status

from apps.dristi_requests.exceptions import ApprovalRoutingError
from apps.dristi_requests.models import ApprovalStep, Request, RequestType
from apps.dristi_requests.services import candidate_approvers, resolve_approver
from apps.users.models import User
from apps.users.services.approvers import BAR_ID_APPROVER, seed_superuser_approvers
from apps.users.tasks import request_registration_verification
from apps.users.verification import ADVOCATE_REGISTRATION

from .base import MOBILE, OTPTestCase
from .test_api import IN_MEMORY_FILES, PASSWORD, pdf_upload

ADMIN_MOBILE = "+919800000100"
OTHER_MOBILE = "+919800000101"


def approvers():
    """Return the mobile numbers in BAR_ID_APPROVER."""
    return set(
        Group.objects.get(name=BAR_ID_APPROVER).user_set.values_list("mobile_number", flat=True)
    )


def delete_group():
    """Remove BAR_ID_APPROVER; its approval steps protect it, so they go first."""
    ApprovalStep.objects.filter(approver_group__name=BAR_ID_APPROVER).delete()
    Group.objects.filter(name=BAR_ID_APPROVER).delete()


def run_post_migrate_receiver(apps=global_apps):
    """Call the receiver the way ``migrate`` does."""
    seed_superuser_approvers(sender=None, apps=apps, using="default")


@override_settings(SEED_SUPERUSER_APPROVERS=True)
class SuperuserCreationTests(TestCase):
    """A superuser created after migrations is made an approver at once."""

    def test_create_superuser_joins_the_group(self):
        User.objects.create_superuser(mobile_number=ADMIN_MOBILE, password="x")
        self.assertEqual(approvers(), {ADMIN_MOBILE})

    def test_create_user_with_is_superuser_joins_the_group(self):
        """The hook sits under create_user too, not only create_superuser."""
        User.objects.create_user(mobile_number=ADMIN_MOBILE, is_staff=True, is_superuser=True)
        self.assertEqual(approvers(), {ADMIN_MOBILE})

    def test_regular_and_staff_users_do_not_join(self):
        User.objects.create_user(mobile_number=ADMIN_MOBILE)
        User.objects.create_user(mobile_number=OTHER_MOBILE, is_staff=True)
        self.assertEqual(approvers(), set())

    def test_group_is_created_if_missing(self):
        delete_group()
        User.objects.create_superuser(mobile_number=ADMIN_MOBILE)
        self.assertEqual(approvers(), {ADMIN_MOBILE})

    def test_createsuperuser_command_noinput(self):
        """The non-interactive command a setup script would run."""
        env = {
            "DJANGO_SUPERUSER_MOBILE_NUMBER": ADMIN_MOBILE,
            "DJANGO_SUPERUSER_NAME": "Admin",
            "DJANGO_SUPERUSER_PASSWORD": PASSWORD,
        }
        with patch.dict(os.environ, env):
            call_command("createsuperuser", "--noinput", stdout=StringIO())
        self.assertEqual(approvers(), {ADMIN_MOBILE})

    def test_inactive_superuser_joins_but_is_never_routed_to(self):
        """Membership follows the role; routing still skips inactive accounts."""
        admin = User.objects.create_superuser(mobile_number=ADMIN_MOBILE, is_active=False)
        self.assertEqual(approvers(), {ADMIN_MOBILE})

        step = RequestType.objects.get(code=ADVOCATE_REGISTRATION).approval_steps.get()
        request = SimpleNamespace(requester_id=None)
        self.assertNotIn(admin, candidate_approvers(step, request))

    @override_settings(SEED_SUPERUSER_APPROVERS=False)
    def test_disabled_adds_nobody(self):
        User.objects.create_superuser(mobile_number=ADMIN_MOBILE)
        User.objects.create_user(mobile_number=OTHER_MOBILE, is_superuser=True)
        self.assertEqual(approvers(), set())


@override_settings(SEED_SUPERUSER_APPROVERS=True)
class PostMigrateTests(TestCase):
    """Superusers that already exist when migrations run are made approvers."""

    def setUp(self):
        """Create the users while seeding is off, as if they predate the change."""
        with override_settings(SEED_SUPERUSER_APPROVERS=False):
            self.admin = User.objects.create_superuser(mobile_number=ADMIN_MOBILE)
            self.second_admin = User.objects.create_superuser(mobile_number=OTHER_MOBILE)
            self.user = User.objects.create_user(mobile_number=MOBILE)
        self.assertEqual(approvers(), set())

    def test_existing_superusers_join_and_others_do_not(self):
        run_post_migrate_receiver()
        self.assertEqual(approvers(), {ADMIN_MOBILE, OTHER_MOBILE})

    def test_running_again_changes_nothing(self):
        run_post_migrate_receiver()
        run_post_migrate_receiver()
        self.assertEqual(approvers(), {ADMIN_MOBILE, OTHER_MOBILE})
        self.assertEqual(Group.objects.filter(name=BAR_ID_APPROVER).count(), 1)

    def test_existing_members_are_kept(self):
        """Approvers added by hand stay; only superusers are added."""
        Group.objects.get(name=BAR_ID_APPROVER).user_set.add(self.user)
        run_post_migrate_receiver()
        self.assertEqual(approvers(), {MOBILE, ADMIN_MOBILE, OTHER_MOBILE})

    def test_group_is_created_if_missing(self):
        delete_group()
        run_post_migrate_receiver()
        self.assertEqual(approvers(), {ADMIN_MOBILE, OTHER_MOBILE})

    def test_missing_tables_in_migration_state_are_skipped(self):
        """After ``migrate users zero`` the state has no user model: do nothing."""

        def get_model(*args):
            raise LookupError

        delete_group()
        run_post_migrate_receiver(apps=SimpleNamespace(get_model=get_model))
        self.assertFalse(Group.objects.filter(name=BAR_ID_APPROVER).exists())

    @override_settings(SEED_SUPERUSER_APPROVERS=False)
    def test_disabled_adds_nobody(self):
        run_post_migrate_receiver()
        self.assertEqual(approvers(), set())

    def test_receiver_is_connected_to_post_migrate(self):
        """The users app's receiver answers post_migrate.

        Emitted without ``apps``, as ``flush`` (and so every transactional test)
        does: the receiver must not require it.
        """
        emit_post_migrate_signal(verbosity=0, interactive=False, db="default")
        self.assertEqual(approvers(), {ADMIN_MOBILE, OTHER_MOBILE})


@override_settings(STORAGES=IN_MEMORY_FILES, SEED_SUPERUSER_APPROVERS=True)
class FreshSetupRoutingTests(OTPTestCase):
    """On a fresh stack with only a superuser, a registration finds an approver."""

    def setUp(self):
        """Create only a superuser, then log in a new registrant."""
        super().setUp()
        self.admin = User.objects.create_superuser(mobile_number=ADMIN_MOBILE)
        self.broker = dramatiq.get_broker()
        self.broker.flush_all()
        self.create_account()

    def register_advocate(self):
        """Register the logged-in account as an advocate, running on-commit callbacks."""
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                reverse("advocate-create"),
                {
                    "name": "Asha Menon",
                    "password": PASSWORD,
                    "terms_accepted": True,
                    "profile.bar_registration_id": "KER/1234/2019",
                    "bar_id_document": pdf_upload(),
                },
                format="multipart",
            )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def run_queued_verification(self):
        """Run the verification message the registration queued, in-process."""
        queue = self.broker.queues[request_registration_verification.queue_name]
        (message,) = [dramatiq.Message.decode(data) for data in list(queue.queue)]
        request_registration_verification(*message.args)

    def test_advocate_registration_is_routed_to_the_superuser(self):
        self.register_advocate()
        self.run_queued_verification()

        request = Request.objects.get()
        self.assertEqual(request.request_type.code, ADVOCATE_REGISTRATION)
        self.assertEqual(request.current_approval.approver, self.admin)

    def test_superuser_never_approves_their_own_request(self):
        """The requester is excluded, so a lone superuser cannot route to itself."""
        step = RequestType.objects.get(code=ADVOCATE_REGISTRATION).approval_steps.get()
        request = SimpleNamespace(requester_id=self.admin.pk, request_type=step.request_type)
        with self.assertRaises(ApprovalRoutingError):
            resolve_approver(step, request)

    @override_settings(SEED_SUPERUSER_APPROVERS=False)
    def test_without_seeding_registration_has_no_approver(self):
        """The gap the issue describes, reproduced with seeding off."""
        Group.objects.get(name=BAR_ID_APPROVER).user_set.clear()
        self.register_advocate()
        with self.assertRaises(ApprovalRoutingError):
            self.run_queued_verification()
        self.assertFalse(Request.objects.exists())
