"""Dependency-direction tests (spec 0015 #1, #15)."""

import ast
import sys
from pathlib import Path

from django.test import SimpleTestCase, override_settings

import apps.esign
from apps.esign.providers import get_provider, reset_provider_cache
from apps.esign.providers.mock import MockESignProvider

PACKAGE_ROOT = Path(apps.esign.__file__).parent
ADDON_PACKAGE = "addon"


def addon_imports(source: str) -> list[str]:
    """Return ``name:line`` for every addon import in ``source``.

    Parsed rather than pattern-matched so ``from addon import cdac_esign``,
    ``from addon.cdac_esign.provider import X`` and ``import addon.cdac_esign``
    are all caught by one rule.
    """

    offenders = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _is_addon(alias.name):
                    offenders.append(f"{alias.name}:{node.lineno}")
        elif isinstance(node, ast.ImportFrom) and node.module and _is_addon(node.module):
            offenders.append(f"{node.module}:{node.lineno}")
    return offenders


def _is_addon(dotted: str) -> bool:
    """Whether ``dotted`` names the addon package or something inside it."""

    return dotted == ADDON_PACKAGE or dotted.startswith(f"{ADDON_PACKAGE}.")


class DependencyDirectionTests(SimpleTestCase):
    """``apps.esign`` must never depend on an addon."""

    def test_the_detector_catches_every_import_spelling(self):
        """The guardrail cannot quietly stop guarding."""
        for source in (
            "import addon",
            "import addon.cdac_esign",
            "from addon import cdac_esign",
            "from addon.cdac_esign.provider import CDACESignProvider",
            "from addon.cdac_esign import constants as cdac_constants",
        ):
            with self.subTest(source=source):
                self.assertTrue(addon_imports(source), source)

        self.assertEqual(addon_imports("from apps.esign.providers import get_provider"), [])

    def test_no_module_imports_an_addon(self):
        """The domain knows providers only as a settings string."""
        offenders = []
        for path in PACKAGE_ROOT.rglob("*.py"):
            if "tests" in path.parts:
                continue
            for offender in addon_imports(path.read_text()):
                offenders.append(f"{path.relative_to(PACKAGE_ROOT)}:{offender}")

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
