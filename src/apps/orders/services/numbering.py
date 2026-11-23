"""Order and Roznama numbers (spec 0039 #8.3).

Allotted at the first signing attempt, from ``OrderNumberCounter`` under a row
lock, kept through retries and moves back, and never reused. The format is
whatever ``ORDERS_NUMBER_FORMATTER`` says (open question 1: ``case-numbers.md``
defines neither).
"""

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils.module_loading import import_string

from apps.cases.selectors import state_code
from apps.hearings.services import calendar

from ..enums import NumberSeries
from ..models import OrderNumberCounter

SERIES_CODE = {NumberSeries.ORDER: "ORD", NumberSeries.ROZNAMA: "RZN"}


def default_formatter(*, court_code, series, seq, year, state):
    """``{court_code}/ORD/{seq}/{year}`` and ``{court_code}/RZN/{seq}/{year}``."""
    return f"{court_code}/{SERIES_CODE[series]}/{seq}/{year}"


def _formatter():
    path = getattr(settings, "ORDERS_NUMBER_FORMATTER", None)
    return import_string(path) if path else default_formatter


def next_value(court_id, series, year):
    """Return the next number in ``(court, series, year)``, under the counter's row lock."""
    try:
        with transaction.atomic():
            OrderNumberCounter.objects.get_or_create(court_id=court_id, series=series, year=year)
    except IntegrityError:
        pass
    counter = OrderNumberCounter.objects.select_for_update().get(
        court_id=court_id, series=series, year=year
    )
    counter.last_value += 1
    counter.save(update_fields=["last_value", "updated_at"])
    return counter.last_value


def allot(order, series):
    """Return a formatted number from ``series`` for the order's courtroom, for today's year."""
    year = calendar.business_date().year
    seq = next_value(order.court_id, series, year)
    return _formatter()(
        court_code=order.court.code,
        series=series,
        seq=seq,
        year=year,
        state=state_code(order.case_id),
    )
