"""Bounded values of the hearings module (spec 0023)."""

from django.db import models


class CalendarEntryType(models.TextChoices):
    """Why a court's day differs from a normal sitting day (#2.5).

    Only ``REDUCED_SITTING`` is a sitting day; every other type is not (#4).
    """

    HOLIDAY = "HOLIDAY", "Holiday"
    PRESIDING_OFFICER_LEAVE = "PRESIDING_OFFICER_LEAVE", "Presiding officer on leave"
    NON_SITTING = "NON_SITTING", "Non-sitting day"
    REDUCED_SITTING = "REDUCED_SITTING", "Reduced sitting"


class HearingStatus(models.TextChoices):
    """Where a hearing is in its lifecycle (#3)."""

    PROVISIONAL = "PROVISIONAL", "Provisional"
    SCHEDULED = "SCHEDULED", "Scheduled"
    IN_PROGRESS = "IN_PROGRESS", "In progress"
    PASSED_OVER = "PASSED_OVER", "Passed over"
    COMPLETED = "COMPLETED", "Completed"
    ABANDONED = "ABANDONED", "Abandoned"
    CANCELLED = "CANCELLED", "Cancelled"
    RELEASED = "RELEASED", "Released"


# The statuses shown on a day's board, each with a serial number (#2.1, #5).
BOARD_STATUSES = (
    HearingStatus.SCHEDULED,
    HearingStatus.IN_PROGRESS,
    HearingStatus.PASSED_OVER,
    HearingStatus.COMPLETED,
    HearingStatus.ABANDONED,
)

# The statuses that never have a serial number (#2.1).
UNSEQUENCED_STATUSES = (HearingStatus.PROVISIONAL, HearingStatus.RELEASED)

# Sorts a board as #3 lists it: being heard, waiting, passed over, heard,
# abandoned. Statuses off the board sort after all of them.
OFF_BOARD_STATUS_ORDER = 90
STATUS_ORDER = {
    HearingStatus.IN_PROGRESS: 10,
    HearingStatus.SCHEDULED: 20,
    HearingStatus.PASSED_OVER: 30,
    HearingStatus.COMPLETED: 40,
    HearingStatus.ABANDONED: 50,
    HearingStatus.PROVISIONAL: OFF_BOARD_STATUS_ORDER,
    HearingStatus.CANCELLED: OFF_BOARD_STATUS_ORDER,
    HearingStatus.RELEASED: OFF_BOARD_STATUS_ORDER,
}


class HearingMode(models.TextChoices):
    """How the hearing is held (#2.1)."""

    IN_PERSON = "IN_PERSON", "In person"
    VIDEO = "VIDEO", "Video"
    HYBRID = "HYBRID", "Hybrid"


class Side(models.TextChoices):
    """Who sought an adjournment or a move (#2.1, #2.4, #11.3)."""

    COMPLAINANT = "COMPLAINANT", "Complainant"
    ACCUSED = "ACCUSED", "Accused"
    COURT = "COURT", "Court"


class CancellationReason(models.TextChoices):
    """Why a listed hearing will not be heard (#7.6)."""

    CASE_DISPOSED = "CASE_DISPOSED", "Case disposed"
    CASE_TRANSFERRED = "CASE_TRANSFERRED", "Case transferred"
    LONG_PENDING_REGISTER = "LONG_PENDING_REGISTER", "Moved to the Long Pending Register"
    LISTED_IN_ERROR = "LISTED_IN_ERROR", "Listed in error"


class ReleaseReason(models.TextChoices):
    """Why a provisional date never became a hearing (#7.4)."""

    DRAFT_DISCARDED = "DRAFT_DISCARDED", "Draft order discarded"
    DATE_REMOVED = "DATE_REMOVED", "Date removed from the draft"
    CONSUMED = "CONSUMED", "Applied to the original hearing"
    CASE_CLOSED = "CASE_CLOSED", "Case closed"
