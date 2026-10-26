"""Dependency direction and schema declarations (spec 0017 #9, #12.5, #18 "Isolation")."""

import ast
from pathlib import Path

import pytest
from django.test import SimpleTestCase
from drf_spectacular.generators import SchemaGenerator

import apps.payments
from apps.api.errors import all_errors

PACKAGE_ROOT = Path(apps.payments.__file__).parent


def addon_imports(source: str) -> list[str]:
    """``name:line`` for every import of the ``addon`` package in ``source``."""

    offenders = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            names = [node.module]
        else:
            continue
        offenders += [f"{n}:{node.lineno}" for n in names if n == "addon" or n.startswith("addon.")]
    return offenders


class DependencyDirectionTests(SimpleTestCase):
    def test_the_detector_catches_every_spelling(self):
        for source in (
            "import addon",
            "import addon.egras_payment_gateway",
            "from addon import egras_payment_gateway",
            "from addon.egras_payment_gateway.provider import EGRASProvider",
        ):
            with self.subTest(source=source):
                self.assertTrue(addon_imports(source))
        self.assertEqual(addon_imports("from apps.payments.providers import registry"), [])

    def test_no_module_imports_an_addon(self):
        # Filter on the package-relative path: a checkout under any directory
        # named "tests" would otherwise skip every file and pass vacuously.
        modules = [
            path
            for path in PACKAGE_ROOT.rglob("*.py")
            if "tests" not in path.relative_to(PACKAGE_ROOT).parts
        ]
        self.assertIn(PACKAGE_ROOT / "services" / "payments.py", modules)
        offenders = [
            f"{path.relative_to(PACKAGE_ROOT)}:{offender}"
            for path in modules
            for offender in addon_imports(path.read_text())
        ]
        self.assertEqual(offenders, [])


@pytest.mark.django_db
def test_every_payments_code_is_declared_on_an_endpoint():
    """Every E06 code appears as an example on at least one operation (spec 0017 #12.5)."""

    schema = SchemaGenerator().get_schema(request=None, public=True)
    text = str(schema["paths"])
    codes = [error.code for error in all_errors() if error.domain == "payments"]
    assert len(codes) == 22
    missing = [code for code in codes if code not in text]
    assert missing == []
