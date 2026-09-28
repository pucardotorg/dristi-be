"""Response parsing tests (spec 0015 #7.3)."""

import base64
from datetime import timedelta

from django.test import SimpleTestCase
from django.utils import timezone

from addon.cdac_esign.config import CDACESignConfig
from addon.cdac_esign.response_parser import (
    SIGNATURE_INVALID,
    SIGNATURE_MISSING,
    SIGNATURE_OK,
    CDACResponseMalformed,
    extract_response_document,
    is_pkcs7_signed_data,
    parse_response_xml,
)

from .responses import PKCS7_BASE64, PKCS7_BLOB, build_response, signer_certificate_base64


class ExtractionTests(SimpleTestCase):
    """Finding the response document in a callback payload."""

    def test_configured_field_wins(self):
        """The ASP onboarding pack decides the field name."""
        config = CDACESignConfig(response_field="esignResp")
        self.assertEqual(
            extract_response_document({"esignResp": "<EsignResp/>", "msg": "other"}, config),
            "<EsignResp/>",
        )

    def test_known_field_names_are_tried(self):
        """The names seen in practice are recognised without configuration."""
        self.assertEqual(
            extract_response_document({"msg": "<EsignResp/>"}, CDACESignConfig()),
            "<EsignResp/>",
        )

    def test_raw_xml_body_is_accepted(self):
        """An interceptor may forward the document as the request body."""
        self.assertEqual(
            extract_response_document({"response_xml": "<EsignResp/>"}, CDACESignConfig()),
            "<EsignResp/>",
        )

    def test_unnamed_document_is_recognised(self):
        """A response under an unexpected key is still found."""
        self.assertEqual(
            extract_response_document({"weird": "<EsignResp txn='a'/>"}, CDACESignConfig()),
            "<EsignResp txn='a'/>",
        )

    def test_payload_without_a_document_is_malformed(self):
        """A payload with nothing to parse is rejected."""
        with self.assertRaises(CDACResponseMalformed):
            extract_response_document({"unrelated": "value"}, CDACESignConfig())


