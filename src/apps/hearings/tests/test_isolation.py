"""The dependency direction stays one-way (spec 0023 #1, #12).

``apps.cases`` never imports ``apps.hearings``: hearings calls it and mounts
its own routes under ``/cases/``. ``apps.hearings`` never imports the orders
or applications modules: they call hearings, never the other way round.
"""

import ast
import re
from pathlib import Path

import pytest

APPS_ROOT = Path(__file__).resolve().parents[2]
# A string reference reaches hearings without an import, e.g. a lazy FK "hearings.Hearing".
HEARINGS_REFERENCE = re.compile(r"""apps\.hearings|["']hearings\.""")


def imported_modules(path):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.append(node.module)
    return names


def sources(app):
    return sorted((APPS_ROOT / app).rglob("*.py"))


def test_cases_does_not_import_hearings():
    offenders = [
        f"{path.relative_to(APPS_ROOT)}: {module}"
        for path in sources("cases")
        for module in imported_modules(path)
        if module == "apps.hearings" or module.startswith("apps.hearings.")
    ]
    assert offenders == []


def test_cases_does_not_reference_hearings_by_name():
    offenders = [
        str(path.relative_to(APPS_ROOT))
        for path in sources("cases")
        if HEARINGS_REFERENCE.search(path.read_text(encoding="utf-8"))
    ]
    assert offenders == []


@pytest.mark.parametrize("downstream", ["orders", "applications"])
def test_hearings_does_not_import_its_callers(downstream):
    offenders = [
        f"{path.relative_to(APPS_ROOT)}: {module}"
        for path in sources("hearings")
        for module in imported_modules(path)
        if module.startswith(f"apps.{downstream}")
    ]
    assert offenders == []
