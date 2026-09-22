"""Tests for CDAC password hashing and request signing."""

import hashlib

from django.test import SimpleTestCase

from addon.cdac_sms_gateway.hashing import generate_password_hash, generate_signature


class PasswordHashTests(SimpleTestCase):
    """SHA-1 password hash tests."""

    def test_sha1_lowercase_hex(self):
        self.assertEqual(
            generate_password_hash("secret"),
            "e5e9fa1ba31ecd1ae84f75caaa474f3a663f05f4",
        )

    def test_encodes_with_iso_8859_1(self):
        password = "pässwörd"
        expected = hashlib.sha1(password.encode("iso-8859-1")).hexdigest()
        self.assertEqual(generate_password_hash(password), expected)
        self.assertNotEqual(
            generate_password_hash(password),
            hashlib.sha1(password.encode("utf-8")).hexdigest(),
        )

    def test_empty_password(self):
        self.assertEqual(generate_password_hash(""), hashlib.sha1(b"").hexdigest())


class SignatureTests(SimpleTestCase):
    """SHA-512 request signature tests."""

    def test_no_separators_between_components(self):
        expected = hashlib.sha512(b"userSENDERcontentkey").hexdigest()
        self.assertEqual(generate_signature("user", "SENDER", "content", "key"), expected)

    def test_components_are_stripped(self):
        self.assertEqual(
            generate_signature("  user ", " SENDER", " content ", "key  "),
            generate_signature("user", "SENDER", "content", "key"),
        )

    def test_lowercase_hex_digest(self):
        signature = generate_signature("user", "SENDER", "content", "key")
        self.assertEqual(signature, signature.lower())
        self.assertEqual(len(signature), 128)

    def test_signature_uses_final_encoded_content(self):
        encoded = "&#2344;&#2350;"
        self.assertEqual(
            generate_signature("user", "SENDER", encoded, "key"),
            hashlib.sha512(f"userSENDER{encoded}key".encode()).hexdigest(),
        )
