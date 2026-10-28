"""Server-to-server GRN status verification (spec 0022 #6.1).

The only authoritative outcome of an e-GRAS payment comes from this SOAP lookup,
always by our *own* ``Applicationnumber`` and ``Deptcode`` — never by a
callback-supplied GRN, which a forged callback could point at someone else's
successful receipt. The envelope is built by hand and the response parsed with
``defusedxml``, so one operation needs no SOAP framework and an untrusted XML
reply cannot mount an entity-expansion attack.
"""

import logging
import time
from xml.etree.ElementTree import Element

import requests
from defusedxml.common import DefusedXmlException
from defusedxml.ElementTree import ParseError, fromstring

from apps.payments.providers.base import ProviderTransientError

from . import constants

logger = logging.getLogger(constants.LOGGER_NAME)

# An unparsable body and a rejected entity-expansion attack are both "the reply
# cannot be trusted as XML", mapped to the same transient failure.
_XML_ERRORS = (ParseError, DefusedXmlException)

# Elements of interest in the ``<GrnDetails>`` document, by local name.
_WANTED = {
    constants.GRN_ELEMENT,
    constants.AMOUNT_ELEMENT,
    constants.PURPOSE_ELEMENT,
    constants.STATUS_ELEMENT,
    constants.CIN_ELEMENT,
    constants.BANKDATE_ELEMENT,
}


def _local_name(tag: str) -> str:
    """Element local name, dropping any ``{namespace}`` prefix."""

    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def build_envelope(application_number: str, dept_code: str) -> str:
    """The SOAP 1.1 request envelope for the identity lookup."""

    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">'
        "<soap:Body>"
        f'<{constants.SOAP_OPERATION} xmlns="{constants.SOAP_NAMESPACE}">'
        f"<{constants.SOAP_PARAM_APPLICATION}>{application_number}</{constants.SOAP_PARAM_APPLICATION}>"
        f"<{constants.SOAP_PARAM_DEPT_CODE}>{dept_code}</{constants.SOAP_PARAM_DEPT_CODE}>"
        f"</{constants.SOAP_OPERATION}>"
        "</soap:Body>"
        "</soap:Envelope>"
    )


def _extract_details(root: Element) -> dict[str, str] | None:
    """Collect the wanted ``<GrnDetails>`` fields from a parsed response.

    Namespaces vary with the NIC environment, so elements are matched by local
    name. Some deployments wrap the ``<GrnDetails>`` document as escaped XML
    inside a result element; that nested document is parsed once more.
    """

    found = {}
    for element in root.iter():
        name = _local_name(element.tag)
        if name in _WANTED and name not in found:
            found[name] = (element.text or "").strip()

    if found:
        return found

    # The XML-in-a-string case: a single text node that is itself a document.
    for element in root.iter():
        text = (element.text or "").strip()
        if text.startswith("<") and constants.GRN_DETAILS_ELEMENT in text:
            try:
                return _extract_details(fromstring(text))
            except _XML_ERRORS:
                return None
    return None


def fetch_grn_details(config, *, provider_payment_id: str) -> dict[str, str]:
    """Look the transaction up by identity and return the ``GrnDetails`` fields.

    Raises :class:`ProviderTransientError` on timeout, connection failure, a
    non-2xx response or an unparsable body, so the poller retries rather than
    the payment being resolved on a broken answer.
    """

    envelope = build_envelope(provider_payment_id, config.dept_code)
    logger.info(
        "event=%s provider_payment_id=%s dept_code=%s",
        constants.EVENT_VERIFY_REQUEST,
        provider_payment_id,
        config.dept_code,
    )
    started = time.monotonic()
    try:
        response = requests.post(
            config.verify_url,
            data=envelope.encode("utf-8"),
            headers={
                "Content-Type": constants.SOAP_CONTENT_TYPE,
                "SOAPAction": constants.SOAP_ACTION,
            },
            timeout=config.timeout,
            verify=config.verify_ssl,
        )
    except requests.Timeout as exc:
        raise ProviderTransientError(
            constants.EGRAS_VERIFY_TIMEOUT, "The e-GRAS status service timed out."
        ) from exc
    except requests.RequestException as exc:
        raise ProviderTransientError(
            constants.EGRAS_VERIFY_UNAVAILABLE, "The e-GRAS status service is unreachable."
        ) from exc

    latency_ms = int((time.monotonic() - started) * 1000)
    if not response.ok:
        raise ProviderTransientError(
            constants.EGRAS_VERIFY_UNAVAILABLE,
            f"The e-GRAS status service returned HTTP {response.status_code}.",
        )

    try:
        root = fromstring(response.content)
    except _XML_ERRORS as exc:
        raise ProviderTransientError(
            constants.EGRAS_VERIFY_MALFORMED, "The e-GRAS status response was not valid XML."
        ) from exc

    details = _extract_details(root)
    if details is None:
        raise ProviderTransientError(
            constants.EGRAS_VERIFY_MALFORMED,
            "The e-GRAS status response carried no GrnDetails.",
        )

    logger.info(
        "event=%s provider_payment_id=%s egras_status=%r grn=%s amount=%s latency_ms=%d",
        constants.EVENT_VERIFY_RESPONSE,
        provider_payment_id,
        details.get(constants.STATUS_ELEMENT, ""),
        details.get(constants.GRN_ELEMENT, ""),
        details.get(constants.AMOUNT_ELEMENT, ""),
        latency_ms,
    )
    return details
