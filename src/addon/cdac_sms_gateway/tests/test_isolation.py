"""The dependency direction must stay one-way: addon -> apps.messaging."""

import ast
from pathlib import Path

from django.test import SimpleTestCase

MESSAGING_ROOT = Path(__file__).resolve().parents[3] / "apps" / "messaging"


def imported_modules(path: Path):
    """Return every module name imported by a Python source file."""

    tree = ast.parse(path.read_text(), filename=str(path))
    names = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.append(node.module)
    return names


class MessagingDoesNotImportAddonsTests(SimpleTestCase):
    """apps.messaging must never depend on an addon."""

    def test_messaging_package_exists(self):
        self.assertTrue(MESSAGING_ROOT.is_dir(), MESSAGING_ROOT)

    def test_no_module_imports_addon(self):
        offenders = []
        for path in sorted(MESSAGING_ROOT.rglob("*.py")):
            for module in imported_modules(path):
                if module == "addon" or module.startswith("addon."):
                    offenders.append(f"{path}: imports {module}")
        self.assertEqual(offenders, [])

    def test_no_module_mentions_the_addon_by_name(self):
        offenders = [
            str(path)
            for path in sorted(MESSAGING_ROOT.rglob("*.py"))
            if "addon." in path.read_text()
        ]
        self.assertEqual(offenders, [])

    def test_addon_imports_only_the_messaging_contract(self):
        allowed = {
            "apps.messaging.senders.sms",
            "apps.messaging.services",
        }
        addon_root = Path(__file__).resolve().parents[1]
        offenders = []
        for path in sorted(addon_root.rglob("*.py")):
            if path.parent.name == "tests":
                continue
            for module in imported_modules(path):
                if module.startswith("apps.") and module not in allowed:
                    offenders.append(f"{path}: imports {module}")
        self.assertEqual(offenders, [])
