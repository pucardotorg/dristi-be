"""Bounded values of the scrutiny module (spec 0024 #3)."""

from django.db import models


class Decision(models.TextChoices):
    """A decision scrutiny delegates to a business rule bound per jurisdiction (#2.4)."""

    CHECKS = "CHECKS", "Advisory checks"


class CourtRole(models.TextChoices):
    """The court roles scrutiny and registration need, held per establishment (#2.2)."""

    SCRUTINY_OFFICER = "SCRUTINY_OFFICER", "Scrutiny officer"
    CASE_REGISTERER = "CASE_REGISTERER", "Case registerer"


class RoundStage(models.TextChoices):
    """The workflow state a round belongs to (#3.1)."""

    SCRUTINY = "SCRUTINY", "Scrutiny"
    REGISTRATION = "REGISTRATION", "Registration"


class RoutingReason(models.TextChoices):
    """Why the case reached scrutiny; display only (#3.1)."""

    FILER_SKIPPED_WARNING = "FILER_SKIPPED_WARNING", "Filer skipped a warning"
    LOW_READ_CONFIDENCE = "LOW_READ_CONFIDENCE", "Low read confidence"
    NOT_MACHINE_READ = "NOT_MACHINE_READ", "Not machine read"
    RANDOM_CHECK = "RANDOM_CHECK", "Random check"
    RESUBMITTED = "RESUBMITTED", "Resubmitted"


class RoundDecision(models.TextChoices):
    """How a round was closed; empty while it is open (#3.1, #4)."""

    SENT_BACK = "SENT_BACK", "Sent back"
    FORWARDED = "FORWARDED", "Forwarded"
    REGISTERED = "REGISTERED", "Registered"


class FlagTarget(models.TextChoices):
    """What a flag points at (#3.2)."""

    FIELD = "FIELD", "Field"
    SECTION = "SECTION", "Section"
    DOCUMENT = "DOCUMENT", "Document"
    OATH = "OATH", "Oath"


class DocumentIssue(models.TextChoices):
    """What is wrong with a flagged document (#3.2)."""

    BLURRY_UNREADABLE = "BLURRY_UNREADABLE", "Blurry / unreadable"
    PAGE_MISSING = "PAGE_MISSING", "Page missing"
    WRONG_DOCUMENT = "WRONG_DOCUMENT", "Wrong document"
    OTHER = "OTHER", "Other"


class FlagStatus(models.TextChoices):
    """Where a flag is in its lifecycle (#3.5)."""

    DRAFT = "DRAFT", "Draft"
    RAISED = "RAISED", "Raised"
    RESPONDED = "RESPONDED", "Responded"
    RESOLVED = "RESOLVED", "Resolved"
    CARRIED = "CARRIED", "Carried"
    WITHDRAWN = "WITHDRAWN", "Withdrawn"


class ResponseKind(models.TextChoices):
    """How the filer answered a raised flag (#3.6, #5.2)."""

    CORRECTED = "CORRECTED", "Corrected"
    REUPLOADED = "REUPLOADED", "Re-uploaded"
    EXPLAINED = "EXPLAINED", "Explained"
