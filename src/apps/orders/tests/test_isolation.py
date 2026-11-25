"""The dependency direction stays one-way (spec 0039 #1).

``apps.orders`` never imports the modules that register handlers with it or the
A-Diary; ``apps.cases``, ``apps.hearings`` and ``apps.workflows`` never import it.
"""

import ast
import re
from pathlib import Path

import pytest

APPS_ROOT = Path(__file__).resolve().parents[2]
FORBIDDEN_FOR_ORDERS = ("applications", "processes", "submissions", "adiary")
NEVER_IMPORT_ORDERS = ("cases", "hearings", "workflows", "esign", "payments", "pdf", "files")


def imported_modules(path):
    return modules_in(path.read_text(encoding="utf-8"), filename=str(path))


def modules_in(source, filename="<test>"):
    """Every module ``source`` may import: ``from a import b`` names both ``a`` and ``a.b``,
    since ``b`` may be a module (``from apps import applications``)."""
    names = []
    for node in ast.walk(ast.parse(source, filename=filename)):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.append(node.module)
            names.extend(f"{node.module}.{alias.name}" for alias in node.names)
    return names


def forbidden_for_orders(module):
    return (
        any(
            module == f"apps.{name}" or module.startswith(f"apps.{name}.")
            for name in FORBIDDEN_FOR_ORDERS
        )
        or module == "addon"
        or module.startswith("addon.")
    )


def imports_orders(module):
    return module == "apps.orders" or module.startswith("apps.orders.")


@pytest.mark.parametrize(
    "source",
    [
        "from apps import applications",
        "from apps import adiary as diary",
        "from apps.applications import services",
        "from apps.processes.services import issue",
        "import apps.submissions",
        "from addon import cdac_sms_gateway",
    ],
)
def test_the_parser_finds_a_forbidden_module_in_every_import_form(source):
    assert any(forbidden_for_orders(module) for module in modules_in(source))


@pytest.mark.parametrize(
    "source",
    [
        "from apps import orders",
        "from apps.orders import handlers",
        "from apps.orders.handlers import register",
        "import apps.orders.signals",
    ],
)
def test_the_parser_finds_an_import_of_orders_in_every_form(source):
    assert any(imports_orders(module) for module in modules_in(source))


@pytest.mark.parametrize(
    "source",
    [
        "from apps import cases",
        "from apps.cases import selectors",
        "from apps.core.models import BaseModel",
        "from . import errors",
        "from .services import common",
    ],
)
def test_the_parser_lets_allowed_imports_through(source):
    modules = modules_in(source)
    assert not any(forbidden_for_orders(module) or imports_orders(module) for module in modules)


def sources(app, *, tests=False):
    root = APPS_ROOT / app
    if not root.is_dir():
        return []
    return [
        path
        for path in sorted(root.rglob("*.py"))
        if tests or "tests" not in path.relative_to(root).parts
    ]


def test_orders_does_not_import_the_modules_that_call_it():
    offenders = [
        f"{path.relative_to(APPS_ROOT)}: {module}"
        for path in sources("orders")
        for module in imported_modules(path)
        if forbidden_for_orders(module)
    ]
    assert offenders == []


def test_orders_names_no_forbidden_module_even_as_a_string():
    pattern = re.compile(r"""["']apps\.(applications|processes|submissions|adiary)""")
    offenders = [
        str(path.relative_to(APPS_ROOT))
        for path in sources("orders")
        if pattern.search(path.read_text(encoding="utf-8"))
    ]
    assert offenders == []


def test_the_modules_orders_calls_never_import_it():
    offenders = [
        f"{path.relative_to(APPS_ROOT)}: {module}"
        for app in NEVER_IMPORT_ORDERS
        for path in sources(app)
        for module in imported_modules(path)
        if imports_orders(module)
    ]
    assert offenders == []


def test_the_only_foreign_keys_into_other_domain_apps_are_case_court_and_hearing():
    from django.apps import apps

    allowed = {
        ("order", "case"): "cases.case",
        ("order", "court"): "organizations.organization",
        ("order", "hearing"): "hearings.hearing",
        ("ordernumbercounter", "court"): "organizations.organization",
        ("orderitemtype", "suggested_for_purposes"): "hearings.hearingpurpose",
    }
    found = {}
    for model in apps.get_app_config("orders").get_models():
        if model._meta.model_name.startswith("historical"):
            continue
        for field in model._meta.get_fields():
            related = getattr(field, "related_model", None)
            if (
                related is not None
                and field.concrete
                and related._meta.app_label not in ("orders", "users", "auth", "simple_history")
            ):
                found[(model._meta.model_name, field.name)] = related._meta.label_lower
    assert found == allowed


def test_applications_processes_and_documents_are_plain_ids():
    from apps.orders.models import OrderItem, OrderLinkedDocument

    assert OrderItem._meta.get_field("target_id").get_internal_type() == "UUIDField"
    assert OrderLinkedDocument._meta.get_field("document_id").get_internal_type() == "UUIDField"
