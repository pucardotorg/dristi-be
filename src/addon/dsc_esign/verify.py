"""Verify a client-supplied detached PKCS#7 against the prepared document (spec 0038 #8.1).

Because a DSC signature arrives from the signer's own client, the server cannot
trust it: it binds the CMS to this document's digest, verifies the signature with
the embedded certificate, and applies the certificate policy before the signature
is embedded and stored.

Failures map onto the domain's client-signature codes:
  * digest / algorithm mismatch -> ESignClientSignatureMismatch
  * unusable CMS or bad signature -> ESignClientSignatureInvalid
  * certificate policy / signer binding -> ESignCertificateNotPermitted
"""

import asyncio
import hashlib
from datetime import UTC, datetime

from asn1crypto import cms
from asn1crypto import x509 as asn1_x509
from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa
from django.utils.module_loading import import_string

from apps.esign.exceptions import (
    ESignCertificateNotPermitted,
    ESignClientSignatureInvalid,
    ESignClientSignatureMismatch,
    ESignError,
)
from apps.esign.providers.base import ESignProviderResponse

from . import constants

_HASHES = {"sha256": hashes.SHA256, "sha384": hashes.SHA384, "sha512": hashes.SHA512}


def verify_client_signature(transaction, pkcs7: bytes, config) -> ESignProviderResponse:
    """Verify ``pkcs7`` against ``transaction`` and return the response audit.

    Every step after parsing runs under a catch-all so a malformed CMS always
    surfaces as a 4xx client error (``ESignClientSignatureInvalid``) rather than
    a 500 — otherwise the row is left stuck in ``SIGNING``. Domain errors
    (mismatch, certificate policy) are re-raised unchanged.
    """

    signed_data, signer_info = _parse(pkcs7)
    try:
        digest_algorithm = _digest_algorithm(signer_info, config)
        _check_message_digest(signer_info, transaction.document_hash)

        cert_der = _signer_certificate(signed_data, signer_info)
        cert = _load_cert(cert_der)
        _verify_signature(signer_info, cert, digest_algorithm)

        # Validity is evaluated at the server's clock, never the client-chosen
        # signingTime attribute (which is recorded only for audit).
        _check_certificate(cert, datetime.now(UTC))
        _check_trust_chain(cert_der, signed_data, config)

        audit = _certificate_audit(cert_der, cert)
        signing_time = _signing_time(signer_info)
    except ESignError:
        raise
    except Exception as exc:
        raise ESignClientSignatureInvalid() from exc

    _check_registered_binding(transaction, audit["certificate_fingerprint"], config)

    return ESignProviderResponse(
        provider_transaction_id=f"{constants.TRANSACTION_ID_PREFIX}-{transaction.pk}",
        success=True,
        signed_at=signing_time,
        response_audit=audit,
    )


def _parse(pkcs7: bytes):
    """Load the CMS SignedData and its single signer, or raise invalid.

    ``dump(force=True)`` forces full structural parsing up front, so lazy
    ``asn1crypto`` parse errors surface here as a client error rather than deeper
    in verification where they would escape as a 500.
    """

    try:
        content_info = cms.ContentInfo.load(pkcs7)
        if content_info["content_type"].native != "signed_data":
            raise ESignClientSignatureInvalid("The signature is not a CMS SignedData.")
        content_info.dump(force=True)
        signed_data = content_info["content"]
        signer_infos = signed_data["signer_infos"]
    except ESignClientSignatureInvalid:
        raise
    except Exception as exc:
        raise ESignClientSignatureInvalid() from exc
    if len(signer_infos) != 1:
        raise ESignClientSignatureInvalid("Exactly one signer is required.")
    return signed_data, signer_infos[0]


def _digest_algorithm(signer_info, config) -> str:
    """Return the CMS digest name, requiring it to match the configured one."""

    try:
        name = signer_info["digest_algorithm"]["algorithm"].native
    except Exception as exc:
        raise ESignClientSignatureInvalid() from exc
    name = (name or "").lower()
    if name not in _HASHES:
        raise ESignClientSignatureInvalid(f"Unsupported digest algorithm {name!r}.")
    if name != config.hash_algorithm.lower():
        raise ESignClientSignatureMismatch("The signature uses the wrong digest algorithm.")
    return name


