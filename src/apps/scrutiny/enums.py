"""Bounded values of the scrutiny module (spec 0024 #3)."""

from django.db import models


class Decision(models.TextChoices):
    """A decision scrutiny delegates to a business rule bound per jurisdiction (#2.4)."""

    CHECKS = "CHECKS", "Advisory checks"


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
