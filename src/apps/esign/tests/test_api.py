"""Endpoint contract tests (spec 0015 #6, spec 0000 #8)."""

import uuid

from django.core.cache import cache
from django.test import override_settings
from django.urls import reverse
from rest_framework import status

from apps.esign import permissions
from apps.esign.constants import (
    ESIGN_DISABLED,
    ESIGN_MAX_ATTEMPTS_EXCEEDED,
    ESIGN_NOT_PERMITTED,
    ESIGN_NOT_RETRYABLE,
    ESignStatus,
)
from apps.esign.models import ESignTransaction

from .base import PKCS7_BASE64, ESignTestCase, registered_user


class InitiateEndpointTests(ESignTestCase):
    """``POST /api/v1/esign/_esign``."""

    def test_returns_the_esp_form_and_the_meta_envelope(self):
        """The UI gets an opaque form plus the standard envelope."""
        response = self.initiate()

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        payload = response.json()
        self.assert_meta(payload)

        transaction = ESignTransaction.objects.get()
        self.assertEqual(payload["transaction_id"], str(transaction.pk))
        self.assertEqual(payload["provider_transaction_id"], transaction.provider_transaction_id)
        self.assertEqual(payload["form_method"], "POST")
        self.assertEqual(payload["esign_url"], "https://esign.mock.invalid/esign")
        self.assertIn("eSignRequest", payload["form_fields"])
        self.assertIn("expires_at", payload)

    def test_requires_authentication(self):
        """Nothing about signing is readable anonymously."""
        self.client.force_authenticate(user=None)
        self.assertEqual(self.initiate().status_code, status.HTTP_403_FORBIDDEN)

    def test_requires_completed_registration(self):
        """A half-registered session cannot sign."""
        from apps.users.models import RegistrationStatus

        self.user.registration_status = RegistrationStatus.PENDING_PROFILE.value
        self.user.save(update_fields=["registration_status"])

        self.assertEqual(self.initiate().status_code, status.HTTP_403_FORBIDDEN)

    def test_unknown_file_is_a_validation_error(self):
        """The source document is resolved during validation."""
        response = self.initiate(file_id="missing")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("file_id", response.json())

    def test_non_pdf_source_is_a_validation_error(self):
        """Only PDFs can be signed, and the client is told which field is wrong."""
        image = self.files.add(b"\x89PNG", content_type="image/png")
        response = self.initiate(file_id=image)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("file_id", response.json())

    def test_invalid_entity_type_is_rejected(self):
        """entity_type is a bounded enum."""
        response = self.initiate(entity_type="INVOICE")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("entity_type", response.json())

    def test_unknown_placement_keys_are_rejected(self):
        """A placement key the PDF Service would refuse fails fast."""
        response = self.initiate(sign_placeholder={"page": 1, "x": 1, "y": 1, "rotate": 90})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_incomplete_placement_is_rejected(self):
        """Coordinates and size are required."""
        response = self.initiate(sign_placeholder={"page": 1})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_organization_id_is_optional(self):
        """Not every signed document is organization scoped."""
        response = self.initiate(organization_id=None)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIsNone(ESignTransaction.objects.get().organization_id)

    def test_organization_id_is_persisted_when_supplied(self):
        """A supplied organization is recorded on the transaction."""
        organization_id = uuid.uuid4()
        response = self.initiate(organization_id=str(organization_id))
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(ESignTransaction.objects.get().organization_id, organization_id)

    @override_settings(ESIGN_ENABLED=False)
    def test_kill_switch_returns_service_unavailable(self):
        """The kill switch is reported as 503, not as a validation error."""
        response = self.initiate()
        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
        self.assertEqual(response.json()["code"], ESIGN_DISABLED)

    def test_permission_denial_returns_forbidden(self):
        """An owning module's refusal is a 403 with the domain code."""
        permissions.register_entity_authorizer("ORDER", lambda **kwargs: False)
        self.addCleanup(permissions.unregister_entity_authorizer, "ORDER")

        response = self.initiate()
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.json()["code"], ESIGN_NOT_PERMITTED)