def _signed_attrs(signer_info):
    """Return the CMS signed attributes, or raise invalid (detached needs them)."""

    signed_attrs = signer_info["signed_attrs"]
    if signed_attrs is None or len(signed_attrs) == 0:
        raise ESignClientSignatureInvalid("The signature carries no signed attributes.")
    return signed_attrs


def _check_message_digest(signer_info, document_hash: str) -> None:
    """Require the ``messageDigest`` attribute to equal this document's digest."""

    message_digest = None
    for attr in _signed_attrs(signer_info):
        if attr["type"].native == "message_digest":
            message_digest = attr["values"][0].native
            break
    if message_digest is None:
        raise ESignClientSignatureInvalid("The signature carries no message digest.")
    try:
        expected = bytes.fromhex(document_hash)
    except ValueError as exc:
        raise ESignClientSignatureInvalid() from exc
    if message_digest != expected:
        raise ESignClientSignatureMismatch()


def _signer_certificate(signed_data, signer_info) -> bytes:
    """Return the DER of the certificate that matches the signer identifier."""

    certificates = signed_data["certificates"]
    if certificates is None or len(certificates) == 0:
        raise ESignClientSignatureInvalid("The signature carries no certificate.")

    sid = signer_info["sid"]
    candidates = []
    for choice in certificates:
        if choice.name != "certificate":
            continue
        cert = choice.chosen
        candidates.append(cert)
        if _matches_sid(cert, sid):
            return cert.dump()
    if len(candidates) == 1:
        return candidates[0].dump()
    raise ESignClientSignatureInvalid("The signer certificate is not in the signature.")


def _matches_sid(cert, sid) -> bool:
    """Whether ``cert`` matches the CMS signer identifier."""

    try:
        if sid.name == "issuer_and_serial_number":
            chosen = sid.chosen
            return (
                cert.issuer == chosen["issuer"]
                and cert.serial_number == chosen["serial_number"].native
            )
        # subject_key_identifier
        return cert.key_identifier == sid.chosen.native
    except Exception:
        return False


def _load_cert(cert_der: bytes):
    """Load the signer certificate with ``cryptography``."""

    try:
        return x509.load_der_x509_certificate(cert_der)
    except Exception as exc:
        raise ESignClientSignatureInvalid() from exc


def _verify_signature(signer_info, cert, digest_algorithm: str) -> None:
    """Verify the signature over the signed attributes with the certificate."""

    to_verify = _signed_attrs(signer_info).untag().dump()
    signature = signer_info["signature"].native
    public_key = cert.public_key()
    hash_cls = _HASHES[digest_algorithm]
    try:
        algo = signer_info["signature_algorithm"].signature_algo
    except Exception as exc:
        raise ESignClientSignatureInvalid() from exc

    try:
        if isinstance(public_key, rsa.RSAPublicKey):
            if algo == "rsassa_pss":
                public_key.verify(
                    signature,
                    to_verify,
                    padding.PSS(mgf=padding.MGF1(hash_cls()), salt_length=padding.PSS.AUTO),
                    hash_cls(),
                )
            else:
                public_key.verify(signature, to_verify, padding.PKCS1v15(), hash_cls())
        elif isinstance(public_key, ec.EllipticCurvePublicKey):
            public_key.verify(signature, to_verify, ec.ECDSA(hash_cls()))
        else:
            raise ESignClientSignatureInvalid("Unsupported signing key type.")
    except InvalidSignature as exc:
        raise ESignClientSignatureInvalid() from exc


def _signing_time(signer_info) -> datetime:
    """Return the signing-time attribute, or now if absent."""

    for attr in _signed_attrs(signer_info):
        if attr["type"].native == "signing_time":
            return attr["values"][0].native
    return datetime.now(UTC)


def _check_certificate(cert, moment: datetime) -> None:
    """Check the validity period at ``moment`` and that signing is permitted.

    ``moment`` is the server clock, not the client's signingTime attribute, so a
    backdated signingTime cannot resurrect an expired certificate.
    """

    if not (cert.not_valid_before_utc <= moment <= cert.not_valid_after_utc):
        raise ESignCertificateNotPermitted("The certificate is not currently valid.")

    try:
        key_usage = cert.extensions.get_extension_for_class(x509.KeyUsage).value
    except x509.ExtensionNotFound:
        return
    if not (key_usage.digital_signature or key_usage.content_commitment):
        raise ESignCertificateNotPermitted("The certificate may not be used for signing.")