class ParsingTests(SimpleTestCase):
    """The ``<EsignResp>`` document."""

    def test_successful_response_is_parsed(self):
        """Status 1 with a PKCS#7 signature is a success."""
        parsed = parse_response_xml(build_response(txn="orders-1"))

        self.assertTrue(parsed.success)
        self.assertEqual(parsed.transaction_id, "orders-1")
        self.assertEqual(parsed.signature, PKCS7_BASE64)
        self.assertEqual(parsed.signature_error, SIGNATURE_OK)
        self.assertEqual(parsed.result_code, "OK")
        self.assertIsNotNone(parsed.timestamp)

    def test_failure_status_is_parsed(self):
        """Anything other than 1 is a failure with the ESP's codes."""
        parsed = parse_response_xml(
            build_response(status="0", error_code="ESP-11", error_message="OTP failed")
        )

        self.assertFalse(parsed.success)
        self.assertEqual(parsed.error_code, "ESP-11")
        self.assertEqual(parsed.error_message, "OTP failed")
        self.assertIsNone(parsed.signature)

    def test_empty_signature_is_missing_not_malformed(self):
        """The response still correlates, so the domain can record a failure."""
        parsed = parse_response_xml(build_response(signatures=[("", "")]))

        self.assertFalse(parsed.success)
        self.assertEqual(parsed.signature_error, SIGNATURE_MISSING)

    def test_error_attribute_marks_the_signature_missing(self):
        """A DocSignature with an error carries nothing usable."""
        parsed = parse_response_xml(build_response(signatures=[(PKCS7_BASE64, "E12")]))

        self.assertFalse(parsed.success)
        self.assertEqual(parsed.signature_error, SIGNATURE_MISSING)

    def test_non_base64_signature_is_invalid(self):
        """A signature that cannot be decoded is refused."""
        parsed = parse_response_xml(build_response(signatures=[("not base64 !!", "")]))

        self.assertFalse(parsed.success)
        self.assertEqual(parsed.signature_error, SIGNATURE_INVALID)

    def test_non_pkcs7_signature_is_invalid(self):
        """The blob must parse as PKCS#7 before it reaches the PDF Service."""
        parsed = parse_response_xml(
            build_response(signatures=[(base64.b64encode(b"just bytes").decode(), "")])
        )

        self.assertFalse(parsed.success)
        self.assertEqual(parsed.signature_error, SIGNATURE_INVALID)

    def test_signature_count_mismatch_is_rejected(self):
        """One InputHash was sent, so one signature must come back."""
        with self.assertRaises(CDACResponseMalformed):
            parse_response_xml(build_response(signatures=[(PKCS7_BASE64, ""), (PKCS7_BASE64, "")]))

    def test_missing_transaction_id_is_rejected(self):
        """A response that correlates to nothing cannot be processed."""
        with self.assertRaises(CDACResponseMalformed):
            parse_response_xml(build_response(txn=""))

    def test_malformed_xml_is_rejected(self):
        """An unparsable document is a rejection, not a guess."""
        for document in ("", "   ", "<EsignResp", "<Other txn='a'/>"):
            with self.assertRaises(CDACResponseMalformed):
                parse_response_xml(document)

    def test_unknown_extra_elements_are_ignored(self):
        """The ESP may add fields without breaking the integration."""
        document = build_response().replace("</EsignResp>", "<Extra x='1'/></EsignResp>")
        self.assertTrue(parse_response_xml(document).success)

    def test_certificate_metadata_is_recorded_but_not_the_certificate(self):
        """Only the subject and serial are persistable."""
        parsed = parse_response_xml(build_response())

        self.assertTrue(parsed.certificate_audit["signer_certificate_parsed"])
        self.assertIn("Signer Test", parsed.certificate_audit["signer_certificate_subject"])
        self.assertNotIn(signer_certificate_base64(), str(parsed.certificate_audit))

    def test_unparsable_certificate_is_recorded_as_such(self):
        """A bad certificate does not break parsing; verification is the gate."""
        parsed = parse_response_xml(build_response(certificate="not base64"))
        self.assertFalse(parsed.certificate_audit["signer_certificate_parsed"])

    def test_timestamp_forms_are_accepted(self):
        """C-DAC's IST format and ISO-8601 both parse to an aware datetime."""
        moment = timezone.now() - timedelta(minutes=1)
        parsed = parse_response_xml(build_response(timestamp=moment))

        self.assertIsNotNone(parsed.timestamp)
        self.assertLess(abs((parsed.timestamp - moment).total_seconds()), 2)

    def test_xml_entities_are_not_resolved(self):
        """An XXE payload must not be expanded while parsing."""
        document = (
            '<?xml version="1.0"?>'
            '<!DOCTYPE EsignResp [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>'
            '<EsignResp status="0" txn="orders-1" errMsg="&xxe;"/>'
        )
        with self.assertRaises(CDACResponseMalformed):
            parse_response_xml(document)


class PKCS7StructureTests(SimpleTestCase):
    """The DER prologue check."""

    def test_signed_data_is_recognised(self):
        """A SignedData ContentInfo is accepted."""
        self.assertTrue(is_pkcs7_signed_data(PKCS7_BLOB))

    def test_long_form_lengths_are_handled(self):
        """A real blob is long enough to use multi-byte DER lengths."""
        body = PKCS7_BLOB[2:] + b"\x00" * 300
        der = bytes((0x30, 0x82, len(body) >> 8, len(body) & 0xFF)) + body
        self.assertTrue(is_pkcs7_signed_data(der))

    def test_other_structures_are_rejected(self):
        """Random bytes and other content types are refused."""
        for der in (b"", b"just bytes", bytes((0x30, 0x03, 0x06, 0x01, 0x2A))):
            self.assertFalse(is_pkcs7_signed_data(der))
