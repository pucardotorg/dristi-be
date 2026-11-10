"""Provider registration in the production settings module (spec 0022 #8).

Registering e-GRAS must not depend on it being the default: payments still
pending at e-GRAS keep needing its callback and status lookup after the default
is cleared or moved to another provider. Each case loads
``config.settings.production`` in a fresh interpreter with its own environment.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

from django.test import SimpleTestCase

from addon.egras_payment_gateway import constants

SRC_ROOT = Path(__file__).resolve().parents[3]
PRINT_PROVIDERS = (
    "import json, config.settings.production as s; print(json.dumps(s.PAYMENT_PROVIDERS))"
)


def production_providers(**env) -> dict | str:
    """``PAYMENT_PROVIDERS`` as production computes it, or the error text."""

    environ = {
        **os.environ,
        "SECRET_KEY": "test",
        "ALLOWED_HOSTS": "example.com",
        "PAYMENT_DEFAULT_PROVIDER": "",
        "PAYMENT_REGISTERED_PROVIDERS": "",
        **env,
    }
    environ.pop("DJANGO_SETTINGS_MODULE", None)
    result = subprocess.run(
        [sys.executable, "-c", PRINT_PROVIDERS],
        cwd=SRC_ROOT,
        env=environ,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode:
        return result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1])


class ProductionRegistrationTests(SimpleTestCase):
    """Registered providers are independent of the default (spec 0022 #8)."""

    def test_nothing_is_registered_before_onboarding(self):
        self.assertEqual(production_providers(), {})

    def test_the_default_is_registered(self):
        self.assertEqual(
            production_providers(PAYMENT_DEFAULT_PROVIDER="egras"),
            {"egras": constants.PROVIDER_PATH},
        )

    def test_egras_stays_registered_after_the_default_is_cleared(self):
        """In-flight e-GRAS payments still verify once new payments stop."""
        self.assertEqual(
            production_providers(PAYMENT_REGISTERED_PROVIDERS="egras"),
            {"egras": constants.PROVIDER_PATH},
        )

    def test_spaces_and_trailing_commas_are_ignored(self):
        for value in (" egras", "egras ", "egras, ", "egras,,"):
            with self.subTest(value=value):
                self.assertEqual(
                    production_providers(PAYMENT_REGISTERED_PROVIDERS=value),
                    {"egras": constants.PROVIDER_PATH},
                )

    def test_an_unknown_registered_name_fails_loudly(self):
        error = production_providers(PAYMENT_REGISTERED_PROVIDERS="egras,egrass")
        self.assertIsInstance(error, str)
        self.assertIn("ImproperlyConfigured", error)
        self.assertIn("egrass", error)