class StatusEndpointTests(ESignTestCase):
    """``GET /api/v1/esign/transactions/{id}``."""

    def setUp(self):
        """Create a transaction owned by the signed-in user."""
        super().setUp()
        self.transaction = self.create_transaction()
        self.url = reverse("esign-transaction", args=[self.transaction.pk])

    def test_returns_the_status_with_the_meta_envelope(self):
        """The UI polls this endpoint after the browser returns."""
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        payload = response.json()
        self.assert_meta(payload)
        self.assertEqual(payload["transaction_id"], str(self.transaction.pk))
        self.assertEqual(payload["status"], ESignStatus.PENDING.value)
        self.assertEqual(payload["signed_file_id"], "")

    def test_reports_the_signed_file_on_success(self):
        """A completed transaction exposes the signed document id."""
        self.post_callback(self.transaction)
        self.transaction.refresh_from_db()

        payload = self.client.get(self.url).json()
        self.assertEqual(payload["status"], ESignStatus.SUCCESS.value)
        self.assertEqual(payload["signed_file_id"], self.transaction.signed_file_id)

    def test_reports_the_failure_code_on_failure(self):
        """A failed transaction exposes a code and a safe message."""
        self.transaction.mark_failed("ESIGN_PROVIDER_REJECTED", "The signing service refused.")

        payload = self.client.get(self.url).json()
        self.assertEqual(payload["failure_code"], "ESIGN_PROVIDER_REJECTED")
        self.assertEqual(payload["failure_message"], "The signing service refused.")

    def test_another_users_transaction_is_not_readable(self):
        """Transactions are scoped to the signer."""
        self.client.force_authenticate(user=registered_user("+919812345678"))
        self.assertEqual(self.client.get(self.url).status_code, status.HTTP_404_NOT_FOUND)

    def test_requires_authentication(self):
        """Status is not public."""
        self.client.force_authenticate(user=None)
        self.assertEqual(self.client.get(self.url).status_code, status.HTTP_403_FORBIDDEN)


class RetryEndpointTests(ESignTestCase):
    """``POST /api/v1/esign/transactions/{id}/_retry``."""

    def setUp(self):
        """Create a failed transaction to retry."""
        super().setUp()
        self.transaction = self.create_transaction()
        self.transaction.mark_failed("ESIGN_PROVIDER_REJECTED", "refused")
        self.url = reverse("esign-retry", args=[self.transaction.pk])

    def test_retry_creates_a_linked_transaction(self):
        """A retry is a new row, not a mutation of the old one."""
        response = self.client.post(self.url)

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        payload = response.json()
        self.assert_meta(payload)

        retry = ESignTransaction.objects.get(pk=payload["transaction_id"])
        self.assertEqual(retry.retry_of, self.transaction)
        self.assertEqual(retry.attempt_count, 2)
        self.assertEqual(retry.status, ESignStatus.PENDING.value)
        self.assertEqual(retry.placeholder_file_id, self.transaction.placeholder_file_id)
        self.assertEqual(retry.document_hash, self.transaction.document_hash)
        self.assertNotEqual(retry.provider_transaction_id, self.transaction.provider_transaction_id)

    def test_pending_transactions_are_not_retryable(self):
        """Only failed or expired attempts can be retried."""
        pending = self.create_transaction(provider_transaction_id="orders-pending")
        response = self.client.post(reverse("esign-retry", args=[pending.pk]))

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["code"], ESIGN_NOT_RETRYABLE)

    def test_successful_transactions_are_not_retryable(self):
        """A signed document is never signed twice."""
        succeeded = self.create_transaction(provider_transaction_id="orders-done")
        self.post_callback(succeeded)

        response = self.client.post(reverse("esign-retry", args=[succeeded.pk]))
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @override_settings(ESIGN_MAX_ATTEMPTS=1)
    def test_attempt_budget_is_enforced(self):
        """ESIGN_MAX_ATTEMPTS bounds the attempts per document."""
        response = self.client.post(self.url)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["code"], ESIGN_MAX_ATTEMPTS_EXCEEDED)

    def test_another_users_transaction_cannot_be_retried(self):
        """Retry is scoped to the signer."""
        self.client.force_authenticate(user=registered_user("+919812345678"))
        self.assertEqual(self.client.post(self.url).status_code, status.HTTP_404_NOT_FOUND)


