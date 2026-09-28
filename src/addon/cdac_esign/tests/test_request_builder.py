"""Request XML tests (spec 0015 #7.1)."""

import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

from django.test import SimpleTestCase
from lxml import etree

from addon.cdac_esign import constants
from addon.cdac_esign.config import CDACESignConfig
from addon.cdac_esign.request_builder import (
    build_request_xml,
    build_transaction_id,
    format_timestamp,
)

CONFIG = CDACESignConfig(
    url="https://esign.cdac.invalid/esign",
    asp_id="ASP-TEST",
    response_url="https://dristi.invalid/api/v1/esign/_signed",
    keystore_path="/dev/null",
    keystore_password="secret",
)


class TransactionIdTests(SimpleTestCase):
    """The ESP correlation id."""

    def test_template_embeds_the_module_and_uuid(self):
        """The internal UUID keeps the id collision free and traceable."""
        transaction_id = str(uuid.uuid4())
        self.assertEqual(
            build_transaction_id(CONFIG, module="orders", transaction_id=transaction_id),
            f"orders-{transaction_id}",
        )

    def test_template_is_configurable(self):
        """C-DAC can change the format without a code change."""
        config = CDACESignConfig(txn_template="dristi/{module}/{transaction_id}")
        self.assertEqual(
            build_transaction_id(config, module="orders", transaction_id="abc"),
            "dristi/orders/abc",
        )

    def test_long_ids_are_truncated_keeping_the_uuid(self):
        """Truncation must not destroy uniqueness."""
        transaction_id = str(uuid.uuid4())
        rendered = build_transaction_id(
            CDACESignConfig(txn_template="{module}-{transaction_id}"),
            module="a" * 100,
            transaction_id=transaction_id,
        )
        self.assertEqual(len(rendered), constants.MAX_TRANSACTION_ID_LENGTH)
        self.assertTrue(rendered.endswith(transaction_id))


class TimestampTests(SimpleTestCase):
    """``ts`` formatting."""

    def test_timestamp_is_ist_without_a_suffix(self):
        """C-DAC expects IST in yyyy-MM-dd'T'HH:mm:ss with no offset."""
        moment = datetime(2026, 9, 22, 12, 10, 3, tzinfo=ZoneInfo("UTC"))
        self.assertEqual(format_timestamp(moment), "2026-09-22T17:40:03")


class RequestXMLTests(SimpleTestCase):
    """The ``<Esign>`` document."""

    def build(self, **overrides):
        """Build and parse a request document."""

        kwargs = {
            "transaction_id": "orders-0f9d",
            "document_hash": "a1b2c3",
            "doc_info": "ORDER 9f2c",
            "timestamp": datetime(2026, 9, 22, 12, 10, 3, tzinfo=ZoneInfo("UTC")),
        }
        kwargs.update(overrides)
        return etree.fromstring(build_request_xml(CONFIG, **kwargs))

    def test_every_required_attribute_is_present(self):
        """The attributes and defaults of #7.1."""
        root = self.build()

        self.assertEqual(root.tag, "Esign")
        self.assertEqual(root.get("ver"), "2.1")
        self.assertEqual(root.get("sc"), "Y")
        self.assertEqual(root.get("ts"), "2026-09-22T17:40:03")
        self.assertEqual(root.get("txn"), "orders-0f9d")
        self.assertEqual(root.get("ekycIdType"), "A")
        self.assertEqual(root.get("aspId"), "ASP-TEST")
        self.assertEqual(root.get("AuthMode"), "1")
        self.assertEqual(root.get("responseSigType"), "pkcs7")
        self.assertEqual(root.get("responseUrl"), "https://dristi.invalid/api/v1/esign/_signed")

    def test_exactly_one_input_hash_is_emitted(self):
        """This iteration signs one document per transaction."""
        root = self.build()
        hashes = root.findall("./Docs/InputHash")

        self.assertEqual(len(hashes), constants.EXPECTED_SIGNATURE_COUNT)
        self.assertEqual(hashes[0].text, "a1b2c3")
        self.assertEqual(hashes[0].get("hashAlgorithm"), "SHA256")
        self.assertEqual(hashes[0].get("id"), "1")
        self.assertEqual(hashes[0].get("docInfo"), "ORDER 9f2c")
        self.assertEqual(hashes[0].get("docUrl"), "")

    def test_document_bytes_are_never_sent(self):
        """Only the hash travels to the ESP."""
        xml = build_request_xml(
            CONFIG,
            transaction_id="orders-0f9d",
            document_hash="a1b2c3",
            doc_info="ORDER",
            timestamp=datetime(2026, 9, 22, 12, 10, 3, tzinfo=ZoneInfo("UTC")),
        )
        self.assertNotIn(b"%PDF", xml)

    def test_a_missing_hash_is_refused(self):
        """There is nothing to sign without a digest."""
        with self.assertRaises(ValueError):
            build_request_xml(
                CONFIG,
                transaction_id="orders-0f9d",
                document_hash="",
                doc_info="ORDER",
                timestamp=datetime(2026, 9, 22, 12, 10, 3, tzinfo=ZoneInfo("UTC")),
            )
