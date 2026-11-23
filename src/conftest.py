"""Project-wide pytest fixtures and the integration/scenario machinery (spec 0037)."""

import inspect
import json
from io import StringIO
from pathlib import Path

import pytest
from django.conf import settings
from django.core.management import call_command

CORE_SEED = settings.BASE_DIR.parent / "data" / "seed" / "core"
# The reference data that data migrations used to insert (spec 0036), and the order
# catalogue (spec 0039 #3.11), which was never migrated but every orders test needs. The rest
# of core/ (languages, configurations, public configurations, attribute
# definitions) was never in the migrated test database; the tests that need it
# seed it themselves, and some expect those tables to start empty.
MIGRATED_DATA = ("auth", "cms", "dristi_requests", "hearings", "messaging", "orders", "scrutiny")


@pytest.fixture(scope="session")
def django_db_setup(django_db_setup, django_db_blocker):
    """Seed the reference data the migrations used to insert, once per session.

    ``--strict`` fails the session if any row is skipped.
    """
    paths = [str(CORE_SEED / name) for name in MIGRATED_DATA]
    with django_db_blocker.unblock():
        call_command("seed", *paths, "--strict", stdout=StringIO())


# -- integration marker and scenario IDs (spec 0037 §2 rule 6 and §15) -------


def pytest_addoption(parser):
    """Register the ``--scenario`` and ``--scenario-report`` options (§14)."""
    group = parser.getgroup("scenario", "scenario IDs (spec 0037 §15)")
    group.addoption(
        "--scenario",
        action="append",
        default=[],
        metavar="ID",
        help="run only tests tagged @pytest.mark.scenario(ID); repeatable.",
    )
    group.addoption(
        "--scenario-report",
        metavar="PATH",
        help="write the scenario ID -> tests map as JSON to PATH after the run.",
    )


def pytest_configure(config):
    """Register the markers so neither use nor ``-m`` selection warns."""
    config.addinivalue_line(
        "markers",
        "integration: flow test in a tests/integration/ package "
        "(auto-applied by the root conftest; spec 0037 §2 rule 6).",
    )
    config.addinivalue_line(
        "markers",
        "scenario(ID): pin a test to an externally tracked scenario ID (spec 0037 §15).",
    )


def _scenario_ids(item):
    """Return the scenario IDs ``item`` is tagged with.

    A bare ``@pytest.mark.scenario`` (no ID) is a collection error (§15 rule 2).
    """
    ids = []
    for marker in item.iter_markers(name="scenario"):
        if not marker.args or not all(isinstance(arg, str) and arg for arg in marker.args):
            raise pytest.UsageError(
                f"{item.nodeid}: @pytest.mark.scenario takes an ID, e.g. "
                '@pytest.mark.scenario("ORD-CANCEL-3") (spec 0037 §15 rule 2).'
            )
        ids.extend(marker.args)
    return ids


def pytest_collection_modifyitems(config, items):
    """Auto-mark integration packages, validate scenario markers, select by ID.

    Every test collected under a ``tests/integration/`` package gets the
    ``integration`` mark (§2 rule 6), so ``-m integration`` selects the flow
    suites with no per-file ``pytestmark`` lines. ``--scenario ID`` deselects
    every test not tagged with one of the given IDs (§15 rule 3). Tagged IDs
    are mirrored to ``item.user_properties`` so the JUnit XML carries one
    ``<property name="scenario" .../>`` per ID (§15 rule 5).
    """
    selected = set(config.getoption("scenario"))
    kept, deselected = [], []
    for item in items:
        if "integration" in item.path.parts:
            item.add_marker(pytest.mark.integration)
        ids = _scenario_ids(item)
        item.user_properties.extend(("scenario", scenario_id) for scenario_id in ids)
        if selected and selected.isdisjoint(ids):
            deselected.append(item)
        else:
            kept.append(item)
    if deselected:
        items[:] = kept
        config.hook.pytest_deselected(items=deselected)


def pytest_sessionfinish(session):
    """Write the scenario ID -> tests map when ``--scenario-report`` was given.

    Each tagged ID maps to the selected tests (node ID + first docstring
    line); on an unfiltered run the report is the full inventory (§15 rule 4).
    """
    report = session.config.getoption("scenario_report")
    if not report:
        return
    mapping = {}
    for item in session.items:
        target = getattr(item, "obj", None)
        doc = inspect.getdoc(target) if target is not None else None
        entry = {"nodeid": item.nodeid, "doc": doc.splitlines()[0] if doc else ""}
        for scenario_id in _scenario_ids(item):
            mapping.setdefault(scenario_id, []).append(entry)
    Path(report).write_text(json.dumps(mapping, indent=2, sort_keys=True) + "\n", encoding="utf-8")
