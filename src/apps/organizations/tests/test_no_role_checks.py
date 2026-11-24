"""No code outside this module reads a role (spec 0029 #3.2, #12 "No role checks", ``RLE-08``).

Static, like ``addon/cdac_sms_gateway/tests/test_isolation.py``: outside
``apps/organizations``, no module imports ``CourtRole``, ``CourtRoleAction``
or ``RoleAssignment``, and a declared action code appears as a string literal
only in ``court_actions.py`` files and migrations.
"""

import ast
from pathlib import Path

from django.test import SimpleTestCase

from apps.organizations import court_actions

SRC = Path(__file__).resolve().parents[3]
ROLE_MODELS = {"CourtRole", "CourtRoleAction", "RoleAssignment"}
# Tests and migrations may name things directly; the admin of users only shows the inlines.
EXEMPT_PARTS = {"tests", "migrations"}


def source_files():
    """Every Python module under apps/ and addon/ outside organizations, tests and migrations."""
    for root in ("apps", "addon"):
        for path in sorted((SRC / root).rglob("*.py")):
            relative = path.relative_to(SRC)
            if relative.parts[:2] == ("apps", "organizations"):
                continue
            if EXEMPT_PARTS & set(relative.parts):
                continue
            yield relative, path


class NoRoleChecksTests(SimpleTestCase):
    """Code checks actions, never roles."""

    def test_no_module_imports_the_role_models(self):
        offenders = []
        for relative, path in source_files():
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and (node.module or "").startswith(
                    "apps.organizations"
                ):
                    names = {alias.name for alias in node.names} & ROLE_MODELS
                    if names:
                        offenders.append(f"{relative}: {', '.join(sorted(names))}")
                elif isinstance(node, ast.Attribute) and node.attr in ROLE_MODELS:
                    offenders.append(f"{relative}: .{node.attr}")
        self.assertEqual(offenders, [])

    def test_action_codes_are_literals_only_in_court_actions_files(self):
        codes = {action.code for action in court_actions.all()}
        offenders = []
        for relative, path in source_files():
            if path.name == "court_actions.py":
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and node.value in codes:
                    offenders.append(f"{relative}:{node.lineno}: {node.value!r}")
        self.assertEqual(offenders, [])
