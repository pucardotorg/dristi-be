"""Shared fixtures for the eSign test suite."""

import base64
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.esign.constants import ESignStatus
from apps.esign.models import ESignTransaction
from apps.esign.providers import reset_provider_cache
from apps.users.models import RegistrationStatus, Role

from .fakes import FakeFileClient, FakePDFClient

SOURCE_PDF = b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\ntrailer\n%%EOF\n"
PLACEHOLDER = {
    "page": 1,
    "position": "bottom-right",
    "x": 380,
    "y": 60,
    "width": 160,
    "height": 60,
    "reason": "Approved",
    "location": "District Court, Ernakulam",
}

# A minimal DER PKCS#7 SignedData ContentInfo: SEQUENCE { OID signedData }.
PKCS7_BLOB = bytes((0x30, 0x0B, 0x06, 0x09, 0x2A, 0x86, 0x48, 0x86, 0xF7, 0x0D, 0x01, 0x07, 0x02))
PKCS7_BASE64 = base64.b64encode(PKCS7_BLOB).decode()


def registered_user(mobile_number="+919876543210", **extra):
    """Create an account that has finished the registration wizard."""

    return get_user_model().objects.create_user(
        mobile_number=mobile_number,
        name="Presiding Officer",
        role=Role.LITIGANT.value,
        registration_status=RegistrationStatus.COMPLETE.value,
        **extra,
    )


class ESignTestCase(APITestCase):
    """Patches the module adapters with in-memory fakes for every test."""

    def setUp(self):
        """Install the fakes and a registered, signed-in user."""

        reset_provider_cache()
        self.files = FakeFileClient()
        self.pdf = FakePDFClient()
        for target in (
            "apps.esign.clients.get_file_client",
            "apps.esign.serializers.get_file_client",
            "apps.esign.services.initiation.get_file_client",
            "apps.esign.services.callback.get_file_client",
            "apps.esign.services.recovery.get_file_client",
        ):
            patcher = patch(target, return_value=self.files)
            patcher.start()
            self.addCleanup(patcher.stop)
        for target in (
            "apps.esign.clients.get_pdf_client",
            "apps.esign.services.initiation.get_pdf_client",
            "apps.esign.services.callback.get_pdf_client",
        ):
            patcher = patch(target, return_value=self.pdf)
            patcher.start()
            self.addCleanup(patcher.stop)

        self.user = registered_user()
        self.source_file_id = self.files.add(SOURCE_PDF)
        self.client.force_authenticate(user=self.user)

    # -- helpers ------------------------------------------------------------
    def initiate_payload(self, **overrides):
        """Return a valid initiation request body."""

        payload = {
            "module": "orders",
            "entity_type": "ORDER",
            "entity_id": "9f2c0001",
            "file_id": self.source_file_id,
            "sign_placeholder": dict(PLACEHOLDER),
        }
        payload.update(overrides)
        return payload

    def initiate(self, **overrides):
        """Call the initiation endpoint and return the response."""

        return self.client.post(
            reverse("esign-initiate"), self.initiate_payload(**overrides), format="json"
        )

    def create_transaction(self, **overrides):
        """Create a PENDING transaction directly, bypassing the API."""

        prepared = self.pdf.prepare_for_signing(SOURCE_PDF, dict(PLACEHOLDER))
        placeholder_file_id = self.files.add(prepared.prepared_document)
        fields = {
            "module": "orders",
            "entity_type": "ORDER",
            "entity_id": "9f2c0001",
            "signer": self.user,
            "provider": "mock",
            "provider_transaction_id": f"orders-{timezone.now().timestamp()}",
            "source_file_id": self.source_file_id,
            "placeholder_file_id": placeholder_file_id,
            "sign_placeholder": dict(PLACEHOLDER),
            "document_hash": prepared.document_hash,
            "signature_field_name": prepared.field_name,
            "status": ESignStatus.PENDING.value,
            "expires_at": timezone.now() + timezone.timedelta(seconds=900),
        }
        fields.update(overrides)
        return ESignTransaction.objects.create(**fields)

    @staticmethod
    def callback_payload(transaction, *, status="1", signature=PKCS7_BASE64, **extra):
        """Return a mock-provider callback payload for ``transaction``."""

        payload = {
            "txn": transaction.provider_transaction_id,
            "status": status,
            "ts": timezone.now().isoformat(),
        }
        if signature is not None:
            payload["signature"] = signature
        payload.update(extra)
        return payload

    def post_callback(self, transaction, **kwargs):
        """Post a callback as a browser form."""

        return self.client.post(
            reverse("esign-callback"),
            self.callback_payload(transaction, **kwargs),
            format="multipart",
        )

    def assert_meta(self, payload):
        """Assert the envelope required by spec 0000 section 8 is present."""

        self.assertIn("meta", payload)
        meta = payload["meta"]
        self.assertIn("timestamp", meta)
        self.assertIn("app_version", meta)
        self.assertEqual(meta["spec_version"], "1.0")
