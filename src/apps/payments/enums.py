"""Bounded vocabularies of the payments module (spec 0017 #3, #4).

New values are added with a migration. ``OTHER`` / ``OTHER_FEE`` exist so an
early consumer is never blocked, not as a permanent home.
"""

from django.db import models


class ReferenceType(models.TextChoices):
    """What within a case a demand or a demand item is raised against."""

    CASE = "CASE", "Case"
    CASE_FILING = "CASE_FILING", "Case filing"
    APPLICATION = "APPLICATION", "Application"
    SUMMONS = "SUMMONS", "Summons"
    NOTICE = "NOTICE", "Notice"
    WARRANT = "WARRANT", "Warrant"
    PROCLAMATION = "PROCLAMATION", "Proclamation"
    ATTACHMENT = "ATTACHMENT", "Attachment"
    HEARING = "HEARING", "Hearing"
    ORDER = "ORDER", "Order"
    VAKALATNAMA = "VAKALATNAMA", "Vakalatnama"
    TASK = "TASK", "Task"
    OTHER = "OTHER", "Other"


class ChargeType(models.TextChoices):
    """The fee head of a line item. A label only: no behaviour hangs off it."""

    COURT_FEE = "COURT_FEE", "Court fee"
    LEGAL_BENEFIT_FEE = "LEGAL_BENEFIT_FEE", "Legal benefit fee"
    ADVOCATE_WELFARE_FUND = "ADVOCATE_WELFARE_FUND", "Advocate welfare fund"
    STIPEND_STAMP = "STIPEND_STAMP", "Stipend stamp"
    ADVOCATE_CLERK_WELFARE_FUND = "ADVOCATE_CLERK_WELFARE_FUND", "Advocate clerk welfare fund"
    COMPLAINT_FEE = "COMPLAINT_FEE", "Complaint fee"
    DELAY_CONDONATION_FEE = "DELAY_CONDONATION_FEE", "Delay condonation fee"
    PROCESS_COURT_FEE = "PROCESS_COURT_FEE", "Process court fee"
    EPOST_FEE = "EPOST_FEE", "e-Post fee"
    VAKALATNAMA_FEE = "VAKALATNAMA_FEE", "Vakalatnama fee"
    APPLICATION_FEE = "APPLICATION_FEE", "Application fee"
    COST = "COST", "Cost"
    OTHER_FEE = "OTHER_FEE", "Other fee"


class DemandStatus(models.TextChoices):
    """Derived from the items; never set by a client (spec 0017 #4)."""

    RAISED = "RAISED", "Raised"
    PARTIALLY_PAID = "PARTIALLY_PAID", "Partially paid"
    PAID = "PAID", "Paid"
    CANCELLED = "CANCELLED", "Cancelled"


class DemandItemStatus(models.TextChoices):
    """The authoritative state of one charge."""

    UNPAID = "UNPAID", "Unpaid"
    PAID = "PAID", "Paid"
    CANCELLED = "CANCELLED", "Cancelled"


class PaymentStatus(models.TextChoices):
    """One collection attempt's lifecycle."""

    INITIATED = "INITIATED", "Initiated"
    PENDING = "PENDING", "Pending"
    SUCCESS = "SUCCESS", "Success"
    FAILED = "FAILED", "Failed"
    CANCELLED = "CANCELLED", "Cancelled"


# A payment in one of these may still collect money; its items are in flight.
OPEN_PAYMENT_STATUSES = (PaymentStatus.INITIATED, PaymentStatus.PENDING)
TERMINAL_PAYMENT_STATUSES = (
    PaymentStatus.SUCCESS,
    PaymentStatus.FAILED,
    PaymentStatus.CANCELLED,
)
PAYABLE_DEMAND_STATUSES = (DemandStatus.RAISED, DemandStatus.PARTIALLY_PAID)

# Stored reasons on ``Payment.failure_code`` (spec 0017 #12.5): not API codes.
FAILURE_NOT_FOUND_AT_PROVIDER = "PAYMENT_NOT_FOUND_AT_PROVIDER"
FAILURE_PROVIDER_FAILED = "PAYMENT_FAILED_AT_PROVIDER"
FAILURE_PROVIDER_ERROR = "PROVIDER_ERROR"
FAILURE_CANCELLED = "PAYMENT_CANCELLED"
