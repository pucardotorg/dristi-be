"""The dependency direction stays one-way (spec 0028 #1).

Processes calls cases, hearings, payments and locations; none of them, nor
the orders module that will start processes, imports processes. Processes
imports no addon.
"""

import ast
import re
from pathlib import Path

import pytest

APPS_ROOT = Path(__file__).resolve().parents[2]
# A string reference reaches processes without an import, e.g. a lazy FK "processes.Process".
PROCESSES_REFERENCE = re.compile(r"""apps\.processes|["']processes\.""")


def imported_modules(path):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            yield from (alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            yield node.module


def sources(app):
    return sorted((APPS_ROOT / app).rglob("*.py"))


@pytest.mark.parametrize("upstream", ["cases", "hearings", "payments", "locations", "orders"])
def test_upstream_never_references_processes(upstream):
    offenders = [
        str(path.relative_to(APPS_ROOT))
        for path in sources(upstream)
        if PROCESSES_REFERENCE.search(path.read_text(encoding="utf-8"))
    ]
    assert offenders == []


def test_processes_imports_no_addon():
    offenders = [
        f"{path.relative_to(APPS_ROOT)}: {module}"
        for path in sources("processes")
        for module in imported_modules(path)
        if module == "addon" or module.startswith("addon.")
    ]
    assert offenders == []
