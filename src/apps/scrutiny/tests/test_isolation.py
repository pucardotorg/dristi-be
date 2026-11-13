"""The dependency direction stays one-way (spec 0024 #1).

Scrutiny reads the case and moves it through the workflow; neither module may
depend on scrutiny. ``apps.cases`` learns nothing from scrutiny: scrutiny listens
to its signals and mounts the filer's correction routes itself.
"""

import ast
import re
from pathlib import Path

import pytest

APPS_ROOT = Path(__file__).resolve().parents[2]
# The modules that must never depend on scrutiny.
UPSTREAM = ("cases", "workflows")
# A string reference reaches scrutiny without an import: apps.get_model("scrutiny.X"),
# a lazy FK "scrutiny.ScrutinyRound", or a dotted path in settings-like code.
SCRUTINY_REFERENCE = re.compile(r"""apps\.scrutiny|["']scrutiny\.""")


def imported_modules(path):
    """Return every absolute module name imported by a Python source file."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.append(node.module)
    return names


def sources(app):
    root = APPS_ROOT / app
    if not root.is_dir():
        pytest.skip(f"apps.{app} does not exist yet")
    return sorted(root.rglob("*.py"))


def test_scrutiny_package_is_found():
    assert (APPS_ROOT / "scrutiny" / "apps.py").is_file()


@pytest.mark.parametrize("app", UPSTREAM)
def test_does_not_import_scrutiny(app):
    offenders = [
        f"{path.relative_to(APPS_ROOT)}: imports {module}"
        for path in sources(app)
        for module in imported_modules(path)
        if module == "apps.scrutiny" or module.startswith("apps.scrutiny.")
    ]
    assert offenders == []


@pytest.mark.parametrize("app", UPSTREAM)
def test_does_not_reference_scrutiny_by_name(app):
    offenders = [
        str(path.relative_to(APPS_ROOT))
        for path in sources(app)
        if SCRUTINY_REFERENCE.search(path.read_text(encoding="utf-8"))
    ]
    assert offenders == []
