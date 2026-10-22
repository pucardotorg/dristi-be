"""API errors raised by the case filing services (spec 0021)."""

from rest_framework import status
from rest_framework.exceptions import APIException


class CaseNotEditable(APIException):  # noqa: N818 - named after its code
    """The case has been submitted, so its filing can no longer change."""

    status_code = status.HTTP_409_CONFLICT
    default_detail = "This case has been submitted and can no longer be changed."
    default_code = "case_not_editable"


class InvalidStatusTransition(APIException):  # noqa: N818 - named after its code
    """The case is not in the status this step starts from."""

    status_code = status.HTTP_409_CONFLICT
    default_detail = "The case is not in a status this step can start from."
    default_code = "invalid_status_transition"


class CaseNotReady(APIException):  # noqa: N818 - named after its code
    """The step's precondition does not hold; ``errors`` lists why."""

    status_code = status.HTTP_400_BAD_REQUEST
    default_code = "case_not_ready"

    def __init__(self, message, errors):
        super().__init__({"detail": message, "errors": errors})


class AlreadySigned(APIException):  # noqa: N818 - named after its code
    """The participant's signature is already recorded."""

    status_code = status.HTTP_409_CONFLICT
    default_detail = "This participant has already signed."
    default_code = "already_signed"