class CallbackEndpointTests(ESignTestCase):
    """``POST /api/v1/esign/_signed``."""

    def setUp(self):
        """Create a PENDING transaction and drop the session."""
        super().setUp()
        self.transaction = self.create_transaction()
        # The ESP posts from the user's browser with no Dristi credentials.
        self.client.force_authenticate(user=None)
        self.url = reverse("esign-callback")

    @override_settings(ESIGN_UI_REDIRECT_URL="https://ui.example.org/esign/return")
    def test_successful_callback_redirects_to_the_configured_url(self):
        """The browser is sent back to the UI with the outcome."""
        response = self.post_callback(self.transaction)

        self.assertEqual(response.status_code, status.HTTP_302_FOUND)
        self.assertEqual(
            response["Location"],
            "https://ui.example.org/esign/return"
            f"?transaction_id={self.transaction.pk}&status=SUCCESS",
        )

    def test_without_a_redirect_url_a_minimal_page_is_rendered(self):
        """A browser mid-navigation always gets something to render."""
        response = self.post_callback(self.transaction)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response["Content-Type"], "text/html; charset=utf-8")
        self.assertIn(b"SUCCESS", response.content)
        # Explicitly not the JSON envelope: the caller is a browser.
        self.assertNotIn(b"spec_version", response.content)

    def test_form_encoded_payload_is_accepted(self):
        """C-DAC posts a browser form, not JSON."""
        response = self.client.post(
            self.url,
            self.callback_payload(self.transaction),
            format="multipart",
        )
        self.assertIn(response.status_code, (status.HTTP_200_OK, status.HTTP_302_FOUND))
        self.transaction.refresh_from_db()
        self.assertEqual(self.transaction.status, ESignStatus.SUCCESS.value)

    def test_xml_payload_is_accepted(self):
        """A deployment may forward the raw response document instead."""
        response = self.client.post(
            self.url,
            "<EsignResp status='1' txn='unknown'/>",
            content_type="application/xml",
        )
        # The mock provider reads flat fields, so an XML body correlates to
        # nothing — the point here is that the parser accepted the media type.
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_unknown_transaction_is_rejected_without_a_redirect(self):
        """An unverifiable callback is refused, never redirected."""
        response = self.client.post(
            self.url,
            {"txn": "orders-unknown", "status": "1", "signature": PKCS7_BASE64},
            format="multipart",
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertNotIn("Location", response)

    def test_malformed_payload_is_rejected(self):
        """A payload that correlates to nothing is a 400."""
        response = self.client.post(self.url, {"status": "1"}, format="multipart")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_failed_transaction_callback_is_a_conflict(self):
        """A dead-end transaction is not resurrected by a late callback."""
        self.transaction.mark_failed("ESIGN_PROVIDER_REJECTED", "refused")
        response = self.post_callback(self.transaction)
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)

    @override_settings(ESIGN_CALLBACK_MAX_BODY_BYTES=10)
    def test_oversized_payload_is_refused(self):
        """The public endpoint is body-size limited."""
        response = self.post_callback(self.transaction)
        self.assertEqual(response.status_code, status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)

    @override_settings(ESIGN_CALLBACK_THROTTLE_RATE="1/min")
    def test_callback_is_throttled_per_ip(self):
        """The public endpoint is throttled."""
        cache.clear()
        self.addCleanup(cache.clear)

        first = self.post_callback(self.transaction)
        self.assertNotEqual(first.status_code, status.HTTP_429_TOO_MANY_REQUESTS)

        second = self.post_callback(self.transaction)
        self.assertEqual(second.status_code, status.HTTP_429_TOO_MANY_REQUESTS)

    def test_csrf_is_not_required(self):
        """The ESP cannot carry a CSRF token."""
        from rest_framework.test import APIClient

        enforcing = APIClient(enforce_csrf_checks=True)
        response = enforcing.post(
            self.url, self.callback_payload(self.transaction), format="multipart"
        )
        self.assertNotEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class SchemaTests(ESignTestCase):
    """Swagger documentation of the endpoints."""

    def test_endpoints_are_documented_and_tagged(self):
        """Every route is in the schema under the esign tag."""
        response = self.client.get(reverse("api-schema"), {"format": "json"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        schema = response.json()

        for path, method in (
            ("/api/v1/esign/_esign", "post"),
            ("/api/v1/esign/_signed", "post"),
            ("/api/v1/esign/transactions/{transaction_id}", "get"),
            ("/api/v1/esign/transactions/{transaction_id}/_retry", "post"),
        ):
            self.assertIn(path, schema["paths"], path)
            self.assertEqual(schema["paths"][path][method]["tags"], ["esign"])

        callback = schema["paths"]["/api/v1/esign/_signed"]["post"]
        self.assertIn("302", callback["responses"])


class CallbackFailureRedirectTests(ESignTestCase):
    """A trusted callback that fails still returns the browser to the UI."""

    def setUp(self):
        """Create a PENDING transaction and drop the session."""
        super().setUp()
        self.transaction = self.create_transaction()
        self.client.force_authenticate(user=None)

    @override_settings(ESIGN_UI_REDIRECT_URL="https://ui.example.org/return")
    def test_embed_failure_redirects_with_failure_status(self):
        """The failure is recorded, and the UI reads it from the status endpoint."""
        from apps.esign.exceptions import ESignPDFEmbedError

        self.pdf.fail_embed = ESignPDFEmbedError()

        response = self.post_callback(self.transaction)

        self.assertEqual(response.status_code, status.HTTP_302_FOUND)
        self.assertEqual(
            response["Location"],
            f"https://ui.example.org/return?transaction_id={self.transaction.pk}&status=FAILURE",
        )
        self.transaction.refresh_from_db()
        self.assertEqual(self.transaction.status, ESignStatus.FAILURE.value)

    @override_settings(ESIGN_UI_REDIRECT_URL="https://ui.example.org/return")
    def test_provider_rejection_redirects_with_failure_status(self):
        """An ESP-reported failure is an outcome, not an error page."""
        response = self.post_callback(self.transaction, status="0", signature=None)

        self.assertEqual(response.status_code, status.HTTP_302_FOUND)
        self.assertIn("status=FAILURE", response["Location"])


class CallbackBodyLimitTests(ESignTestCase):
    """The public callback bounds what it will read (spec 0015 #6.3, #12)."""

    def setUp(self):
        """Create a PENDING transaction and drop the session."""
        super().setUp()
        self.transaction = self.create_transaction()
        self.client.force_authenticate(user=None)
        self.url = reverse("esign-callback")

    @override_settings(ESIGN_CALLBACK_MAX_BODY_BYTES=64)
    def test_oversized_xml_body_is_refused_with_413(self):
        """An oversized XML body answers 413, like the form-encoded guard."""
        document = "<EsignResp txn='orders-1'>" + ("x" * 4096) + "</EsignResp>"

        response = self.client.post(self.url, document, content_type="application/xml")

        self.assertEqual(response.status_code, status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)
        self.transaction.refresh_from_db()
        self.assertEqual(self.transaction.status, ESignStatus.PENDING.value)

    @override_settings(ESIGN_CALLBACK_MAX_BODY_BYTES=64)
    def test_parser_read_is_bounded_even_without_a_content_length(self):
        """Called directly, the parser refuses to buffer the whole body, with 413."""
        import io

        from apps.esign.parsers import CallbackBodyTooLarge, ESignResponseXMLParser

        with self.assertRaises(CallbackBodyTooLarge) as caught:
            ESignResponseXMLParser().parse(io.BytesIO(b"<EsignResp/>" + b"x" * 8192))
        self.assertEqual(caught.exception.status_code, status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)

    @override_settings(ESIGN_CALLBACK_MAX_BODY_BYTES=4096)
    def test_a_body_inside_the_limit_is_parsed(self):
        """The limit does not truncate a legitimate response document."""
        import io

        from apps.esign.parsers import RESPONSE_XML_FIELD, ESignResponseXMLParser

        parsed = ESignResponseXMLParser().parse(io.BytesIO(b"<EsignResp txn='a'/>"))
        self.assertEqual(parsed, {RESPONSE_XML_FIELD: "<EsignResp txn='a'/>"})

    @override_settings(ESIGN_CALLBACK_MAX_BODY_BYTES=0)
    def test_the_limit_can_be_switched_off(self):
        """Zero means no limit, for a deployment that bounds bodies upstream."""
        import io

        from apps.esign.parsers import RESPONSE_XML_FIELD, ESignResponseXMLParser

        body = b"<EsignResp txn='a'>" + b"x" * 5000 + b"</EsignResp>"
        parsed = ESignResponseXMLParser().parse(io.BytesIO(body))
        self.assertEqual(len(parsed[RESPONSE_XML_FIELD]), len(body))
