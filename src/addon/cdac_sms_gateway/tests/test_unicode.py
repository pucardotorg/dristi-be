"""Tests for numeric HTML-entity encoding."""

from django.test import SimpleTestCase

from addon.cdac_sms_gateway.unicode_encoding import is_unicode_content, to_html_entities


class ToHtmlEntitiesTests(SimpleTestCase):
    """Entity encoding tests."""

    def test_single_character(self):
        self.assertEqual(to_html_entities("न"), "&#2344;")

    def test_multiple_characters(self):
        self.assertEqual(
            to_html_entities("नमस्ते"),
            "&#2344;&#2350;&#2360;&#2381;&#2340;&#2375;",
        )

    def test_ascii_is_encoded_too(self):
        self.assertEqual(to_html_entities("Hi"), "&#72;&#105;")

    def test_mixed_content(self):
        self.assertEqual(to_html_entities("A न"), "&#65;&#32;&#2344;")

    def test_empty_string(self):
        self.assertEqual(to_html_entities(""), "")


class IsUnicodeContentTests(SimpleTestCase):
    """Unicode detection tests."""

    def test_ascii_is_not_unicode(self):
        self.assertFalse(is_unicode_content("Your OTP is 1234"))

    def test_non_ascii_is_unicode(self):
        self.assertTrue(is_unicode_content("OTP नमस्ते"))

    def test_empty_string_is_not_unicode(self):
        self.assertFalse(is_unicode_content(""))
