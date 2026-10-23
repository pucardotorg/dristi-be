"""Plain helpers shared by the payments tests."""

from decimal import Decimal

from apps.payments.enums import ChargeType


def item(charge_type=ChargeType.PROCESS_COURT_FEE, unit_amount="12.50", quantity=1, **extra):
    """A demand item spec as a raising module passes it."""

    return {
        "charge_type": charge_type,
        "description": extra.pop("description", f"{charge_type} line"),
        "quantity": Decimal(str(quantity)),
        "unit_amount": Decimal(unit_amount),
        **extra,
    }


def item_ids(demand, *positions):
    """Ids of the demand's items at ``positions`` (all when none given)."""

    items = list(demand.items.order_by("position"))
    if not positions:
        return [i.pk for i in items]
    return [items[p].pk for p in positions]


def assert_error(response, error, field=None):
    """The standard error body with exactly ``error`` on ``field`` (spec 0000 #9)."""

    assert response.status_code == error.status, response.content
    body = response.json()
    assert "meta" in body
    codes = [(e["code"], e.get("field")) for e in body["errors"]]
    assert (error.code, field) in codes, codes
