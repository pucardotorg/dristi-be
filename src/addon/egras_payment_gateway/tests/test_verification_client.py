"""SOAP GRN verification tests (spec 0022 #6.1), with e-GRAS mocked out."""

from unittest import mock

import requests
from django.test import SimpleTestCase

from addon.egras_payment_gateway import constants, verification_client
from apps.payments.providers.base import ProviderTransientError

from .base import make_config

APPLICATION_NUMBER = "DR0F9D3A6C1B2E4F5A7B"

SUCCESS_XML = b"""<?xml version="1.0"?>
<GrnDetails>
  <GRN>1231234</GRN>
  <Amount>775</Amount>
  <Purpose>Dristi DMD-1</Purpose>
  <Status>Successfull</Status>
  <CIN>CIN123</CIN>
  <Bankdate>12/10/2026</Bankdate>
</GrnDetails>"""

NAMESPACED_XML = b"""<?xml version="1.0"?>
<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Body>
    <GrnDetails xmlns="http://egras.nic.in/">
      <GRN>1231234</GRN>
      <Status>Success</Status>
      <CIN>CIN123</CIN>
      <Amount>775</Amount>
    </GrnDetails>
  </soap:Body>
</soap:Envelope>"""

# The real .NET response (grn_status.asmx): GetGrnDetails_identity returns an
# ArrayOfGrnDetails wrapped in the response/result elements, namespace tempuri.
ARRAY_RESPONSE_XML = b"""<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Body>
    <GetGrnDetails_identityResponse xmlns="http://tempuri.org/">
      <GetGrnDetails_identityResult>
        <GrnDetails>
          <GRN>1231234</GRN>
          <Amount>775</Amount>
          <Purpose>Dristi DMD-1</Purpose>
          <Status>Successfull</Status>
          <CIN>CIN123</CIN>
          <Bankdate>12/10/2026</Bankdate>
        </GrnDetails>
      </GetGrnDetails_identityResult>
    </GetGrnDetails_identityResponse>
  </soap:Body>
</soap:Envelope>"""

ENTITY_EXPANSION_XML = (
    b'<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY a "aaaaaaaaaa">]>'
    b"<GrnDetails><Status>&a;</Status></GrnDetails>"
)


def _response(content, *, status_code=200):
    response = mock.Mock(spec=requests.Response)
    response.content = content
    response.status_code = status_code
    response.ok = 200 <= status_code < 300
    return response


class EnvelopeTests(SimpleTestCase):
    def test_lookup_is_by_identity_not_grn(self):
        envelope = verification_client.build_envelope(APPLICATION_NUMBER, "DRI")
        self.assertIn(constants.SOAP_OPERATION, envelope)
        self.assertIn(f"<{constants.SOAP_PARAM_APPLICATION}>{APPLICATION_NUMBER}", envelope)
        self.assertIn(f"<{constants.SOAP_PARAM_DEPT_CODE}>DRI", envelope)
        self.assertNotIn("GRN", envelope)

    def test_matches_the_live_wsdl(self):
        """Namespace, SOAPAction and param names come from grn_status.asmx?WSDL."""
        self.assertEqual(constants.SOAP_NAMESPACE, "http://tempuri.org/")
        self.assertEqual(constants.SOAP_ACTION, "http://tempuri.org/GetGrnDetails_identity")
        self.assertEqual(constants.SOAP_PARAM_APPLICATION, "identity")
        self.assertEqual(constants.SOAP_PARAM_DEPT_CODE, "dept")
        envelope = verification_client.build_envelope(APPLICATION_NUMBER, "DRI")
        self.assertIn('<GetGrnDetails_identity xmlns="http://tempuri.org/">', envelope)


class FetchGrnDetailsTests(SimpleTestCase):
    def setUp(self):
        self.config = make_config()

    def _fetch(self, response):
        with mock.patch.object(requests, "post", return_value=response) as post:
            details = verification_client.fetch_grn_details(
                self.config, provider_payment_id=APPLICATION_NUMBER
            )
        return details, post

    def test_success_is_parsed(self):
        details, post = self._fetch(_response(SUCCESS_XML))
        self.assertEqual(details[constants.GRN_ELEMENT], "1231234")
        self.assertEqual(details[constants.STATUS_ELEMENT], "Successfull")
        self.assertEqual(details[constants.CIN_ELEMENT], "CIN123")

    def test_tls_and_timeout_are_applied(self):
        _, post = self._fetch(_response(SUCCESS_XML))
        kwargs = post.call_args.kwargs
        self.assertEqual(kwargs["timeout"], self.config.timeout)
        self.assertTrue(kwargs["verify"])
        self.assertEqual(kwargs["headers"]["SOAPAction"], constants.SOAP_ACTION)

    def test_namespaced_response_is_parsed(self):
        details, _ = self._fetch(_response(NAMESPACED_XML))
        self.assertEqual(details[constants.GRN_ELEMENT], "1231234")

    def test_array_of_grndetails_response_is_parsed(self):
        """The real .NET ArrayOfGrnDetails wrapper is unwrapped by local name."""
        details, _ = self._fetch(_response(ARRAY_RESPONSE_XML))
        self.assertEqual(details[constants.GRN_ELEMENT], "1231234")
        self.assertEqual(details[constants.STATUS_ELEMENT], "Successfull")
        self.assertEqual(details[constants.CIN_ELEMENT], "CIN123")

    def test_timeout_is_transient(self):
        with mock.patch.object(requests, "post", side_effect=requests.Timeout()):
            with self.assertRaises(ProviderTransientError) as caught:
                verification_client.fetch_grn_details(
                    self.config, provider_payment_id=APPLICATION_NUMBER
                )
        self.assertEqual(caught.exception.code, constants.EGRAS_VERIFY_TIMEOUT)

    def test_connection_error_is_transient(self):
        with mock.patch.object(requests, "post", side_effect=requests.ConnectionError()):
            with self.assertRaises(ProviderTransientError) as caught:
                verification_client.fetch_grn_details(
                    self.config, provider_payment_id=APPLICATION_NUMBER
                )
        self.assertEqual(caught.exception.code, constants.EGRAS_VERIFY_UNAVAILABLE)

    def test_non_2xx_is_transient(self):
        with self.assertRaises(ProviderTransientError) as caught:
            self._fetch(_response(b"error", status_code=503))
        self.assertEqual(caught.exception.code, constants.EGRAS_VERIFY_UNAVAILABLE)

    def test_malformed_xml_is_transient(self):
        with self.assertRaises(ProviderTransientError) as caught:
            self._fetch(_response(b"<not-xml"))
        self.assertEqual(caught.exception.code, constants.EGRAS_VERIFY_MALFORMED)

    def test_missing_grn_details_is_transient(self):
        with self.assertRaises(ProviderTransientError) as caught:
            self._fetch(_response(b"<Envelope><Body/></Envelope>"))
        self.assertEqual(caught.exception.code, constants.EGRAS_VERIFY_MALFORMED)

    def test_entity_expansion_is_rejected(self):
        with self.assertRaises(ProviderTransientError) as caught:
            self._fetch(_response(ENTITY_EXPANSION_XML))
        self.assertEqual(caught.exception.code, constants.EGRAS_VERIFY_MALFORMED)
