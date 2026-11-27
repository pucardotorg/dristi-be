"""Bounded vocabularies of the applications module (spec 0033 #4, #5).

Application type codes are deliberately not here: a type is a code spec plus a
seeded ``ApplicationType`` row (#3.1, #4.1), so a new type needs no migration.
"""

from django.db import models


class ApplicationStatus(models.TextChoices):
    """The PRD's ten statuses, by their own names (#5.1, #5.3)."""

    DRAFT = "DRAFT", "Draft"
    PENDING_SIGNATURE = "PENDING_SIGNATURE", "Pending signature"
    PENDING_PAYMENT = "PENDING_PAYMENT", "Pending payment"
    PENDING_REVIEW = "PENDING_REVIEW", "Pending review"
    PENDING_DECISION = "PENDING_DECISION", "Pending decision"
    ACCEPTED = "ACCEPTED", "Accepted"
    REJECTED = "REJECTED", "Rejected"
    DISMISSED = "DISMISSED", "Dismissed"
    SUBMITTED = "SUBMITTED", "Submitted"
    EXPIRED = "EXPIRED", "Expired"


# Step 1, still with the filer: visible only to its side (#2.3).
FILER_STATUSES = (
    ApplicationStatus.DRAFT,
    ApplicationStatus.PENDING_SIGNATURE,
    ApplicationStatus.PENDING_PAYMENT,
)
# Visible to its drafting circle only (#2.3).
CIRCLE_ONLY_STATUSES = (ApplicationStatus.DRAFT, ApplicationStatus.PENDING_SIGNATURE)
# Before the court: an order can still act on it (#8.1 ``unavailable_reason``).
OPEN_STATUSES = (ApplicationStatus.PENDING_REVIEW, ApplicationStatus.PENDING_DECISION)
# Nothing leaves these (#5.1).
TERMINAL_STATUSES = (
    ApplicationStatus.ACCEPTED,
    ApplicationStatus.REJECTED,
    ApplicationStatus.DISMISSED,
    ApplicationStatus.SUBMITTED,
    ApplicationStatus.EXPIRED,
)
# Decided by an order; ``outcome`` mirrors the status (#4.2).
DECIDED_STATUSES = (
    ApplicationStatus.ACCEPTED,
    ApplicationStatus.REJECTED,
    ApplicationStatus.DISMISSED,
)
# Everything from submission on is visible to the whole case (#2.3).
SUBMITTED_STATUSES = tuple(
    status for status in ApplicationStatus.values if status not in FILER_STATUSES
)


class Side(models.TextChoices):
    """The side of the litigant an application is raised for (#2.1)."""

    COMPLAINANT = "COMPLAINANT", "Complainant"
    ACCUSED = "ACCUSED", "Accused"

    @property
    def opposite(self):
        return Side.ACCUSED if self == Side.COMPLAINANT else Side.COMPLAINANT


class Outcome(models.TextChoices):
    """What the deciding order recorded (#4.2, ``ALC-38`` row 3)."""

    ACCEPTED = "ACCEPTED", "Accepted"
    REJECTED = "REJECTED", "Rejected"
    DISMISSED = "DISMISSED", "Dismissed"


class WorkflowStatus(models.TextChoices):
    """The type's on-acceptance workflow (#12.1)."""

    NOT_APPLICABLE = "NOT_APPLICABLE", "Not applicable"
    PENDING = "PENDING", "Pending"
    DONE = "DONE", "Done"
    FAILED = "FAILED", "Failed"


class Action(models.TextChoices):
    """Every entry of the transition log (#4.4, #5.2)."""

    CREATE = "CREATE", "Created"
    EDIT = "EDIT", "Edited"
    PROCEED_TO_SIGN = "PROCEED_TO_SIGN", "Sent for signature"
    BACK_TO_DRAFT = "BACK_TO_DRAFT", "Moved back to draft"
    DELETE = "DELETE", "Deleted"
    SIGN = "SIGN", "Signed"
    PAY = "PAY", "Paid"
    SUBMIT = "SUBMIT", "Submitted"
    ONBOARD = "ONBOARD", "Onboarded"
    DEFER_REVIEW = "DEFER_REVIEW", "Review deferred"
    MOVE_DECISION_DATE = "MOVE_DECISION_DATE", "Decision date moved"
    ACCEPT = "ACCEPT", "Accepted"
    REJECT = "REJECT", "Rejected"
    DISMISS = "DISMISS", "Dismissed"
    EXPIRE = "EXPIRE", "Expired"
    WORKFLOW_DONE = "WORKFLOW_DONE", "Type workflow done"
    WORKFLOW_FAILED = "WORKFLOW_FAILED", "Type workflow failed"


# Court acts: each carries the order that did it (#4.4, ``ALC-33``).
ORDER_ACTIONS = (
    Action.ONBOARD,
    Action.DEFER_REVIEW,
    Action.MOVE_DECISION_DATE,
    Action.ACCEPT,
    Action.REJECT,
    Action.DISMISS,
)


class CounterKind(models.TextChoices):
    """The two number series (#4.5, #7)."""

    SUBMISSION = "SUBMISSION", "Submission"
    REPLACEMENT = "REPLACEMENT", "Replacement"


class NumberScope(models.TextChoices):
    """What one counter series is keyed by (#7)."""

    CASE = "CASE", "Case"
    COURT = "COURT", "Court"


class ObjectionStatus(models.TextChoices):
    """Where the objection stands, as every reader sees it (#14.4)."""

    NOT_CALLED_FOR = "NOT_CALLED_FOR", "Not called for"
    DUE = "DUE", "Due"
    NONE_RECEIVED = "NONE_RECEIVED", "None received"
    FILED = "FILED", "Filed"


class SigningMethod(models.TextChoices):
    """How an application is signed (#6.7, ``signing-methods.md``)."""

    AADHAAR_ESIGN = "AADHAAR_ESIGN", "Aadhaar e-sign"
    DSC = "DSC", "Digital signature certificate"
    UPLOAD_SIGNED_COPY = "UPLOAD_SIGNED_COPY", "Signed copy uploaded"


class ExpiryReason(models.TextChoices):
    """Why a hearing-linked application expired (#13)."""

    HEARING_PASSED = "HEARING_PASSED", "Hearing passed"
    HEARING_MOVED = "HEARING_MOVED", "Hearing moved"
    HEARING_CANCELLED = "HEARING_CANCELLED", "Hearing cancelled"
