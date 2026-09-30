"""Password hashing and request signing for the CDAC gateway."""

import hashlib


def generate_password_hash(password: str) -> str:
    """Return the SHA-1 hex digest of the password over ISO-8859-1 bytes.

    CDAC expects the hash, never the plaintext password.
    """

    return hashlib.sha1(password.encode("iso-8859-1")).hexdigest()  # noqa: S324


def generate_signature(username: str, sender_id: str, content: str, secure_key: str) -> str:
    """Return the SHA-512 request signature.

    The components are concatenated verbatim, with no separators and no
    trimming: CDAC recomputes the digest over the field values it receives, so
    the caller must sign exactly the values it puts on the wire. ``content``
    must be the final content, i.e. after any Unicode entity encoding.
    """

    joined = f"{username}{sender_id}{content}{secure_key}"
    return hashlib.sha512(joined.encode("utf-8")).hexdigest()
