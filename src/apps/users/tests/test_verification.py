"""Registration verification: queued after registration, raised in the background."""

import dramatiq
from django.contrib.auth.models import Group
from django.test import override_settings
from django.urls import reverse
from rest_framework import status

from apps.dristi_requests.exceptions import ApprovalRoutingError
from apps.dristi_requests.models import Request, RequestApproval
from apps.dristi_requests.services import decide
from apps.files.models import File
from apps.users.models import (
    AdvocateProfile,
    ApprovalStatus,
    User,
)
from apps.users.tasks import request_registration_verification
from apps.users.verification import ADVOCATE_REGISTRATION, CLERK_REGISTRATION

from .base import MOBILE, OTPTestCase
from .test_api import IN_MEMORY_FILES, PASSWORD, pdf_upload

APPROVER_MOBILE = "+919800000001"


@override_settings(STORAGES=IN_MEMORY_FILES)
class RegistrationVerificationTests(OTPTestCase):
    """POST /advocates and /clerks raise a verification request asynchronously."""

    def setUp(self):
        """Log in an account at PENDING_PROFILE, and give the approver group a member."""
        super().setUp()
        self.approver = User.objects.create_user(mobile_number=APPROVER_MOBILE)
        Group.objects.get(name="BAR_ID_APPROVER").user_set.add(self.approver)

        self.create_account()
        self.user = User.objects.get(mobile_number=MOBILE)

        self.broker = dramatiq.get_broker()
        self.broker.flush_all()

    def body(self, **extra):
        """Return the common part of a registration body."""
        return {"name": "Asha Menon", "password": PASSWORD, "terms_accepted": True, **extra}

    def register_advocate(self):
        """Register as an advocate with a bar ID, running on-commit callbacks."""
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                reverse("advocate-create"),
                self.body(
                    **{"profile.bar_registration_id": "KER/1234/2019"},
                    bar_id_document=pdf_upload(),
                ),
                format="multipart",
            )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        return response

    def queued(self):
        """Return the messages waiting on the actor's queue in the stub broker."""
        queue = self.broker.queues[request_registration_verification.queue_name]
        return [dramatiq.Message.decode(data) for data in list(queue.queue)]

    def test_advocate_registration_queues_verification(self):
        """The message carries the user and the bar ID already stored."""
        self.register_advocate()

        (message,) = self.queued()
        self.assertEqual(message.actor_name, request_registration_verification.actor_name)
        self.assertEqual(message.args, (str(self.user.pk), str(File.objects.get().pk)))
        # Queued, not run: nothing is raised during the request itself.
        self.assertFalse(Request.objects.exists())

    def run_queued_verification(self):
        """Run the queued message's actor in-process."""
        (message,) = self.queued()
        request_registration_verification(*message.args)

    def test_actor_raises_the_request_with_the_stored_bar_id(self):
        """The request links the registration's file rather than uploading again."""
        self.register_advocate()
        self.run_queued_verification()

        request = Request.objects.get()
        self.assertEqual(request.request_type.code, ADVOCATE_REGISTRATION)
        self.assertEqual(request.requester, self.user)
        self.assertEqual(request.status, Request.Status.PENDING)
        self.assertEqual(
            request.data, {"name": "Asha Menon", "bar_registration_id": "KER/1234/2019"}
        )
        self.assertEqual(
            list(request.documents.values_list("file_id", flat=True)),
            [File.objects.get().pk],
        )
        self.assertEqual(File.objects.count(), 1)
        self.assertEqual(request.current_approval.approver, self.approver)

    def test_actor_is_idempotent(self):
        """A redelivered message does not raise a second request."""
        self.register_advocate()
        self.run_queued_verification()
        self.run_queued_verification()
        self.assertEqual(Request.objects.count(), 1)

    def test_clerk_request_has_no_document(self):
        """A clerk who sent no bar ID is verified on the number alone."""
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(
                reverse("clerk-create"),
                self.body(profile={"clerk_registration_number": "CLK/99/2020"}),
                format="json",
            )
        self.run_queued_verification()

        request = Request.objects.get()
        self.assertEqual(request.request_type.code, CLERK_REGISTRATION)
        self.assertFalse(request.documents.exists())

    def test_actor_failure_leaves_nothing_half_raised(self):
        """With no approver to route to, the attempt rolls back for a retry.

        The registration's file is kept: it belongs to the registration, and
        the retry links it again.
        """
        self.register_advocate()
        self.approver.groups.clear()

        with self.assertRaises(ApprovalRoutingError):
            self.run_queued_verification()

        self.assertFalse(Request.objects.exists())
        self.assertEqual(File.objects.count(), 1)

    def test_approval_accepts_the_advocate(self):
        """Approving the request is what moves the profile to ACCEPTED."""
        self.register_advocate()
        self.run_queued_verification()

        approval = Request.objects.get().current_approval
        decide(approval, RequestApproval.Status.APPROVED, self.approver)

        profile = AdvocateProfile.objects.get(user=self.user)
        self.assertEqual(profile.approval_status, ApprovalStatus.ACCEPTED)
        # Attributed to the approver, not left on the registrant.
        self.assertEqual(profile.updated_by, self.approver)
