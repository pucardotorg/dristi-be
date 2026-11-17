"""In-process exceptions raised to the modules that fix dates (spec 0023 #7.7).

Raised by ``services.listing`` to the orders module, never to a view. Each
carries the registered ``ErrorCode`` of the same meaning, so a caller can
surface it unchanged with ``BusinessError(exc.error, exc.message)``.
"""

from . import errors
from .enums import ReleaseReason

# Why a case cannot be listed, as a message says it (``get_listability``).
NOT_LISTABLE_REASONS = {
    "NOT_REGISTERED": "it is not registered in a court",
    "DISPOSED": "it has been disposed of",
    "LONG_PENDING_REGISTER": "it is in the Long Pending Register",
    "TRANSFERRED": "it has been transferred to another court",
}


def not_listable_message(reason):
    """``This case cannot be listed for a hearing: it is not registered in a court.``"""
    because = NOT_LISTABLE_REASONS.get(reason)
    base = errors.CASE_NOT_LISTABLE.message.rstrip(".")
    return f"{base}: {because}." if because else errors.CASE_NOT_LISTABLE.message


class HearingError(Exception):
    """Base of every in-process hearings exception."""

    error = None

    def __init__(self, message=None, *, error=None):
        if error is not None:
            self.error = error
        self.message = message or self.error.message
        super().__init__(self.message)

    @property
    def code(self):
        """The registered API code, e.g. ``E10003``."""
        return self.error.code


class CaseNotListable(HearingError):  # noqa: N818
    """The case is not registered, is disposed, in the LPR or transferred (``E10003``)."""

    error = errors.CASE_NOT_LISTABLE

    def __init__(self, reason):
        self.reason = reason
        super().__init__(not_listable_message(reason))


class CaseAlreadyScheduled(HearingError):  # noqa: N818
    """The case already has a ``SCHEDULED`` hearing (``E10004``)."""

    error = errors.CASE_ALREADY_SCHEDULED

    def __init__(self, hearing_id, message=None):
        self.hearing_id = hearing_id
        super().__init__(message)


class InvalidHearingDate(HearingError):  # noqa: N818
    """The date breaks a rule of #4 (``E10005``-``E10008``); ``problem`` says which."""

    def __init__(self, problem):
        self.problem = problem
        super().__init__(problem.message, error=problem.error)


class InvalidPurpose(HearingError):  # noqa: N818
    """The purpose is retired or unknown (``E10014``)."""

    error = errors.PURPOSE_INACTIVE


class CourtDayFull(HearingError):  # noqa: N818
    """The day is at capacity and ``capacity_mode = block`` (``E10009``)."""

    error = errors.COURT_DAY_FULL


class HoldNotFound(HearingError):  # noqa: N818
    """No hold for the order (``E10020``)."""

    error = errors.HOLD_NOT_FOUND


class HoldReleased(HearingError):  # noqa: N818
    """Confirming a hold that was released (``E10021``)."""

    error = errors.HOLD_RELEASED

    def __init__(self, release_reason):
        self.release_reason = release_reason
        label = ReleaseReason(release_reason).label.lower() if release_reason else ""
        base = errors.HOLD_RELEASED.message.rstrip(".")
        super().__init__(f"{base}: {label}." if label else errors.HOLD_RELEASED.message)


class HoldInvalid(HearingError):  # noqa: N818
    """The held date can no longer be confirmed (``E10023``); ``problems`` say why."""

    error = errors.HOLD_INVALID

    def __init__(self, problems):
        self.problems = list(problems)
        base = errors.HOLD_INVALID.message.rstrip(".")
        detail = " ".join(problem.message for problem in self.problems)
        super().__init__(f"{base}. {detail}" if detail else errors.HOLD_INVALID.message)
