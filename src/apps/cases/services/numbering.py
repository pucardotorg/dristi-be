"""Case numbers from a registration type's series (spec 0024 #6.1, ``case-numbers.md``).

A stand-in format, ``{series}/{n}/{year}``, until ``case-numbers.md`` lands;
the series counter stays when the format changes.
"""

from .. import models


def format_case_number(series, number, year):
    """Return the case number ``number`` of ``series`` in ``year``."""
    return f"{series}/{number}/{year}"


def next_case_number(series, year):
    """Take the next free number of the series and return the case number.

    Call inside the transaction that saves it: the series row stays locked
    until that transaction ends, so concurrent registrations in one series get
    consecutive numbers, and a rolled-back registration gives its number back.
    A number some case already holds (one set by hand) is skipped.
    """
    row, _ = models.CaseNumberSeries.objects.select_for_update().get_or_create(
        series=series, year=year
    )
    number = row.last_number + 1
    while models.Case.objects.filter(case_number=format_case_number(series, number, year)).exists():
        number += 1
    row.last_number = number
    row.save(update_fields=["last_number", "updated_at"])
    return format_case_number(series, number, year)
