"""Session-wide pytest configuration."""

import pytest


def pytest_collection_modifyitems(items):
    """Mark every test collected from an ``integration/`` package (spec 0037 §2).

    Location, not decoration: a flow test gets the marker by living in
    ``apps/<domain>/tests/integration/``, so ``pytest -m integration`` and
    ``pytest -m "not integration"`` select the suites with no per-file
    ``pytestmark`` lines to forget.
    """
    for item in items:
        if "integration" in item.path.parts:
            item.add_marker(pytest.mark.integration)
