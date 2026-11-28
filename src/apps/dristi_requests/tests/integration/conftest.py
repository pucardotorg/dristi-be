"""Shared helpers for the dristi-requests integration flows (spec 0037).

The per-test fixtures (users, types, uploads, clients) come from the app
conftest one level up; this module adds what the flow tests need on top:
seed TOML parsing (the TOML files are the single source of truth), an admin
client for the between-calls shape, and small request builders.
"""

import json
import tomllib
from io import StringIO
from pathlib import Path

import pytest
from django.conf import settings
from django.core.management import call_command
from django.test import Client
from django.urls import reverse

from apps.dristi_requests import hooks
from apps.dristi_requests.models import ApprovalStep, RequestType

CORE_SEED = settings.BASE_DIR.parent / "data" / "seed" / "core"


def error_codes(response):
    """Return a standard error body as ``{field: [code, ...]}`` (spec 0000 §9.1).

    An error on the request as a whole is keyed ``None``.
    """
    codes = {}
    for error in response.json()["errors"]:
        codes.setdefault(error.get("field"), []).append(error["code"])
    return codes


def read_seed_rows(model_label, seed_dir=None):
    """Return the ``[[rows]]`` every TOML under ``seed_dir`` declares for ``model_label``.

    The TOML files are the single source of truth: tests validate API output
    against exactly what was seeded.
    """
    rows = []
    for path in sorted(Path(seed_dir).glob("*.toml")):
        document = tomllib.loads(path.read_text(encoding="utf-8"))
        if document["seed"]["model"] == model_label:
            rows.extend(document["rows"])
    return rows


def stored_paths(storage):
    """Return every object key held by an in-memory storage backend."""
    found = []

    def walk(prefix):
        dirs, files = storage.listdir(prefix)
        found.extend(prefix + name for name in files)
        for name in dirs:
            walk(f"{prefix}{name}/")

    walk("")
    return found


def submit(client, request_type, attributes, documents=()):
    """POST a request creation; ``documents`` are ``SimpleUploadedFile``s."""
    data = {"request_type": request_type.code, "attributes": json.dumps(attributes)}
    if documents:
        data["documents"] = list(documents)
    return client.post(reverse("request-list"), data, format="multipart")


@pytest.fixture
def admin_client(make_user):
    """A Django test client logged in as a superuser, for real admin POSTs (§5)."""
    user = make_user("admin@example.com", is_staff=True, is_superuser=True)
    client = Client()
    client.force_login(user)
    client.user = user
    return client


@pytest.fixture
def unroutable_type(db):
    """A request type whose only step resolves no approver (an empty group)."""
    request_type = RequestType.objects.create(
        code="UNROUTABLE",
        name="Unroutable request",
        schema={"type": "object", "properties": {"reason": {"type": "string"}}},
        min_documents=0,
    )
    ApprovalStep.objects.create(request_type=request_type, order=0, approver_role="NO_SUCH_GROUP")
    return request_type


@pytest.fixture
def conditional_type(db):
    """A two-step type whose second step only matches when data.amount > 1000."""
    request_type = RequestType.objects.create(
        code="CONDITIONAL",
        name="Conditional request",
        schema={"type": "object", "properties": {"amount": {"type": "number"}}},
        min_documents=0,
    )
    ApprovalStep.objects.create(request_type=request_type, order=0, approver_role="LEVEL_ONE")
    ApprovalStep.objects.create(
        request_type=request_type,
        order=1,
        approver_role="LEVEL_TWO",
        condition={"field": "data.amount", "op": "gt", "value": 1000},
    )
    return request_type


@pytest.fixture
def hook_type(db):
    """A request type with a hook-registered code; its hooks are removed on teardown."""
    request_type = RequestType.objects.create(
        code="HOOKED",
        name="Hooked request",
        schema={"type": "object", "properties": {"reason": {"type": "string"}}},
        min_documents=0,
    )
    ApprovalStep.objects.create(request_type=request_type, order=0, approver_role="LEVEL_ONE")
    yield request_type
    hooks.POST_APPROVAL_HOOKS.pop("HOOKED", None)
    hooks.REJECTION_HOOKS.pop("HOOKED", None)


@pytest.fixture(scope="module")
def seeded_configuration(django_db_setup, django_db_blocker):
    """Seed ``data/seed/core/configurations.toml`` once for the numbering module.

    The row is committed outside the per-test transactions, so the module's
    tests share it; the app-wide ``state_code`` fixture is shadowed there so
    it does not clash on the unique ``(config_set, config_key)``. The teardown
    deletes exactly what the TOML declares (spec 0037 §7).
    """
    with django_db_blocker.unblock():
        call_command("seed", str(CORE_SEED / "configurations.toml"), stdout=StringIO())
        yield
        from apps.core.models import Configuration

        for row in read_seed_rows("core.Configuration", CORE_SEED):
            Configuration.objects.filter(
                config_set=row["config_set"], config_key=row["config_key"]
            ).delete()
