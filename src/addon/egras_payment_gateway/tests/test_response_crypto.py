"""Encrypted-callback decryption and checksum tests (spec 0022 #5.4)."""

import base64
import hashlib
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from django.test import SimpleTestCase

from addon.egras_payment_gateway import response_crypto
from addon.egras_payment_gateway.config import EGRASKeyError, load_response_key, reset_config_cache

from .base import RESPONSE_FIELDS, encrypt_pay_res, make_response_key, write_key_file


class DecryptTests(SimpleTestCase):
    def setUp(self):
        self.key = make_response_key()

    def test_round_trip(self):
        pay_res = encrypt_pay_res(RESPONSE_FIELDS, self.key)
        data = response_crypto.decrypt_pay_res(pay_res, self.key)
        self.assertEqual(data["Applicationnumber"], "DR0F9D3A6C1B2E4F5A7B")
        self.assertEqual(data["status"], "Success")

    def test_wrong_key_fails(self):
        pay_res = encrypt_pay_res(RESPONSE_FIELDS, self.key)
        with self.assertRaises(response_crypto.ResponseDecryptionError):
            response_crypto.decrypt_pay_res(pay_res, make_response_key())

    def test_tampered_ciphertext_fails(self):
        pay_res = encrypt_pay_res(RESPONSE_FIELDS, self.key)
        raw = bytearray(base64.b64decode(pay_res))
        raw[-1] ^= 0x01  # flip a bit in the GCM tag
        tampered = base64.b64encode(bytes(raw)).decode()
        with self.assertRaises(response_crypto.ResponseDecryptionError):
            response_crypto.decrypt_pay_res(tampered, self.key)

    def test_not_base64_fails(self):
        with self.assertRaises(response_crypto.ResponseDecryptionError):
            response_crypto.decrypt_pay_res("not base64!!!", self.key)

    def test_too_short_fails(self):
        short = base64.b64encode(os.urandom(8)).decode()
        with self.assertRaises(response_crypto.ResponseDecryptionError):
            response_crypto.decrypt_pay_res(short, self.key)

    def test_non_json_plaintext_fails(self):
        nonce = os.urandom(response_crypto.NONCE_LENGTH)
        blob = nonce + AESGCM(self.key).encrypt(nonce, b"not json", None)
        with self.assertRaises(response_crypto.ResponseDecryptionError):
            response_crypto.decrypt_pay_res(base64.b64encode(blob).decode(), self.key)


class ChecksumTests(SimpleTestCase):
    def test_expected_checksum_is_sha256_of_pipe_joined_fields(self):
        checksum = response_crypto.expected_checksum(RESPONSE_FIELDS)
        joined = "|".join(RESPONSE_FIELDS[f] for f in response_crypto.CHECKSUM_FIELDS)
        self.assertEqual(checksum, hashlib.sha256(joined.encode()).hexdigest())

    def test_matches_when_present_and_correct(self):
        data = {**RESPONSE_FIELDS, "checksum": response_crypto.expected_checksum(RESPONSE_FIELDS)}
        self.assertTrue(response_crypto.checksum_matches(data))

    def test_does_not_match_when_wrong_or_absent(self):
        self.assertFalse(response_crypto.checksum_matches(RESPONSE_FIELDS))  # no checksum
        self.assertFalse(
            response_crypto.checksum_matches({**RESPONSE_FIELDS, "checksum": "deadbeef"})
        )


class LoadKeyTests(SimpleTestCase):
    def tearDown(self):
        reset_config_cache()

    def test_valid_key_file_loads(self):
        key = make_response_key()
        path = write_key_file(key)
        self.addCleanup(os.unlink, path)
        self.assertEqual(load_response_key(path), key)

    def test_empty_path_raises(self):
        with self.assertRaises(EGRASKeyError):
            load_response_key("")

    def test_missing_file_raises(self):
        with self.assertRaises(EGRASKeyError):
            load_response_key("/no/such/egras.key")

    def test_wrong_length_raw_key_raises(self):
        path = write_key_file(b"too-short")
        self.addCleanup(os.unlink, path)
        with self.assertRaises(EGRASKeyError):
            load_response_key(path, "raw")

    def test_base64_key_file_is_decoded(self):
        key = make_response_key()
        path = write_key_file(base64.b64encode(key) + b"\n")  # text + trailing newline
        self.addCleanup(os.unlink, path)
        self.assertEqual(load_response_key(path, "base64"), key)

    def test_hex_key_file_is_decoded(self):
        key = make_response_key()
        path = write_key_file(key.hex().encode() + b"\n")
        self.addCleanup(os.unlink, path)
        self.assertEqual(load_response_key(path, "hex"), key)

    def test_base64_text_read_as_raw_is_rejected(self):
        # A 32-byte key saved as base64 is 44 text bytes: valid base64, but as raw
        # it is the wrong length, so "raw" must not silently accept it.
        path = write_key_file(base64.b64encode(make_response_key()))
        self.addCleanup(os.unlink, path)
        with self.assertRaises(EGRASKeyError):
            load_response_key(path, "raw")

    def test_unknown_format_raises(self):
        path = write_key_file(make_response_key())
        self.addCleanup(os.unlink, path)
        with self.assertRaises(EGRASKeyError):
            load_response_key(path, "pem")

    def test_bad_base64_content_raises(self):
        path = write_key_file(b"not valid base64 !!!")
        self.addCleanup(os.unlink, path)
        with self.assertRaises(EGRASKeyError):
            load_response_key(path, "base64")
