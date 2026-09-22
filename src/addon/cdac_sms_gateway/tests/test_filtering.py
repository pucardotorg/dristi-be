"""Tests for recipient filtering."""

from dataclasses import replace

from django.test import SimpleTestCase

from addon.cdac_sms_gateway import constants
from addon.cdac_sms_gateway.config import CDACConfig
from addon.cdac_sms_gateway.filtering import compile_pattern, matches_any, resolve_recipient
from apps.messaging.services import RecipientFilteredError

BASE = CDACConfig(
    url="https://gateway.example.com/esms",
    username="user",
    password="secret",
    sender_id="DRISTI",
    secure_key="key",
    mobile_prefix="91",
)


class PatternTests(SimpleTestCase):
    """Pattern compilation tests."""

    def test_x_matches_a_single_digit(self):
        pattern = compile_pattern("98765XXXXX")
        self.assertTrue(pattern.fullmatch("9876512345"))
        self.assertFalse(pattern.fullmatch("9123456789"))

    def test_star_matches_remaining_digits(self):
        pattern = compile_pattern("9876*")
        self.assertTrue(pattern.fullmatch("9876512345"))
        self.assertTrue(pattern.fullmatch("98761"))
        self.assertTrue(pattern.fullmatch("9876"))
        self.assertFalse(pattern.fullmatch("9875512345"))

    def test_literal_is_exact_match_only(self):
        pattern = compile_pattern("9876512345")
        self.assertTrue(pattern.fullmatch("9876512345"))
        self.assertFalse(pattern.fullmatch("98765123456"))

    def test_matches_any_ignores_blank_patterns(self):
        self.assertFalse(matches_any("9876512345", ["", "  "]))
        self.assertTrue(matches_any("9876512345", ["", "9876*"]))


class ResolveRecipientTests(SimpleTestCase):
    """Filtering pipeline tests."""

    def test_allows_when_no_policy_configured(self):
        self.assertEqual(resolve_recipient("9876512345", BASE), "9876512345")

    def test_kill_switch_filters_first(self):
        cfg = replace(BASE, enabled=False, whitelist_numbers=("9876512345",))
        with self.assertRaises(RecipientFilteredError) as ctx:
            resolve_recipient("9876512345", cfg)
        self.assertEqual(ctx.exception.reason, constants.REASON_DISABLED)

    def test_empty_whitelist_allows_all(self):
        cfg = replace(BASE, whitelist_numbers=())
        self.assertEqual(resolve_recipient("9123456789", cfg), "9123456789")

    def test_whitelist_rejection(self):
        cfg = replace(BASE, whitelist_numbers=("98765XXXXX",))
        with self.assertRaises(RecipientFilteredError) as ctx:
            resolve_recipient("9123456789", cfg)
        self.assertEqual(ctx.exception.reason, constants.REASON_WHITELIST)

    def test_whitelist_match_allows(self):
        cfg = replace(BASE, whitelist_numbers=("98765XXXXX",))
        self.assertEqual(resolve_recipient("9876512345", cfg), "9876512345")

    def test_blacklist_rejection(self):
        cfg = replace(BASE, blacklist_numbers=("9876*",))
        with self.assertRaises(RecipientFilteredError) as ctx:
            resolve_recipient("9876512345", cfg)
        self.assertEqual(ctx.exception.reason, constants.REASON_BLACKLIST)

    def test_default_number_override_replaces_recipient(self):
        cfg = replace(BASE, use_default_number=True, default_number="9000000000")
        self.assertEqual(resolve_recipient("9876512345", cfg), "9000000000")

    def test_override_off_keeps_recipient(self):
        cfg = replace(BASE, use_default_number=False, default_number="9000000000")
        self.assertEqual(resolve_recipient("9876512345", cfg), "9876512345")

    def test_filtering_applies_to_the_overridden_number(self):
        cfg = replace(
            BASE,
            use_default_number=True,
            default_number="9000000000",
            whitelist_numbers=("98765XXXXX",),
        )
        with self.assertRaises(RecipientFilteredError) as ctx:
            resolve_recipient("9876512345", cfg)
        self.assertEqual(ctx.exception.reason, constants.REASON_WHITELIST)

    def test_matching_happens_before_the_prefix_is_applied(self):
        cfg = replace(BASE, mobile_prefix="91", whitelist_numbers=("9876512345",))
        # The prefixed number (919876512345) would not match the pattern.
        self.assertEqual(resolve_recipient("9876512345", cfg), "9876512345")

    def test_filtered_event_is_logged_with_identifiers(self):
        cfg = replace(BASE, enabled=False)
        with self.assertLogs(constants.LOGGER_NAME, level="INFO") as captured:
            with self.assertRaises(RecipientFilteredError):
                resolve_recipient(
                    "9876512345",
                    cfg,
                    {"message_id": "mid-1", "correlation_id": "cid-1"},
                )
        line = captured.output[0]
        self.assertIn("event=FILTERED", line)
        self.assertIn("message_id=mid-1", line)
        self.assertIn("correlation_id=cid-1", line)
        self.assertIn("reason=disabled", line)
