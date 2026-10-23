"""In-process exceptions that never reach a view (spec 0017 #1).

API failures are ``BusinessError(errors.X)``; these are signals between the
services, or between a provider and this module.
"""

from django.core.exceptions import ValidationError


class PaymentNotConfirmable(Exception):  # noqa: N818
    """Raised when a payment (or its batch) is not in a state that can be credited."""


class ImmutableRecordError(ValidationError):
    """Raised when code tries to edit money history that is frozen (spec 0017 #10)."""
