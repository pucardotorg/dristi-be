"""A rejected registration: told why, corrected, and resubmitted as the same application."""

from unittest.mock import patch

import dramatiq
from django.contrib.auth.models import Group
from django.test import override_settings
from django.urls import reverse
from rest_framework import status

from apps.dristi_requests.models import Request, RequestApproval
from apps.dristi_requests.services import decide
from apps.files.models import File
from apps.users import errors
from apps.users.models import AdvocateProfile, ApprovalStatus, ClerkProfile, Role, User
from apps.users.services.registration import RegistrationNotRejected
from apps.users.tasks import request_registration_verification

from .base import MOBILE, PASSWORD, OTPTestCase
from .test_api import IN_MEMORY_FILES, pdf_upload

APPROVER_MOBILE = "+919800000001"
OTHER_MOBILE = "+919800000002"
REASON = "The name does not match the Bar Council record, and the ID scan is unreadable."


@override_settings(STORAGES=IN_MEMORY_FILES, ROOT_URLCONF="apps.users.tests.test_api")
class RejectionTestCase(OTPTestCase):
    """Registers an advocate, raises their verification request, and rejects it."""

    def setUp(self):
        """Give the approver group a member and start from an empty broker."""
        super().setUp()
        self.approver = User.objects.create_user(mobile_number=APPROVER_MOBILE)
        Group.objects.get(name="BAR_ID_APPROVER").user_set.add(self.approver)
        dramatiq.get_broker().flush_all()

    def register(self, role=Role.ADVOCATE, document=True, mobile_number=MOBILE, number=None):
        """Register through the API and raise the verification request in-process."""
        self.create_account(mobile_number)
        if role == Role.ADVOCATE:
            url = reverse("advocate-create")
            profile = {"profile.bar_registration_id": number or "K/1742/2019"}
        else:
            url = reverse("clerk-create")
            profile = {"profile.clerk_registration_number": number or "CLK/99/2020"}
        body = {
            "name": "Sreelakshmi Menonn",
            "email": f"{mobile_number[-4:]}@example.com",
            "password": PASSWORD,
            "terms_accepted": True,
            **profile,
        }
        if document:
            body["bar_id_document"] = pdf_upload("first-scan.pdf")
        response = self.client.post(url, body, format="multipart")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.content)

        user = User.objects.get(mobile_number=mobile_number)
        file_id = File.objects.filter(user=user).values_list("pk", flat=True).first()
        request_registration_verification(str(user.pk), str(file_id) if file_id else None)
        return user

    def request_of(self, user):
        """Return the user's verification request, fresh from the database."""
        return Request.objects.get(requester=user)

    def reject(self, user, reason=REASON):
        """Reject the current round as the approver, running on-commit callbacks."""
        with self.captureOnCommitCallbacks(execute=True):
            decide(self.request_of(user).current_approval, "rejected", self.approver, reason)

    def sign_in(self, mobile_number=MOBILE):
        """Log in with the password, as the rejection SMS asks."""
        self.client.logout()
        return self.client.post(
            reverse("session"),
            {"mobile_number": mobile_number, "password": PASSWORD},
            format="json",
        )

    def resubmit(self, **overrides):
        """Post a corrected registration, running on-commit callbacks."""
        body = {
            "name": "Sreelakshmi Menon",
            "email": "sreelakshmi@example.com",
            "registration_number": "K/1742/2019",
            "bar_id_document": pdf_upload("clear-scan.pdf"),
            **overrides,
        }
        body = {key: value for key, value in body.items() if value is not None}
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post(reverse("registration-resubmit"), body, format="multipart")


class RejectionTests(RejectionTestCase):
    """What the approver's rejection changes."""

    def test_rejection_marks_the_profile_rejected(self):
        """Attributed to the approver who rejected it."""
        user = self.register()
        self.reject(user)

        profile = AdvocateProfile.objects.get(user=user)
        self.assertEqual(profile.approval_status, ApprovalStatus.REJECTED)
        self.assertEqual(profile.updated_by, self.approver)


