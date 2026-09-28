"""ASP key material loading (spec 0015 #7.2, #12).

The ASP private key and certificate come from a deployment-managed PKCS#12
keystore. They are read once, cached in memory, and never written to the
database, a log line, an API response or ``request_audit``.
"""

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.serialization import pkcs12


class CDACKeystoreError(Exception):
    """Raised when the keystore is missing, unreadable or incomplete."""


@dataclass(frozen=True)
class ASPKeyMaterial:
    """The ASP signing key and its certificate."""

    private_key: object = field(repr=False)
    certificate: object = field(repr=False)

    def __repr__(self):
        """Never render key material."""

        return f"ASPKeyMaterial(subject={self.subject!r})"

    @property
    def subject(self) -> str:
        """RFC 4514 subject of the ASP certificate."""

        return self.certificate.subject.rfc4514_string()

    @property
    def not_valid_after(self):
        """Expiry of the ASP certificate as an aware datetime."""

        return self.certificate.not_valid_after_utc

    def certificate_pem(self) -> str:
        """PEM encoding of the ASP certificate (public material only)."""

        return self.certificate.public_bytes(serialization.Encoding.PEM).decode()


def load_key_material(path: str, password: str) -> ASPKeyMaterial:
    """Return the ASP key material held in the keystore at ``path``."""

    if not path:
        raise CDACKeystoreError("No keystore path is configured.")
    keystore = Path(path)
    try:
        stat = keystore.stat()
    except OSError as exc:
        raise CDACKeystoreError("The configured keystore could not be read.") from exc

    # The mtime and size are part of the cache key so a rotated keystore is
    # picked up without a restart, while a hot path still never re-reads it.
    return _load_cached(str(keystore), password, stat.st_mtime_ns, stat.st_size)


@lru_cache(maxsize=2)
def _load_cached(path: str, password: str, mtime_ns: int, size: int) -> ASPKeyMaterial:
    """Load and cache the keystore contents."""

    try:
        data = Path(path).read_bytes()
    except OSError as exc:
        raise CDACKeystoreError("The configured keystore could not be read.") from exc

    try:
        private_key, certificate, _ = pkcs12.load_key_and_certificates(
            data, password.encode() if password else None
        )
    except Exception as exc:
        raise CDACKeystoreError("The keystore could not be opened with the given password.") from (
            exc
        )

    if private_key is None or certificate is None:
        raise CDACKeystoreError("The keystore must hold both a private key and a certificate.")

    return ASPKeyMaterial(private_key=private_key, certificate=certificate)


def reset_keystore_cache() -> None:
    """Clear the cached key material."""

    _load_cached.cache_clear()
