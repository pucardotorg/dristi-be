"""Throw-away key material for the addon tests.

Generated in-process so the repository holds no keys, real or otherwise, and
cached for the session because RSA generation is slow.
"""

import datetime
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID

KEYSTORE_PASSWORD = "keystore-secret"


@dataclass(frozen=True)
class TestKeyPair:
    """A private key with its self-signed certificate."""

    private_key: object
    certificate: object

    @property
    def certificate_pem(self) -> str:
        """PEM encoding of the certificate."""

        return self.certificate.public_bytes(serialization.Encoding.PEM).decode()

    def pkcs12(self, *, password: str = KEYSTORE_PASSWORD, name: bytes = b"asp") -> bytes:
        """Return the pair as a PKCS#12 keystore."""

        return pkcs12.serialize_key_and_certificates(
            name=name,
            key=self.private_key,
            cert=self.certificate,
            cas=None,
            encryption_algorithm=(
                serialization.BestAvailableEncryption(password.encode())
                if password
                else serialization.NoEncryption()
            ),
        )


def generate_key_pair(
    common_name: str = "ASP Test",
    *,
    not_valid_after: datetime.datetime | None = None,
) -> TestKeyPair:
    """Generate a self-signed key pair for tests."""

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])
    now = datetime.datetime.now(datetime.UTC)
    expiry = not_valid_after or (now + datetime.timedelta(days=365))
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        # An already-expired certificate is a valid test fixture, so the start
        # date follows the expiry rather than the other way round.
        .not_valid_before(min(now, expiry) - datetime.timedelta(days=1))
        .not_valid_after(expiry)
        .sign(private_key, hashes.SHA256())
    )
    return TestKeyPair(private_key=private_key, certificate=certificate)


@lru_cache(maxsize=1)
def asp_key_pair() -> TestKeyPair:
    """The ASP key pair used across the addon tests."""

    return generate_key_pair("ASP Test")


@lru_cache(maxsize=1)
def esp_key_pair() -> TestKeyPair:
    """The key pair standing in for the C-DAC ESP's response key."""

    return generate_key_pair("CDAC ESP Test")


@lru_cache(maxsize=1)
def signer_key_pair() -> TestKeyPair:
    """The key pair standing in for the Aadhaar signer certificate."""

    return generate_key_pair("Signer Test")


def write_keystore(directory: Path, *, key_pair=None, password: str = KEYSTORE_PASSWORD) -> str:
    """Write a PKCS#12 keystore into ``directory`` and return its path."""

    keystore = Path(directory) / "asp.p12"
    keystore.write_bytes((key_pair or asp_key_pair()).pkcs12(password=password))
    return str(keystore)
