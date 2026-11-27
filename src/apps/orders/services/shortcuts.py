"""A person's own text shortcuts (#3.6, ``SHC-``): per person, case-insensitively unique by name."""

from django.db import IntegrityError, transaction
from rest_framework.exceptions import NotFound

from apps.api.errors import BusinessError

from .. import errors
from ..enums import SHORTCUT_SCOPE_ORDER_TEXT
from ..models import OrderShortcut
from . import common


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
                body=common.clean_text(body, field="body"),
                scope=list(scope),
                created_by=owner,
                updated_by=owner,
            )
    except IntegrityError as exc:
        raise BusinessError(errors.SHORTCUT_NAME_TAKEN, field="name") from exc


def _own(owner, shortcut_id, *, lock=False):
    rows = OrderShortcut.objects.select_for_update() if lock else OrderShortcut.objects
    row = rows.filter(pk=shortcut_id, owner=owner).first()
    if row is None:
        raise NotFound("Shortcut not found.")
    return row


def update(owner, shortcut_id, **changes):
    """Change a shortcut; only its owner may (``SHC-06``)."""
    # The row is read under its lock and only the fields this call changes are written,
    # so an overlapping edit of another field of the same shortcut is never overwritten.
    fields = ["updated_by", "updated_at"]
    try:
        with transaction.atomic():
            row = _own(owner, shortcut_id, lock=True)
            if "name" in changes:
                row.name = changes["name"]
                fields.append("name")
            if "body" in changes:
                row.body = common.clean_text(changes["body"], field="body")
                fields.append("body")
            if "scope" in changes:
                row.scope = list(changes["scope"])
                fields.append("scope")
            row.updated_by = owner
            row.save(update_fields=fields)
    except IntegrityError as exc:
        raise BusinessError(errors.SHORTCUT_NAME_TAKEN, field="name") from exc
    return row


def delete(owner, shortcut_id):
    """Remove a shortcut; only its owner may."""
    _own(owner, shortcut_id).delete()
