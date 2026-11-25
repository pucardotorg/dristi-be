"""Client-signature verification against the document and certificate (spec 0038 #8.1, #14)."""

import datetime
import hashlib
import uuid
from types import SimpleNamespace

from django.test import SimpleTestCase

from addon.dsc_esign.config import DSCESignConfig
from addon.dsc_esign.verify import verify_client_signature
from apps.esign.exceptions import (
    ESignCertificateNotPermitted,
    ESignClientSignatureInvalid,
    ESignClientSignatureMismatch,
)

from .factories import detached_cms, make_signer

DIGEST = hashlib.sha256(b"prepared pdf byterange").digest()


def _txn(document_hash=None):
    return SimpleNamespace(document_hash=(document_hash or DIGEST.hex()), pk=uuid.uuid4())


def _config(**overrides):
    base = {"hash_algorithm": "SHA256"}
    base.update(overrides)
    return DSCESignConfig(**base)


class VerifyClientSignatureTests(SimpleTestCase):
    """The server verifies the client-supplied CMS before trusting it."""

    def test_valid_signature_over_the_document_digest(self):
        signer = make_signer()
        pkcs7 = detached_cms(signer, DIGEST).dump()
        response = verify_client_signature(_txn(), pkcs7, _config())
        self.assertTrue(response.success)
        self.assertEqual(response.response_audit["certificate_subject"], "CN=Judge Test")

    def test_digest_of_another_document_is_a_mismatch(self):
        signer = make_signer()
        other = hashlib.sha256(b"a different document").digest()
        pkcs7 = detached_cms(signer, other).dump()
        with self.assertRaises(ESignClientSignatureMismatch):
            verify_client_signature(_txn(), pkcs7, _config())

    def test_wrong_digest_algorithm_is_a_mismatch(self):
        signer = make_signer()
        pkcs7 = detached_cms(signer, DIGEST).dump()
        with self.assertRaises(ESignClientSignatureMismatch):
            verify_client_signature(_txn(), pkcs7, _config(hash_algorithm="SHA512"))

    def test_garbage_is_invalid(self):
        with self.assertRaises(ESignClientSignatureInvalid):
            verify_client_signature(_txn(), b"not a cms", _config())

    def test_tampered_signature_is_invalid(self):
        signer = make_signer()
        content_info = detached_cms(signer, DIGEST)
        signer_info = content_info["content"]["signer_infos"][0]
        original = signer_info["signature"].native
        signer_info["signature"] = bytes(len(original))  # zeroed, same length
        with self.assertRaises(ESignClientSignatureInvalid):
            verify_client_signature(_txn(), content_info.dump(), _config())

    def test_expired_certificate_is_not_permitted(self):
        past = datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=10)
        signer = make_signer(
            not_valid_before=past - datetime.timedelta(days=5),
            not_valid_after=past,
        )
        pkcs7 = detached_cms(signer, DIGEST).dump()
        with self.assertRaises(ESignCertificateNotPermitted):
            verify_client_signature(_txn(), pkcs7, _config())

    def test_certificate_without_signing_key_usage_is_not_permitted(self):
        signer = make_signer(digital_signature=False, content_commitment=False)
        pkcs7 = detached_cms(signer, DIGEST).dump()
        with self.assertRaises(ESignCertificateNotPermitted):
            verify_client_signature(_txn(), pkcs7, _config())

    def test_audit_holds_metadata_not_the_blob(self):
        signer = make_signer()
        pkcs7 = detached_cms(signer, DIGEST).dump()
        audit = verify_client_signature(_txn(), pkcs7, _config()).response_audit
        self.assertEqual(
            set(audit),
            {
                "provider",
                "certificate_subject",
                "certificate_issuer",
                "certificate_serial",
                "certificate_fingerprint",
            },
        )
        self.assertEqual(len(audit["certificate_fingerprint"]), 64)


class RegisteredBindingTests(SimpleTestCase):
    """The certificate may be required to match the signer's registered DSC."""

    def test_binding_off_by_default_allows_any_valid_certificate(self):
        signer = make_signer()
        pkcs7 = detached_cms(signer, DIGEST).dump()
        self.assertTrue(verify_client_signature(_txn(), pkcs7, _config()).success)

    def test_binding_rejects_an_unregistered_certificate(self):
        signer = make_signer()
        pkcs7 = detached_cms(signer, DIGEST).dump()
        config = _config(
            require_registered_cert=True,
            identity_resolver="addon.dsc_esign.tests.test_verify.resolve_none",
        )
        with self.assertRaises(ESignCertificateNotPermitted):
            verify_client_signature(_txn(), pkcs7, config)

    def test_binding_accepts_a_registered_certificate(self):
        signer = make_signer()
        content_info = detached_cms(signer, DIGEST)
        fingerprint = _fingerprint(content_info)
        config = _config(
            require_registered_cert=True,
            identity_resolver="addon.dsc_esign.tests.test_verify.resolve_fixed",
        )
        global _REGISTERED_FINGERPRINT
        _REGISTERED_FINGERPRINT = fingerprint
        self.assertTrue(verify_client_signature(_txn(), content_info.dump(), config).success)

    def test_binding_required_without_resolver_is_refused(self):
        signer = make_signer()
        pkcs7 = detached_cms(signer, DIGEST).dump()
        with self.assertRaises(ESignCertificateNotPermitted):
            verify_client_signature(_txn(), pkcs7, _config(require_registered_cert=True))


def _fingerprint(content_info) -> str:
    cert = content_info["content"]["certificates"][0].chosen
    return hashlib.sha256(cert.dump()).hexdigest()


# Resolvers referenced by dotted path in the binding tests.
_REGISTERED_FINGERPRINT = ""


def resolve_none(transaction):
    return None


def resolve_fixed(transaction):
    return {_REGISTERED_FINGERPRINT}
