"""Dependency-direction tests for the addon (spec 0015 #1)."""

import re
from pathlib import Path

from django.test import SimpleTestCase

import addon.cdac_esign

PACKAGE_ROOT = Path(addon.cdac_esign.__file__).parent

# The addon may import the contract — the provider base class, the exception
# types, the shared failure codes and the settings helpers — but never the
# domain's behaviour.
FORBIDDEN_IMPORT = re.compile(
    r"^\s*(from|import)\s+apps\.esign\.(models|services|tasks|views|serializers|urls|admin)\b"
)


class AddonIsolationTests(SimpleTestCase):
    """The addon depends on the contract only."""

    def test_no_module_imports_domain_behaviour(self):
        """Models, services, tasks and views stay out of the integration."""
        offenders = []
        for path in PACKAGE_ROOT.rglob("*.py"):
            if "tests" in path.parts:
                continue
            for number, line in enumerate(path.read_text().splitlines(), start=1):
                if FORBIDDEN_IMPORT.match(line):
                    offenders.append(f"{path.relative_to(PACKAGE_ROOT)}:{number}")

        self.assertEqual(offenders, [])

    def test_addon_contributes_no_routes_or_models(self):
        """It is an installed app only so it can register system checks."""
        for name in ("models.py", "urls.py", "admin.py", "migrations"):
            self.assertFalse((PACKAGE_ROOT / name).exists(), name)