def _check_trust_chain(cert_der: bytes, signed_data, config) -> None:
    """Require the signer certificate to chain to a configured trust anchor.

    ``DSC_ESIGN_TRUST_ROOTS`` points at a PEM bundle (or directory) of the India
    CCA roots/intermediates. When it is set, the signer certificate must build a
    valid path to one of those anchors, using any intermediates carried in the
    CMS; a self-signed or otherwise untrusted certificate is refused. When it is
    not set, verification refuses untrusted certificates unless
    ``DSC_ESIGN_ALLOW_UNTRUSTED_CERT`` is explicitly enabled (non-production
    only), so the default never silently accepts an arbitrary self-signed cert.
    """

    roots = _load_trust_roots(config.trust_roots)
    if not roots:
        if config.allow_untrusted_cert:
            return
        raise ESignCertificateNotPermitted(
            "DSC trust is not configured (set DSC_ESIGN_TRUST_ROOTS)."
        )

    from pyhanko_certvalidator import CertificateValidator, ValidationContext
    from pyhanko_certvalidator.errors import PathError, ValidationError

    intermediates = _cms_certificates(signed_data)
    context = ValidationContext(trust_roots=roots, allow_fetching=False)
    validator = CertificateValidator(
        asn1_x509.Certificate.load(cert_der),
        intermediate_certs=intermediates,
        validation_context=context,
    )
    try:
        asyncio.run(validator.async_validate_usage(key_usage=set()))
    except (PathError, ValidationError) as exc:
        raise ESignCertificateNotPermitted(
            "The certificate does not chain to a trusted root."
        ) from exc


def _load_trust_roots(trust_roots: str) -> list:
    """Load CCA trust anchors from a PEM bundle or directory; [] when unset."""

    if not trust_roots:
        return []
    import os

    from asn1crypto import pem

    paths = []
    if os.path.isdir(trust_roots):
        paths = [os.path.join(trust_roots, name) for name in sorted(os.listdir(trust_roots))]
    else:
        paths = [trust_roots]

    roots = []
    for path in paths:
        try:
            with open(path, "rb") as handle:
                data = handle.read()
        except OSError:
            continue
        for _, _, der in pem.unarmor(data, multiple=True):
            roots.append(asn1_x509.Certificate.load(der))
    return roots


def _cms_certificates(signed_data) -> list:
    """Every certificate carried in the CMS, as asn1crypto objects."""

    certificates = signed_data["certificates"]
    if certificates is None:
        return []
    return [choice.chosen for choice in certificates if choice.name == "certificate"]


def _certificate_audit(cert_der: bytes, cert) -> dict:
    """Return persistable certificate metadata (never the certificate itself).

    Keys are chosen so ``apps.esign``'s audit redaction keeps them.
    """

    return {
        "provider": constants.PROVIDER_NAME,
        "certificate_subject": cert.subject.rfc4514_string()[:256],
        "certificate_issuer": cert.issuer.rfc4514_string()[:256],
        "certificate_serial": format(cert.serial_number, "x"),
        "certificate_fingerprint": hashlib.sha256(cert_der).hexdigest(),
    }


def _check_registered_binding(transaction, fingerprint: str, config) -> None:
    """Enforce that the certificate belongs to the signer (spec 0038 #8.1.4).

    The identity source is an open question (#18.1); until it is settled the
    binding is off by default and the fingerprint is recorded for audit. When
    enabled, ``DSC_ESIGN_IDENTITY_RESOLVER`` returns the acceptable fingerprints
    for the transaction's signer.
    """

    if not config.require_registered_cert:
        return
    if not config.identity_resolver:
        raise ESignCertificateNotPermitted(
            "Registered-DSC binding is required but no identity resolver is configured."
        )
    resolver = import_string(config.identity_resolver)
    expected = resolver(transaction)
    if not expected:
        raise ESignCertificateNotPermitted("No registered DSC certificate for this signer.")
    if fingerprint.lower() not in {str(value).lower() for value in expected}:
        raise ESignCertificateNotPermitted()
