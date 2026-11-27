"""Application numbers (spec 0033 #7, ``ALC-02``).

One number from submission; where the state says so, a new number replaces it
at onboarding and the earlier one is kept and searchable. Formats, scopes and
whether the series restarts yearly are per-state configuration. The counter row
is locked, so concurrent submissions in one scope get consecutive numbers; a
rolled-back transaction gives its number back.
"""

import logging

from django.db import IntegrityError, transaction
from django.db.models import Q

from apps.api.errors import BusinessError

from .. import conf, errors, ports
from ..enums import CounterKind, NumberScope
from ..models import Application, ApplicationCounter
from .calendar import today

logger = logging.getLogger(__name__)

# A runaway series is a configuration error; never loop forever skipping numbers.
MAX_SKIPS = 1000


class _Values(dict):
    """Placeholder values; an unknown placeholder renders empty instead of raising."""

    def __missing__(self, key):
        return ""


def _scope_key(application, scope):
    if scope == NumberScope.COURT:
        return str(application.case.court_id or application.case_id)
    return str(application.case_id)


def _format(fmt, application, n, year):
    case = application.case
    return fmt.format_map(
        _Values(
            n=n,
            year=year,
            filing_number=case.filing_number or "",
            case_number=case.case_number or "",
        )
    )


def _taken(application, number, scope):
    """Whether some application of the scope already holds ``number``, in use or earlier."""
    holders = Application.objects.exclude(pk=application.pk).filter(
        Q(application_number=number) | Q(earlier_application_number=number)
    )
    if scope == NumberScope.COURT:
        return holders.filter(case__court_id=application.case.court_id).exists()
    return holders.filter(case_id=application.case_id).exists()


def _allot(application, kind, fmt, scope, yearly):
    scope = NumberScope(scope if scope in NumberScope.values else NumberScope.CASE)
    year = today().year
    counter, _ = ApplicationCounter.objects.get_or_create(
        kind=kind, scope_key=_scope_key(application, scope), year=year if yearly else 0
    )
    counter = ApplicationCounter.objects.select_for_update().get(pk=counter.pk)
    for _ in range(MAX_SKIPS):
        counter.last_number += 1
        number = _format(fmt, application, counter.last_number, year)
        if not _taken(application, number, scope):
            counter.save(update_fields=["last_number", "updated_at"])
            return number
    raise BusinessError(errors.NUMBER_TAKEN)


def allot_submission_number(application):
    """Set ``application_number`` at submission (#6.9 step 1). The caller holds the lock."""
    settings = conf.numbering(ports.state_code(application.case))
    if settings["numbers_from_cis"]:
        # Recorded when CIS returns it (case-numbers.md); until then none is shown.
        return None
    fmt = settings["submission_number_format"]
    if not fmt:
        raise BusinessError(errors.NUMBERING_NOT_CONFIGURED)
    number = _allot(
        application,
        CounterKind.SUBMISSION,
        fmt,
        settings["submission_number_scope"],
        settings["submission_number_yearly"],
    )
    application.application_number = number
    logger.info(
        "event=APPLICATION_NUMBER_ALLOTTED application_id=%s kind=SUBMISSION", application.pk
    )
    return number


def replace_on_onboarding(application):
    """Replace the number at onboarding where the state does so; return ``{from, to}`` or None."""
    settings = conf.numbering(ports.state_code(application.case))
    fmt = settings["replacement_number_format"]
    if not settings["replace_on_onboarding"] or not fmt or settings["numbers_from_cis"]:
        return None
    number = _allot(
        application,
        CounterKind.REPLACEMENT,
        fmt,
        settings["replacement_number_scope"],
        settings["replacement_number_yearly"],
    )
    earlier = application.application_number
    application.earlier_application_number = earlier
    application.application_number = number
    logger.info(
        "event=APPLICATION_NUMBER_REPLACED application_id=%s kind=REPLACEMENT", application.pk
    )
    return {"from": earlier, "to": number}


def guard_number_clash(save):
    """Run ``save`` in a savepoint; a number taken outside numbering at that moment is ``E13027``."""
    try:
        with transaction.atomic():
            return save()
    except IntegrityError as exc:
        raise BusinessError(errors.NUMBER_TAKEN) from exc
