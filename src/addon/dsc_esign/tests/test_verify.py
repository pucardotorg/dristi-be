"""Client-signature verification against the document and certificate (spec 0038 #8.1, #14)."""

import datetime
import hashlib
import os
import random
import tempfile
import uuid
from types import SimpleNamespace

from asn1crypto import pem
from django.test import SimpleTestCase

from addon.dsc_esign.config import DSCESignConfig
from addon.dsc_esign.verify import verify_client_signature
from apps.esign.exceptions import (
    ESignCertificateNotPermitted,
    ESignClientSignatureInvalid,
    ESignClientSignatureMismatch,
    ESignError,
)

from .factories import detached_cms, make_signer

DIGEST = hashlib.sha256(b"prepared pdf byterange").digest()


def _txn(document_hash=None):
    return SimpleNamespace(document_hash=(document_hash or DIGEST.hex()), pk=uuid.uuid4())


def _config(**overrides):
    # Default to allowing untrusted (self-signed) certs so these tests exercise
    # the digest/signature/certificate-policy checks; trust-chain behaviour has
    # its own dedicated tests below.
    base = {"hash_algorithm": "SHA256", "allow_untrusted_cert": True}
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


class TrustChainTests(SimpleTestCase):
    """The certificate must chain to a configured trust anchor (spec 0038 #8.1)."""

    def test_untrusted_is_refused_by_default(self):
        signer = make_signer()
        pkcs7 = detached_cms(signer, DIGEST).dump()
        config = DSCESignConfig(hash_algorithm="SHA256")  # no roots, not allowed
        with self.assertRaises(ESignCertificateNotPermitted):
            verify_client_signature(_txn(), pkcs7, config)

    def test_certificate_chaining_to_a_configured_root_is_accepted(self):
        signer = make_signer()
        content_info = detached_cms(signer, DIGEST)
        cert_der = signer.signing_cert.dump()
        with tempfile.TemporaryDirectory() as tmp:
            bundle = os.path.join(tmp, "roots.pem")
            with open(bundle, "wb") as handle:
                handle.write(pem.armor("CERTIFICATE", cert_der))
            config = DSCESignConfig(hash_algorithm="SHA256", trust_roots=bundle)
            response = verify_client_signature(_txn(), content_info.dump(), config)
        self.assertTrue(response.success)

    def test_backdated_signing_time_cannot_resurrect_an_expired_certificate(self):
        """Validity is checked at server time, not the client's signingTime."""
        past = datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=400)
        signer = make_signer(
            not_valid_before=past - datetime.timedelta(days=400),
            not_valid_after=past,
        )
        pkcs7 = detached_cms(signer, DIGEST).dump()  # signingTime is ~now, cert expired
        with self.assertRaises(ESignCertificateNotPermitted):
            verify_client_signature(_txn(), pkcs7, _config())


class FuzzTests(SimpleTestCase):
    """A malformed CMS is always a 4xx client error, never a 500 (spec 0038 #14)."""

    def test_mutated_blobs_always_raise_a_domain_error(self):
        signer = make_signer()
        valid = detached_cms(signer, DIGEST).dump()
        rng = random.Random(1234)
        for _ in range(400):
            blob = bytearray(valid)
            # Truncate and/or flip a handful of bytes.
            if rng.random() < 0.5 and len(blob) > 10:
                blob = blob[: rng.randint(1, len(blob) - 1)]
            for _ in range(rng.randint(1, 6)):
                if blob:
                    blob[rng.randrange(len(blob))] = rng.randrange(256)
            try:
                verify_client_signature(_txn(), bytes(blob), _config())
            except ESignError:
                pass  # expected: always a mapped 4xx
            except Exception as exc:  # noqa: BLE001 - the whole point of the test
                self.fail(f"non-domain exception escaped verify: {type(exc).__name__}: {exc}")


# Resolvers referenced by dotted path in the binding tests.
_REGISTERED_FINGERPRINT = ""


def resolve_none(transaction):
    return None


def resolve_fixed(transaction):
    return {_REGISTERED_FINGERPRINT}
