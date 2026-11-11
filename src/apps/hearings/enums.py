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


BOARD_STATUSES = (
    HearingStatus.SCHEDULED,
    HearingStatus.IN_PROGRESS,
    HearingStatus.PASSED_OVER,
    HearingStatus.COMPLETED,
    HearingStatus.ABANDONED,
)

UNSEQUENCED_STATUSES = (HearingStatus.PROVISIONAL, HearingStatus.RELEASED)

CONFIRMED_STATUSES = tuple(status for status in HearingStatus if status not in UNSEQUENCED_STATUSES)

# The status alone is not enough: the hearing must also have been started (#6.5).
ATTENDANCE_STATUSES = (
    HearingStatus.IN_PROGRESS,
    HearingStatus.PASSED_OVER,
    HearingStatus.COMPLETED,
    HearingStatus.ABANDONED,
)

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


class AttendeeType(models.TextChoices):
    """A line on a hearing's attendance roll (#2.3, ``ATT-01``)."""

    COMPLAINANT = "COMPLAINANT", "Complainant"
    ACCUSED = "ACCUSED", "Accused"
    POA_HOLDER = "POA_HOLDER", "PoA holder"
    COMPLAINANT_ADVOCATE = "COMPLAINANT_ADVOCATE", "Advocate for complainant"
    ACCUSED_ADVOCATE = "ACCUSED_ADVOCATE", "Advocate for accused"


class AttendanceMark(models.TextChoices):
    """How a person on the roll is marked (``ATT-02``)."""

    PRESENT = "PRESENT", "Present"
    ABSENT = "ABSENT", "Absent"
    NOT_REQUIRED = "NOT_REQUIRED", "Not required"


class AppearanceMode(models.TextChoices):
    """How a present person appeared (§355, §530 BNSS)."""

    IN_PERSON = "IN_PERSON", "In person"
    VIDEO = "VIDEO", "Video"


# A hearing in one of these can be moved to another date (#8.1).
MOVABLE_STATUSES = (HearingStatus.SCHEDULED, HearingStatus.PASSED_OVER, HearingStatus.ABANDONED)


class RescheduleReason(models.TextChoices):
    """Why a hearing that has not been heard was moved (#8.1)."""

    PRESIDING_OFFICER_ON_LEAVE = "PRESIDING_OFFICER_ON_LEAVE", "Presiding officer on leave"
    COURT_HOLIDAY = "COURT_HOLIDAY", "Court holiday"
    COURT_NOT_SITTING = "COURT_NOT_SITTING", "Court not sitting"
    NOT_REACHED = "NOT_REACHED", "Not reached"
    LISTED_IN_ERROR = "LISTED_IN_ERROR", "Listed in error"
    PARTY_APPLICATION = "PARTY_APPLICATION", "Party application"
    JUDICIAL_DIRECTION = "JUDICIAL_DIRECTION", "Judicial direction"


# Administrative reasons court staff may move a hearing for without an order (#8.1).
COURT_SIDE_REASONS = (
    RescheduleReason.PRESIDING_OFFICER_ON_LEAVE,
    RescheduleReason.COURT_HOLIDAY,
    RescheduleReason.COURT_NOT_SITTING,
    RescheduleReason.NOT_REACHED,
    RescheduleReason.LISTED_IN_ERROR,
)


class ChangeSource(models.TextChoices):
    """What moved the hearing (#2.4)."""

    ORDER = "ORDER", "Order"
    COURT_ADMIN = "COURT_ADMIN", "Court staff"
    BULK = "BULK", "Bulk move"
