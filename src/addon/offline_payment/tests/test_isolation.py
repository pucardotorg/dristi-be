"""Dependency direction of the offline addon (spec 0032 #1, #17.6)."""

import ast
import io
import re
import tokenize
from pathlib import Path

from django.test import SimpleTestCase

import addon.offline_payment
import apps.payments

PACKAGE_ROOT = Path(addon.offline_payment.__file__).parent
PAYMENTS_ROOT = Path(apps.payments.__file__).parent

# The only apps.payments modules the addon may import (spec 0032 #1).
ALLOWED_MODULES = frozenset(
    {
        "apps.payments.providers.base",
        "apps.payments.conf",
        "apps.payments.checks",
        "apps.payments.enums",
    }
)


def payments_imports(source: str) -> list[tuple[str, int]]:
    """Every ``apps.payments`` module imported by ``source``, with its line."""

    found = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found += [(alias.name, node.lineno) for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            if node.module in ("apps.payments", "apps.payments.providers"):
                found += [(f"{node.module}.{alias.name}", node.lineno) for alias in node.names]
            else:
                found.append((node.module, node.lineno))
    return [(name, line) for name, line in found if name.startswith("apps.payments")]


def forbidden(source: str) -> list[str]:
    return [
        f"{name}:{line}" for name, line in payments_imports(source) if name not in ALLOWED_MODULES
    ]


def code_without_comments(source: str) -> str:
    """``source`` with comments and docstrings removed."""

    tree = ast.parse(source)
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            if (
                node.body
                and isinstance(node.body[0], ast.Expr)
                and isinstance(node.body[0].value, ast.Constant)
                and isinstance(node.body[0].value.value, str)
            ):
                docstrings.add(node.body[0].lineno)
    kept = []
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type == tokenize.COMMENT:
            continue
        if token.type == tokenize.STRING and token.start[0] in docstrings:
            continue
        kept.append(token.string)
    return " ".join(kept)


class DetectorTests(SimpleTestCase):
    def test_forbidden_spellings_are_caught(self):
        for source in (
            "from apps.payments.models import Payment",
            "from apps.payments import models",
            "from apps.payments import services",
            "import apps.payments.services.payments",
            "from apps.payments.providers import registry",
            "from apps.payments.providers.mock import MockPaymentProvider",
            "from apps.payments.selectors import payments_for",
            "from apps.payments import errors",
        ):
            with self.subTest(source=source):
                self.assertTrue(forbidden(source))

    def test_the_contract_is_allowed(self):
        for source in (
            "from apps.payments.providers.base import PaymentProvider",
            "from apps.payments.providers import base",
            "from apps.payments import conf as payments_conf",
            "from apps.payments.checks import is_production_settings",
            "from apps.payments.enums import ChargeType",
        ):
            with self.subTest(source=source):
                self.assertEqual(forbidden(source), [])

    def test_comment_stripper(self):
        source = '"""Offline doc."""\n# offline comment\nx = 1  # offline\n'
        self.assertNotIn("offline", code_without_comments(source).lower())
        self.assertIn("offline", code_without_comments('x = "offline"\n'))


class AddonIsolationTests(SimpleTestCase):
    def test_addon_imports_only_the_contract(self):
        offenders = [
            f"{path.relative_to(PACKAGE_ROOT)}:{offender}"
            for path in PACKAGE_ROOT.rglob("*.py")
            if "tests" not in path.relative_to(PACKAGE_ROOT).parts
            for offender in forbidden(path.read_text())
        ]
        self.assertEqual(offenders, [])

    def test_addon_ships_no_domain_surface(self):
        for name in ("models.py", "urls.py", "views.py", "admin.py", "errors.py", "migrations"):
            self.assertFalse((PACKAGE_ROOT / name).exists(), name)

    def test_payments_never_names_the_offline_provider(self):
        """No module under apps.payments imports addon.* or mentions offline (#17.6)."""

        modules = [
            path
            for path in PAYMENTS_ROOT.rglob("*.py")
            if "tests" not in path.relative_to(PAYMENTS_ROOT).parts
        ]
        self.assertIn(PAYMENTS_ROOT / "services" / "payments.py", modules)
        offenders = []
        for path in modules:
            code = code_without_comments(path.read_text())
            if re.search(r"offline", code, re.IGNORECASE) or re.search(r"\baddon\b", code):
                offenders.append(str(path.relative_to(PAYMENTS_ROOT)))
        self.assertEqual(offenders, [])

    def test_payments_templates_never_name_the_offline_provider(self):
        offenders = [
            str(path.relative_to(PAYMENTS_ROOT))
            for path in PAYMENTS_ROOT.rglob("*.html")
            if "offline" in path.read_text().lower()
        ]
        self.assertEqual(offenders, [])
