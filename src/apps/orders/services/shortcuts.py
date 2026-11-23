"""A person's own text shortcuts (#3.6, ``SHC-``): per person, case-insensitively unique by name."""

from django.db import IntegrityError, transaction
from rest_framework.exceptions import NotFound

from apps.api.errors import BusinessError

from .. import errors, rendering
from ..enums import SHORTCUT_SCOPE_ORDER_TEXT
from ..models import OrderShortcut


def list_for(owner, *, scope="", search=""):
    """The caller's own shortcuts, on ``scope`` when given, by name (``SHC-06``)."""
    rows = OrderShortcut.objects.filter(owner=owner)
    if search:
        rows = rows.filter(name__icontains=search)
    # ``scope`` is a JSON list, filtered here: it holds a handful of values per person.
    return [row for row in rows.order_by("name") if not scope or scope in row.scope]


def create(owner, *, name, body, scope):
    """Add a shortcut; a new one is offered on the screen it was created on (``SHC-07``)."""
    scope = scope or [SHORTCUT_SCOPE_ORDER_TEXT]
    try:
        with transaction.atomic():
            return OrderShortcut.objects.create(
                owner=owner,
                name=name,
                body=rendering.sanitize_html(body),
                scope=list(scope),
                created_by=owner,
                updated_by=owner,
            )
    except IntegrityError as exc:
        raise BusinessError(errors.SHORTCUT_NAME_TAKEN, field="name") from exc


def _own(owner, shortcut_id):
    row = OrderShortcut.objects.filter(pk=shortcut_id, owner=owner).first()
    if row is None:
        raise NotFound("Shortcut not found.")
    return row


def update(owner, shortcut_id, **changes):
    """Change a shortcut; only its owner may (``SHC-06``)."""
    row = _own(owner, shortcut_id)
    try:
        with transaction.atomic():
            if "name" in changes:
                row.name = changes["name"]
            if "body" in changes:
                row.body = rendering.sanitize_html(changes["body"])
            if "scope" in changes:
                row.scope = list(changes["scope"])
            row.updated_by = owner
            row.save()
    except IntegrityError as exc:
        raise BusinessError(errors.SHORTCUT_NAME_TAKEN, field="name") from exc
    return row


def delete(owner, shortcut_id):
    """Remove a shortcut; only its owner may."""
    _own(owner, shortcut_id).delete()
