"""Decrypt and validate the encrypted e-GRAS payment response (spec 0022 #5.4).

e-GRAS v3.7 posts the return-URL callback as a single ``payRes`` parameter — an
AES-GCM-encrypted, base64 string — instead of plain form fields. This module
turns ``payRes`` back into the payment fields and computes the documented
checksum.

AES-GCM is *authenticated* encryption: a ``payRes`` tampered in transit fails to
decrypt, so a successful decryption already proves integrity under the shared
key. The checksum is therefore a redundant extra check that is logged, not
enforced. Either way the decrypted fields stay an untrusted *hint*: the
authoritative outcome still comes from the server-to-server GRN lookup (#6).
"""

import base64
import binascii
import hashlib
import json
from collections.abc import Mapping

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

# e-GRAS prepends a 16-byte random nonce to the ciphertext (which carries the
# 128-bit GCM tag), then base64-encodes the whole blob (Annexure B).
NONCE_LENGTH = 16

# Fields hashed for the checksum, in order, joined by ``|`` (SOP §4).
CHECKSUM_FIELDS = (
    "GRN",
    "status",
    "Applicationnumber",
    "CIN",
    "tdate",
    "payment_type",
    "bankcode",
    "amount",
)


class ResponseDecryptionError(Exception):
    """``payRes`` could not be base64-decoded, decrypted or parsed as JSON."""


def decrypt_pay_res(pay_res: str, key: bytes) -> dict:
    """Decrypt the ``payRes`` blob to the payment-fields JSON object.

    ``key`` is the shared symmetric key NIC issues (16/24/32 bytes). Raises
    :class:`ResponseDecryptionError` on any malformed, tampered or unreadable
    input so the caller can treat the callback as uncorrelatable.
    """

    try:
        blob = base64.b64decode(pay_res, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ResponseDecryptionError("payRes is not valid base64.") from exc

    if len(blob) <= NONCE_LENGTH:
        raise ResponseDecryptionError("payRes is too short to hold a nonce and ciphertext.")

    nonce, ciphertext = blob[:NONCE_LENGTH], blob[NONCE_LENGTH:]
    try:
        plaintext = AESGCM(key).decrypt(nonce, ciphertext, None)
    except (InvalidTag, ValueError) as exc:
        raise ResponseDecryptionError(
            "payRes could not be decrypted (bad key or tampered)."
        ) from exc

    try:
        data = json.loads(plaintext.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ResponseDecryptionError("Decrypted payRes is not valid JSON.") from exc

    if not isinstance(data, dict):
        raise ResponseDecryptionError("Decrypted payRes is not a JSON object.")
    return data


def expected_checksum(data: Mapping) -> str:
    """SHA-256 hex of the pipe-joined checksum fields (SOP §4)."""

    joined = "|".join(str(data.get(field, "")) for field in CHECKSUM_FIELDS)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def checksum_matches(data: Mapping) -> bool:
    """Whether the response's ``checksum`` matches the computed one."""

    received = str(data.get("checksum", "") or "").strip().lower()
    return bool(received) and received == expected_checksum(data)
