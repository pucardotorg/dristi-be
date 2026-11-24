"""The court action registry (spec 0029 #3, #12 "Registry")."""

from unittest import mock

from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase

from apps.organizations import checks, court_actions
from apps.organizations.enums import CourtLevel

from . import court_actions as actions


class RegistryTests(SimpleTestCase):
    """Declaring and resolving actions."""

    def setUp(self):
        # Each test declares into a copy, so nothing leaks into the real registry.
        patch_registry = mock.patch.dict(court_actions._REGISTRY)
        patch_problems = mock.patch.object(court_actions, "_PROBLEMS", [])
        patch_registry.start()
        patch_problems.start()
        self.addCleanup(patch_registry.stop)
        self.addCleanup(patch_problems.stop)

    def test_define_registers_and_returns_the_action(self):
        action = court_actions.define(
            "sample.do_it", CourtLevel.COURTROOM, "Do it", group="Doer", scoped=True
        )
        self.assertEqual(court_actions.get("sample.do_it"), action)
        self.assertTrue(action.scoped)
        self.assertFalse(action.is_establishment)
        self.assertIn(action, court_actions.all())

    def test_duplicate_code_fails_and_is_reported_by_e003(self):
        court_actions.define("sample.twice", CourtLevel.ESTABLISHMENT, "Once", group="G")
        with self.assertRaises(ImproperlyConfigured):
            court_actions.define("sample.twice", CourtLevel.ESTABLISHMENT, "Twice", group="G")
        ids = [error.id for error in checks.check_registry(None)]
        self.assertEqual(ids, ["organizations.E003"])

    def test_malformed_codes_fail(self):
        for code in ("NoDot", "Sample.Upper", "sample.", ".x", "sample.do-it", "a.b.c"):
            with self.subTest(code=code), self.assertRaises(ImproperlyConfigured):
                court_actions.define(code, CourtLevel.ESTABLISHMENT, "Bad", group="G")
        self.assertTrue(all(e.id == "organizations.E003" for e in checks.check_registry(None)))

    def test_unknown_level_fails(self):
        with self.assertRaises(ImproperlyConfigured):
            court_actions.define("sample.levelless", "STATE", "Bad", group="G")

    def test_resolve_refuses_an_undeclared_action(self):
        self.assertEqual(court_actions.resolve(actions.FLAG), actions.FLAG)
        self.assertEqual(court_actions.resolve("testing.flag"), actions.FLAG)
        with self.assertRaises(ImproperlyConfigured):
            court_actions.resolve("sample.nobody_declares")

    def test_clean_registry_passes_e003(self):
        self.assertEqual(checks.check_registry(None), [])
