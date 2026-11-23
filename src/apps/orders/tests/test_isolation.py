"""The dependency direction stays one-way (spec 0039 #1).

``apps.orders`` never imports the modules that register handlers with it or the
A-Diary; ``apps.cases``, ``apps.hearings`` and ``apps.workflows`` never import it.
"""

import ast
import re
from pathlib import Path

APPS_ROOT = Path(__file__).resolve().parents[2]
FORBIDDEN_FOR_ORDERS = ("applications", "processes", "submissions", "adiary")
NEVER_IMPORT_ORDERS = ("cases", "hearings", "workflows", "esign", "payments", "pdf", "files")


def imported_modules(path):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.append(node.module)
    return names


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
        if any(
            module == f"apps.{name}" or module.startswith(f"apps.{name}.")
            for name in FORBIDDEN_FOR_ORDERS
        )
        or module.startswith("addon.")
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
        if module == "apps.orders" or module.startswith("apps.orders.")
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
