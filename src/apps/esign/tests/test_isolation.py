"""Dependency-direction tests (spec 0015 #1, #15)."""

import re
import sys
from pathlib import Path

from django.test import SimpleTestCase, override_settings

import apps.esign
from apps.esign.providers import get_provider, reset_provider_cache
from apps.esign.providers.mock import MockESignProvider

PACKAGE_ROOT = Path(apps.esign.__file__).parent
IMPORTS_ADDON = re.compile(r"^\s*(from|import)\s+addon\b")


class DependencyDirectionTests(SimpleTestCase):
    """``apps.esign`` must never depend on an addon."""

    def test_no_module_imports_an_addon(self):
        """The domain knows providers only as a settings string."""
        offenders = []
        for path in PACKAGE_ROOT.rglob("*.py"):
            if "tests" in path.parts:
                continue
            for number, line in enumerate(path.read_text().splitlines(), start=1):
                if IMPORTS_ADDON.match(line):
                    offenders.append(f"{path.relative_to(PACKAGE_ROOT)}:{number}")

        self.assertEqual(offenders, [])

    def test_domain_modules_import_without_the_addon(self):
        """Deleting the addon must leave the app working on the mock provider."""
        hidden = {
            name: module
            for name, module in sys.modules.items()
            if name.startswith("addon.cdac_esign")
        }
        for name in hidden:
            del sys.modules[name]
        self.addCleanup(sys.modules.update, hidden)

        reset_provider_cache()
        self.addCleanup(reset_provider_cache)
        with override_settings(ESIGN_PROVIDER="apps.esign.providers.mock.MockESignProvider"):
            self.assertIsInstance(get_provider(), MockESignProvider)

    def test_the_addon_is_not_a_schema_contributor(self):
        """The addon has no models or migrations of its own."""
        from django.apps import apps as django_apps

        addon_config = django_apps.get_app_config("cdac_esign")
        self.assertEqual(list(addon_config.get_models()), [])
        self.assertFalse((Path(addon_config.path) / "migrations").exists())
