"""Dependency-direction tests for the addon (spec 0022 #1, #13 "Isolation")."""

import ast
from pathlib import Path

from django.test import SimpleTestCase

import addon.egras_payment_gateway

PACKAGE_ROOT = Path(addon.egras_payment_gateway.__file__).parent

DOMAIN_PACKAGE = "apps.payments"

# The addon may import the contract — the provider base class, its dataclasses
# and exceptions — plus the shared settings helpers (``conf``, ``checks``) and
# the label-only ``enums``. It must never reach the domain's behaviour.
FORBIDDEN_MODULES = frozenset(
    {"models", "services", "tasks", "views", "serializers", "urls", "admin", "selectors", "signals"}
)

# ``providers`` is a mixed package: ``providers.base`` is the contract, while
# ``providers.registry`` and ``providers.mock`` are behaviour the addon must not
# reach into.
PROVIDERS_PACKAGE = f"{DOMAIN_PACKAGE}.providers"
PROVIDERS_CONTRACT = f"{PROVIDERS_PACKAGE}.base"


def forbidden_imports(source: str) -> list[str]:
    """Return ``name:line`` for every import of domain behaviour in ``source``."""

    judged_by_name = {DOMAIN_PACKAGE, PROVIDERS_PACKAGE}

    offenders = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _is_forbidden_module(alias.name):
                    offenders.append(f"{alias.name}:{node.lineno}")
        elif isinstance(node, ast.ImportFrom) and node.module:
            if node.module in judged_by_name:
                for alias in node.names:
                    candidate = f"{node.module}.{alias.name}"
                    if _is_forbidden_module(candidate):
                        offenders.append(f"{candidate}:{node.lineno}")
            elif _is_forbidden_module(node.module):
                offenders.append(f"{node.module}:{node.lineno}")
    return offenders


def _is_forbidden_module(dotted: str) -> bool:
    """Whether ``dotted`` names a domain module the addon may not import."""

    prefix = f"{DOMAIN_PACKAGE}."
    if not dotted.startswith(prefix):
        return False
    if dotted == PROVIDERS_PACKAGE or dotted.startswith(f"{PROVIDERS_PACKAGE}."):
        return dotted != PROVIDERS_CONTRACT and not dotted.startswith(f"{PROVIDERS_CONTRACT}.")
    return dotted[len(prefix) :].split(".", 1)[0] in FORBIDDEN_MODULES


class ForbiddenImportDetectionTests(SimpleTestCase):
    """The detector itself, so the guardrail cannot quietly stop guarding."""

    def test_both_import_spellings_are_caught(self):
        for source in (
            "from apps.payments.models import Payment",
            "from apps.payments import models",
            "from apps.payments import services, selectors",
            "import apps.payments.services",
            "import apps.payments.services.payments",
            "from apps.payments.providers.registry import get_default",
            "from apps.payments.providers import registry",
            "from apps.payments.providers.mock import MockPaymentProvider",
            "import apps.payments.providers",
        ):
            with self.subTest(source=source):
                self.assertTrue(forbidden_imports(source), source)

    def test_contract_imports_are_allowed(self):
        for source in (
            "from apps.payments import conf as payments_conf",
            "from apps.payments.checks import is_production_settings",
            "from apps.payments.enums import ChargeType",
            "from apps.payments.providers.base import PaymentProvider",
            "from apps.payments.providers import base",
            "import apps.payments.providers.base",
            "import apps.payments",
        ):
            with self.subTest(source=source):
                self.assertEqual(forbidden_imports(source), [])


class AddonIsolationTests(SimpleTestCase):
    """The addon depends on the contract only, and ships no domain surface."""

    def test_no_module_imports_domain_behaviour(self):
        offenders = []
        for path in PACKAGE_ROOT.rglob("*.py"):
            if "tests" in path.parts:
                continue
            for offender in forbidden_imports(path.read_text()):
                offenders.append(f"{path.relative_to(PACKAGE_ROOT)}:{offender}")
        self.assertEqual(offenders, [])

    def test_addon_contributes_no_routes_models_or_errors(self):
        """No models, migrations, URLs, admin or errors.py (spec 0022 #15)."""
        for name in ("models.py", "urls.py", "admin.py", "errors.py", "migrations"):
            self.assertFalse((PACKAGE_ROOT / name).exists(), name)