class RejectedSignInTests(RejectionTestCase):
    """POST /sessions for a rejected registrant."""

    def test_rejected_advocate_signs_in_and_is_sent_to_resubmit(self):
        """A session, and a body that routes the client to the correction screens."""
        user = self.register()
        self.reject(user)

        response = self.sign_in()

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.json()
        self.assertEqual(body["approval_status"], ApprovalStatus.REJECTED)
        self.assertEqual(body["next"], "resubmit")
        self.assertEqual(self.client.session["_auth_user_id"], str(user.pk))

    def test_rejected_session_reaches_nothing_else(self):
        """The default gate keeps a rejected registrant to the resubmission endpoints."""
        user = self.register()
        self.reject(user)
        self.sign_in()

        response = self.client.get(reverse("gated-probe"))

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class CurrentRegistrationTests(RejectionTestCase):
    """GET /registrations/current/."""

    def test_shows_the_reason_and_the_claim_as_submitted(self):
        """Everything the correction screens show, to pre-fill the steps."""
        user = self.register()
        self.reject(user)
        self.sign_in()

        response = self.client.get(reverse("registration-current"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.json()
        request = self.request_of(user)
        self.assertEqual(body["application_id"], str(request.pk))
        self.assertEqual(body["approval_status"], ApprovalStatus.REJECTED)
        self.assertEqual(body["role"], Role.ADVOCATE)
        self.assertEqual(body["officer_message"], REASON)
        self.assertIsNotNone(body["rejected_at"])
        self.assertEqual(body["name"], "Sreelakshmi Menonn")
        self.assertEqual(body["email"], f"{MOBILE[-4:]}@example.com")
        self.assertEqual(body["mobile_number"], MOBILE)
        self.assertEqual(body["registration_number"], "K/1742/2019")
        self.assertEqual(body["document"]["file_name"], "first-scan.pdf")

    def test_shows_only_the_latest_rounds_reason(self):
        """After a second rejection, the second reason is the one to act on."""
        user = self.register()
        self.reject(user, reason="First reason.")
        self.sign_in()
        self.resubmit()
        self.reject(user, reason="Second reason.")
        self.sign_in()

        response = self.client.get(reverse("registration-current"))

        self.assertEqual(response.json()["officer_message"], "Second reason.")

    def test_refused_to_anyone_not_rejected(self):
        """A pending, accepted or litigant account has nothing to correct."""
        user = self.register()
        decide(self.request_of(user).current_approval, "approved", self.approver)
        self.sign_in()

        response = self.client.get(reverse("registration-current"))

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_registration_gone_since_the_permission_check_is_a_409(self):
        """A rejection undone after the permission passed has nothing to show."""
        user = self.register()
        self.reject(user)
        self.sign_in()

        with patch(
            "apps.users.views.describe_rejected_registration",
            side_effect=RegistrationNotRejected,
        ):
            response = self.client.get(reverse("registration-current"))

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        [error] = response.json()["errors"]
        self.assertEqual(error["code"], errors.NOTHING_TO_RESUBMIT.code)


class ResubmissionTests(RejectionTestCase):
    """POST /registrations/current/resubmit/."""

    def setUp(self):
        """Register, reject and sign back in, as the SMS asks."""
        super().setUp()
        self.user = self.register()
        self.reject(self.user)
        self.sign_in()
        self.original = self.request_of(self.user)

    def test_resubmits_the_same_application(self):
        """No new request: the same row goes back for approval in a new round."""
        response = self.resubmit()

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        body = response.json()
        self.assertEqual(body["application_id"], str(self.original.pk))
        self.assertEqual(body["approval_status"], ApprovalStatus.PENDING)
        self.assertEqual(Request.objects.filter(requester=self.user).count(), 1)
        request = self.request_of(self.user)
        self.assertEqual(request.version, 2)
        self.assertEqual(request.status, Request.Status.PENDING)
        self.assertEqual(
            request.data, {"name": "Sreelakshmi Menon", "bar_registration_id": "K/1742/2019"}
        )
        self.assertEqual(request.current_approval.approver, self.approver)
        self.assertEqual(request.current_approval.version, 2)

    def test_applies_the_corrections_and_waits_for_approval(self):
        """The account and profile take the corrections; the profile is PENDING again."""
        self.resubmit(registration_number="K/1743/2019")

        self.user.refresh_from_db()
        profile = AdvocateProfile.objects.get(user=self.user)
        self.assertEqual(self.user.name, "Sreelakshmi Menon")
        self.assertEqual(self.user.email, "sreelakshmi@example.com")
        self.assertEqual(profile.name, "Sreelakshmi Menon")
        self.assertEqual(profile.bar_registration_id, "K/1743/2019")
        self.assertEqual(profile.approval_status, ApprovalStatus.PENDING)

    def test_replaces_the_document_and_keeps_the_old_file(self):
        """The approver sees the new scan; the old one stays in the files store."""
        old_file_id = self.original.documents.get().file_id

        self.resubmit()

        document = self.request_of(self.user).documents.get()
        self.assertNotEqual(document.file_id, old_file_id)
        self.assertEqual(document.filename, "clear-scan.pdf")
        self.assertTrue(File.objects.filter(pk=old_file_id).exists())

    def test_ends_the_session(self):
        """A pending account holds no session, so the resubmission signs them out."""
        self.resubmit()

        self.assertNotIn("_auth_user_id", self.client.session)
        response = self.client.get(reverse("registration-current"))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_resubmitting_twice_is_refused(self):
        """Once resubmitted, the registration is no longer rejected."""
        self.resubmit()
        self.client.force_authenticate(self.user)

        response = self.resubmit()

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(self.request_of(self.user).version, 2)

    def test_advocate_must_send_the_document(self):
        """The bar ID is required of an advocate, as at registration."""
        response = self.resubmit(bar_id_document=None)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            [{"code": e["code"], "field": e.get("field")} for e in response.json()["errors"]],
            [{"code": "E00002", "field": "bar_id_document"}],
        )
        self.assertEqual(self.request_of(self.user).status, Request.Status.REJECTED)

    def test_registration_number_held_by_another_advocate_is_refused(self):
        """The number stays unique across advocates."""
        self.client.logout()
        self.register(mobile_number=OTHER_MOBILE, number="K/2000/2020")
        self.sign_in()

        response = self.resubmit(registration_number="K/2000/2020")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            [{"code": e["code"], "field": e.get("field")} for e in response.json()["errors"]],
            [{"code": "E00010", "field": "registration_number"}],
        )

    def test_email_held_by_another_account_is_refused(self):
        """The email stays unique across accounts."""
        User.objects.create_user(mobile_number=OTHER_MOBILE, email="taken@example.com")

        response = self.resubmit(email="taken@example.com")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        [error] = response.json()["errors"]
        self.assertEqual(error["code"], errors.EMAIL_TAKEN.code)
        self.assertEqual(error["field"], "email")

    def test_resubmission_can_be_approved(self):
        """Approving the corrected round accepts the advocate."""
        self.resubmit()

        approval = self.request_of(self.user).current_approval
        decide(approval, RequestApproval.Status.APPROVED, self.approver)

        profile = AdvocateProfile.objects.get(user=self.user)
        self.assertEqual(profile.approval_status, ApprovalStatus.ACCEPTED)
        self.assertEqual(self.sign_in().status_code, status.HTTP_200_OK)


class ClerkResubmissionTests(RejectionTestCase):
    """A clerk's bar ID is optional on resubmission, as at registration."""

    def test_clerk_resubmits_without_a_document_and_keeps_the_old_one(self):
        """Left out, the document already on the request stays."""
        user = self.register(role=Role.CLERK)
        old_file_id = self.request_of(user).documents.get().file_id
        self.reject(user)
        self.sign_in()

        response = self.resubmit(registration_number="CLK/100/2020", bar_id_document=None)

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        request = self.request_of(user)
        self.assertEqual(request.version, 2)
        self.assertEqual(
            request.data, {"name": "Sreelakshmi Menon", "clerk_registration_number": "CLK/100/2020"}
        )
        self.assertEqual(list(request.documents.values_list("file_id", flat=True)), [old_file_id])
        self.assertEqual(
            ClerkProfile.objects.get(user=user).approval_status, ApprovalStatus.PENDING
        )
