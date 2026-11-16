"""Human-readable request numbers, ``{STATE_CODE}-REQ-{seq:05d}`` (spec 0010 #1.1).

The state code is read from the configuration store on every call, so an
admin edit applies to the next request. The counter row is bumped with an
atomic ``UPDATE`` in the caller's transaction, which holds its row lock until
commit, so two concurrent creations can never draw the same number;
``max(...) + 1`` is never used. Five digits is a minimum width, not a limit:
after ``99999`` comes ``100000``.
"""

import re

from django.db import IntegrityError, transaction
from django.db.models import F
from django.utils import timezone

from apps.api.errors import BusinessError
from apps.core import services as config

from . import errors
from .models import RequestNumberSequence

STATE_CODE_SET = "tenant"
STATE_CODE_KEY = "state_code"
STATE_CODE_PATTERN = re.compile(r"^[A-Z]{2,3}$")
REQUEST_NUMBER_KIND = "REQ"


def state_code() -> str:
    """Return the configured state code, e.g. ``KL``; there is no default."""
    try:
        value = config.get(STATE_CODE_SET, STATE_CODE_KEY).strip().upper()
    except config.ConfigurationNotFound:
        raise BusinessError(errors.REQUEST_NUMBERING_NOT_CONFIGURED) from None
    if not STATE_CODE_PATTERN.match(value):
        raise BusinessError(errors.REQUEST_NUMBERING_NOT_CONFIGURED)
    return value


def format_request_number(prefix: str, value: int) -> str:
    """Return the request number ``value`` under ``prefix``."""
    return f"{prefix}-{value:05d}"


def next_request_number() -> str:
    """Allocate the next request number. Call inside the creating transaction."""
    prefix = f"{state_code()}-{REQUEST_NUMBER_KIND}"
    rows = RequestNumberSequence.objects.filter(prefix=prefix)

    with transaction.atomic():
        if not rows.update(value=F("value") + 1, updated_at=timezone.now()):
            try:
                with transaction.atomic():
                    RequestNumberSequence.objects.create(prefix=prefix, value=1)
            except IntegrityError:
                # Another transaction created the row first.
                rows.update(value=F("value") + 1, updated_at=timezone.now())
        value = rows.values_list("value", flat=True).get()

    return format_request_number(prefix, value)
