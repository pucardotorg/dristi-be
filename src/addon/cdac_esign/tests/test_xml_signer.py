"""XMLDSig request signing and keystore tests (spec 0015 #7.2)."""

import datetime
import tempfile
from pathlib import Path

from django.test import SimpleTestCase
from lxml import etree

from addon.cdac_esign.keystore import (
    CDACKeystoreError,
    load_key_material,
    reset_keystore_cache,
)
from addon.cdac_esign.xml_signer import CDACXMLSigningError, sign_request_xml

from .keys import KEYSTORE_PASSWORD, asp_key_pair, generate_key_pair, write_keystore

DSIG = "{http://www.w3.org/2000/09/xmldsig#}"
REQUEST = b'<Esign ver="2.1" txn="orders-1"><Docs><InputHash id="1">ab</InputHash></Docs></Esign>'


class KeystoreTests(SimpleTestCase):
    """PKCS#12 loading."""

    def setUp(self):
        """Work against a freshly written keystore."""
        reset_keystore_cache()
        self.addCleanup(reset_keystore_cache)
        self.directory = tempfile.mkdtemp()
        self.path = write_keystore(self.directory)

    def test_key_and_certificate_are_loaded(self):
        """The ASP identity comes from the keystore, not from the database."""
        material = load_key_material(self.path, KEYSTORE_PASSWORD)

        self.assertIsNotNone(material.private_key)
        self.assertIn("ASP Test", material.subject)
        self.assertIn("BEGIN CERTIFICATE", material.certificate_pem())

    def test_repr_never_renders_key_material(self):
        """Key material must not leak through a log line or traceback."""
        material = load_key_material(self.path, KEYSTORE_PASSWORD)
        rendered = repr(material)

        self.assertIn("ASP Test", rendered)
        self.assertNotIn("PRIVATE KEY", rendered)
        self.assertNotIn(KEYSTORE_PASSWORD, rendered)

    def test_missing_keystore_is_reported(self):
        """A missing file is a configuration error, not a crash."""
        with self.assertRaises(CDACKeystoreError):
            load_key_material(str(Path(self.directory) / "absent.p12"), KEYSTORE_PASSWORD)

    def test_unset_keystore_path_is_reported(self):
        """An unset path is reported rather than read as the current directory."""
        with self.assertRaises(CDACKeystoreError):
            load_key_material("", KEYSTORE_PASSWORD)

    def test_wrong_password_is_reported(self):
        """The password is validated by opening the keystore."""
        with self.assertRaises(CDACKeystoreError):
            load_key_material(self.path, "wrong-password")

    def test_rotated_keystore_is_picked_up(self):
        """Caching must not pin a rotated keystore."""
        first = load_key_material(self.path, KEYSTORE_PASSWORD)
        rotated = generate_key_pair("ASP Rotated")
        Path(self.path).write_bytes(rotated.pkcs12())

        second = load_key_material(self.path, KEYSTORE_PASSWORD)
        self.assertNotEqual(first.subject, second.subject)
        self.assertIn("ASP Rotated", second.subject)

    def test_expiry_is_exposed_for_the_system_checks(self):
        """The checks warn before the ASP certificate expires."""
        expiring = generate_key_pair(
            "ASP Expiring",
            not_valid_after=datetime.datetime.now(datetime.UTC) + datetime.timedelta(days=5),
        )
        path = write_keystore(tempfile.mkdtemp(), key_pair=expiring)

        material = load_key_material(path, KEYSTORE_PASSWORD)
        self.assertLess(
            material.not_valid_after,
            datetime.datetime.now(datetime.UTC) + datetime.timedelta(days=6),
        )


class SigningTests(SimpleTestCase):
    """Enveloped XMLDSig over the request."""

    def setUp(self):
        """Sign the sample request with the ASP key."""
        self.material = type(
            "Material",
            (),
            {
                "private_key": asp_key_pair().private_key,
                "certificate_pem": staticmethod(lambda: asp_key_pair().certificate_pem),
            },
        )()
        self.signed = etree.fromstring(sign_request_xml(REQUEST, self.material))

    def test_signature_is_enveloped(self):
        """The signature sits inside the signed document."""
        self.assertEqual(self.signed.tag, "Esign")
        signature = self.signed.find(f"{DSIG}Signature")
        self.assertIsNotNone(signature)

    def test_algorithms_are_sha256_and_exclusive_c14n(self):
        """The algorithm set C-DAC validates the request with."""
        method = self.signed.find(f"{DSIG}Signature/{DSIG}SignedInfo/{DSIG}SignatureMethod")
        digest = self.signed.find(
            f"{DSIG}Signature/{DSIG}SignedInfo/{DSIG}Reference/{DSIG}DigestMethod"
        )
        c14n = self.signed.find(f"{DSIG}Signature/{DSIG}SignedInfo/{DSIG}CanonicalizationMethod")

        self.assertEqual(
            method.get("Algorithm"), "http://www.w3.org/2001/04/xmldsig-more#rsa-sha256"
        )
        self.assertEqual(digest.get("Algorithm"), "http://www.w3.org/2001/04/xmlenc#sha256")
        self.assertEqual(c14n.get("Algorithm"), "http://www.w3.org/2001/10/xml-exc-c14n#")

    def test_enveloped_transform_is_declared(self):
        """Without the transform the digest would cover the signature itself."""
        transforms = [element.get("Algorithm") for element in self.signed.iter(f"{DSIG}Transform")]
        self.assertIn("http://www.w3.org/2000/09/xmldsig#enveloped-signature", transforms)

    def test_asp_certificate_is_included_in_key_info(self):
        """The ESP needs the ASP certificate to verify the request."""
        certificate = self.signed.find(
            f"{DSIG}Signature/{DSIG}KeyInfo/{DSIG}X509Data/{DSIG}X509Certificate"
        )
        self.assertIsNotNone(certificate)
        self.assertTrue(certificate.text.strip())

    def test_malformed_request_xml_is_reported(self):
        """A document that will not parse cannot be signed."""
        with self.assertRaises(CDACXMLSigningError):
            sign_request_xml(b"<Esign", self.material)

    def test_unusable_key_is_reported(self):
        """A broken key is a signing failure, not an unhandled exception."""
        broken = type(
            "Material",
            (),
            {"private_key": object(), "certificate_pem": staticmethod(lambda: "nonsense")},
        )()
        with self.assertRaises(CDACXMLSigningError):
            sign_request_xml(REQUEST, broken)
