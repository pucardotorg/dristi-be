"""Endpoint tests for registration and login (spec 0005 section 4)."""

from unittest.mock import patch

from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import path, reverse
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.files.models import File, FileType
from apps.users.documents import BAR_COUNCIL_ID_TAG
from apps.users.models import (
    AdvocateProfile,
    AdvocateType,
    ApprovalStatus,
    ClerkProfile,
    LitigantProfile,
    RegistrationStatus,
    Role,
    User,
)
from apps.users.serializers import MAX_PASSWORD_LENGTH
from apps.users.services.otp import Purpose
from config.urls import urlpatterns as project_urlpatterns

from .base import MOBILE, PASSWORD, OTPTestCase

# Sentinel for "use the default document", so None can mean "send none".
MISSING = object()

PDF_CONTENT = b"%PDF-1.4\n%test bar council id\n"

# Keep uploaded documents in memory so tests never touch the filesystem.
IN_MEMORY_FILES = {
    **settings.STORAGES,
    "files": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
}


def pdf_upload(name="bar-id.pdf", content=PDF_CONTENT, content_type="application/pdf"):
    """Return a fresh upload; an upload is consumed by the request it is sent in."""
    return SimpleUploadedFile(name, content, content_type=content_type)


class OTPRequestTests(OTPTestCase):
    """POST /auth/otp/request."""

    def test_code_is_sent(self):
        """A first request sends a code of the configured length."""
        code = self.request_code()
        self.assertEqual(len(code), 6)
        self.assertTrue(code.isdigit())

    def test_response_does_not_reveal_account_existence(self):
        """The body is identical whether or not the number has an account."""
        User.objects.create_user(mobile_number=MOBILE)
        with patch("apps.users.services.otp._send_sms"):
            known = self.client.post(
                reverse("otp-request"), {"mobile_number": MOBILE}, format="json"
            )
        cache.clear()
        with patch("apps.users.services.otp._send_sms"):
            unknown = self.client.post(
                reverse("otp-request"), {"mobile_number": "+919000000000"}, format="json"
            )
        # Compare the payload only: the renderer stamps a `meta.timestamp` that
        # differs between any two responses and reveals nothing.
        self.assertEqual(known.json()["detail"], unknown.json()["detail"])
        self.assertEqual(known.status_code, unknown.status_code)

    def test_resend_inside_cooldown_is_refused(self):
        """A second request inside the window returns 429 with Retry-After."""
        self.request_code()
        with patch("apps.users.services.otp._send_sms") as send:
            response = self.client.post(
                reverse("otp-request"), {"mobile_number": MOBILE}, format="json"
            )
        self.assertEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        self.assertIn("Retry-After", response)
        self.assertGreaterEqual(int(response["Retry-After"]), 1)
        send.assert_not_called()

        # The message names what was throttled and what to do about it.
        detail = response.json()["detail"]
        self.assertIn("A code was already sent", detail)
        self.assertIn("You can request another in", detail)
        self.assertNotIn("Request was throttled", detail)

    def test_cooldown_is_per_number(self):
        """A cooldown on one number does not block another."""
        self.request_code()
        with patch("apps.users.services.otp._send_sms") as send:
            response = self.client.post(
                reverse("otp-request"), {"mobile_number": "+919000000000"}, format="json"
            )
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        send.assert_called_once()

    @override_settings(OTP_RESEND_COOLDOWN_SECONDS=900)
    def test_cooldown_is_read_from_settings_per_request(self):
        """Changing the setting changes the window without a code change."""
        self.request_code()
        response = self.client.post(
            reverse("otp-request"), {"mobile_number": MOBILE}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        self.assertGreater(int(response["Retry-After"]), 800)

    def test_malformed_number_is_rejected(self):
        """A number that is not in international format is refused."""
        response = self.client.post(
            reverse("otp-request"), {"mobile_number": "9876543210"}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class MobileNumberFormatTests(OTPTestCase):
    """Only Indian mobile numbers are accepted, on every endpoint that takes one."""

    # Each case is structurally valid E.164 but not an Indian mobile number, so
    # these are exactly the inputs the old country-agnostic pattern let through.
    NON_INDIAN = {
        "foreign_country_code": "+998639167",
        "india_landline_leading_digit": "+912212345678",
        "india_too_few_digits": "+9198765432",
        "india_too_many_digits": "+91987654321012",
        "leading_zero_after_country_code": "+910987654321",
        "missing_plus": "919876543210",
    }

    def test_non_indian_numbers_are_rejected_on_otp_request(self):
        """POST /auth/otp/request refuses anything outside +91 mobile ranges."""
        for label, number in self.NON_INDIAN.items():
            with self.subTest(label):
                response = self.client.post(
                    reverse("otp-request"), {"mobile_number": number}, format="json"
                )
                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
                self.assertIn("mobile_number", response.json())

    def test_non_indian_numbers_are_rejected_on_user_create(self):
        """POST /users refuses the same set, before the OTP is even consulted."""
        for label, number in self.NON_INDIAN.items():
            with self.subTest(label):
                response = self.client.post(
                    reverse("user-create"),
                    {"mobile_number": number, "otp": "123456"},
                    format="json",
                )
                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
                self.assertIn("mobile_number", response.json())

    def test_indian_mobile_ranges_are_accepted(self):
        """India allocates mobile numbers on leading digits 6 through 9."""
        for leading in "6789":
            number = f"+91{leading}000000000"
            with self.subTest(number):
                response = self.client.post(
                    reverse("otp-request"), {"mobile_number": number}, format="json"
                )
                self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)


class UserCreateTests(OTPTestCase):
    """POST /users."""

    def test_new_account_is_created(self):
        """A valid code creates the account and issues a cookie."""
        response = self.create_account()
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        body = response.json()
        self.assert_meta(body)
        self.assertEqual(body["registration_status"], RegistrationStatus.PENDING_PROFILE)
        self.assertEqual(body["next"], "profile")
        self.assertIn("sessionid", response.cookies)

        user = User.objects.get(mobile_number=MOBILE)
        self.assertFalse(user.has_usable_password())

    def test_invalid_code_is_rejected(self):
        """A wrong code creates nothing."""
        self.request_code()
        response = self.client.post(
            reverse("user-create"),
            {"mobile_number": MOBILE, "otp": "000000"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertFalse(User.objects.filter(mobile_number=MOBILE).exists())

    def test_abandoned_registration_is_resumable(self):
        """A second run against an incomplete account resumes it with a 200."""
        self.create_account()
        self.client.logout()

        # The user comes back later, so the resend cooldown has lapsed.
        cache.clear()

        response = self.create_account()
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(User.objects.filter(mobile_number=MOBILE).count(), 1)

    def test_complete_account_is_refused(self):
        """A finished account is told to use POST /sessions."""
        User.objects.create_user(
            mobile_number=MOBILE,
            registration_status=RegistrationStatus.COMPLETE,
        )
        response = self.create_account()
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)

    def test_otp_is_never_echoed(self):
        """The response body contains no trace of the credential."""
        code = self.request_code()
        response = self.client.post(
            reverse("user-create"),
            {"mobile_number": MOBILE, "otp": code},
            format="json",
        )
        self.assertNotIn(code, response.content.decode())


@override_settings(STORAGES=IN_MEMORY_FILES)
class RegistrationCompletionTests(OTPTestCase):
    """POST /litigants, /advocates and /clerks."""

    def setUp(self):
        """Create an account sitting at PENDING_PROFILE, already logged in."""
        super().setUp()
        self.create_account()
        self.user = User.objects.get(mobile_number=MOBILE)

    def body(self, **extra):
        """Return a valid completion body."""
        return {
            "name": "Asha Menon",
            "email": "asha@example.com",
            "password": PASSWORD,
            "terms_accepted": True,
            **extra,
        }

    def post_advocate(self, profile=None, document=MISSING, **extra):
        """POST /advocates as multipart, with a valid bar ID unless overridden.

        A multipart body cannot nest, so the profile goes as `profile.<field>`
        keys, which is what a client sends too.
        """
        data = self.body(**extra)
        for key, value in (profile or {}).items():
            data[f"profile.{key}"] = value
        if document is MISSING:
            document = pdf_upload()
        if document is not None:
            data["bar_id_document"] = document
        return self.client.post(reverse("advocate-create"), data, format="multipart")

    def test_litigant_completes(self):
        """A litigant gets a profile, a role and COMPLETE status."""
        response = self.client.post(reverse("litigant-create"), self.body(), format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        self.user.refresh_from_db()
        self.assertEqual(self.user.registration_status, RegistrationStatus.COMPLETE)
        self.assertEqual(self.user.role, Role.LITIGANT)
        self.assertTrue(self.user.check_password(PASSWORD))
        self.assertTrue(LitigantProfile.objects.filter(user=self.user).exists())

    def test_registration_attributes_the_account_and_profile_to_the_registrant(self):
        """The registrant is the actor, so the rows are not left unattributed."""
        response = self.client.post(reverse("litigant-create"), self.body(), format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        self.user.refresh_from_db()
        self.assertEqual(self.user.created_by, self.user)
        self.assertEqual(self.user.updated_by, self.user)

        profile = LitigantProfile.objects.get(user=self.user)
        self.assertEqual(profile.created_by, self.user)
        self.assertEqual(profile.updated_by, self.user)

    def test_advocate_completes_with_profile(self):
        """The nested profile is written to the advocate table."""
        response = self.post_advocate(profile={"bar_registration_id": "KER/1234/2019"})
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        profile = AdvocateProfile.objects.get(user=self.user)
        self.assertEqual(profile.bar_registration_id, "KER/1234/2019")
        # Omitted rather than defaulted: no practice area was stated.
        self.assertIsNone(profile.advocate_type)
        self.assertEqual(profile.approval_status, ApprovalStatus.PENDING)

    def test_advocate_can_state_a_practice_area(self):
        """advocate_type is optional, and is stored when supplied."""
        response = self.post_advocate(
            profile={
                "bar_registration_id": "KER/5678/2021",
                "advocate_type": AdvocateType.CRIMINAL,
            }
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(
            AdvocateProfile.objects.get(user=self.user).advocate_type,
            AdvocateType.CRIMINAL,
        )

    def test_unknown_practice_area_is_rejected(self):
        """Only the declared choices are accepted."""
        response = self.post_advocate(
            profile={
                "bar_registration_id": "KER/9999/2021",
                "advocate_type": "TAX",
            }
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(AdvocateProfile.objects.exists())
        self.assertFalse(File.objects.exists())

    def test_overlong_password_is_rejected_before_hashing(self):
        """A password past the cap is a 400, not work for the hasher."""
        response = self.client.post(
            reverse("litigant-create"),
            self.body(password="x" * (MAX_PASSWORD_LENGTH + 1)),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("password", response.data)
        self.user.refresh_from_db()
        self.assertEqual(self.user.registration_status, RegistrationStatus.PENDING_PROFILE)

    def test_password_similar_to_the_submitted_name_is_rejected(self):
        """The name in this request counts, though it is not yet on the row.

        UserAttributeSimilarityValidator only sees what it is handed, and the
        account holds no name until registration completes.
        """
        response = self.client.post(
            reverse("litigant-create"),
            self.body(name="Asha Menon", password="asha menon"),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("password", response.data)

    def test_password_similar_to_the_submitted_email_is_rejected(self):
        """Likewise the email, which is also only in the request body."""
        response = self.client.post(
            reverse("litigant-create"),
            self.body(email="ashamenon@example.com", password="ashamenon"),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("password", response.data)

    def test_password_similar_to_the_mobile_number_is_rejected(self):
        """The mobile number is on the row, but is not in Django's default list.

        Given a trailing letter so NumericPasswordValidator has nothing to say
        and only the similarity check can be what rejects this.
        """
        response = self.client.post(
            reverse("litigant-create"),
            self.body(password=MOBILE.lstrip("+") + "x"),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("password", response.data)

    def test_password_at_the_cap_is_accepted(self):
        """The cap is inclusive, so a password of exactly that length works."""
        response = self.client.post(
            reverse("litigant-create"),
            self.body(password="x" * MAX_PASSWORD_LENGTH),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def register_second_account(self, mobile_number="+919812345678"):
        """Register a second account and leave it logged in at PENDING_PROFILE."""
        self.client.logout()
        self.create_account(mobile_number)

    def test_duplicate_bar_registration_id_is_rejected(self):
        """A bar ID already claimed answers 400, not the database's 500.

        The uniqueness is on the column, so without a model-aware serializer
        the duplicate reaches Postgres and surfaces as a server error.
        """
        self.post_advocate(profile={"bar_registration_id": "KER/1234/2019"})
        self.register_second_account()

        response = self.post_advocate(
            email="other@example.com", profile={"bar_registration_id": "KER/1234/2019"}
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("bar_registration_id", response.data["profile"])
        self.assertEqual(AdvocateProfile.objects.count(), 1)
        # Rejected before the upload, so only the first advocate's file exists.
        self.assertEqual(File.objects.count(), 1)

    def test_duplicate_clerk_registration_number_is_rejected(self):
        """A clerk number already claimed answers 400, not 500."""
        self.client.post(
            reverse("clerk-create"),
            self.body(profile={"clerk_registration_number": "CLK/99/2020"}),
            format="json",
        )
        self.register_second_account()

        response = self.client.post(
            reverse("clerk-create"),
            self.body(
                email="other@example.com",
                profile={"clerk_registration_number": "CLK/99/2020"},
            ),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("clerk_registration_number", response.data["profile"])
        self.assertEqual(ClerkProfile.objects.count(), 1)

    def test_clerk_completes_with_profile(self):
        """The nested profile is written to the clerk table."""
        response = self.client.post(
            reverse("clerk-create"),
            self.body(profile={"clerk_registration_number": "CLK/99/2020"}),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(
            ClerkProfile.objects.get(user=self.user).clerk_registration_number,
            "CLK/99/2020",
        )

    def test_advocate_requires_profile(self):
        """A missing profile block is a 400, and nothing is written."""
        response = self.post_advocate()
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(File.objects.exists())

        self.user.refresh_from_db()
        self.assertEqual(self.user.registration_status, RegistrationStatus.PENDING_PROFILE)

    def test_advocate_bar_id_is_stored_against_the_registrant(self):
        """The bar ID lands in the files module, owned and tagged."""
        response = self.post_advocate(profile={"bar_registration_id": "KER/1234/2019"})
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        stored = File.objects.get()
        self.assertEqual(stored.user, self.user)
        self.assertEqual(stored.file_type, FileType.PDF)
        self.assertEqual(stored.file_name, "bar-id.pdf")
        self.assertEqual(list(stored.tags.values_list("name", flat=True)), [BAR_COUNCIL_ID_TAG])

    def test_advocate_requires_bar_id(self):
        """An advocate without the document is a 400, and nothing is written."""
        response = self.post_advocate(
            profile={"bar_registration_id": "KER/1234/2019"}, document=None
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("bar_id_document", response.data)
        self.assertFalse(AdvocateProfile.objects.exists())

        self.user.refresh_from_db()
        self.assertEqual(self.user.registration_status, RegistrationStatus.PENDING_PROFILE)

    def assert_document_rejected(self, document):
        """POST the document and assert it is refused before anything is stored."""
        response = self.post_advocate(
            profile={"bar_registration_id": "KER/1234/2019"}, document=document
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("bar_id_document", response.data)
        self.assertFalse(File.objects.exists())
        self.assertFalse(AdvocateProfile.objects.exists())

    def test_unsupported_document_type_is_rejected(self):
        """Only PDF, JPEG and PNG are accepted."""
        self.assert_document_rejected(pdf_upload("bar-id.txt", b"hello", "text/plain"))

    def test_document_refused_by_the_files_module_is_a_400(self):
        """A refusal from apps.files is reported on the field, not as a 500."""
        refusal = DjangoValidationError({"files[0].file": "refused by the files module."})
        with patch("apps.files.services.upload_file", side_effect=refusal):
            self.assert_document_rejected(pdf_upload())

    def test_terms_must_be_accepted(self):
        """A false acceptance rejects the registration rather than warning."""
        response = self.client.post(
            reverse("litigant-create"), self.body(terms_accepted=False), format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        self.user.refresh_from_db()
        self.assertEqual(self.user.registration_status, RegistrationStatus.PENDING_PROFILE)

    @override_settings(CURRENT_TERMS_VERSION=7)
    def test_terms_version_comes_from_the_server(self):
        """A client-supplied version is ignored in favour of server config."""
        response = self.client.post(
            reverse("litigant-create"), self.body(terms_version=999), format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        self.user.refresh_from_db()
        self.assertEqual(self.user.terms_version_accepted, 7)
        self.assertIsNotNone(self.user.terms_accepted_at)

    def test_completing_twice_is_refused(self):
        """A finished registration cannot be overwritten."""
        self.client.post(reverse("litigant-create"), self.body(), format="json")
        response = self.client.post(reverse("litigant-create"), self.body(), format="json")
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)

    def test_session_survives_the_password_being_set(self):
        """The user is still logged in immediately after completing."""
        self.client.post(reverse("litigant-create"), self.body(), format="json")
        response = self.client.post(reverse("litigant-create"), self.body(), format="json")
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)  # not 403

    def test_anonymous_caller_is_refused(self):
        """Completion requires the session issued by POST /users."""
        self.client.logout()
        response = self.client.post(reverse("litigant-create"), self.body(), format="json")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class SessionTests(OTPTestCase):
    """POST /sessions."""

    def setUp(self):
        """Create a fully registered account."""
        super().setUp()
        self.user = User.objects.create_user(
            mobile_number=MOBILE,
            password=PASSWORD,
            name="Asha Menon",
            role=Role.LITIGANT,
            registration_status=RegistrationStatus.COMPLETE,
        )
        self.client.logout()

    def test_login_with_password(self):
        """Mobile plus password issues a session."""
        response = self.client.post(
            reverse("session"),
            {"mobile_number": MOBILE, "password": PASSWORD},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["registration_status"], RegistrationStatus.COMPLETE)
        self.assertIsNone(response.json()["next"])

    def test_login_with_otp(self):
        """Mobile plus a login-purpose code issues a session."""
        code = self.request_code(purpose=Purpose.LOGIN)
        response = self.client.post(
            reverse("session"),
            {"mobile_number": MOBILE, "otp": code},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_wrong_password_is_refused(self):
        """A bad password issues nothing."""
        response = self.client.post(
            reverse("session"),
            {"mobile_number": MOBILE, "password": "wrong-password"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_overlong_password_is_refused_without_hashing(self):
        """Login caps the password too, so the hasher is never handed the string.

        A 400 rather than the usual 401: the request is malformed, and it is
        turned away while parsing, before `authenticate` is reached.
        """
        with patch("apps.users.views.authenticate") as authenticate:
            response = self.client.post(
                reverse("session"),
                {"mobile_number": MOBILE, "password": "x" * (MAX_PASSWORD_LENGTH + 1)},
                format="json",
            )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        authenticate.assert_not_called()

    def test_exactly_one_credential_is_required(self):
        """Neither zero credentials nor both are accepted."""
        for body in (
            {"mobile_number": MOBILE},
            {"mobile_number": MOBILE, "otp": "1", "password": "x"},
        ):
            response = self.client.post(reverse("session"), body, format="json")
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_incomplete_account_can_log_in_and_is_told_so(self):
        """A PENDING_PROFILE account logs in, and the body routes it to the wizard."""
        self.user.registration_status = RegistrationStatus.PENDING_PROFILE
        self.user.save()

        response = self.client.post(
            reverse("session"),
            {"mobile_number": MOBILE, "password": PASSWORD},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["next"], "profile")

    def test_logout_discards_the_session(self):
        """DELETE /sessions clears the cookie."""
        self.client.post(
            reverse("session"),
            {"mobile_number": MOBILE, "password": PASSWORD},
            format="json",
        )
        response = self.client.delete(reverse("session"))
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)


class GatedProbeView(APIView):
    """An endpoint that declares no permissions, so it inherits the defaults.

    Defined here rather than borrowing one from another app: what is under test
    is this project's DEFAULT_PERMISSION_CLASSES, and the test should not break
    when some other app retires an endpoint.
    """

    def get(self, request):
        """Return 200 to any caller the default permissions let through."""
        return Response({"ok": True})


# The project's real routes plus the probe, so tests can use both.
urlpatterns = [
    *project_urlpatterns,
    path("gated-probe/", GatedProbeView.as_view(), name="gated-probe"),
]


@override_settings(ROOT_URLCONF=__name__)
class GateTests(OTPTestCase):
    """The default permission classes."""

    def test_anonymous_caller_is_refused(self):
        """No session at all fails the IsAuthenticated half of the default."""
        response = self.client.get(reverse("gated-probe"))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_incomplete_account_is_gated(self):
        """A valid session for an unfinished account is still refused."""
        self.create_account()
        response = self.client.get(reverse("gated-probe"))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_complete_account_passes(self):
        """A finished account reaches the same endpoint."""
        user = User.objects.create_user(
            mobile_number=MOBILE,
            password=PASSWORD,
            registration_status=RegistrationStatus.COMPLETE,
        )
        self.client.force_authenticate(user=user)
        response = self.client.get(reverse("gated-probe"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)


class ResponseEnvelopeTests(OTPTestCase):
    """Every endpoint carries the meta envelope (spec 0000 section 8)."""

    def test_otp_request_carries_meta(self):
        """POST /auth/otp/request/ returns the envelope."""
        with patch("apps.users.services.otp._send_sms"):
            response = self.client.post(
                reverse("otp-request"), {"mobile_number": MOBILE}, format="json"
            )
        self.assert_meta(response.json())

    def test_user_create_carries_meta(self):
        """POST /users/ returns the envelope."""
        self.assert_meta(self.create_account().json())

    def test_session_carries_meta(self):
        """POST /sessions/ returns the envelope."""
        User.objects.create_user(
            mobile_number=MOBILE,
            password=PASSWORD,
            registration_status=RegistrationStatus.COMPLETE,
        )
        response = self.client.post(
            reverse("session"),
            {"mobile_number": MOBILE, "password": PASSWORD},
            format="json",
        )
        self.assert_meta(response.json())

    def test_registration_completion_carries_meta(self):
        """POST /litigants/ returns the envelope."""
        self.create_account()
        response = self.client.post(
            reverse("litigant-create"),
            {
                "name": "Asha Menon",
                "password": PASSWORD,
                "terms_accepted": True,
            },
            format="json",
        )
        self.assert_meta(response.json())

    def test_error_responses_carry_meta(self):
        """The envelope is present on failures too, not only success."""
        response = self.client.post(
            reverse("otp-request"), {"mobile_number": "not-a-number"}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assert_meta(response.json())
