"""Fixtures shared by the orders tests.

Courts, cases and users come from the hearings test builders; dates are fixed the
way the product fixes them (``listing.hold`` then ``confirm``), never by writing rows.
"""

import pytest

from apps.hearings.tests.conftest import (  # noqa: F401  (fixtures re-exported)
    advocate_user,
    business_date,
    case,
    complainant_user,
    courtroom,
    establishment,
    foreign_court,
    no_query_cache,
    other_case,
    sibling_courtroom,
    stranger,
    third_case,
)

from ..enums import OrderRole
from .factories import all_roles, make_user


@pytest.fixture
def drafter():
    return make_user(OrderRole.ORDER_DRAFTER, name="Drafter")


@pytest.fixture
def filler():
    return make_user(OrderRole.ORDER_DATA_FILLER, name="Filler")


@pytest.fixture
def setter():
    return make_user(OrderRole.NEXT_HEARING_SETTER, name="Setter")


@pytest.fixture
def signer():
    return make_user(OrderRole.ORDER_SIGNER, name="Signer")


@pytest.fixture
def staff():
    """Court staff holding every order role and the hearing controller role."""
    return make_user(*all_roles(), name="All roles")


@pytest.fixture(autouse=True)
def record_ports(monkeypatch):
    """Record what the stand-ins for 0011 are asked, so tests assert on it."""
    from apps.orders import ports

    calls = []

    def recorder(name):
        def record(*args, **kwargs):
            calls.append((name, args, kwargs))
            return f"ref:{name}"

        return record

    for name in (
        "open_task",
        "complete_task",
        "expire_task",
        "open_item_task",
        "complete_item_task",
        "complete_case_task",
        "dispatch_stage_event",
        "record_outcome",
    ):
        monkeypatch.setattr(ports, name, recorder(name))
    return calls


@pytest.fixture
def hearing(case, staff):  # noqa: F811
    """A started hearing of ``case``, today."""
    from .factories import started_hearing

    return started_hearing(case, staff)


@pytest.fixture
def order(hearing, drafter):
    """The draft order of ``hearing``."""
    from apps.orders.services import drafting

    return drafting.create_in_hearing(hearing_id=hearing.pk, actor=drafter)[0]


@pytest.fixture
def ready(hearing, order, staff):
    """A hearing order ready to send for signing: text written, next hearing set, roll marked."""
    from apps.orders.services import drafting, next_hearing

    from .factories import TODAY, mark_roll

    drafting.edit_text(order.pk, "<p>Heard. Called again on the next date.</p>", actor=staff)
    next_hearing.set_next_hearing(
        order.pk,
        state="LISTED",
        date=TODAY.replace(day=19),
        purpose="EVIDENCE_OF_COMPLAINANT",
        actor=staff,
    )
    mark_roll(hearing, staff)
    order.refresh_from_db()
    return order
