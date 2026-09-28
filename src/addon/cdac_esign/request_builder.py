"""The ``<Esign>`` 2.1 request document (spec 0015 #7.1).

Only the hash of the document is sent: the document itself never leaves Dristi.
"""

from datetime import datetime

from lxml import etree

from . import constants
from .config import CDACESignConfig


def build_transaction_id(config: CDACESignConfig, *, module: str, transaction_id: str) -> str:
    """Render the ESP correlation id from the configured template.

    The internal UUID is part of the id, which keeps it collision free and
    makes a support lookup in either system trivial. Truncation keeps the tail
    (the UUID) rather than the head, so uniqueness survives the ESP limit.
    """

    rendered = config.txn_template.format(module=module or "", transaction_id=transaction_id)
    if len(rendered) > constants.MAX_TRANSACTION_ID_LENGTH:
        rendered = rendered[-constants.MAX_TRANSACTION_ID_LENGTH :]
    return rendered


def format_timestamp(moment: datetime) -> str:
    """Return ``moment`` as IST with no timezone suffix, as C-DAC expects."""

    return moment.astimezone(constants.IST).strftime(constants.TIMESTAMP_FORMAT)


def build_request_xml(
    config: CDACESignConfig,
    *,
    transaction_id: str,
    document_hash: str,
    doc_info: str,
    timestamp: datetime,
) -> bytes:
    """Return the unsigned ``<Esign>`` document as UTF-8 XML bytes."""

    if not document_hash:
        raise ValueError("A document hash is required to build an eSign request.")

    root = etree.Element(
        constants.ESIGN_ELEMENT,
        {
            "ver": config.version,
            "sc": config.consent,
            "ts": format_timestamp(timestamp),
            "txn": transaction_id,
            "ekycIdType": config.ekyc_id_type,
            "aspId": config.asp_id,
            "AuthMode": config.auth_mode,
            "responseSigType": constants.RESPONSE_SIG_TYPE,
            "responseUrl": config.response_url,
        },
    )
    docs = etree.SubElement(root, constants.DOCS_ELEMENT)
    # The structure supports several InputHash elements; this iteration emits
    # exactly one and the parser rejects a response with a different count.
    input_hash = etree.SubElement(
        docs,
        constants.INPUT_HASH_ELEMENT,
        {
            "id": constants.INPUT_HASH_ID,
            "hashAlgorithm": config.hash_algorithm,
            "docInfo": doc_info or "",
            "docUrl": "",
        },
    )
    input_hash.text = document_hash

    return etree.tostring(root, xml_declaration=False, encoding="UTF-8")
