"""A person's own text shortcuts (spec 0039 #3.6): editing one."""

import pytest

from apps.api.errors import BusinessError
from apps.orders import rendering
from apps.orders.models import OrderShortcut
from apps.orders.services import shortcuts

from .factories import code

pytestmark = pytest.mark.django_db


@pytest.fixture
def shortcut(drafter):
    return shortcuts.create(drafter, name="called", body="<p>Called.</p>", scope=None)


def test_an_edit_changes_only_the_fields_it_names(drafter, shortcut):
    shortcuts.update(drafter, shortcut.pk, body="<p>Called again.</p>")
    row = OrderShortcut.objects.get(pk=shortcut.pk)
    assert (row.name, row.body, row.scope) == ("called", "<p>Called again.</p>", ["ORDER_TEXT"])
    assert row.updated_by == drafter


def test_an_edit_does_not_overwrite_a_field_another_edit_changed(drafter, shortcut, monkeypatch):
    """Another request renames the shortcut while this one is changing its body."""
    real = rendering.sanitize_html

    def rename_meanwhile(html, **kwargs):
        OrderShortcut.objects.filter(pk=shortcut.pk).update(name="renamed")
        return real(html, **kwargs)

    monkeypatch.setattr(rendering, "sanitize_html", rename_meanwhile)
    shortcuts.update(drafter, shortcut.pk, body="<p>Heard.</p>")
    row = OrderShortcut.objects.get(pk=shortcut.pk)
    assert (row.name, row.body) == ("renamed", "<p>Heard.</p>")


def test_a_rename_onto_another_shortcut_is_refused(drafter, shortcut):
    other = shortcuts.create(drafter, name="adjourned", body="<p>x</p>", scope=None)
    with pytest.raises(BusinessError) as excinfo:
        shortcuts.update(drafter, other.pk, name="CALLED")
    assert code(excinfo) == "E14018"
    assert OrderShortcut.objects.get(pk=other.pk).name == "adjourned"


def test_only_the_owner_may_edit(drafter, filler, shortcut):
    from rest_framework.exceptions import NotFound

    with pytest.raises(NotFound):
        shortcuts.update(filler, shortcut.pk, name="mine")
    assert OrderShortcut.objects.get(pk=shortcut.pk).name == "called"
