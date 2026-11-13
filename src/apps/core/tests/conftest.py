"""Shared fixtures for core tests."""

from io import StringIO

import pytest
from django.conf import settings
from django.core.management import call_command

LANGUAGES_SEED = settings.BASE_DIR.parent / "data" / "seed" / "core" / "languages.toml"


@pytest.fixture
def languages(db):
    """Seed the initial languages (spec 0030 section 10) with the seed command."""
    call_command("seed", str(LANGUAGES_SEED), stdout=StringIO())
