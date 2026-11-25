"""Bounded values of the processes module (spec 0028 #3, #4)."""

from django.db import models


class ProcessStatus(models.TextChoices):
    """Where a process is in its lifecycle (#4)."""

    PENDING_STEPS = "PENDING_STEPS", "Pending steps"
    PENDING_SIGNATURE = "PENDING_SIGNATURE", "Pending signature"
    SIGNED = "SIGNED", "Signed"
    SENT = "SENT", "Sent"
    DELIVERED = "DELIVERED", "Delivered"
    NOT_DELIVERED = "NOT_DELIVERED", "Not delivered"
    ERRORED = "ERRORED", "Errored"
    EXPIRED = "EXPIRED", "Expired"
    RECALLED = "RECALLED", "Recalled"


OUTCOME_STATUSES = (ProcessStatus.DELIVERED, ProcessStatus.NOT_DELIVERED)
TERMINAL_STATUSES = (*OUTCOME_STATUSES, ProcessStatus.EXPIRED, ProcessStatus.RECALLED)
LIVE_STATUSES = tuple(status for status in ProcessStatus if status not in TERMINAL_STATUSES)
# Only a process that has not been sent expires (``EXP-02``).
EXPIRABLE_STATUSES = (
    ProcessStatus.PENDING_STEPS,
    ProcessStatus.PENDING_SIGNATURE,
    ProcessStatus.SIGNED,
    ProcessStatus.ERRORED,
)
# A signed document exists from signing on (``SGN-04``).
SIGNED_STATUSES = (
    ProcessStatus.SIGNED,
    ProcessStatus.SENT,
    *OUTCOME_STATUSES,
    ProcessStatus.ERRORED,
)


class StepMode(models.TextChoices):
    """Whether a channel's send or status update is done by the system or a person (``DSP-01``)."""

    SYSTEM = "SYSTEM", "System"
    MANUAL = "MANUAL", "Manual"


class DestinationKind(models.TextChoices):
    """What a channel delivers to (§6.2)."""

    MOBILE = "MOBILE", "Mobile number"
    EMAIL = "EMAIL", "Email address"
    POSTAL = "POSTAL", "Postal address"
    POLICE_STATION = "POLICE_STATION", "Police station"


class RecipientType(models.TextChoices):
    """Who a process is addressed to (``SVC-01``, ``PRC-02``)."""

    ACCUSED = "ACCUSED", "Accused"
    ACCUSED_PERSON_IN_CHARGE = "ACCUSED_PERSON_IN_CHARGE", "Person in charge of the accused"
    WITNESS = "WITNESS", "Witness"
    COMPLAINANT = "COMPLAINANT", "Complainant"


class Side(models.TextChoices):
    """The party directed to take steps (``PRC-07``)."""

    COMPLAINANT = "COMPLAINANT", "Complainant"
    ACCUSED = "ACCUSED", "Accused"


class EventSource(models.TextChoices):
    """What recorded a status change (#3.4)."""

    USER = "USER", "User"
    SYSTEM = "SYSTEM", "System"
    CALLBACK = "CALLBACK", "Callback"
    POLL = "POLL", "Poll"
    SWEEP = "SWEEP", "Sweep"


class Step(models.TextChoices):
    """A court-side step on one process, as named in ``allowed_actions`` (#11.2).

    Signing and the system channels' steps (``sign``, ``resend``) come with
    the signing and channel-backend work.
    """

    RECEIVE_ENVELOPE = "receive_envelope", "Record receipt of the envelope"
    SEND = "send", "Mark as sent"
    RECORD_OUTCOME = "record_outcome", "Record outcome"
    RECALL = "recall", "Recall"
