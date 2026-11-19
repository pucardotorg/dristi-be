"""Session-wide pytest configuration."""

import json
from pathlib import Path

import pytest


def pytest_addoption(parser):
    """Register the scenario selection and reporting options (spec 0037 §15)."""
    parser.addoption(
        "--scenario",
        action="append",
        default=None,
        metavar="ID",
        help="Run only tests tagged @pytest.mark.scenario(ID); repeatable.",
    )
    parser.addoption(
        "--scenario-report",
        metavar="PATH",
        help="Write a JSON map of scenario ID to the selected tests after the run.",
    )


def pytest_collection_modifyitems(config, items):
    """Mark by location, select by scenario, and build the scenario report.

    Location, not decoration: a flow test gets the ``integration`` marker by
    living in ``apps/<domain>/tests/integration/``, so ``pytest -m
    integration`` and ``pytest -m "not integration"`` select the suites with
    no per-file ``pytestmark`` lines (spec 0037 §2).

    Scenario IDs (spec 0037 §15) are recorded as user properties — the JUnit
    XML writer emits them as testcase properties — and ``--scenario`` deselects
    everything not tagged with a wanted ID.
    """
    wanted = set(config.getoption("--scenario") or [])
    report = {}
    kept = []
    deselected = []
    for item in items:
        if "integration" in item.path.parts:
            item.add_marker(pytest.mark.integration)

        ids = []
        for marker in item.iter_markers(name="scenario"):
            if not marker.args:
                raise pytest.UsageError(f"{item.nodeid}: @pytest.mark.scenario needs an ID")
            ids.append(str(marker.args[0]))
        if wanted and not wanted.intersection(ids):
            deselected.append(item)
            continue
        for scenario_id in ids:
            item.user_properties.append(("scenario", scenario_id))
            doc = (getattr(item.obj, "__doc__", "") or "").strip()
            report.setdefault(scenario_id, []).append(
                {"nodeid": item.nodeid, "doc": doc.splitlines()[0] if doc else ""}
            )
        kept.append(item)

    if deselected:
        config.hook.pytest_deselected(items=deselected)
        items[:] = kept
    config._scenario_report = report


def pytest_sessionfinish(session, exitstatus):
    """Write the scenario report for the selected tests, if asked."""
    path = session.config.getoption("--scenario-report")
    if path:
        report = getattr(session.config, "_scenario_report", {})
        Path(path).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
