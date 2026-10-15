"""Dependency-direction tests for the addon (spec 0015 #1)."""

import ast
from pathlib import Path

from django.test import SimpleTestCase

import addon.cdac_esign

PACKAGE_ROOT = Path(addon.cdac_esign.__file__).parent

DOMAIN_PACKAGE = "apps.esign"

# The addon may import the contract — the provider base class, the exception
# types, the shared failure codes and the settings helpers — but never the
# domain's behaviour. Both spellings have to be caught: the dotted
# ``from apps.esign.models import X`` and the bare
# ``from apps.esign import models``, which is the form the addon already uses
# for the parts it is allowed to import.
FORBIDDEN_MODULES = frozenset(
    {"models", "services", "tasks", "views", "serializers", "urls", "admin"}
)

# ``providers`` is a mixed package: ``providers.base`` is the contract (the ABC
# and the request/response dataclasses), while ``providers.registry`` and
# ``providers.mock`` are behaviour the addon must not reach into. The package
# itself (``apps.esign.providers``) re-exports the registry, so importing it
# bare is forbidden too.
PROVIDERS_PACKAGE = f"{DOMAIN_PACKAGE}.providers"
PROVIDERS_CONTRACT = f"{PROVIDERS_PACKAGE}.base"


def forbidden_imports(source: str) -> list[str]:
    """Return ``name:line`` for every import of domain behaviour in ``source``.

    The module is parsed rather than pattern-matched so aliases, parenthesised
    lists and multi-line imports are all covered by the same rule.
    """

    # apps.esign and apps.esign.providers are packages the addon imports *from*
    # for both contract and (forbidden) behaviour, so ``from <pkg> import name``
    # is judged by each name rather than by the package.
    judged_by_name = {DOMAIN_PACKAGE, PROVIDERS_PACKAGE}

    offenders = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _is_forbidden_module(alias.name):
                    offenders.append(f"{alias.name}:{node.lineno}")
        elif isinstance(node, ast.ImportFrom) and node.module:
            if node.module in judged_by_name:
                # ``from apps.esign import models`` /
                # ``from apps.esign.providers import registry``.
                for alias in node.names:
                    candidate = f"{node.module}.{alias.name}"
                    if _is_forbidden_module(candidate):
                        offenders.append(f"{candidate}:{node.lineno}")
            elif _is_forbidden_module(node.module):
                # ``from apps.esign.models import X`` /
                # ``from apps.esign.providers.registry import get_provider``.
                offenders.append(f"{node.module}:{node.lineno}")
    return offenders


def _is_forbidden_module(dotted: str) -> bool:
    """Whether ``dotted`` names a domain module the addon may not import."""

    prefix = f"{DOMAIN_PACKAGE}."
    if not dotted.startswith(prefix):
        return False
    if dotted == PROVIDERS_PACKAGE or dotted.startswith(f"{PROVIDERS_PACKAGE}."):
        # Everything under providers is behaviour except the contract itself.
        return dotted != PROVIDERS_CONTRACT and not dotted.startswith(f"{PROVIDERS_CONTRACT}.")
    return dotted[len(prefix) :].split(".", 1)[0] in FORBIDDEN_MODULES


class ForbiddenImportDetectionTests(SimpleTestCase):
    """The detector itself, so the guardrail cannot quietly stop guarding."""

    def test_both_import_spellings_are_caught(self):
        """The dotted path and the bare module name are equally forbidden."""
        for source in (
            "from apps.esign.models import ESignTransaction",
            "from apps.esign import models",
            "from apps.esign import constants, services",
            "from apps.esign import tasks as esign_tasks",
            "import apps.esign.services",
            "import apps.esign.services.callback",
            "from apps.esign import (\n    conf,\n    views,\n)",
            # providers.* is behaviour except .base, in either spelling.
            "import apps.esign.providers.registry",
            "from apps.esign.providers.registry import get_provider",
            "from apps.esign.providers import registry",
            "from apps.esign.providers.mock import MockESignProvider",
            "from apps.esign.providers import registry, mock",
            "import apps.esign.providers",
        ):
            with self.subTest(source=source):
                self.assertTrue(forbidden_imports(source), source)

    def test_contract_imports_are_allowed(self):
        """Exceptions, the provider base class, constants and conf are the contract."""
        for source in (
            "from apps.esign import constants as esign_constants",
            "from apps.esign import conf as esign_conf",
            "from apps.esign.checks import is_production_settings",
            "from apps.esign.exceptions import ESignResponseUntrusted",
            "from apps.esign.providers.base import ESignProvider",
            "from apps.esign.providers import base",
            "import apps.esign.providers.base",
            "from apps.esign.constants import ESIGN_PROVIDER_REJECTED",
            "import apps.esign",
        ):
            with self.subTest(source=source):
                self.assertEqual(forbidden_imports(source), [])


class AddonIsolationTests(SimpleTestCase):
    """The addon depends on the contract only."""

    def test_no_module_imports_domain_behaviour(self):
        """Models, services, tasks and views stay out of the integration."""
        offenders = []
        for path in PACKAGE_ROOT.rglob("*.py"):
            if "tests" in path.parts:
                continue
            for offender in forbidden_imports(path.read_text()):
                offenders.append(f"{path.relative_to(PACKAGE_ROOT)}:{offender}")

        self.assertEqual(offenders, [])

    def test_addon_contributes_no_routes_or_models(self):
        """It is an installed app only so it can register system checks."""
        for name in ("models.py", "urls.py", "admin.py", "migrations"):
            self.assertFalse((PACKAGE_ROOT / name).exists(), name)
