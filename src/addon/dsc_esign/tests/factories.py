"""Test helpers: a software signer standing in for the DSC token (spec 0038 #14).

Mirrors exactly what the real local agent does — ``async_sign(data_digest=...,
use_pades=False)`` — so the tests exercise the same CMS the token produces, not a
hand-rolled structure.
"""

import asyncio
import base64
import datetime

from asn1crypto import keys as asn1_keys
from asn1crypto import x509 as asn1_x509
from cryptography import x509 as cx509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from pyhanko.sign import signers
from pyhanko_certvalidator.registry import SimpleCertificateStore


def make_signer(
    *,
    common_name: str = "Judge Test",
    not_valid_before: datetime.datetime | None = None,
    not_valid_after: datetime.datetime | None = None,
    digital_signature: bool = True,
    content_commitment: bool = True,
    include_key_usage: bool = True,
) -> signers.SimpleSigner:
    """Build a self-signed software signer with the given validity/key usage."""

    now = datetime.datetime.now(datetime.UTC)
    not_valid_before = not_valid_before or (now - datetime.timedelta(days=1))
    not_valid_after = not_valid_after or (now + datetime.timedelta(days=365))

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = cx509.Name([cx509.NameAttribute(NameOID.COMMON_NAME, common_name)])
    builder = (
        cx509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(cx509.random_serial_number())
        .not_valid_before(not_valid_before)
        .not_valid_after(not_valid_after)
    )
    if include_key_usage:
        builder = builder.add_extension(
            cx509.KeyUsage(
                digital_signature=digital_signature,
                content_commitment=content_commitment,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
    cert = builder.sign(key, hashes.SHA256())

    signing_cert = asn1_x509.Certificate.load(cert.public_bytes(serialization.Encoding.DER))
    signing_key = asn1_keys.PrivateKeyInfo.load(
        key.private_bytes(
            serialization.Encoding.DER,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    return signers.SimpleSigner(
        signing_cert=signing_cert,
        signing_key=signing_key,
        cert_registry=SimpleCertificateStore(),
    )


def detached_cms(signer: signers.SimpleSigner, digest: bytes, *, digest_algorithm: str = "sha256"):
    """Return the ``asn1crypto`` ContentInfo the agent would return for ``digest``."""

    return asyncio.run(
        signer.async_sign(
            data_digest=digest,
            digest_algorithm=digest_algorithm,
            use_pades=False,
        )
    )


def pkcs7_b64(
    signer: signers.SimpleSigner, digest: bytes, *, digest_algorithm: str = "sha256"
) -> str:
    """Base64 of the detached CMS, as the agent posts it back."""

    return base64.b64encode(
        detached_cms(signer, digest, digest_algorithm=digest_algorithm).dump()
    ).decode()
